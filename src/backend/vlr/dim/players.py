"""Historical VLR players → players.jsonl → vlr.dim_players via /v2/player profile."""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from backend.api_connectors.ip_rotator_gateway import assert_container_rotator
from backend.api_connectors.vlr_v2_connector import VlrV2Connector
from backend.config.env import load_project_env
from backend.vlr.dim.from_landings import FLAG_TO_COUNTRY
from backend.vlr.dim.load import apply_dim_schema, stamp_rows, upsert_dim_rows
from backend.vlr.dim.util import (
    events_jsonl_path,
    json_dumps,
    player_ids_in_jsonl,
    player_social_links_map,
    players_jsonl_path,
    serialize_player_row,
    teams_jsonl_path,
    utc_now,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[4]
SITE_BASE = "https://www.vlr.gg"

DIM_COLS = (
    "vlr_player_id",
    "rib_player_id",
    "ign",
    "full_name",
    "first_name",
    "last_name",
    "country_flag",
    "country_name",
    "image_url",
    "player_href",
    "vlr_team_id",
    "current_team_name",
    "current_team_joined",
    "social_links_json",
    "teams_json",
    "insert_date",
    "update_date",
)
JSON_COLS = ("social_links_json", "teams_json")
DIM_TYPES = {
    "row_number": "BIGINT",
    "vlr_player_id": "TEXT",
    "rib_player_id": "BIGINT",
    "ign": "TEXT",
    "full_name": "TEXT",
    "first_name": "TEXT",
    "last_name": "TEXT",
    "country_flag": "TEXT",
    "country_name": "TEXT",
    "image_url": "TEXT",
    "player_href": "TEXT",
    "vlr_team_id": "TEXT",
    "current_team_name": "TEXT",
    "current_team_joined": "TEXT",
    "social_links_json": "JSONB",
    "teams_json": "JSONB",
    "insert_date": "TIMESTAMPTZ",
    "update_date": "TIMESTAMPTZ",
}

_DATE_SPLIT_RE = re.compile(r"\s*[–—\-]\s*")
_JOINED_RE = re.compile(r"^joined in\s+(.+)$", re.I)
_LEFT_RE = re.compile(r"^left in\s+(.+)$", re.I)


def _root(repo_root: Path | None) -> Path:
    """Resolve the git root so JSON landings stay under data/vlr."""
    return Path(repo_root or REPO_ROOT)


def _text(value: Any) -> str | None:
    """Trim API scalars; empty string becomes null so upserts stay clean."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _profile_usable(profile: dict[str, Any] | None) -> bool:
    """True when /v2/player returned a real person (skip 429/empty stubs)."""
    if not isinstance(profile, dict):
        return False
    return bool(_text(profile.get("id")) and _text(profile.get("name")))


def _split_full_name(full_name: str | None) -> tuple[str | None, str | None]:
    """First token = first_name; remainder = last_name (handles multi-word surnames)."""
    if not full_name:
        return None, None
    parts = full_name.split()
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


def _stint_dates(raw: str | None, *, is_current: bool) -> tuple[str | None, str | None]:
    """Parse VLR 'joined in …' / 'left in …' / 'Jan 2025 – Nov 2025' into (joined_at, left_at)."""
    text = _text(raw)
    if not text:
        return None, None
    joined_match = _JOINED_RE.match(text)
    if joined_match:
        return joined_match.group(1).strip() or None, None
    left_match = _LEFT_RE.match(text)
    if left_match:
        return None, left_match.group(1).strip() or None
    parts = [p.strip() for p in _DATE_SPLIT_RE.split(text) if p.strip()]
    if len(parts) >= 2:
        left = parts[1]
        if left.lower() in {"present", "now", "current"}:
            left = None
        return parts[0] or None, left
    if is_current:
        return text, None
    return None, text


def _team_status(raw: dict[str, Any]) -> str | None:
    """wf-tag on the player page is stand-in/inactive, not the org short code."""
    tag = _text(raw.get("tag"))
    if not tag:
        return None
    if tag.lower() in {"stand-in", "inactive", "loan", "loaned"}:
        return tag
    return tag


def team_id_lookup(repo_root: Path) -> dict[str, str]:
    """Map unique team_name → vlr_team_id so player stints can join when the API omits id."""
    path = teams_jsonl_path(repo_root)
    counts: dict[str, set[str]] = {}
    if not path.exists():
        logger.info("[players] Team lookup skip missing %s", path)
        return {}
    logger.info("[players] Team name lookup path=%s", path)
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            team_id = _text(obj.get("vlr_team_id"))
            name = _text(obj.get("team_name"))
            if not team_id or not name:
                continue
            counts.setdefault(name.lower(), set()).add(team_id)
    lookup = {name: next(iter(ids)) for name, ids in counts.items() if len(ids) == 1}
    logger.info("[players] Team lookup unique_names=%s", len(lookup))
    return lookup


def _resolve_team_id(raw: dict[str, Any], lookup: dict[str, str]) -> str | None:
    """Prefer API team id; else unique name match from teams.jsonl."""
    team_id = _text(raw.get("id") or raw.get("vlr_team_id"))
    if team_id:
        return team_id
    name = _text(raw.get("name") or raw.get("team_name"))
    if not name:
        return None
    return lookup.get(name.lower())


def _stint_json(raw: dict[str, Any], lookup: dict[str, str], *, is_current: bool) -> dict[str, Any] | None:
    """One team history object keyed by vlr_team_id; left_at is null while current."""
    name = _text(raw.get("name") or raw.get("team_name"))
    if not name:
        return None
    dates_raw = raw.get("joined") if is_current else raw.get("dates")
    joined_at, left_at = _stint_dates(_text(dates_raw), is_current=is_current)
    row: dict[str, Any] = {
        "vlr_team_id": _resolve_team_id(raw, lookup),
        "team_name": name,
        "joined_at": joined_at,
        "left_at": None if is_current else left_at,
        "status": _team_status(raw),
    }
    return row


def format_row(profile: dict[str, Any], *, lookup: dict[str, str]) -> dict[str, Any]:
    """Map /v2/player onto dim_players: identity columns + teams_json with leave dates."""
    player_id = _text(profile.get("id")) or ""
    ign = _text(profile.get("name"))
    full_name = _text(profile.get("real_name"))
    first_name, last_name = _split_full_name(full_name)
    flag = (_text(profile.get("country")) or "").lower() or None
    current_raw = profile.get("current_team") if isinstance(profile.get("current_team"), dict) else {}
    past_raw = profile.get("past_teams") if isinstance(profile.get("past_teams"), list) else []
    current_stint = _stint_json(current_raw, lookup, is_current=True) if current_raw else None
    past_stints = [
        stint
        for item in past_raw
        if isinstance(item, dict)
        for stint in [_stint_json(item, lookup, is_current=False)]
        if stint
    ]
    teams: list[dict[str, Any]] = []
    if current_stint:
        teams.append(current_stint)
    teams.extend(past_stints)
    now = utc_now()
    return {
        "vlr_player_id": player_id,
        "rib_player_id": None,
        "ign": ign,
        "full_name": full_name,
        "first_name": first_name,
        "last_name": last_name,
        "country_flag": flag,
        "country_name": FLAG_TO_COUNTRY.get(flag, flag.upper() if flag else None) if flag else None,
        "image_url": _text(profile.get("avatar")),
        "player_href": f"{SITE_BASE}/player/{player_id}" if player_id else None,
        "vlr_team_id": current_stint.get("vlr_team_id") if current_stint else None,
        "current_team_name": current_stint.get("team_name") if current_stint else None,
        "current_team_joined": current_stint.get("joined_at") if current_stint else None,
        "social_links_json": player_social_links_map(profile.get("social_links")),
        "teams_json": teams,
        "insert_date": now,
        "update_date": now,
        "current_team": current_raw,
        "past_teams": past_raw,
        "social_links": profile.get("social_links") if isinstance(profile.get("social_links"), list) else [],
    }


def collect_player_ids(repo_root: Path) -> list[str]:
    """Unique vlr_player_id from event rosters + team profile rosters (no extra scrape)."""
    ids: dict[str, None] = {}
    events_path = events_jsonl_path(repo_root)
    logger.info("[players] Scan event rosters path=%s", events_path)
    if events_path.exists():
        scanned = 0
        with events_path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                scanned += 1
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                teams = obj.get("teams_json") or []
                if isinstance(teams, str):
                    try:
                        teams = json.loads(teams)
                    except json.JSONDecodeError:
                        teams = []
                if not isinstance(teams, list):
                    continue
                for team in teams:
                    if not isinstance(team, dict):
                        continue
                    for player in team.get("players") or []:
                        if not isinstance(player, dict):
                            continue
                        player_id = _text(player.get("id"))
                        if player_id:
                            ids[player_id] = None
                if scanned % 500 == 0:
                    logger.info("[players] Event scan events=%s players=%s", scanned, len(ids))
        logger.info("[players] Event scan done events=%s players=%s", scanned, len(ids))
    teams_path = teams_jsonl_path(repo_root)
    logger.info("[players] Scan team rosters path=%s", teams_path)
    if teams_path.exists():
        scanned = 0
        with teams_path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                scanned += 1
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                for person in obj.get("roster") or []:
                    if not isinstance(person, dict):
                        continue
                    player_id = _text(person.get("id"))
                    if player_id:
                        ids[player_id] = None
                if scanned % 5000 == 0:
                    logger.info("[players] Team scan lines=%s players=%s", scanned, len(ids))
        logger.info("[players] Team scan done lines=%s players=%s", scanned, len(ids))
    out = list(ids.keys())
    logger.info("[players] Unique player ids=%s", len(out))
    return out


def _run_pool(items: list[Any], fn: Callable[[Any], None], workers: int) -> None:
    """Bounded in-flight work so 28k player ids do not create 28k Future objects."""
    if not items:
        return
    work: queue.Queue = queue.Queue(maxsize=max(workers * 4, 32))
    errors: list[BaseException] = []
    stop = threading.Event()

    def consume() -> None:
        while True:
            item = work.get()
            try:
                if item is None:
                    return
                if stop.is_set():
                    return
                fn(item)
            except Exception as exc:
                errors.append(exc)
                stop.set()
            finally:
                work.task_done()

    threads = [threading.Thread(target=consume, daemon=True) for _ in range(workers)]
    for thread in threads:
        thread.start()
    try:
        for item in items:
            if stop.is_set():
                break
            work.put(item)
    finally:
        for _ in threads:
            work.put(None)
        for thread in threads:
            thread.join()
    if errors:
        raise errors[0]


@dataclass
class Progress:
    """Log extract pace so Dagster shows where /v2/player is."""

    total: int
    done: int = 0
    failed: int = 0
    t0: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def mark(self, label: str, *, failed: bool = False) -> None:
        with self.lock:
            self.done += 1
            if failed:
                self.failed += 1
            if self.done % 50 == 0 or self.done == self.total or failed:
                elapsed = max(time.monotonic() - self.t0, 0.001)
                rate = self.done / elapsed
                logger.info(
                    "[players] %s/%s %.1f/s fail=%s %s",
                    self.done,
                    self.total,
                    rate,
                    self.failed,
                    label,
                )


@dataclass
class Landing:
    """Append-only players.jsonl with one open handle so writes stay cheap."""

    repo_root: Path
    ids: set[str]
    handle: Any
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    written: int = 0

    @classmethod
    def open(cls, repo_root: Path) -> Landing:
        """Load existing ids so a resume appends only missing profiles."""
        path = players_jsonl_path(repo_root)
        logger.info("[players] Scanning landed ids path=%s", path)
        ids = player_ids_in_jsonl(repo_root)
        logger.info("[players] Already landed=%s", len(ids))
        handle = path.open("a", encoding="utf-8")
        return cls(repo_root=repo_root, ids=ids, handle=handle)

    def has(self, player_id: str) -> bool:
        with self.lock:
            return player_id in self.ids

    def write(self, row: dict[str, Any]) -> bool:
        """Append one landing line. Serialize off the lock; write under the lock."""
        player_id = str(row.get("vlr_player_id") or "")
        if not player_id:
            return False
        payload = json.dumps(serialize_player_row(row), ensure_ascii=False, default=str)
        with self.lock:
            if player_id in self.ids:
                return False
            self.handle.write(payload + "\n")
            self.ids.add(player_id)
            self.written += 1
            if self.written % 16 == 0:
                self.handle.flush()
            return True

    def close(self) -> None:
        with self.lock:
            self.handle.flush()
            self.handle.close()


def _fetch_one(
    connector: VlrV2Connector,
    player_id: str,
    landing: Landing,
    progress: Progress,
    lookup: dict[str, str],
) -> None:
    """GET /v2/player?q=profile for one id; skip land on empty/error so resume retries."""
    label = f"player_id={player_id}"
    try:
        profile = connector.get_player_profile(player_id, timespan="all")
    except Exception as exc:
        logger.warning("[players] Profile failed player_id=%s err=%s; not landed", player_id, exc)
        progress.mark(label, failed=True)
        return
    if not _profile_usable(profile):
        logger.warning("[players] Empty profile player_id=%s; not landed", player_id)
        progress.mark(label, failed=True)
        return
    landing.write(format_row(profile, lookup=lookup))
    progress.mark(label)


def extract_players(repo_root: Path | None = None) -> int:
    """GET /v2/player for every known id; resume skips usable rows in players.jsonl."""
    load_project_env(repo_root)
    repo_root = _root(repo_root)
    assert_container_rotator()
    connector = VlrV2Connector()
    logger.info("[players] Health check base=%s", connector.base_url)
    try:
        connector.health()
    except Exception as exc:
        raise RuntimeError(
            f"vlrggapi is not reachable at {connector.base_url}. "
            "Start it with: docker compose up -d --build vlrggapi"
        ) from exc
    player_ids = collect_player_ids(repo_root)
    if not player_ids:
        raise RuntimeError(
            "No vlr_player_id found in events.jsonl / teams.jsonl. Run vlr_events and vlr_teams first."
        )
    max_players = os.getenv("VLR_MAX_PLAYERS")
    if max_players:
        player_ids = player_ids[: int(max_players)]
        logger.info("[players] Capped players=%s", len(player_ids))
    skip_existing = os.getenv("VLR_PLAYER_SKIP_EXISTING", "1") == "1"
    workers = int(os.getenv("VLR_PLAYER_WORKERS", os.getenv("VLR_MATCH_WORKERS", "6")))
    lookup = team_id_lookup(repo_root)
    landing = Landing.open(repo_root)
    pending = [pid for pid in player_ids if not (skip_existing and landing.has(pid))]
    progress = Progress(total=len(pending))
    logger.info(
        "[players] Profiles pending=%s already=%s workers=%s concurrency=%s jsonl=%s",
        len(pending),
        len(landing.ids),
        workers,
        os.getenv("VLR_API_CONCURRENCY", "6"),
        players_jsonl_path(repo_root),
    )
    detail_connector = VlrV2Connector(max_workers=workers, timeout=60)

    def _one(player_id: str) -> None:
        _fetch_one(detail_connector, player_id, landing, progress, lookup)

    try:
        # Independent /v2/player I/O; landing/progress use locks.
        _run_pool(pending, _one, workers)
    finally:
        landing.close()
    count = len(landing.ids)
    logger.info(
        "[players] Done landed=%s processed=%s/%s jsonl=%s",
        count,
        progress.done,
        progress.total,
        players_jsonl_path(repo_root),
    )
    return count


def json_loads_obj(line: str) -> dict[str, Any] | None:
    """Parse one JSONL line; skip corrupt rows so a huge file can still load."""
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        logger.warning("[players] Skip bad JSONL line")
        return None
    return obj if isinstance(obj, dict) else None


def _row_rank(row: dict[str, Any]) -> tuple[int, int, int]:
    """Prefer a profile with full name / current team / socials when jsonl has duplicates."""
    teams = row.get("teams_json")
    has_teams = bool(teams) and teams not in ("[]", None, [])
    socials = row.get("social_links_json")
    has_socials = False
    if isinstance(socials, dict):
        has_socials = bool(socials.get("twitter") or socials.get("twitch"))
    elif isinstance(socials, str) and socials not in ("{}", "[]", ""):
        has_socials = '"twitter": "' in socials or '"twitch": "' in socials
    elif isinstance(socials, list) and socials:
        has_socials = True
    return (
        1 if row.get("full_name") else 0,
        1 if has_teams else 0,
        1 if has_socials else 0,
    )


def _as_jsonb(value: Any) -> str | None:
    """JSONB upsert wants JSON text; jsonl may already store a list."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json_dumps(value)


def unique_dim_rows(repo_root: Path | None = None) -> list[dict[str, Any]]:
    """One dim row per player id. Postgres ON CONFLICT cannot update the same key twice."""
    path = players_jsonl_path(_root(repo_root))
    by_id: dict[str, dict[str, Any]] = {}
    scanned = 0
    if not path.exists():
        logger.info("[players] Load skip missing jsonl=%s", path)
        return []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            obj = json_loads_obj(line)
            if not obj:
                continue
            scanned += 1
            player_id = str(obj.get("vlr_player_id") or "")
            if not player_id:
                continue
            row = {col: obj.get(col) for col in DIM_COLS}
            if row.get("social_links_json") is None:
                row["social_links_json"] = player_social_links_map(obj.get("social_links"))
            else:
                row["social_links_json"] = player_social_links_map(row.get("social_links_json"))
            if row.get("teams_json") is None:
                lookup: dict[str, str] = {}
                rebuilt = format_row(
                    {
                        "id": obj.get("vlr_player_id"),
                        "name": obj.get("ign"),
                        "real_name": obj.get("full_name"),
                        "country": obj.get("country_flag"),
                        "avatar": obj.get("image_url"),
                        "social_links": obj.get("social_links") or [],
                        "current_team": obj.get("current_team") or {},
                        "past_teams": obj.get("past_teams") or [],
                    },
                    lookup=lookup,
                )
                row["teams_json"] = rebuilt["teams_json"]
            row["social_links_json"] = _as_jsonb(row.get("social_links_json"))
            row["teams_json"] = _as_jsonb(row.get("teams_json"))
            prev = by_id.get(player_id)
            if prev is None or _row_rank(row) >= _row_rank(prev):
                by_id[player_id] = row
            if scanned % 5000 == 0:
                logger.info("[players] Load scan lines=%s unique=%s", scanned, len(by_id))
    logger.info("[players] Load scan done lines=%s unique=%s", scanned, len(by_id))
    return stamp_rows(list(by_id.values()))


def load_players(repo_root: Path | None = None) -> int:
    """Upsert dim columns from players.jsonl; keep row_number on re-run."""
    load_project_env(repo_root)
    repo_root = _root(repo_root)
    logger.info("[players] Load start jsonl=%s", players_jsonl_path(repo_root))
    rows = unique_dim_rows(repo_root)
    loaded = upsert_dim_rows(
        rows,
        table="dim_players",
        columns=DIM_COLS,
        conflict_column="vlr_player_id",
        jsonb_columns=JSON_COLS,
    )
    logger.info("[players] Load done upserted=%s", loaded)
    return loaded


def apply_players_schema(repo_root: Path | None = None) -> Path:
    """Create vlr.dim_players if missing; ADD / ALTER profile columns (no DROP)."""
    load_project_env(repo_root)
    repo_root = _root(repo_root)
    logger.info("[players] Ensuring schema")
    path = apply_dim_schema(
        repo_root,
        "vlr_dim_players.sql",
        "dim_players",
        DIM_TYPES,
        indexes=(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_vlr_dim_players_vlr_player_id "
            "ON vlr.dim_players (vlr_player_id)",
            "CREATE INDEX IF NOT EXISTS idx_vlr_dim_players_team ON vlr.dim_players (vlr_team_id)",
            "CREATE INDEX IF NOT EXISTS idx_vlr_dim_players_country ON vlr.dim_players (country_name)",
        ),
    )
    logger.info("[players] Schema ready (create-if-missing + alter, no drop)")
    return path


def run_players(repo_root: Path | None = None) -> dict[str, int]:
    """End-to-end: ensure table, extract /v2/player, upsert dim_players."""
    apply_players_schema(repo_root)
    extracted = extract_players(repo_root)
    loaded = load_players(repo_root)
    return {"extracted": extracted, "loaded": loaded}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(run_players())
