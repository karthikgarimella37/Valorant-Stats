"""Why: pull only rows since the watermark (minus overlap) into memory — daily volume must stay small."""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from backend.api_connectors.ip_rotator_gateway import assert_container_rotator
from backend.api_connectors.vlr_v2_connector import VlrV2Connector
from backend.config.env import load_project_env
from backend.database_connectors.supabase_connectors import SupabaseConnector
from backend.vlr.dim.historical import (
    DIM_EVENT_COLUMNS,
    format_dim_event_row,
    load_events,
)
from backend.vlr.dim.load import stamp_rows, upsert_dim_rows
from backend.vlr.dim.matches import (
    DIM_COLS as MATCH_DIM_COLS,
    _listing_id,
    _needs_detail,
    format_row as format_match_row,
)
from backend.vlr.dim.players import (
    DIM_COLS as PLAYER_DIM_COLS,
    JSON_COLS as PLAYER_JSON_COLS,
    _profile_usable as player_profile_usable,
    format_row as format_player_row,
)
from backend.vlr.dim.teams import (
    DIM_COLS as TEAM_DIM_COLS,
    JSON_COLS as TEAM_JSON_COLS,
    _profile_usable as team_profile_usable,
    format_row as format_team_row,
    ranking_region_lookup,
)
from backend.vlr.dim.util import (
    event_id_from_url,
    parse_event_dates,
    parse_match_at,
    parse_project_date,
    year_from_text,
)
from backend.vlr.ops.watermarks import iso_seconds
from backend.vlr.fact.pipeline import upsert_facts_from_match_rows
from backend.vlr.fact.tables import FACT_SPECS
from backend.vlr.ops.run import peek_stash, stash

logger = logging.getLogger(__name__)

LIVE_STATUSES = frozenset({"live", "upcoming", "ongoing"})


@dataclass
class ExtractResult:
    """In-memory extract payload passed to merge; extra holds details for later steps."""

    rows: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    max_source_at: datetime | None = None
    has_live: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


def _max_dt(*values: datetime | None) -> datetime | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def _event_end_at(end_raw: Any, start_raw: Any = None) -> datetime | None:
    """Event listings have no clock; treat the end calendar day as 23:59:59 UTC for since compares."""
    day = parse_project_date(str(end_raw or start_raw or "") or None)
    if day is None:
        return None
    return datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=timezone.utc)


def _keep_since(value: datetime | None, since: datetime) -> bool:
    """Keep rows at or after since (last_source_at minus 1 hour). Missing clock → keep."""
    if value is None:
        return True
    return value >= since


def _health() -> VlrV2Connector:
    """Fail loud if vlrggapi is down before we page catalogs."""
    load_project_env()
    assert_container_rotator()
    connector = VlrV2Connector()
    logger.info("[inc] Health check base=%s", connector.base_url)
    try:
        connector.health()
    except Exception as exc:
        raise RuntimeError(
            f"vlrggapi is not reachable at {connector.base_url}. "
            "Start it with: docker compose up -d --build vlrggapi"
        ) from exc
    logger.info("[inc] Health ok base=%s", connector.base_url)
    return connector


def _normalize_listing(segment: dict[str, Any], status: str) -> dict[str, Any] | None:
    """Same event-id fill as the historical catalog so live and completed pages share one shape."""
    url_path = segment.get("url_path") or segment.get("url") or ""
    event_id = str(
        segment.get("event_id") or segment.get("id") or event_id_from_url(str(url_path)) or ""
    )
    if not event_id:
        return None
    row = dict(segment)
    row["id"] = event_id
    row["event_id"] = event_id
    row["status"] = row.get("status") or status
    return row


