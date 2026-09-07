"""Historical (one-shot) VLR event extract → JSON files → vlr.dim_events."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from backend.api_connectors.vlr_v2_connector import VlrV2Connector
from backend.database_connectors.supabase_connectors import SupabaseConnector
import json

from backend.vlr.dim.util import (
    event_id_from_url,
    event_json_path,
    infer_event_tier,
    json_dumps,
    parse_event_dates,
    parse_prize_pool,
    slug_from_url,
    utc_now,
    write_event_json,
)
from backend.vlr.regions import split_event_region
from backend.vlr.watermarks import upsert_watermarks_batch

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[4]
EVENT_STATUSES = ("completed", "upcoming", "live")
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


def _repo_root(repo_root: Path | None) -> Path:
    """Resolve the git root so JSON landings stay under data/vlr/events."""
    return Path(repo_root or REPO_ROOT)


def list_event_catalog(connector: VlrV2Connector) -> list[dict[str, Any]]:
    """Page every /v2/events status until empty so the historical load is complete."""
    logger.info("[events_historical] Starting catalog statuses=%s", EVENT_STATUSES)
    by_id: dict[str, dict[str, Any]] = {}
    page_size = int(os.getenv("VLR_EVENT_PAGE_WORKERS", str(connector.max_workers)))
    max_pages = int(os.getenv("VLR_EVENT_MAX_PAGES", "500"))
    for status in EVENT_STATUSES:
        empty_streak = 0
        page = 1
        while page <= max_pages:
            batch_pages = list(range(page, min(page + page_size, max_pages + 1)))
            results = connector.map_parallel(
                batch_pages,
                lambda p, q=status: (p, connector.get_events_page(p, q)),
                desc=f"events {status}",
            )
            results.sort(key=lambda item: item[0])
            hit_empty = False
            for page_no, segments in results:
                if not segments:
                    empty_streak += 1
                    hit_empty = True
                    continue
                empty_streak = 0
                for segment in segments:
                    if not isinstance(segment, dict):
                        continue
                    url_path = segment.get("url_path") or segment.get("url") or ""
                    event_id = str(segment.get("id") or event_id_from_url(str(url_path)) or "")
                    if not event_id:
                        continue
                    row = dict(segment)
                    row["id"] = event_id
                    row["status"] = row.get("status") or status
                    by_id[event_id] = row
            if hit_empty and empty_streak >= 2:
                break
            if all(not segs for _, segs in results):
                break
            page += page_size
        logger.info("[events_historical] Status %s done catalog_size=%s", status, len(by_id))
    logger.info("[events_historical] Catalog done unique_events=%s", len(by_id))
    return list(by_id.values())


def format_dim_event_row(listing: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    """Flatten list + detail into one dim_events row (codes, not mixed region grains)."""
    event = detail.get("event") if isinstance(detail.get("event"), dict) else {}
    event_id = str(listing.get("id") or detail.get("event_id") or "")
    name = event.get("name") or listing.get("title") or listing.get("name")
    series = event.get("series")
    dates_text = event.get("dates") or listing.get("dates")
    start_date, end_date = parse_event_dates(dates_text)
    prize_text = event.get("prize") or listing.get("prize") or listing.get("prizepool")
    prize_pool, currency, prize_raw = parse_prize_pool(prize_text)
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
        "event_tier": infer_event_tier(name, series),
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


def _fetch_one_event(
    connector: VlrV2Connector,
    repo_root: Path,
    listing: dict[str, Any],
    *,
    skip_existing: bool,
) -> dict[str, Any]:
    """Fetch one event detail and land JSON so a failed worker does not drop the catalog row."""
    event_id = str(listing.get("id") or "")
    path = event_json_path(repo_root, event_id)
    if skip_existing and path.exists():
        import json

        payload = json.loads(path.read_text())
        detail = payload.get("detail") if isinstance(payload, dict) else {}
        return format_dim_event_row(listing, detail if isinstance(detail, dict) else {})
    detail = connector.get_event_detail(event_id)
    payload = {
        "event_id": event_id,
        "listing": listing,
        "detail": detail,
        "source_url": f"https://www.vlr.gg/event/{event_id}",
    }
    write_event_json(repo_root, event_id, payload)
    return format_dim_event_row(listing, detail)


def extract_historical_events(repo_root: Path | None = None) -> list[dict[str, Any]]:
    """Pull every VLR event once, write data/vlr/events/<id>.json, return dim rows."""
    repo_root = _repo_root(repo_root)
    connector = VlrV2Connector()
    logger.info("[events_historical] Health check base=%s", connector.base_url)
    connector.health()
    listings = list_event_catalog(connector)
    max_events = os.getenv("VLR_MAX_EVENTS")
    if max_events:
        listings = listings[: int(max_events)]
        logger.info("[events_historical] Capped listings=%s", len(listings))
    skip_existing = os.getenv("VLR_EVENT_SKIP_EXISTING", "1") == "1"
    logger.info(
        "[events_historical] Fetching details events=%s skip_existing=%s workers=%s",
        len(listings),
        skip_existing,
        connector.max_workers,
    )
    rows = connector.map_parallel(
        listings,
        lambda listing: _fetch_one_event(connector, repo_root, listing, skip_existing=skip_existing),
        desc="event details",
    )
    rows = [row for row in rows if row.get("vlr_event_id")]
    for row in rows:
        upsert_watermark(
            repo_root,
            entity_type="events",
            entity_id=str(row["vlr_event_id"]),
            source_url=row.get("url") or f"https://www.vlr.gg/event/{row['vlr_event_id']}",
            extra={"json_path": str(event_json_path(repo_root, str(row["vlr_event_id"])))},
        )
    logger.info("[events_historical] Done dim_rows=%s json_dir=%s", len(rows), repo_root / "data" / "vlr" / "events")
    return rows


def load_dim_events(rows: list[dict[str, Any]]) -> int:
    """Upsert formatted rows into vlr.dim_events without dropping row_number on re-run."""
    logger.info("[events_historical] Load start rows=%s", len(rows))
    connector = SupabaseConnector()
    count = connector.upsert_rows(
        rows,
        schema="vlr",
        table="dim_events",
        columns=DIM_EVENT_COLUMNS,
        conflict_column="vlr_event_id",
        update_columns=[c for c in DIM_EVENT_COLUMNS if c not in {"vlr_event_id", "insert_date"}],
    )
    logger.info("[events_historical] Load done upserted=%s", count)
    return count


def run_historical_events(repo_root: Path | None = None) -> dict[str, int]:
    """End-to-end historical events: extract JSON then upsert dim_events."""
    rows = extract_historical_events(repo_root)
    loaded = load_dim_events(rows)
    return {"extracted": len(rows), "loaded": loaded}
