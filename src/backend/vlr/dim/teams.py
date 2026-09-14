"""Historical VLR teams → teams.jsonl → vlr.dim_teams via /v2/team profile."""

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
from backend.api_connectors.vlr_v2_connector import RANKING_REGIONS, VlrV2Connector
from backend.config.env import load_project_env
from backend.vlr.dim.load import apply_dim_schema, stamp_rows, upsert_dim_rows
from backend.vlr.dim.util import (
    events_jsonl_path,
    json_dumps,
    matches_jsonl_path,
    serialize_team_row,
    team_ids_in_jsonl,
    teams_jsonl_path,
    utc_now,
)
from backend.vlr.regions import normalize_region_code

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[4]
SITE_BASE = "https://www.vlr.gg"

DIM_COLS = (
    "vlr_team_id",
    "rib_team_id",
    "region_code",
    "country_name",
    "country_flag",
    "team_name",
    "team_code",
    "logo_url",
    "team_href",
    "division",
    "current_roster_json",
    "coaches_json",
    "assistant_coaches_json",
    "coach_vlr_player_id",
    "insert_date",
    "update_date",
)
JSON_COLS = ("current_roster_json", "coaches_json", "assistant_coaches_json")
DIM_TYPES = {
    "row_number": "BIGINT",
    "vlr_team_id": "TEXT",
    "rib_team_id": "BIGINT",
    "region_code": "TEXT",
    "country_name": "TEXT",
    "country_flag": "TEXT",
    "team_name": "TEXT",
    "team_code": "TEXT",
    "logo_url": "TEXT",
    "team_href": "TEXT",
    "division": "TEXT",
    "current_roster_json": "JSONB",
    "coaches_json": "JSONB",
    "assistant_coaches_json": "JSONB",
    "coach_vlr_player_id": "TEXT",
    "insert_date": "TIMESTAMPTZ",
    "update_date": "TIMESTAMPTZ",
}

_TEAM_1_ID_RE = re.compile(r'"vlr_team_1_id"\s*:\s*"([^"]+)"')
_TEAM_2_ID_RE = re.compile(r'"vlr_team_2_id"\s*:\s*"([^"]+)"')


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
    """True when /v2/team returned a real org (skip 429/empty stubs)."""
    if not isinstance(profile, dict):
        return False
    team_id = _text(profile.get("id"))
    name = _text(profile.get("name"))
    return bool(team_id and name)


def _person_json(person: dict[str, Any], *, include_role: bool) -> dict[str, Any] | None:
    """One joinable {vlr_player_id, ign} object; coaches also keep role text."""
    player_id = _text(person.get("id"))
    if not player_id:
        return None
    row: dict[str, Any] = {
        "vlr_player_id": player_id,
        "ign": _text(person.get("alias")) or _text(person.get("name")),
    }
    if include_role:
        row["role"] = _text(person.get("role"))
    return row