def _list_status(connector: VlrV2Connector, status: str, max_pages: int, since: datetime | None) -> list[dict[str, Any]]:
    """Page one /v2/events status. Completed stops when a page is entirely older than since."""
    logger.info("[inc] events list start status=%s max_pages=%s since=%s", status, max_pages, iso_seconds(since))
    by_id: dict[str, dict[str, Any]] = {}
    for page in range(1, max_pages + 1):
        segments = connector.get_events_page(page, status)
        if not segments:
            logger.info("[inc] events list empty page=%s status=%s; stop", page, status)
            break
        kept = 0
        older = 0
        unparsed = 0
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            listing = _normalize_listing(segment, status)
            if listing is None:
                continue
            if since is not None and status == "completed":
                name = listing.get("title") or listing.get("name")
                _start, end = parse_event_dates(
                    listing.get("dates"), fallback_year=year_from_text(name, listing.get("dates"))
                )
                end_at = _event_end_at(end, _start)
                if end_at is not None and not _keep_since(end_at, since):
                    older += 1
                    continue
                if end_at is None:
                    unparsed += 1
            by_id[listing["event_id"]] = listing
            kept += 1
        logger.info(
            "[inc] events list status=%s page=%s kept=%s older=%s unparsed=%s unique=%s",
            status,
            page,
            kept,
            older,
            unparsed,
            len(by_id),
        )
        if status == "completed" and since is not None and kept == 0 and older > 0:
            logger.info("[inc] events completed page=%s all older than %s; stop paging", page, iso_seconds(since))
            break
    logger.info("[inc] events list done status=%s unique=%s", status, len(by_id))
    return list(by_id.values())


def _warehouse_event_ids(since: datetime) -> list[str]:
    """Re-fetch live/upcoming events already in the warehouse plus anything touched since the cursor."""
    logger.info("[inc] warehouse dim_events since=%s", iso_seconds(since))
    connector = SupabaseConnector()
    rows = connector.fetch_all(
        """
        SELECT vlr_event_id, status, start_date, end_date, update_date
        FROM vlr.dim_events
        """
    )
    keep: list[str] = []
    live = 0
    recent = 0
    dated = 0
    for event_id, status, start_date, end_date, update_date in rows:
        eid = str(event_id or "")
        if not eid:
            continue
        st = str(status or "").strip().lower()
        if st in LIVE_STATUSES:
            keep.append(eid)
            live += 1
            continue
        if isinstance(update_date, datetime) and update_date.replace(tzinfo=update_date.tzinfo or timezone.utc) >= since:
            keep.append(eid)
            recent += 1
            continue
        end_at = _event_end_at(end_date, start_date)
        if end_at is not None and _keep_since(end_at, since):
            keep.append(eid)
            dated += 1
    logger.info(
        "[inc] warehouse dim_events keep=%s live=%s recent_update=%s dated=%s scanned=%s",
        len(keep),
        live,
        recent,
        dated,
        len(rows),
    )
    return keep


