"""Historical VLR matches → matches.jsonl → vlr.dim_matches."""

from __future__ import annotations

import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.api_connectors.ip_rotator_gateway import assert_container_rotator
from backend.api_connectors.vlr_v2_connector import VlrV2Connector
from backend.config.env import load_project_env
from backend.database_connectors.supabase_connectors import SupabaseConnector
from backend.vlr.dim.util import (
    append_event_match_list,
    append_match_row,
    event_ids_from_jsonl,
    event_ids_with_match_lists,
    event_matches_jsonl_path,
    match_id_from_url,
    match_ids_in_jsonl,
    matches_jsonl_path,
    parse_match_date,
    parse_match_patch,
    read_event_match_lists,
    utc_now,
    year_from_text,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[4]
DIM_COLS = (
    "vlr_match_id",
    "vlr_event_id",
    "vlr_team_1_id",
    "vlr_team_2_id",
    "team_1_name",
    "team_2_name",
    "event_series",
    "best_of",
    "team_1_score",
    "team_2_score",
    "match_date",
    "match_date_text",
    "match_note",
    "match_patch",
    "n_maps",
    "is_completed",
    "has_stats",
    "has_vod",
    "has_rib_replay",
    "rib_match_id",
    "url",
    "status",
    "map_vetos",
    "insert_date",
    "update_date",
)
DIM_TYPES = {
    "row_number": "BIGINT",
    "vlr_match_id": "TEXT",
    "vlr_event_id": "TEXT",
    "vlr_team_1_id": "TEXT",
    "vlr_team_2_id": "TEXT",
    "team_1_name": "TEXT",
    "team_2_name": "TEXT",
    "event_series": "TEXT",
    "best_of": "INTEGER",
    "team_1_score": "INTEGER",
    "team_2_score": "INTEGER",
    "match_date": "TEXT",
    "match_date_text": "TEXT",
    "match_note": "TEXT",
    "match_patch": "TEXT",
    "n_maps": "INTEGER",
    "is_completed": "BOOLEAN",
    "has_stats": "BOOLEAN",
    "has_vod": "BOOLEAN",
    "has_rib_replay": "BOOLEAN",
    "rib_match_id": "BIGINT",
    "url": "TEXT",
    "status": "TEXT",
    "map_vetos": "TEXT",
    "insert_date": "TIMESTAMPTZ",
    "update_date": "TIMESTAMPTZ",
}


def _root(repo_root: Path | None) -> Path:
    """Resolve the git root so JSON landings stay under data/vlr."""
    return Path(repo_root or REPO_ROOT)


def _int(value: Any) -> int | None:
    """Parse VLR scores like `2` or `–` into ints."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    text = str(value).strip().replace(",", "").replace("+", "")
    if text in {"-", "–", "—", "tbd", "TBD"}:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _best_of(score_1: int | None, score_2: int | None, n_maps: int | None) -> int | None:
    """Infer BO1/BO3/BO5 from map wins when VLR omits best_of."""
    top = max([s for s in (score_1, score_2) if s is not None], default=None)
    if top is not None:
        if top >= 3:
            return 5
        if top == 2:
            return 3
        if top == 1 and (n_maps or 1) <= 1:
            return 1
        if top == 1:
            return 3
    if n_maps:
        if n_maps <= 1:
            return 1
        if n_maps <= 3:
            return 3
        return 5
    return None


def _done(status: str | None) -> bool:
    """True when the series is finished (VLR uses final/completed)."""
    return str(status or "").strip().lower() in {"final", "completed", "complete"}


def _has_stats(detail: dict[str, Any]) -> bool:
    """True when at least one map has a player scoreboard."""
    maps = detail.get("maps")
    if not isinstance(maps, list):
        return False
    for game in maps:
        if not isinstance(game, dict):
            continue
        players = game.get("players")
        if isinstance(players, dict) and (players.get("team1") or players.get("team2")):
            return True
        if isinstance(players, list) and players:
            return True
    return False


@dataclass
class Progress:
    """Thread-safe N/total so Dagster logs show which match just finished."""

    total: int
    done: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def mark(self, label: str, *, skipped: bool = False) -> None:
        suffix = " skip" if skipped else ""
        with self.lock:
            self.done += 1
            logger.info("[matches] %s/%s %s%s", self.done, self.total, label, suffix)


@dataclass
class Landing:
    """Append-only matches.jsonl; tracks ids so workers do not duplicate."""

    repo_root: Path
    ids: set[str]
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def open(cls, repo_root: Path) -> Landing:
        """Load existing ids so a resume appends only new matches."""
        return cls(repo_root=repo_root, ids=match_ids_in_jsonl(repo_root))

    def has(self, match_id: str) -> bool:
        with self.lock:
            return match_id in self.ids

    def write(self, row: dict[str, Any]) -> bool:
        """Append one landing line. Returns False if the id was already landed."""
        match_id = str(row.get("vlr_match_id") or "")
        if not match_id:
            return False
        with self.lock:
            if match_id in self.ids:
                return False
            append_match_row(self.repo_root, row)
            self.ids.add(match_id)
            return True


def format_row(
    event_id: str,
    listing: dict[str, Any],
    detail: dict[str, Any],
) -> dict[str, Any]:
    """Flatten list + full match detail into one dim_matches row plus raw payloads."""
    teams = detail.get("teams") if isinstance(detail.get("teams"), list) else []
    team_1 = teams[0] if teams else {}
    team_2 = teams[1] if len(teams) > 1 else {}
    if not team_1:
        team_1 = listing.get("team1") if isinstance(listing.get("team1"), dict) else {}
    if not team_2:
        team_2 = listing.get("team2") if isinstance(listing.get("team2"), dict) else {}
    event = detail.get("event") if isinstance(detail.get("event"), dict) else {}
    match_id = str(
        listing.get("match_id")
        or detail.get("match_id")
        or match_id_from_url(str(listing.get("url") or ""))
        or ""
    )
    date_raw = listing.get("date") or detail.get("date")
    year = year_from_text(date_raw, event.get("name"), listing.get("url"))
    maps = detail.get("maps") if isinstance(detail.get("maps"), list) else []
    score_1 = _int(team_1.get("score"))
    score_2 = _int(team_2.get("score"))
    n_maps = len(maps) if maps else None
    vods = detail.get("vods") if isinstance(detail.get("vods"), list) else []
    status = detail.get("status") or listing.get("status")
    url = listing.get("url") or (f"https://www.vlr.gg/{match_id}" if match_id else None)
    now = utc_now()
    name_1 = team_1.get("name") or "TBD"
    name_2 = team_2.get("name") or "TBD"
    match_date = parse_match_date(date_raw, fallback_year=year)
    return {
        "vlr_match_id": match_id,
        "vlr_event_id": event_id,
        "vlr_team_1_id": str(team_1["id"]) if team_1.get("id") else None,
        "vlr_team_2_id": str(team_2["id"]) if team_2.get("id") else None,
        "team_1_name": team_1.get("name"),
        "team_2_name": team_2.get("name"),
        "event_series": listing.get("event_series") or event.get("series"),
        "best_of": _best_of(score_1, score_2, n_maps),
        "team_1_score": score_1,
        "team_2_score": score_2,
        "match_date": match_date,
        "match_date_text": date_raw,
        "match_note": listing.get("note") or None,
        "match_patch": parse_match_patch(str(detail.get("date") or date_raw or "")),
        "n_maps": n_maps,
        "is_completed": _done(status),
        "has_stats": _has_stats(detail),
        "has_vod": bool(vods),
        "has_rib_replay": False,
        "rib_match_id": None,
        "url": url,
        "status": status,
        "map_vetos": detail.get("map_vetos"),
        "insert_date": now,
        "update_date": now,
        "listing": listing,
        "detail": detail,
        "_label": f"{match_id} {name_1} vs {name_2} ({match_date or '?'})",
    }


def _list_one(
    connector: VlrV2Connector,
    repo_root: Path,
    event_id: str,
    cached: set[str],
    lock: threading.Lock,
    skip_listed: bool,
) -> tuple[str, list[dict[str, Any]]]:
    """Fetch /v2/events/matches for one event and cache the list."""
    if skip_listed and event_id in cached:
        return event_id, []
    try:
        matches = connector.get_event_matches(event_id)
    except Exception:
        logger.exception("[matches] List failed event_id=%s", event_id)
        matches = []
    with lock:
        if event_id not in cached:
            append_event_match_list(repo_root, event_id, matches)
            cached.add(event_id)
    return event_id, matches


def _fetch_one(
    connector: VlrV2Connector,
    event_id: str,
    listing: dict[str, Any],
    landing: Landing,
    progress: Progress,
    *,
    skip_existing: bool,
) -> None:
    """Fetch one match detail, land dim + raw JSON, log N/total."""
    match_id = str(listing.get("match_id") or match_id_from_url(str(listing.get("url") or "")) or "")
    team_1 = listing.get("team1") if isinstance(listing.get("team1"), dict) else {}
    team_2 = listing.get("team2") if isinstance(listing.get("team2"), dict) else {}
    label = (
        f"{match_id} {team_1.get('name') or 'TBD'} vs {team_2.get('name') or 'TBD'} "
        f"({parse_match_date(listing.get('date')) or '?'})"
    )
    if not match_id:
        progress.mark("(missing id)", skipped=True)
        return
    if skip_existing and landing.has(match_id):
        progress.mark(label, skipped=True)
        return
    try:
        detail = connector.get_match_details(match_id)
    except Exception:
        logger.exception("[matches] Detail failed match_id=%s; landing list row only", match_id)
        detail = {}
    row = format_row(event_id, listing, detail)
    landing.write(row)
    progress.mark(row.get("_label") or label)


def extract_matches(repo_root: Path | None = None) -> int:
    """List every event's matches, land full /v2/match/details, return row count."""
    load_project_env(repo_root)
    repo_root = _root(repo_root)
    assert_container_rotator()
    connector = VlrV2Connector()
    logger.info("[matches] Health check base=%s", connector.base_url)
    try:
        connector.health()
    except Exception as exc:
        raise RuntimeError(
            f"vlrggapi is not reachable at {connector.base_url}. "
            "Start it with: docker compose up -d --build vlrggapi"
        ) from exc
    event_ids = event_ids_from_jsonl(repo_root)
    if not event_ids:
        raise RuntimeError(
            "data/vlr/events.jsonl is empty. Run the vlr_events job first."
        )
    max_events = os.getenv("VLR_MAX_EVENTS")
    if max_events:
        event_ids = event_ids[: int(max_events)]
        logger.info("[matches] Capped events=%s", len(event_ids))
    skip_listed = os.getenv("VLR_MATCH_SKIP_LISTED", "1") == "1"
    skip_existing = os.getenv("VLR_MATCH_SKIP_EXISTING", "1") == "1"
    list_workers = int(os.getenv("VLR_MATCH_EVENT_WORKERS", "8"))
    detail_workers = int(os.getenv("VLR_MATCH_WORKERS", "8"))
    cached = event_ids_with_match_lists(repo_root)
    cache_lock = threading.Lock()
    logger.info(
        "[matches] Listing events=%s cached_lists=%s workers=%s",
        len(event_ids),
        len(cached),
        list_workers,
    )
    list_connector = VlrV2Connector(max_workers=list_workers)
    # Independent event match lists — parallel; 429/502 retries live in the connector.
    with ThreadPoolExecutor(max_workers=list_workers) as pool:
        futures = [
            pool.submit(
                _list_one,
                list_connector,
                repo_root,
                event_id,
                cached,
                cache_lock,
                skip_listed,
            )
            for event_id in event_ids
        ]
        listed = 0
        for future in as_completed(futures):
            event_id, matches = future.result()
            listed += 1
            logger.info(
                "[matches] list %s/%s event %s matches=%s",
                listed,
                len(event_ids),
                event_id,
                len(matches),
            )
    by_event = read_event_match_lists(repo_root)
    jobs: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for event_id in event_ids:
        for listing in by_event.get(event_id, []):
            match_id = str(
                listing.get("match_id") or match_id_from_url(str(listing.get("url") or "")) or ""
            )
            if not match_id or match_id in seen:
                continue
            seen.add(match_id)
            jobs.append((event_id, listing))
    max_matches = os.getenv("VLR_MAX_MATCHES")
    if max_matches:
        jobs = jobs[: int(max_matches)]
        logger.info("[matches] Capped matches=%s", len(jobs))
    landing = Landing.open(repo_root)
    progress = Progress(total=len(jobs))
    logger.info(
        "[matches] Details matches=%s already=%s skip_existing=%s workers=%s jsonl=%s",
        len(jobs),
        len(landing.ids),
        skip_existing,
        detail_workers,
        matches_jsonl_path(repo_root),
    )
    detail_connector = VlrV2Connector(max_workers=detail_workers)
    # Each match detail is independent I/O; landing/progress use locks.
    with ThreadPoolExecutor(max_workers=detail_workers) as pool:
        futures = [
            pool.submit(
                _fetch_one,
                detail_connector,
                event_id,
                listing,
                landing,
                progress,
                skip_existing=skip_existing,
            )
            for event_id, listing in jobs
        ]
        for future in as_completed(futures):
            future.result()
    count = len(landing.ids)
    logger.info(
        "[matches] Done landed=%s processed=%s/%s lists=%s jsonl=%s",
        count,
        progress.done,
        progress.total,
        event_matches_jsonl_path(repo_root),
        matches_jsonl_path(repo_root),
    )
    return count


def iter_dim_rows(repo_root: Path | None = None):
    """Yield dim columns only so load does not keep full match JSON in memory."""
    path = matches_jsonl_path(_root(repo_root))
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            obj = json_loads_obj(line)
            if not obj or not obj.get("vlr_match_id"):
                continue
            yield {col: obj.get(col) for col in DIM_COLS}


def json_loads_obj(line: str) -> dict[str, Any] | None:
    """Parse one JSONL line; skip corrupt rows so a huge file can still load."""
    import json

    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        logger.warning("[matches] Skip bad JSONL line")
        return None
    return obj if isinstance(obj, dict) else None


def load_matches(repo_root: Path | None = None) -> int:
    """Upsert dim columns from matches.jsonl; keep row_number on re-run."""
    load_project_env(repo_root)
    repo_root = _root(repo_root)
    logger.info("[matches] Load start jsonl=%s", matches_jsonl_path(repo_root))
    connector = SupabaseConnector()
    total = 0
    batch: list[dict[str, Any]] = []
    for row in iter_dim_rows(repo_root):
        batch.append(row)
        if len(batch) >= 1000:
            total += connector.upsert_rows(
                batch,
                schema="vlr",
                table="dim_matches",
                columns=DIM_COLS,
                conflict_column="vlr_match_id",
                update_columns=[c for c in DIM_COLS if c not in {"vlr_match_id", "insert_date"}],
            )
            logger.info("[matches] Load progress upserted=%s", total)
            batch = []
    if batch:
        total += connector.upsert_rows(
            batch,
            schema="vlr",
            table="dim_matches",
            columns=DIM_COLS,
            conflict_column="vlr_match_id",
            update_columns=[c for c in DIM_COLS if c not in {"vlr_match_id", "insert_date"}],
        )
    logger.info("[matches] Load done upserted=%s", total)
    return total


def apply_matches_schema(repo_root: Path | None = None) -> Path:
    """Create vlr.dim_matches if missing; ADD / ALTER columns if the shape drifted."""
    load_project_env(repo_root)
    repo_root = _root(repo_root)
    sql_path = repo_root / "src" / "backend" / "sql" / "ddl" / "vlr_dim_matches.sql"
    logger.info("[matches] Ensuring schema %s", sql_path)
    connector = SupabaseConnector()
    connector.execute_sql_file(sql_path)
    connector.ensure_table_columns("vlr", "dim_matches", DIM_TYPES)
    for stmt in (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_vlr_dim_matches_vlr_match_id "
        "ON vlr.dim_matches (vlr_match_id)",
        "CREATE INDEX IF NOT EXISTS idx_vlr_dim_matches_event ON vlr.dim_matches (vlr_event_id)",
        "CREATE INDEX IF NOT EXISTS idx_vlr_dim_matches_date ON vlr.dim_matches (match_date)",
    ):
        connector.execute(stmt)
    logger.info("[matches] Schema ready (create-if-missing + alter, no drop)")
    return sql_path


def run_matches(repo_root: Path | None = None) -> dict[str, int]:
    """End-to-end historical matches: ensure table, extract JSONL, upsert dim_matches."""
    apply_matches_schema(repo_root)
    extracted = extract_matches(repo_root)
    loaded = load_matches(repo_root)
    return {"extracted": extracted, "loaded": loaded}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(run_matches())
