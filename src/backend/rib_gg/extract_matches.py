"""Parallel rib.gg match + replay extract. Lands JSON first so parse/load can retry without HTTP."""

from __future__ import annotations

import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.api_connectors.ribs_connector import RibSiteConnector
from backend.config.env import load_project_env
from backend.rib_gg.paths import (
    REPO_ROOT,
    event_matches_jsonl_path,
    events_jsonl_path,
    match_json_path,
    matches_jsonl_path,
    replay_json_path,
)
from backend.rib_gg.rsc import first_initial, first_maps_with
from backend.vlr.dim.util import format_project_date

logger = logging.getLogger(__name__)

DEFAULT_WORKERS = 8


def _root(repo_root: Path | None) -> Path:
    """CLI and Dagster share one repo root."""
    return Path(repo_root or REPO_ROOT)


def _now() -> str:
    """UTC stamp for landing metadata."""
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Any) -> Path:
    """Compact JSON so 6MB replays stay smaller on disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    return path


def _ids_in_jsonl(path: Path, key: str) -> set[str]:
    """Resume set from an append-only jsonl."""
    found: set[str] = set()
    if not path.exists():
        return found
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and obj.get(key) is not None:
                found.add(str(obj[key]))
    return found


def _append_jsonl(path: Path, row: dict[str, Any], lock: threading.Lock) -> None:
    """Thread-safe one-row append."""
    line = json.dumps(row, ensure_ascii=False, default=str) + "\n"
    with lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)


def _team(obj: Any) -> dict[str, Any]:
    """Normalize teamA / team1 shapes."""
    if not isinstance(obj, dict):
        return {}
    return {
        "id": obj.get("id"),
        "name": obj.get("name"),
        "short_name": obj.get("shortName") or obj.get("short_name") or obj.get("tag"),
    }


def _map_game_number(map_id: Any, index: int) -> int:
    """270-m2 → 2; otherwise 1-based list order."""
    text = str(map_id or "")
    if "-m" in text:
        suffix = text.rsplit("-m", 1)[-1]
        if suffix.isdigit():
            return int(suffix)
    return index


def _iso_to_project_date(raw: Any) -> str | None:
    """RIB ISO timestamp → YYYY/M/D."""
    if not raw:
        return None
    text = str(raw).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return format_project_date(parsed.date())


def assemble_match_payload(
    connector: RibSiteConnector,
    match_id: str,
    *,
    listing: dict[str, Any] | None = None,
    event: dict[str, Any] | None = None,
    session: Any = None,
) -> dict[str, Any]:
    """RSC overview + economy tab into one JSON object we can parse later."""
    listing = listing or {}
    event = event or {}
    text = connector.get_match_page(match_id, session=session)
    initial = first_initial(text)
    maps = initial.get("maps") if isinstance(initial.get("maps"), list) else []
    maps = [row for row in maps if isinstance(row, dict)]
    if not maps:
        maps = first_maps_with(text, "rounds") or first_maps_with(text, "id")
    needs_economy = bool(maps) and not any(isinstance(row.get("roundEconomy"), list) for row in maps)
    if needs_economy:
        eco_text = connector.get_match_page(match_id, tab="Economy", session=session)
        eco_maps = {str(row.get("id")): row for row in first_maps_with(eco_text, "roundEconomy")}
        for row in maps:
            extra = eco_maps.get(str(row.get("id")))
            if extra and extra.get("roundEconomy") is not None:
                row["roundEconomy"] = extra["roundEconomy"]
    team_a = _team(initial.get("teamA") or listing.get("teamA") or listing.get("team_a"))
    team_b = _team(initial.get("teamB") or listing.get("teamB") or listing.get("team_b"))
    match_time = initial.get("matchTimeIso") or listing.get("matchTimeIso") or listing.get("match_time_iso")
    leftover = {
        key: value
        for key, value in initial.items()
        if key not in {"maps", "teamA", "teamB", "matchTimeIso", "bestOf", "scoreA", "scoreB"}
    }
    return {
        "rib_match_id": str(match_id),
        "rib_event_id": str(event.get("id") or listing.get("eventId") or listing.get("event_id") or "") or None,
        "event_name": event.get("name") or listing.get("event_name"),
        "event_slug": event.get("slug"),
        "fetched_at": _now(),
        "source_url": f"https://rib.gg/matches/{match_id}",
        "match_time_iso": match_time,
        "match_date": _iso_to_project_date(match_time),
        "best_of": initial.get("bestOf") or listing.get("bestOf"),
        "score_a": initial.get("scoreA") if initial.get("scoreA") is not None else listing.get("scoreA"),
        "score_b": initial.get("scoreB") if initial.get("scoreB") is not None else listing.get("scoreB"),
        "team_a": team_a,
        "team_b": team_b,
        "maps": maps,
        "listing": listing,
        "leftover": leftover,
    }


def _index_row(payload: dict[str, Any], replay_maps: list[str], repo_root: Path) -> dict[str, Any]:
    """Slim row for matches.jsonl (join keys + paths, not full maps)."""
    maps = payload.get("maps") or []
    match_id = str(payload.get("rib_match_id"))
    return {
        "rib_match_id": payload.get("rib_match_id"),
        "rib_event_id": payload.get("rib_event_id"),
        "event_name": payload.get("event_name"),
        "match_date": payload.get("match_date"),
        "match_time_iso": payload.get("match_time_iso"),
        "team_a": payload.get("team_a"),
        "team_b": payload.get("team_b"),
        "score_a": payload.get("score_a"),
        "score_b": payload.get("score_b"),
        "best_of": payload.get("best_of"),
        "n_maps": len(maps),
        "has_replay": bool(replay_maps),
        "replay_map_ids": replay_maps,
        "json_path": str(match_json_path(repo_root, match_id)),
    }


def fetch_one_match(
    connector: RibSiteConnector,
    repo_root: Path,
    match_id: str,
    *,
    listing: dict[str, Any] | None = None,
    event: dict[str, Any] | None = None,
    skip_existing: bool = True,
    fetch_replay: bool = True,
) -> dict[str, Any]:
    """Land one match RSC + each map replay. Independent of other matches (thread pool)."""
    session = connector.session_factory.create()
    json_path = match_json_path(repo_root, match_id)
    if skip_existing and json_path.exists():
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        logger.info("[rib_extract] Skip existing match=%s", match_id)
    else:
        payload = assemble_match_payload(
            connector, match_id, listing=listing, event=event, session=session
        )
        _write_json(json_path, payload)
        logger.info("[rib_extract] Landed match=%s maps=%s path=%s", match_id, len(payload.get("maps") or []), json_path)

    replay_ids: list[str] = []
    maps = payload.get("maps") or []
    if fetch_replay:
        for map_row in maps:
            if not isinstance(map_row, dict):
                continue
            map_id = map_row.get("id")
            if not map_id:
                continue
            if map_row.get("hasReplayAvailable") is False:
                continue
            replay_path = replay_json_path(repo_root, match_id, str(map_id))
            if skip_existing and replay_path.exists():
                replay_ids.append(str(map_id))
                continue
            try:
                replay = connector.get_replay_data(match_id, str(map_id), session=session)
            except Exception:
                logger.exception("[rib_extract] Replay failed match=%s map=%s", match_id, map_id)
                continue
            _write_json(replay_path, replay)
            replay_ids.append(str(map_id))
            logger.info(
                "[rib_extract] Landed replay match=%s map=%s bytes=%s",
                match_id,
                map_id,
                replay_path.stat().st_size,
            )
    return _index_row(payload, replay_ids, repo_root)


def _parse_match_id_list(raw: str | None) -> list[str]:
    """RIB_MATCH_IDS=270,271 → targeted extract without crawling /events."""
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def extract_rib_matches(repo_root: Path | None = None) -> dict[str, int]:
    """List events/matches (unless ids given), then fetch match+replay in parallel."""
    load_project_env(repo_root)
    root = _root(repo_root)
    workers = max(1, int(os.environ.get("RIB_MATCH_WORKERS", str(DEFAULT_WORKERS))))
    skip_existing = os.environ.get("RIB_SKIP_EXISTING", "1").strip().lower() not in {"0", "false", "no"}
    fetch_replay = os.environ.get("RIB_FETCH_REPLAY", "1").strip().lower() not in {"0", "false", "no"}
    max_events = os.environ.get("RIB_MAX_EVENTS")
    max_matches = os.environ.get("RIB_MAX_MATCHES")
    match_ids = _parse_match_id_list(os.environ.get("RIB_MATCH_IDS"))
    connector = RibSiteConnector()
    logger.info("=== rib_extract START workers=%s skip_existing=%s replay=%s match_ids=%s ===",
        workers,
        skip_existing,
        fetch_replay,
        ",".join(match_ids) if match_ids else "from /events",
    )

    work: list[tuple[str, dict[str, Any] | None, dict[str, Any] | None]] = []
    if match_ids:
        work = [(mid, None, None) for mid in match_ids]
    else:
        events = connector.list_events()
        events_path = events_jsonl_path(root)
        with events_path.open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        logger.info("[rib_extract] Events listed n=%s path=%s", len(events), events_path)
        if max_events:
            events = events[: max(0, int(max_events))]
        listed: set[str] = set()
        lock = threading.Lock()
        event_matches_path = event_matches_jsonl_path(root)

        def list_one(event: dict[str, Any]) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
            event_id = str(event.get("id"))
            slug = str(event.get("slug") or event_id)
            session = connector.session_factory.create()
            try:
                matches = connector.list_event_matches(event_id, slug, session=session)
            except Exception:
                logger.exception("[rib_extract] Event matches failed event=%s", event_id)
                return []
            rows: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
            for match in matches:
                mid = str(match.get("id"))
                _append_jsonl(
                    event_matches_path,
                    {"rib_event_id": event_id, "rib_match_id": mid, "match": match},
                    lock,
                )
                rows.append((mid, match, event))
            logger.info("[rib_extract] Event %s matches=%s", event_id, len(rows))
            return rows

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(list_one, event) for event in events]
            for fut in as_completed(futures):
                for mid, listing, event in fut.result():
                    if mid in listed:
                        continue
                    listed.add(mid)
                    work.append((mid, listing, event))

    if max_matches:
        work = work[: max(0, int(max_matches))]
    logger.info("[rib_extract] Matches queued=%s", len(work))

    index_path = matches_jsonl_path(root)
    seen_index = _ids_in_jsonl(index_path, "rib_match_id") if skip_existing else set()
    index_lock = threading.Lock()
    done = 0
    errors = 0
    replays = 0
    progress_lock = threading.Lock()

    def run_one(item: tuple[str, dict[str, Any] | None, dict[str, Any] | None]) -> None:
        nonlocal done, errors, replays
        match_id, listing, event = item
        try:
            row = fetch_one_match(
                connector,
                root,
                match_id,
                listing=listing,
                event=event,
                skip_existing=skip_existing,
                fetch_replay=fetch_replay,
            )
        except Exception:
            logger.exception("[rib_extract] Match failed id=%s", match_id)
            with progress_lock:
                errors += 1
            return
        if match_id not in seen_index:
            _append_jsonl(index_path, row, index_lock)
            with index_lock:
                seen_index.add(match_id)
        with progress_lock:
            done += 1
            replays += len(row.get("replay_map_ids") or [])
            if done % 10 == 0 or done == len(work):
                logger.info(
                    "[rib_extract] Progress done=%s/%s errors=%s replays=%s",
                    done,
                    len(work),
                    errors,
                    replays,
                )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_one, item) for item in work]
        for fut in as_completed(futures):
            fut.result()

    counts = {
        "queued": len(work),
        "landed": done,
        "errors": errors,
        "replays": replays,
    }
    logger.info("=== rib_extract DONE queued=%s landed=%s errors=%s replay_maps=%s ===",
        counts["queued"], counts["landed"], counts["errors"], counts["replays"])
    return counts