def extract_events_since(since: datetime, run_id: str = "") -> ExtractResult:
    """Live + upcoming always; completed pages until older than since; details stay in memory."""
    logger.info("[inc] === STEP extract events since=%s ===", iso_seconds(since))
    connector = _health()
    max_live = int(os.getenv("VLR_INC_LIVE_PAGES", "20"))
    max_completed = int(os.getenv("VLR_INC_COMPLETED_PAGES", "8"))
    by_id: dict[str, dict[str, Any]] = {}
    for status in ("live", "upcoming"):
        for listing in _list_status(connector, status, max_live, since=None):
            by_id[listing["event_id"]] = listing
    for listing in _list_status(connector, "completed", max_completed, since):
        by_id.setdefault(listing["event_id"], listing)
    for event_id in _warehouse_event_ids(since):
        by_id.setdefault(event_id, {"id": event_id, "event_id": event_id})
    listings = list(by_id.values())
    logger.info("[inc] events details pending=%s ids=%s", len(listings), [row["event_id"] for row in listings[:20]])
    workers = int(os.getenv("VLR_EVENT_DETAIL_WORKERS", "8"))
    detail_connector = VlrV2Connector(max_workers=workers)
    rows: list[dict[str, Any]] = []
    max_source_at: datetime | None = None
    has_live = False
    errors = 0

    def _one(listing: dict[str, Any]) -> dict[str, Any] | None:
        event_id = str(listing.get("event_id") or listing.get("id") or "")
        try:
            detail = detail_connector.get_event_detail(event_id)
        except Exception:
            logger.exception("[inc] event detail failed event_id=%s", event_id)
            detail = {}
        if not isinstance(detail, dict):
            detail = {}
        return format_dim_event_row(listing, detail)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one, listing) for listing in listings]
        done = 0
        for future in as_completed(futures):
            row = future.result()
            done += 1
            if row is None:
                errors += 1
                continue
            rows.append(row)
            status = str(row.get("status") or "").strip().lower()
            if status in LIVE_STATUSES:
                has_live = True
            if done % 20 == 0 or done == len(listings):
                logger.info("[inc] events details %s/%s rows=%s live=%s", done, len(listings), len(rows), has_live)
    logger.info(
        "[inc] extract events done rows=%s errors=%s has_live=%s max_source_at=%s (events have no source clock; cursor is run time)",
        len(rows),
        errors,
        has_live,
        iso_seconds(max_source_at),
    )
    extra_ids = [str(row.get("vlr_event_id")) for row in rows if row.get("vlr_event_id")]
    if run_id:
        stash(run_id, "event_ids", extra_ids)
    return ExtractResult(
        rows=rows,
        row_count=len(rows),
        max_source_at=max_source_at,
        has_live=has_live,
        extra={"event_ids": extra_ids},
    )


def merge_events(rows: list[dict[str, Any]]) -> int:
    """Upsert in-memory dim_events rows; do not reread jsonl."""
    logger.info("[inc] === STEP merge dim_events rows=%s ===", len(rows))
    cleaned = [{col: row.get(col) for col in DIM_EVENT_COLUMNS} for row in rows]
    loaded = load_events(stamp_rows(cleaned))
    logger.info("[inc] merge dim_events done upserted=%s", loaded)
    return loaded


def _warehouse_match_event_ids(since: datetime) -> list[str]:
    """Events that still need match lists: live/upcoming plus anything with dates on/after since."""
    logger.info("[inc] warehouse events for matches since=%s", iso_seconds(since))
    connector = SupabaseConnector()
    rows = connector.fetch_all(
        "SELECT vlr_event_id, status, start_date, end_date, update_date FROM vlr.dim_events"
    )
    keep: list[str] = []
    for event_id, status, start_date, end_date, update_date in rows:
        eid = str(event_id or "")
        if not eid:
            continue
        st = str(status or "").strip().lower()
        if st in LIVE_STATUSES:
            keep.append(eid)
            continue
        if isinstance(update_date, datetime) and (update_date if update_date.tzinfo else update_date.replace(tzinfo=timezone.utc)) >= since:
            keep.append(eid)
            continue
        end_at = _event_end_at(end_date, start_date)
        if end_at is not None and _keep_since(end_at, since):
            keep.append(eid)
    logger.info("[inc] warehouse events for matches keep=%s scanned=%s", len(keep), len(rows))
    return keep


