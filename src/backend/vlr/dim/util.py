"""Shared dim helpers so historical and incremental event loads share one parse path."""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_EVENT_ID_RE = re.compile(r"/event/(\d+)")
_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def utc_now() -> datetime:
    """Timezone-aware stamp for insert_date / update_date."""
    return datetime.now(timezone.utc)


def event_json_path(repo_root: Path, event_id: str) -> Path:
    """One raw event file under data/vlr/events/<id>.json."""
    path = Path(repo_root) / "data" / "vlr" / "events" / f"{event_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_event_json(repo_root: Path, event_id: str, payload: Any) -> Path:
    """Overwrite the event snapshot so re-runs stay idempotent."""
    path = event_json_path(repo_root, event_id)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return path


def event_id_from_url(url_path: str | None) -> str | None:
    """Parse vlr event id from list url_path when the segment omits id."""
    if not url_path:
        return None
    match = _EVENT_ID_RE.search(str(url_path))
    return match.group(1) if match else None


def slug_from_url(url_path: str | None) -> str | None:
    """Take the trailing slug from /event/2776/vct-2026-pacific-stage-2."""
    if not url_path:
        return None
    parts = [p for p in str(url_path).split("/") if p and p not in {"https:", "http:"}]
    if "event" in parts:
        idx = parts.index("event")
        if idx + 2 < len(parts):
            return parts[-1]
    return None


def year_from_text(*parts: str | None) -> int | None:
    """Pull a 20xx year from the event title when the date string omits it."""
    for part in parts:
        match = re.search(r"(20\d{2})", str(part or ""))
        if match:
            return int(match.group(1))
    return None


def infer_event_tier(name: str | None, series: str | None = None) -> str | None:
    """Bucket VLR titles into vct / vcl / game-changers / t3 for dim_events.event_tier."""
    blob = f"{name or ''} {series or ''}".lower()
    if "game changer" in blob:
        return "game-changers"
    if "challenger" in blob:
        return "vcl"
    if "champions tour" in blob or " vct " in f" {blob} " or blob.startswith("vct "):
        return "vct"
    if "masters" in blob or "champions" in blob:
        return "vct"
    return "t3"


def parse_prize_pool(raw: str | None) -> tuple[float | None, str | None, str | None]:
    """Split `$250,000` into amount + currency so the dim can filter numerically."""
    if raw is None:
        return None, None, None
    text = str(raw).strip()
    if not text or text in {"-", "—", "TBD", "tbd"}:
        return None, None, text or None
    currency = "USD" if "$" in text else None
    digits = re.sub(r"[^\d.]", "", text)
    if not digits:
        return None, currency, text
    try:
        return float(digits), currency, text
    except ValueError:
        return None, currency, text


def _parse_one_date(month: str, day: str, year: str) -> date | None:
    """Build a date from VLR month-name tokens."""
    month_n = _MONTHS.get(month.lower())
    if not month_n:
        return None
    try:
        return date(int(year), month_n, int(day))
    except ValueError:
        return None


def parse_event_dates(raw: str | None, fallback_year: int | None = None) -> tuple[date | None, date | None]:
    """Parse `Jul 15 – Sep 6, 2026` / `Jul 16—Sep 6` into start/end dates."""
    if not raw:
        return None, None
    text = str(raw).replace("–", "-").replace("—", "-").replace(",", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if fallback_year and not re.search(r"\d{4}", text):
        text = f"{text} {fallback_year}"
    range_match = re.search(
        r"([A-Za-z]+)\s+(\d{1,2})\s*-\s*([A-Za-z]+)\s+(\d{1,2})\s+(\d{4})",
        text,
    )
    if range_match:
        m1, d1, m2, d2, year = range_match.groups()
        return _parse_one_date(m1, d1, year), _parse_one_date(m2, d2, year)
    same_month = re.search(
        r"([A-Za-z]+)\s+(\d{1,2})\s*-\s*(\d{1,2})\s+(\d{4})",
        text,
    )
    if same_month:
        month, d1, d2, year = same_month.groups()
        return _parse_one_date(month, d1, year), _parse_one_date(month, d2, year)
    single = re.search(r"([A-Za-z]+)\s+(\d{1,2})\s+(\d{4})", text)
    if single:
        month, day, year = single.groups()
        parsed = _parse_one_date(month, day, year)
        return parsed, parsed
    return None, None


def json_dumps(value: Any) -> str | None:
    """Store nested prize/team lists as JSON text for JSONB upsert."""
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)