def split_current_roster(roster: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Split VLR current roster: active players vs head/other coaches vs assistant coaches.

    vlrggapi puts coaches in the same list as players and is_staff is often false, so classify on role.
    """
    players: list[dict[str, Any]] = []
    coaches: list[dict[str, Any]] = []
    assistants: list[dict[str, Any]] = []
    if not isinstance(roster, list):
        return players, coaches, assistants
    for person in roster:
        if not isinstance(person, dict):
            continue
        role = str(person.get("role") or "").strip().lower()
        if "assistant" in role:
            row = _person_json(person, include_role=True)
            if row:
                assistants.append(row)
            continue
        if "coach" in role:
            row = _person_json(person, include_role=True)
            if row:
                coaches.append(row)
            continue
        row = _person_json(person, include_role=False)
        if row:
            players.append(row)
    return players, coaches, assistants


def _coach_vlr_player_id(coaches: list[dict[str, Any]]) -> str | None:
    """Scalar head-coach id for a simple join; full list lives in coaches_json."""
    if not coaches:
        return None
    head = next((p for p in coaches if "head" in str(p.get("role") or "").lower()), coaches[0])
    return _text(head.get("vlr_player_id"))


def _run_pool(items: list[Any], fn: Callable[[Any], None], workers: int) -> None:
    """Bounded in-flight work so 21k team ids do not create 21k Future objects."""
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
    """Log extract pace so Dagster shows where /v2/team is."""

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
                    "[teams] %s/%s %.1f/s fail=%s %s",
                    self.done,
                    self.total,
                    rate,
                    self.failed,
                    label,
                )


@dataclass
class Landing:
    """Append-only teams.jsonl with one open handle so writes stay cheap."""

    repo_root: Path
    ids: set[str]
    handle: Any
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    written: int = 0

    @classmethod
    def open(cls, repo_root: Path) -> Landing:
        """Load existing ids so a resume appends only missing profiles."""
        path = teams_jsonl_path(repo_root)
        logger.info("[teams] Scanning landed ids path=%s", path)
        ids = team_ids_in_jsonl(repo_root)
        logger.info("[teams] Already landed=%s", len(ids))
        handle = path.open("a", encoding="utf-8")
        return cls(repo_root=repo_root, ids=ids, handle=handle)

    def has(self, team_id: str) -> bool:
        with self.lock:
            return team_id in self.ids

    def write(self, row: dict[str, Any]) -> bool:
        """Append one landing line. Serialize off the lock; write under the lock."""
        team_id = str(row.get("vlr_team_id") or "")
        if not team_id:
            return False
        payload = json.dumps(serialize_team_row(row), ensure_ascii=False, default=str)
        with self.lock:
            if team_id in self.ids:
                return False
            self.handle.write(payload + "\n")
            self.ids.add(team_id)
            self.written += 1
            if self.written % 16 == 0:
                self.handle.flush()
            return True

    def close(self) -> None:
        with self.lock:
            self.handle.flush()
            self.handle.close()


def collect_team_ids(repo_root: Path) -> list[str]:
    """Unique vlr_team_id from event rosters + match dim fields (no extra scrape)."""
    ids: dict[str, None] = {}
    events_path = events_jsonl_path(repo_root)
    logger.info("[teams] Scan event rosters path=%s", events_path)
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
                    team_id = _text(team.get("id"))
                    if team_id:
                        ids[team_id] = None
                if scanned % 500 == 0:
                    logger.info("[teams] Event scan events=%s teams=%s", scanned, len(ids))
        logger.info("[teams] Event scan done events=%s teams=%s", scanned, len(ids))
    matches_path = matches_jsonl_path(repo_root)
    logger.info("[teams] Scan match team ids path=%s", matches_path)
    if matches_path.exists():
        scanned = 0
        with matches_path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                scanned += 1
                head = line[:1200]
                for match in (_TEAM_1_ID_RE.search(head), _TEAM_2_ID_RE.search(head)):
                    if match:
                        ids[match.group(1)] = None
                if scanned % 25000 == 0:
                    logger.info("[teams] Match scan lines=%s teams=%s", scanned, len(ids))
        logger.info("[teams] Match scan done lines=%s teams=%s", scanned, len(ids))
    out = list(ids.keys())
    logger.info("[teams] Unique team ids=%s", len(out))
    return out


def ranking_region_lookup(connector: VlrV2Connector) -> dict[tuple[str, str], str]:
    """Map (team_name, country) → local region_code; rankings usually omit team id."""
    logger.info("[teams] Rankings overlay regions=%s", len(RANKING_REGIONS))
    batches = connector.map_parallel(
        list(RANKING_REGIONS),
        lambda region: (region, connector.get_rankings(region)),
        desc="rankings",
    )
    lookup: dict[tuple[str, str], str] = {}
    for region, segments in batches:
        parsed = normalize_region_code(region)
        local_code = parsed[1] if parsed and parsed[0] == "local" else _text(region)
        if not local_code:
            continue
        for segment in segments or []:
            if not isinstance(segment, dict):
                continue
            name = _text(segment.get("team"))
            country = _text(segment.get("country"))
            if not name:
                continue
            key = (name.lower(), (country or "").lower())
            lookup.setdefault(key, local_code)
    logger.info("[teams] Rankings overlay keys=%s", len(lookup))
    return lookup


def format_row(
    profile: dict[str, Any],
    *,
    region_lookup: dict[tuple[str, str], str],
) -> dict[str, Any]:
    """Map /v2/team profile onto dim_teams columns plus roster for later player work."""
    team_id = _text(profile.get("id")) or ""
    name = _text(profile.get("name"))
    country_name = _text(profile.get("country_name"))
    country_flag = _text(profile.get("country"))
    region_code = None
    if name:
        region_code = region_lookup.get((name.lower(), (country_name or "").lower()))
        if region_code is None:
            region_code = region_lookup.get((name.lower(), ""))
    roster = profile.get("roster") if isinstance(profile.get("roster"), list) else []
    players, coaches, assistants = split_current_roster(roster)
    now = utc_now()
    return {
        "vlr_team_id": team_id,
        "rib_team_id": None,
        "region_code": region_code,
        "country_name": country_name,
        "country_flag": country_flag,
        "team_name": name,
        "team_code": _text(profile.get("tag")),
        "logo_url": _text(profile.get("logo")),
        "team_href": f"{SITE_BASE}/team/{team_id}" if team_id else None,
        "division": None,
        "current_roster_json": players,
        "coaches_json": coaches,
        "assistant_coaches_json": assistants,
        "coach_vlr_player_id": _coach_vlr_player_id(coaches),
        "insert_date": now,
        "update_date": now,
        "roster": roster,
        "social_links": profile.get("social_links") if isinstance(profile.get("social_links"), list) else [],
        "total_winnings": _text(profile.get("total_winnings")),
    }


def _fetch_one(
    connector: VlrV2Connector,
    team_id: str,
    landing: Landing,
    progress: Progress,
    region_lookup: dict[tuple[str, str], str],
) -> None:
    """GET /v2/team?q=profile for one id; skip land on empty/error so resume retries."""
    label = f"team_id={team_id}"
    try:
        profile = connector.get_team_profile(team_id)
    except Exception as exc:
        logger.warning("[teams] Profile failed team_id=%s err=%s; not landed", team_id, exc)
        progress.mark(label, failed=True)
        return
    if not _profile_usable(profile):
        logger.warning("[teams] Empty profile team_id=%s; not landed", team_id)
        progress.mark(label, failed=True)
        return
    landing.write(format_row(profile, region_lookup=region_lookup))
    progress.mark(label)


def extract_teams(repo_root: Path | None = None) -> int:
    """GET /v2/team for every known id; resume skips usable rows in teams.jsonl."""
    load_project_env(repo_root)
    repo_root = _root(repo_root)
    assert_container_rotator()
    connector = VlrV2Connector()
    logger.info("[teams] Health check base=%s", connector.base_url)
    try:
        connector.health()
    except Exception as exc:
        raise RuntimeError(
            f"vlrggapi is not reachable at {connector.base_url}. "
            "Start it with: docker compose up -d --build vlrggapi"
        ) from exc
    team_ids = collect_team_ids(repo_root)
    if not team_ids:
        raise RuntimeError(
            "No vlr_team_id found in events.jsonl / matches.jsonl. Run vlr_events (and vlr_matches) first."
        )
    max_teams = os.getenv("VLR_MAX_TEAMS")
    if max_teams:
        team_ids = team_ids[: int(max_teams)]
        logger.info("[teams] Capped teams=%s", len(team_ids))
    skip_existing = os.getenv("VLR_TEAM_SKIP_EXISTING", "1") == "1"
    workers = int(os.getenv("VLR_TEAM_WORKERS", os.getenv("VLR_MATCH_WORKERS", "6")))
    ranking_connector = VlrV2Connector(max_workers=min(workers, len(RANKING_REGIONS) or 1))
    region_lookup = ranking_region_lookup(ranking_connector)
    landing = Landing.open(repo_root)
    if skip_existing:
        pending = [tid for tid in team_ids if not landing.has(tid)]
    else:
        pending = team_ids
    progress = Progress(total=len(pending))
    logger.info(
        "[teams] Profiles pending=%s already=%s workers=%s concurrency=%s jsonl=%s",
        len(pending),
        len(landing.ids),
        workers,
        os.getenv("VLR_API_CONCURRENCY", "6"),
        teams_jsonl_path(repo_root),
    )
    detail_connector = VlrV2Connector(max_workers=workers, timeout=60)

    def _one(team_id: str) -> None:
        _fetch_one(detail_connector, team_id, landing, progress, region_lookup)

    try:
        # Independent /v2/team I/O; landing/progress use locks.
        _run_pool(pending, _one, workers)
    finally:
        landing.close()
    count = len(landing.ids)
    logger.info(
        "[teams] Done landed=%s processed=%s/%s jsonl=%s",
        count,
        progress.done,
        progress.total,
        teams_jsonl_path(repo_root),
    )
    return count


def json_loads_obj(line: str) -> dict[str, Any] | None:
    """Parse one JSONL line; skip corrupt rows so a huge file can still load."""
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        logger.warning("[teams] Skip bad JSONL line")
        return None
    return obj if isinstance(obj, dict) else None


def _row_rank(row: dict[str, Any]) -> tuple[int, int, int, int]:
    """Prefer a profile with roster JSON + tag/country when jsonl has the same team twice."""
    roster = row.get("current_roster_json")
    has_roster = bool(roster) and roster not in ("[]", None, [])
    return (
        1 if has_roster else 0,
        1 if row.get("team_code") else 0,
        1 if row.get("country_name") else 0,
        1 if row.get("logo_url") else 0,
    )


def _fill_roster_json(obj: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """Use pre-split JSON columns, or rebuild them from a raw profile roster list."""
    players = obj.get("current_roster_json")
    coaches = obj.get("coaches_json")
    assistants = obj.get("assistant_coaches_json")
    if players is None or coaches is None or assistants is None:
        split_players, split_coaches, split_assistants = split_current_roster(obj.get("roster"))
        if players is None:
            players = split_players
        if coaches is None:
            coaches = split_coaches
        if assistants is None:
            assistants = split_assistants
    row["current_roster_json"] = json_dumps(players) if not isinstance(players, str) else players
    row["coaches_json"] = json_dumps(coaches) if not isinstance(coaches, str) else coaches
    row["assistant_coaches_json"] = (
        json_dumps(assistants) if not isinstance(assistants, str) else assistants
    )
    if not row.get("coach_vlr_player_id"):
        parsed = coaches
        if isinstance(parsed, str):
            try:
                parsed = json.loads(parsed)
            except json.JSONDecodeError:
                parsed = []
        row["coach_vlr_player_id"] = _coach_vlr_player_id(parsed if isinstance(parsed, list) else [])
    return row


def unique_dim_rows(repo_root: Path | None = None) -> list[dict[str, Any]]:
    """One dim row per team id. Postgres ON CONFLICT cannot update the same key twice."""
    path = teams_jsonl_path(_root(repo_root))
    by_id: dict[str, dict[str, Any]] = {}
    scanned = 0
    if not path.exists():
        logger.info("[teams] Load skip missing jsonl=%s", path)
        return []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            obj = json_loads_obj(line)
            if not obj:
                continue
            scanned += 1
            team_id = str(obj.get("vlr_team_id") or "")
            if not team_id:
                continue
            row = {col: obj.get(col) for col in DIM_COLS}
            row = _fill_roster_json(obj, row)
            prev = by_id.get(team_id)
            if prev is None or _row_rank(row) >= _row_rank(prev):
                by_id[team_id] = row
            if scanned % 5000 == 0:
                logger.info("[teams] Load scan lines=%s unique=%s", scanned, len(by_id))
    logger.info("[teams] Load scan done lines=%s unique=%s", scanned, len(by_id))
    return stamp_rows(list(by_id.values()))


def load_teams(repo_root: Path | None = None) -> int:
    """Upsert dim columns from teams.jsonl; keep row_number on re-run."""
    load_project_env(repo_root)
    repo_root = _root(repo_root)
    logger.info("[teams] Load start jsonl=%s", teams_jsonl_path(repo_root))
    rows = unique_dim_rows(repo_root)
    loaded = upsert_dim_rows(rows, table="dim_teams", columns=DIM_COLS, conflict_column="vlr_team_id")
    logger.info("[teams] Load done upserted=%s", loaded)
    return loaded


def apply_teams_schema(repo_root: Path | None = None) -> Path:
    """Create vlr.dim_teams if missing; ADD / ALTER profile columns (no DROP)."""
    load_project_env(repo_root)
    repo_root = _root(repo_root)
    logger.info("[teams] Ensuring schema")
    path = apply_dim_schema(
        repo_root,
        "vlr_dim_teams.sql",
        "dim_teams",
        DIM_TYPES,
        indexes=(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_vlr_dim_teams_vlr_team_id "
            "ON vlr.dim_teams (vlr_team_id)",
            "CREATE INDEX IF NOT EXISTS idx_vlr_dim_teams_country ON vlr.dim_teams (country_name)",
            "CREATE INDEX IF NOT EXISTS idx_vlr_dim_teams_region ON vlr.dim_teams (region_code)",
        ),
    )
    logger.info("[teams] Schema ready (create-if-missing + alter, no drop)")
    return path


def run_teams(repo_root: Path | None = None) -> dict[str, int]:
    """End-to-end: ensure table, extract /v2/team, upsert dim_teams."""
    apply_teams_schema(repo_root)
    extracted = extract_teams(repo_root)
    loaded = load_teams(repo_root)
    return {"extracted": extracted, "loaded": loaded}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(run_teams())