def extract_matches_since(since: datetime, run_id: str = "") -> ExtractResult:
    """List matches for recent/live events and fetch details for rows on/after the since day."""
    logger.info("[inc] === STEP extract matches since=%s ===", iso_seconds(since))
    connector = _health()
    stashed_ids = peek_stash(run_id, "event_ids") if run_id else None
    event_ids = list(dict.fromkeys((stashed_ids or []) + _warehouse_match_event_ids(since)))
    logger.info("[inc] matches events=%s sample=%s", len(event_ids), event_ids[:20])
    list_workers = int(os.getenv("VLR_MATCH_EVENT_WORKERS", "8"))
    list_connector = VlrV2Connector(max_workers=list_workers)
    jobs: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()

    def _list(event_id: str) -> tuple[str, list[dict[str, Any]]]:
        try:
            matches = list_connector.get_event_matches(event_id)
        except Exception:
            logger.exception("[inc] event matches list failed event_id=%s", event_id)
            matches = []
        return event_id, matches if isinstance(matches, list) else []

    listed = 0
    with ThreadPoolExecutor(max_workers=list_workers) as pool:
        futures = [pool.submit(_list, event_id) for event_id in event_ids]
        for future in as_completed(futures):
            event_id, matches = future.result()
            listed += 1
            kept = 0
            for listing in matches:
                if not isinstance(listing, dict):
                    continue
                match_id = _listing_id(listing)
                if not match_id or match_id in seen:
                    continue
                status = str(listing.get("status") or "").strip().lower()
                match_at = parse_match_at(
                    listing.get("date"),
                    unix=listing.get("timestamp") or listing.get("unix_timestamp") or listing.get("time"),
                )
                if status not in LIVE_STATUSES and not _keep_since(match_at, since):
                    continue
                seen.add(match_id)
                jobs.append((event_id, listing))
                kept += 1
            if listed % 20 == 0 or listed == len(event_ids):
                logger.info(
                    "[inc] matches list %s/%s event=%s listed=%s kept=%s jobs=%s",
                    listed,
                    len(event_ids),
                    event_id,
                    len(matches),
                    kept,
                    len(jobs),
                )
    logger.info("[inc] matches details pending=%s", len(jobs))
    detail_workers = int(os.getenv("VLR_MATCH_WORKERS", "6"))
    detail_connector = VlrV2Connector(max_workers=detail_workers, timeout=60)
    rows: list[dict[str, Any]] = []
    max_source_at: datetime | None = None
    has_live = False
    errors = 0

    def _detail(item: tuple[str, dict[str, Any]]) -> dict[str, Any] | None:
        event_id, listing = item
        match_id = _listing_id(listing)
        detail: dict[str, Any] = {}
        if _needs_detail(listing):
            try:
                detail = detail_connector.get_match_details(match_id)
            except Exception:
                logger.exception("[inc] match detail failed match_id=%s event_id=%s", match_id, event_id)
                return None
        if not isinstance(detail, dict):
            detail = {}
        return format_match_row(event_id, listing, detail)

    with ThreadPoolExecutor(max_workers=detail_workers) as pool:
        futures = [pool.submit(_detail, item) for item in jobs]
        done = 0
        for future in as_completed(futures):
            row = future.result()
            done += 1
            if row is None:
                errors += 1
                continue
            rows.append(row)
            status = str(row.get("status") or "").strip().lower()
            if status in LIVE_STATUSES or not row.get("is_completed"):
                has_live = True
            max_source_at = _max_dt(max_source_at, row.get("match_at") if isinstance(row.get("match_at"), datetime) else None)
            if done % 20 == 0 or done == len(jobs):
                logger.info("[inc] matches details %s/%s rows=%s errors=%s", done, len(jobs), len(rows), errors)
    logger.info(
        "[inc] extract matches done rows=%s errors=%s has_live=%s max_source_at=%s",
        len(rows),
        errors,
        has_live,
        iso_seconds(max_source_at),
    )
    if run_id:
        stash(run_id, "match_rows", rows)
        stash(
            run_id,
            "team_ids",
            sorted(
                {
                    str(row.get("vlr_team_1_id") or "")
                    for row in rows
                    if row.get("vlr_team_1_id")
                }
                | {
                    str(row.get("vlr_team_2_id") or "")
                    for row in rows
                    if row.get("vlr_team_2_id")
                }
            ),
        )
    return ExtractResult(rows=rows, row_count=len(rows), max_source_at=max_source_at, has_live=has_live)


