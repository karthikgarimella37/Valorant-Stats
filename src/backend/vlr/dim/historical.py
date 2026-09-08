"""Historical (one-shot) VLR event extract → events.jsonl → vlr.dim_events."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.api_connectors.ip_rotator_gateway import VlrIpRotator, assert_container_rotator
from backend.api_connectors.vlr_v2_connector import VlrV2Connector
from backend.config.env import load_project_env
from backend.database_connectors.supabase_connectors import SupabaseConnector
from backend.vlr.dim.util import (
    append_event_row,
    event_id_from_url,
    event_ids_in_jsonl,
    event_json_path,
    events_jsonl_path,
    infer_event_tier,
    json_dumps,
    parse_event_dates,
    parse_prize_pool,
    read_event_rows_jsonl,
    slug_from_url,
    utc_now,
    year_from_text,
)
from backend.vlr.regions import infer_vct_region_from_text, split_event_region
from backend.vlr.watermarks import upsert_watermarks_batch

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[4]
EVENT_STATUSES = ("completed", "upcoming", "live")
VLR_SITE = "https://www.vlr.gg"
DIM_EVENT_COLUMNS = (
    "vlr_event_id",
    "parent_vlr_event_id",
    "vct_region_code",
    "region_code",
    "event_name",
    "series",
    "subtitle",
    "short_name",
    "slug",
    "event_tier",
    "status",
    "dates_text",
    "start_date",
    "end_date",
    "prize_pool",
    "prize_pool_currency",
    "prize_pool_text",
    "location",
    "logo_url",
    "url",
    "participating_team_count",
    "prize_placement_count",
    "prizes_json",
    "teams_json",
    "standings_json",
    "insert_date",
    "update_date",
)
DIM_EVENT_COLUMN_TYPES = {
    "row_number": "BIGINT",
    "vlr_event_id": "TEXT",
    "parent_vlr_event_id": "TEXT",
    "vct_region_code": "TEXT",
    "region_code": "TEXT",
    "event_name": "TEXT",
    "series": "TEXT",
    "subtitle": "TEXT",
    "short_name": "TEXT",
    "slug": "TEXT",
    "event_tier": "TEXT",
    "status": "TEXT",
    "dates_text": "TEXT",
    "start_date": "TEXT",
    "end_date": "TEXT",
    "prize_pool": "NUMERIC",
    "prize_pool_currency": "TEXT",
    "prize_pool_text": "TEXT",
    "location": "TEXT",
    "logo_url": "TEXT",
    "url": "TEXT",
    "participating_team_count": "INTEGER",
    "prize_placement_count": "INTEGER",
    "prizes_json": "JSONB",
    "teams_json": "JSONB",
    "standings_json": "JSONB",
    "insert_date": "TIMESTAMPTZ",
    "update_date": "TIMESTAMPTZ",
}
_DATE_TO_PROJECT_TEXT = (
    "CASE WHEN \"{col}\" IS NULL THEN NULL "
    "ELSE (EXTRACT(YEAR FROM \"{col}\")::int)::text || '/' || "
    "(EXTRACT(MONTH FROM \"{col}\")::int)::text || '/' || "
    "(EXTRACT(DAY FROM \"{col}\")::int)::text END"
)


def _repo_root(repo_root: Path | None) -> Path:
    """Resolve the git root so JSON landings stay under data/vlr."""
    return Path(repo_root or REPO_ROOT)


def _aws_keys_present() -> bool:
    """True when rotator can start; do not log key values."""
    return bool(
        os.getenv("VLR_AWS_ACCESS_KEY_ID")
        or os.getenv("AWS_ACCESS_KEY_ID")
    ) and bool(
        os.getenv("VLR_AWS_SECRET_ACCESS_KEY")
        or os.getenv("AWS_SECRET_ACCESS_KEY")
    )


@dataclass
class EventProgress:
    """Thread-safe N/total + event name so Dagster logs show which event just finished."""

    total: int
    done: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def mark(self, name: str | None, start_date: str | None, end_date: str | None, *, skipped: bool = False) -> None:
        label = (name or "(unnamed)").strip() or "(unnamed)"
        dates = f"{start_date or '?'}–{end_date or '?'}"
        suffix = " skip" if skipped else ""
        with self.lock:
            self.done += 1
            logger.info(
                "[events] %s/%s %s (%s)%s",
                self.done,
                self.total,
                label,
                dates,
                suffix,
            )


@dataclass
class EventLanding:
    """Append-only jsonl of insert rows; tracks ids so workers do not duplicate."""

    repo_root: Path
    ids: set[str]
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def open(cls, repo_root: Path) -> EventLanding:
        """Load existing ids so a resume appends only new events."""
        return cls(repo_root=repo_root, ids=event_ids_in_jsonl(repo_root))

    def has(self, event_id: str) -> bool:
        with self.lock:
            return event_id in self.ids

    def write(self, row: dict[str, Any]) -> bool:
        """Append one insert row. Returns False if the id was already landed."""
        event_id = str(row.get("vlr_event_id") or "")
        if not event_id:
            return False
        with self.lock:
            if event_id in self.ids:
                return False
            append_event_row(self.repo_root, row)
            self.ids.add(event_id)
            return True


def list_event_catalog(connector: VlrV2Connector) -> list[dict[str, Any]]:
    """Page every /v2/events status until empty so the historical load is complete."""
    logger.info("[events] Starting catalog statuses=%s", EVENT_STATUSES)
    by_id: dict[str, dict[str, Any]] = {}
    page_size = int(os.getenv("VLR_EVENT_PAGE_WORKERS", "8"))
    page_delay = float(os.getenv("VLR_EVENT_PAGE_DELAY_SEC", "0.2"))
    max_pages = int(os.getenv("VLR_EVENT_MAX_PAGES", "500"))
    logger.info("[events] Catalog workers=%s page_delay=%s", page_size, page_delay)
    for status in EVENT_STATUSES:
        page = 1
        while page <= max_pages:
            batch_pages = list(range(page, min(page + page_size, max_pages + 1)))
            # Independent list pages — parallel; 502/503 retries live in the connector.
            results = connector.map_parallel(
                batch_pages,
                lambda p, q=status: (p, connector.get_events_page(p, q)),
                desc=f"events {status}",
            )
            results.sort(key=lambda item: item[0])
            new_ids = 0
            for _page_no, segments in results:
                if not segments:
                    continue
                for segment in segments:
                    if not isinstance(segment, dict):
                        continue
                    url_path = segment.get("url_path") or segment.get("url") or ""
                    event_id = str(
                        segment.get("event_id")
                        or segment.get("id")
                        or event_id_from_url(str(url_path))
                        or ""
                    )
                    if not event_id:
                        continue
                    if event_id not in by_id:
                        new_ids += 1
                    row = dict(segment)
                    row["id"] = event_id
                    row["event_id"] = event_id
                    row["status"] = row.get("status") or status
                    by_id[event_id] = row
            logger.info(
                "[events] Catalog %s pages=%s new=%s total=%s",
                status,
                batch_pages,
                new_ids,
                len(by_id),
            )
            # Stop when a window adds nothing (repeat last page or 422/empty).
            if new_ids == 0:
                break
            if page_delay > 0:
                time.sleep(page_delay)
            page += page_size
        logger.info("[events] Status %s done catalog_size=%s", status, len(by_id))
    logger.info("[events] Catalog done unique_events=%s", len(by_id))
    return list(by_id.values())


def format_dim_event_row(listing: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    """Flatten list + detail into one dim_events row (codes, not mixed region grains)."""
    event = detail.get("event") if isinstance(detail.get("event"), dict) else {}
    event_id = str(listing.get("event_id") or listing.get("id") or detail.get("event_id") or "")
    name = event.get("name") or listing.get("title") or listing.get("name")
    series = event.get("series")
    dates_text = event.get("dates") or listing.get("dates")
    start_date, end_date = parse_event_dates(
        dates_text, fallback_year=year_from_text(name, series, dates_text)
    )
    prize_text = event.get("prize") or listing.get("prize") or listing.get("prizepool")
    prize_pool, currency, prize_raw = parse_prize_pool(prize_text)
    tier = infer_event_tier(name, series)
    vct_from_title = infer_vct_region_from_text(name, series) if tier == "vct" else None
    if vct_from_title:
        vct_code, local_code = vct_from_title, None
    else:
        vct_code, local_code = split_event_region(listing.get("region") or listing.get("country"))
    url_path = listing.get("url_path") or listing.get("url") or ""
    url = str(url_path)
    if url and not url.startswith("http"):
        url = f"https://www.vlr.gg{url}" if url.startswith("/") else f"https://www.vlr.gg/{url}"
    prizes = detail.get("prizes") if isinstance(detail.get("prizes"), list) else []
    teams = detail.get("teams") if isinstance(detail.get("teams"), list) else []
    standings = detail.get("standings") if isinstance(detail.get("standings"), list) else []
    now = utc_now()
    return {
        "vlr_event_id": event_id,
        "parent_vlr_event_id": listing.get("parent_id") or event.get("parent_id"),
        "vct_region_code": vct_code,
        "region_code": local_code,
        "event_name": name,
        "series": series,
        "subtitle": event.get("subtitle"),
        "short_name": listing.get("short_name") or listing.get("tag"),
        "slug": slug_from_url(str(url_path)) or listing.get("slug"),
        "event_tier": tier,
        "status": listing.get("status"),
        "dates_text": dates_text,
        "start_date": start_date,
        "end_date": end_date,
        "prize_pool": prize_pool,
        "prize_pool_currency": currency,
        "prize_pool_text": prize_raw,
        "location": event.get("location") or listing.get("location"),
        "logo_url": event.get("logo") or listing.get("img") or listing.get("logo"),
        "url": url or None,
        "participating_team_count": len(teams),
        "prize_placement_count": len(prizes),
        "prizes_json": json_dumps(prizes),
        "teams_json": json_dumps(teams),
        "standings_json": json_dumps(standings),
        "insert_date": now,
        "update_date": now,
    }


def _legacy_detail(repo_root: Path, event_id: str) -> dict[str, Any] | None:
    """Reuse an older per-id JSON file so we do not re-hit the API after the landing change."""
    path = event_json_path(repo_root, event_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    detail = payload.get("detail")
    return detail if isinstance(detail, dict) else {}


def _fetch_one_event(
    connector: VlrV2Connector,
    repo_root: Path,
    listing: dict[str, Any],
    landing: EventLanding,
    progress: EventProgress,
    *,
    skip_existing: bool,
) -> dict[str, Any] | None:
    """Fetch one event, append the insert row, log name + N/total."""
    event_id = str(listing.get("event_id") or listing.get("id") or "")
    if skip_existing and landing.has(event_id):
        name = listing.get("title") or listing.get("name")
        start_date, end_date = parse_event_dates(
            listing.get("dates"), fallback_year=year_from_text(name, listing.get("dates"))
        )
        progress.mark(name, start_date, end_date, skipped=True)
        return None
    detail: dict[str, Any] | None = _legacy_detail(repo_root, event_id) if skip_existing else None
    if detail is None:
        try:
            detail = connector.get_event_detail(event_id)
        except Exception:
            logger.exception(
                "[events] Detail failed event_id=%s; landing list row only",
                event_id,
            )
            detail = {}
    row = format_dim_event_row(listing, detail)
    landing.write(row)
    progress.mark(row.get("event_name"), row.get("start_date"), row.get("end_date"))
    return row


def extract_events(repo_root: Path | None = None) -> list[dict[str, Any]]:
    """Pull every VLR event once, append data/vlr/events.jsonl, return dim rows."""
    load_project_env(repo_root)
    repo_root = _repo_root(repo_root)
    assert_container_rotator()
    connector = VlrV2Connector()
    # Rotator only applies when /v2 is on vlr.gg. Local vlrggapi is not rotated.
    if connector._rotate_api:
        logger.info(
            "[events] IP rotator on aws_keys_present=%s base=%s",
            _aws_keys_present(),
            connector.base_url,
        )
        VlrIpRotator.get_gateway(VLR_SITE)
    else:
        logger.info(
            "[events] IP rotator skipped (API host is not vlr.gg) base=%s aws_keys_present=%s",
            connector.base_url,
            _aws_keys_present(),
        )
    logger.info("[events] Health check base=%s", connector.base_url)
    try:
        connector.health()
    except Exception as exc:
        raise RuntimeError(
            f"vlrggapi is not reachable at {connector.base_url}. "
            "Start it with: docker compose up -d vlrggapi"
        ) from exc
    listings = list_event_catalog(connector)
    max_events = os.getenv("VLR_MAX_EVENTS")
    if max_events:
        listings = listings[: int(max_events)]
        logger.info("[events] Capped listings=%s", len(listings))
    skip_existing = os.getenv("VLR_EVENT_SKIP_EXISTING", "1") == "1"
    detail_workers = int(os.getenv("VLR_EVENT_DETAIL_WORKERS", "12"))
    detail_connector = VlrV2Connector(max_workers=detail_workers)
    landing = EventLanding.open(repo_root)
    progress = EventProgress(total=len(listings))
    logger.info(
        "[events] Fetching details events=%s already_landed=%s skip_existing=%s workers=%s jsonl=%s",
        len(listings),
        len(landing.ids),
        skip_existing,
        detail_workers,
        events_jsonl_path(repo_root),
    )
    # Each event detail is independent I/O; landing/progress use locks.
    with ThreadPoolExecutor(max_workers=detail_workers) as pool:
        futures = [
            pool.submit(
                _fetch_one_event,
                detail_connector,
                repo_root,
                listing,
                landing,
                progress,
                skip_existing=skip_existing,
            )
            for listing in listings
        ]
        for future in as_completed(futures):
            future.result()
    rows = rows_from_events_landing(repo_root)
    upsert_watermarks_batch(
        repo_root,
        [
            {
                "entity_type": "events",
                "entity_id": str(row["vlr_event_id"]),
                "source_url": row.get("url") or f"https://www.vlr.gg/event/{row['vlr_event_id']}",
                "json_path": str(events_jsonl_path(repo_root)),
            }
            for row in rows
        ],
    )
    logger.info(
        "[events] Done dim_rows=%s processed=%s/%s jsonl=%s",
        len(rows),
        progress.done,
        progress.total,
        events_jsonl_path(repo_root),
    )
    return rows


def rows_from_events_landing(repo_root: Path | None = None) -> list[dict[str, Any]]:
    """Read insert rows from events.jsonl (or rebuild from legacy per-id files)."""
    repo_root = _repo_root(repo_root)
    jsonl_rows = read_event_rows_jsonl(repo_root)
    if jsonl_rows:
        logger.info("[events] Reading landing JSONL rows=%s", len(jsonl_rows))
        return jsonl_rows
    return rows_from_event_json_dir(repo_root)


def rows_from_event_json_dir(repo_root: Path | None = None) -> list[dict[str, Any]]:
    """Rebuild dim rows from older data/vlr/events/<id>.json files."""
    repo_root = _repo_root(repo_root)
    folder = repo_root / "data" / "vlr" / "events"
    rows: list[dict[str, Any]] = []
    if not folder.exists():
        return rows
    paths = sorted(folder.glob("*.json"))
    logger.info("[events] Reading legacy JSON files=%s", len(paths))
    for path in paths:
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict):
            continue
        listing = payload.get("listing") if isinstance(payload.get("listing"), dict) else {}
        detail = payload.get("detail") if isinstance(payload.get("detail"), dict) else {}
        if not listing.get("id"):
            listing = {**listing, "id": payload.get("event_id") or path.stem}
        rows.append(format_dim_event_row(listing, detail))
    logger.info("[events] Legacy JSON dim rows=%s", len(rows))
    return rows


def load_events(rows: list[dict[str, Any]]) -> int:
    """Upsert formatted rows into vlr.dim_events without dropping row_number on re-run."""
    logger.info("[events] Load start rows=%s", len(rows))
    connector = SupabaseConnector()
    count = connector.upsert_rows(
        rows,
        schema="vlr",
        table="dim_events",
        columns=DIM_EVENT_COLUMNS,
        conflict_column="vlr_event_id",
        update_columns=[c for c in DIM_EVENT_COLUMNS if c not in {"vlr_event_id", "insert_date"}],
    )
    logger.info("[events] Load done upserted=%s", count)
    return count


def run_events(repo_root: Path | None = None) -> dict[str, int]:
    """End-to-end historical events: ensure table, extract JSONL, upsert dim_events."""
    apply_events_schema(repo_root)
    rows = extract_events(repo_root)
    loaded = load_events(rows)
    return {"extracted": len(rows), "loaded": loaded}


def apply_events_schema(repo_root: Path | None = None) -> Path:
    """Create vlr.dim_events if missing; ADD / ALTER columns if the shape drifted."""
    load_project_env(repo_root)
    repo_root = _repo_root(repo_root)
    sql_path = repo_root / "src" / "backend" / "sql" / "ddl" / "vlr_dim_events.sql"
    logger.info("[events] Ensuring schema %s", sql_path)
    connector = SupabaseConnector()
    connector.execute_sql_file(sql_path)
    type_using = {
        "start_date": _DATE_TO_PROJECT_TEXT.format(col="start_date"),
        "end_date": _DATE_TO_PROJECT_TEXT.format(col="end_date"),
    }
    connector.ensure_table_columns(
        "vlr",
        "dim_events",
        DIM_EVENT_COLUMN_TYPES,
        type_using=type_using,
    )
    # Indexes after columns exist so an older table can be altered first.
    for stmt in (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_vlr_dim_events_vlr_event_id "
        "ON vlr.dim_events (vlr_event_id)",
        "CREATE INDEX IF NOT EXISTS idx_vlr_dim_events_status ON vlr.dim_events (status)",
        "CREATE INDEX IF NOT EXISTS idx_vlr_dim_events_vct ON vlr.dim_events (vct_region_code)",
        "CREATE INDEX IF NOT EXISTS idx_vlr_dim_events_region ON vlr.dim_events (region_code)",
    ):
        connector.execute(stmt)
    logger.info("[events] Schema ready (create-if-missing + alter, no drop)")
    return sql_path


# Old names — keep imports from earlier chats working.
extract_historical_events = extract_events
load_dim_events = load_events
run_historical_events = run_events
apply_dim_events_schema = apply_events_schema


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(run_events())