def merge_matches(rows: list[dict[str, Any]]) -> int:
    """Upsert dim columns only; listing/detail stay in memory for facts."""
    logger.info("[inc] === STEP merge dim_matches rows=%s ===", len(rows))
    cleaned = stamp_rows([{col: row.get(col) for col in MATCH_DIM_COLS} for row in rows])
    loaded = upsert_dim_rows(
        cleaned,
        table="dim_matches",
        columns=MATCH_DIM_COLS,
        conflict_column="vlr_match_id",
    )
    logger.info("[inc] merge dim_matches done upserted=%s", loaded)
    return loaded


def _ids_from_roster(raw: Any) -> list[str]:
    """Pull vlr_player_id off a roster JSON list (warehouse or API)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    ids: list[str] = []
    for person in raw:
        if not isinstance(person, dict):
            continue
        player_id = str(person.get("vlr_player_id") or person.get("id") or "").strip()
        if player_id:
            ids.append(player_id)
    return ids


def _warehouse_team_ids(since: datetime) -> list[str]:
    """Team ids on matches updated since the cursor, when this job runs alone."""
    logger.info("[inc] warehouse team ids since=%s", iso_seconds(since))
    connector = SupabaseConnector()
    rows = connector.fetch_all(
        """
        SELECT vlr_team_1_id, vlr_team_2_id
        FROM vlr.dim_matches
        WHERE update_date >= %s OR match_at >= %s
        """,
        (since, since),
    )
    ids: set[str] = set()
    for team_1, team_2 in rows:
        if team_1:
            ids.add(str(team_1))
        if team_2:
            ids.add(str(team_2))
    logger.info("[inc] warehouse team ids n=%s from_matches=%s", len(ids), len(rows))
    return sorted(ids)


def extract_teams_since(since: datetime, run_id: str = "") -> ExtractResult:
    """GET /v2/team profile for team ids seen on recent matches."""
    logger.info("[inc] === STEP extract teams since=%s ===", iso_seconds(since))
    connector = _health()
    stashed = peek_stash(run_id, "team_ids") if run_id else None
    team_ids = list(dict.fromkeys(stashed or _warehouse_team_ids(since)))
    team_ids = [tid for tid in team_ids if tid and tid != "-1"]
    logger.info("[inc] teams pending=%s sample=%s", len(team_ids), team_ids[:20])
    if not team_ids:
        return ExtractResult()
    workers = int(os.getenv("VLR_TEAM_WORKERS", os.getenv("VLR_MATCH_WORKERS", "6")))
    ranking_connector = VlrV2Connector(max_workers=min(workers, 8))
    region_lookup = ranking_region_lookup(ranking_connector)
    detail_connector = VlrV2Connector(max_workers=workers, timeout=60)
    rows: list[dict[str, Any]] = []
    player_ids: set[str] = set()
    errors = 0

    def _one(team_id: str) -> dict[str, Any] | None:
        try:
            profile = detail_connector.get_team_profile(team_id)
        except Exception:
            logger.exception("[inc] team profile failed team_id=%s", team_id)
            return None
        if not team_profile_usable(profile):
            logger.warning("[inc] team profile empty team_id=%s", team_id)
            return None
        return format_team_row(profile, region_lookup=region_lookup)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one, team_id) for team_id in team_ids]
        done = 0
        for future in as_completed(futures):
            row = future.result()
            done += 1
            if row is None:
                errors += 1
            else:
                rows.append(row)
                player_ids.update(_ids_from_roster(row.get("current_roster_json")))
                player_ids.update(_ids_from_roster(row.get("coaches_json")))
            if done % 10 == 0 or done == len(team_ids):
                logger.info("[inc] teams %s/%s rows=%s errors=%s players=%s", done, len(team_ids), len(rows), errors, len(player_ids))
    if run_id:
        stash(run_id, "player_ids", sorted(player_ids))
    logger.info("[inc] extract teams done rows=%s errors=%s player_ids=%s", len(rows), errors, len(player_ids))
    return ExtractResult(rows=rows, row_count=len(rows), max_source_at=datetime.now(timezone.utc), extra={"player_ids": sorted(player_ids)})


def merge_teams(rows: list[dict[str, Any]]) -> int:
    """Upsert dim_teams from in-memory profiles."""
    logger.info("[inc] === STEP merge dim_teams rows=%s ===", len(rows))
    cleaned = stamp_rows([{col: row.get(col) for col in TEAM_DIM_COLS} for row in rows])
    loaded = upsert_dim_rows(
        cleaned,
        table="dim_teams",
        columns=TEAM_DIM_COLS,
        conflict_column="vlr_team_id",
        jsonb_columns=TEAM_JSON_COLS,
    )
    logger.info("[inc] merge dim_teams done upserted=%s", loaded)
    return loaded


def _warehouse_player_ids(since: datetime) -> list[str]:
    """Player ids from recently updated team rosters when the players job runs alone."""
    logger.info("[inc] warehouse player ids since=%s", iso_seconds(since))
    connector = SupabaseConnector()
    rows = connector.fetch_all(
        """
        SELECT current_roster_json, coaches_json
        FROM vlr.dim_teams
        WHERE update_date >= %s
        """,
        (since,),
    )
    ids: set[str] = set()
    for roster, coaches in rows:
        ids.update(_ids_from_roster(roster))
        ids.update(_ids_from_roster(coaches))
    logger.info("[inc] warehouse player ids n=%s from_teams=%s", len(ids), len(rows))
    return sorted(ids)


def _team_name_lookup() -> dict[str, str]:
    """Map unique team_name → vlr_team_id from the warehouse so player stints can join."""
    logger.info("[inc] team name lookup from vlr.dim_teams")
    connector = SupabaseConnector()
    rows = connector.fetch_all("SELECT team_name, vlr_team_id FROM vlr.dim_teams")
    counts: dict[str, set[str]] = {}
    for name, team_id in rows:
        if not name or not team_id:
            continue
        counts.setdefault(str(name).strip().lower(), set()).add(str(team_id))
    lookup = {name: next(iter(ids)) for name, ids in counts.items() if len(ids) == 1}
    logger.info("[inc] team name lookup unique_names=%s scanned=%s", len(lookup), len(rows))
    return lookup


def extract_players_since(since: datetime, run_id: str = "") -> ExtractResult:
    """GET /v2/player profile for ids on recent team rosters."""
    logger.info("[inc] === STEP extract players since=%s ===", iso_seconds(since))
    connector = _health()
    stashed = peek_stash(run_id, "player_ids") if run_id else None
    player_ids = list(dict.fromkeys(stashed or _warehouse_player_ids(since)))
    player_ids = [pid for pid in player_ids if pid and pid != "-1"]
    logger.info("[inc] players pending=%s sample=%s", len(player_ids), player_ids[:20])
    if not player_ids:
        return ExtractResult()
    workers = int(os.getenv("VLR_PLAYER_WORKERS", os.getenv("VLR_MATCH_WORKERS", "6")))
    lookup = _team_name_lookup()
    if not lookup:
        logger.info("[inc] players team_name lookup empty warehouse; continuing with API team ids only")
    detail_connector = VlrV2Connector(max_workers=workers, timeout=60)
    rows: list[dict[str, Any]] = []
    errors = 0

    def _one(player_id: str) -> dict[str, Any] | None:
        try:
            profile = detail_connector.get_player_profile(player_id)
        except Exception:
            logger.exception("[inc] player profile failed player_id=%s", player_id)
            return None
        if not player_profile_usable(profile):
            logger.warning("[inc] player profile empty player_id=%s", player_id)
            return None
        return format_player_row(profile, lookup=lookup)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one, player_id) for player_id in player_ids]
        done = 0
        for future in as_completed(futures):
            row = future.result()
            done += 1
            if row is None:
                errors += 1
            else:
                rows.append(row)
            if done % 10 == 0 or done == len(player_ids):
                logger.info("[inc] players %s/%s rows=%s errors=%s", done, len(player_ids), len(rows), errors)
    logger.info("[inc] extract players done rows=%s errors=%s", len(rows), errors)
    return ExtractResult(rows=rows, row_count=len(rows), max_source_at=datetime.now(timezone.utc))


def merge_players(rows: list[dict[str, Any]]) -> int:
    """Upsert dim_players from in-memory profiles."""
    logger.info("[inc] === STEP merge dim_players rows=%s ===", len(rows))
    cleaned = stamp_rows([{col: row.get(col) for col in PLAYER_DIM_COLS} for row in rows])
    loaded = upsert_dim_rows(
        cleaned,
        table="dim_players",
        columns=PLAYER_DIM_COLS,
        conflict_column="vlr_player_id",
        jsonb_columns=PLAYER_JSON_COLS,
    )
    logger.info("[inc] merge dim_players done upserted=%s", loaded)
    return loaded


def extract_facts_since(since: datetime, run_id: str = "") -> ExtractResult:
    """Parse in-memory match details (or re-fetch ids from dim_matches) into fact buckets."""
    logger.info("[inc] === STEP extract facts since=%s ===", iso_seconds(since))
    match_rows = peek_stash(run_id, "match_rows") if run_id else None
    if match_rows:
        logger.info("[inc] facts using stashed match_rows n=%s", len(match_rows))
        return ExtractResult(
            rows=match_rows,
            row_count=len(match_rows),
            max_source_at=datetime.now(timezone.utc),
            extra={"source": "stash"},
        )
    logger.info("[inc] facts stash miss; listing dim_matches since=%s then re-fetching details", iso_seconds(since))
    connector = SupabaseConnector()
    rows = connector.fetch_all(
        """
        SELECT vlr_match_id, vlr_event_id
        FROM vlr.dim_matches
        WHERE update_date >= %s OR match_at >= %s
        """,
        (since, since),
    )
    logger.info("[inc] facts warehouse matches n=%s", len(rows))
    if not rows:
        return ExtractResult()
    _health()
    workers = int(os.getenv("VLR_MATCH_WORKERS", "6"))
    detail_connector = VlrV2Connector(max_workers=workers, timeout=60)
    out: list[dict[str, Any]] = []
    errors = 0

    def _one(item: tuple[Any, Any]) -> dict[str, Any] | None:
        match_id, event_id = str(item[0] or ""), str(item[1] or "")
        try:
            detail = detail_connector.get_match_details(match_id)
        except Exception:
            logger.exception("[inc] facts match detail failed match_id=%s", match_id)
            return None
        listing = {"match_id": match_id, "url": f"https://www.vlr.gg/{match_id}"}
        return format_match_row(event_id, listing, detail if isinstance(detail, dict) else {})

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one, item) for item in rows]
        done = 0
        for future in as_completed(futures):
            row = future.result()
            done += 1
            if row is None:
                errors += 1
            else:
                out.append(row)
            if done % 20 == 0 or done == len(rows):
                logger.info("[inc] facts details %s/%s rows=%s errors=%s", done, len(rows), len(out), errors)
    logger.info("[inc] extract facts done rows=%s errors=%s", len(out), errors)
    return ExtractResult(rows=out, row_count=len(out), max_source_at=datetime.now(timezone.utc), extra={"source": "refetch"})


def merge_facts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Parse match rows in memory and upsert every vlr fact table."""
    logger.info("[inc] === STEP merge vlr.fact_* from in-memory matches=%s tables=%s ===", len(rows), len(FACT_SPECS))
    counts = upsert_facts_from_match_rows(rows)
    logger.info("[inc] merge facts done %s", counts)
    return counts
