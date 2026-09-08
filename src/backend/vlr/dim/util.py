"""Shared dim helpers so historical and incremental event loads share one parse path."""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Project-wide calendar dates: YYYY/M/D with no zero-pad (example 2026/7/8).
PROJECT_DATE_EXAMPLE = "2026/7/8"

_EVENT_ID_RE = re.compile(r"/event/(\d+)")
_MATCH_ID_RE = re.compile(r"vlr\.gg/(\d+)")
_PROJECT_DATE_RE = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$")
_TODAY_YESTERDAY_RE = re.compile(r"(Today|Yesterday)$", re.I)
_PATCH_RE = re.compile(r"Patch\s+([\d.]+)", re.I)
_JSONL_LOCK = threading.Lock()
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


def format_project_date(value: date | datetime | None) -> str | None:
    """Render a calendar date as YYYY/M/D so logs, JSON, and warehouse text match."""
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.date()
    return f"{value.year}/{value.month}/{value.day}"


def parse_project_date(raw: str | None) -> date | None:
    """Parse YYYY/M/D back to a date when a caller needs a real date object."""
    if not raw:
        return None
    match = _PROJECT_DATE_RE.match(str(raw).strip())
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def events_jsonl_path(repo_root: Path) -> Path:
    """Single append file of insert-ready dim_events rows (one JSON object per line)."""
    path = Path(repo_root) / "data" / "vlr" / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def event_json_path(repo_root: Path, event_id: str) -> Path:
    """Legacy per-event snapshot path (used only to resume older extracts)."""
    path = Path(repo_root) / "data" / "vlr" / "events" / f"{event_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def serialize_event_row(row: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe copy of an insert row (datetimes as ISO)."""
    out = dict(row)
    for key in ("insert_date", "update_date"):
        value = out.get(key)
        if isinstance(value, datetime):
            out[key] = value.isoformat()
        elif isinstance(value, date):
            out[key] = format_project_date(value)
    for key in ("start_date", "end_date"):
        value = out.get(key)
        if isinstance(value, (date, datetime)):
            out[key] = format_project_date(value)
    return out


def append_event_row(repo_root: Path, row: dict[str, Any]) -> Path:
    """Append one insert row so the landing file grows without rewriting."""
    path = events_jsonl_path(repo_root)
    payload = json.dumps(serialize_event_row(row), ensure_ascii=False, default=str)
    with _JSONL_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(payload + "\n")
    return path


def event_ids_in_jsonl(repo_root: Path) -> set[str]:
    """Ids already appended so a resume does not duplicate lines."""
    path = events_jsonl_path(repo_root)
    ids: set[str] = set()
    if not path.exists():
        return ids
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("[events_landing] Skip bad JSONL line in %s", path)
                continue
            event_id = obj.get("vlr_event_id") if isinstance(obj, dict) else None
            if event_id:
                ids.add(str(event_id))
    return ids


def read_event_rows_jsonl(repo_root: Path) -> list[dict[str, Any]]:
    """Load insert rows from the single landing file for the upsert step."""
    path = events_jsonl_path(repo_root)
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if isinstance(obj, dict) and obj.get("vlr_event_id"):
                rows.append(obj)
    return rows


def write_event_json(repo_root: Path, event_id: str, payload: Any) -> Path:
    """Legacy per-id write kept so older checkpoints can still be read."""
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


def parse_event_dates(
    raw: str | None, fallback_year: int | None = None
) -> tuple[str | None, str | None]:
    """Parse `Jul 15 – Sep 6, 2026` into project dates (`2026/7/15`, `2026/9/6`)."""
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
        return format_project_date(_parse_one_date(m1, d1, year)), format_project_date(
            _parse_one_date(m2, d2, year)
        )
    same_month = re.search(
        r"([A-Za-z]+)\s+(\d{1,2})\s*-\s*(\d{1,2})\s+(\d{4})",
        text,
    )
    if same_month:
        month, d1, d2, year = same_month.groups()
        return format_project_date(_parse_one_date(month, d1, year)), format_project_date(
            _parse_one_date(month, d2, year)
        )
    single = re.search(r"([A-Za-z]+)\s+(\d{1,2})\s+(\d{4})", text)
    if single:
        month, day, year = single.groups()
        parsed = format_project_date(_parse_one_date(month, day, year))
        return parsed, parsed
    return None, None


def json_dumps(value: Any) -> str | None:
    """Store nested prize/team lists as JSON text for JSONB upsert."""
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def matches_jsonl_path(repo_root: Path) -> Path:
    """Single append file: dim_matches row + listing + full /v2/match/details."""
    path = Path(repo_root) / "data" / "vlr" / "matches.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def event_matches_jsonl_path(repo_root: Path) -> Path:
    """Per-event match list cache so resume does not re-hit /v2/events/matches."""
    path = Path(repo_root) / "data" / "vlr" / "event_matches.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def match_id_from_url(url: str | None) -> str | None:
    """Parse vlr match id from a match page URL when the payload omits match_id."""
    if not url:
        return None
    match = _MATCH_ID_RE.search(str(url))
    return match.group(1) if match else None


def parse_match_patch(raw: str | None) -> str | None:
    """Pull `13.04` from `... Patch 13.04` so dim_matches.match_patch is stable."""
    if not raw:
        return None
    match = _PATCH_RE.search(str(raw))
    return match.group(1) if match else None


def parse_match_date(raw: str | None, fallback_year: int | None = None) -> str | None:
    """Parse VLR match date strings into project dates (`2026/8/29`)."""
    if not raw:
        return None
    text = _TODAY_YESTERDAY_RE.sub("", str(raw)).strip()
    text = re.sub(r"\d{1,2}:\d{2}\s*(AM|PM).*$", "", text, flags=re.I)
    text = _PATCH_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" ,")
    start, _ = parse_event_dates(text, fallback_year=fallback_year)
    return start


def serialize_match_row(row: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe copy of a match landing line (datetimes as ISO)."""
    out = dict(row)
    for key in ("insert_date", "update_date"):
        value = out.get(key)
        if isinstance(value, datetime):
            out[key] = value.isoformat()
        elif isinstance(value, date):
            out[key] = format_project_date(value)
    value = out.get("match_date")
    if isinstance(value, (date, datetime)):
        out["match_date"] = format_project_date(value)
    return out


def append_match_row(repo_root: Path, row: dict[str, Any]) -> Path:
    """Append one match landing line (dim fields + listing + detail)."""
    path = matches_jsonl_path(repo_root)
    payload = json.dumps(serialize_match_row(row), ensure_ascii=False, default=str)
    with _JSONL_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(payload + "\n")
    return path


def append_event_match_list(repo_root: Path, event_id: str, matches: list[dict[str, Any]]) -> Path:
    """Cache one event's match list so a resume skips that /v2/events/matches call."""
    path = event_matches_jsonl_path(repo_root)
    payload = json.dumps({"vlr_event_id": str(event_id), "matches": matches}, ensure_ascii=False)
    with _JSONL_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(payload + "\n")
    return path


def match_ids_in_jsonl(repo_root: Path) -> set[str]:
    """Ids already appended so a resume does not duplicate match lines."""
    path = matches_jsonl_path(repo_root)
    ids: set[str] = set()
    if not path.exists():
        return ids
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("[matches] Skip bad JSONL line in %s", path)
                continue
            match_id = obj.get("vlr_match_id") if isinstance(obj, dict) else None
            if match_id:
                ids.add(str(match_id))
    return ids


def event_ids_with_match_lists(repo_root: Path) -> set[str]:
    """Event ids already listed in event_matches.jsonl."""
    path = event_matches_jsonl_path(repo_root)
    ids: set[str] = set()
    if not path.exists():
        return ids
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_id = obj.get("vlr_event_id") if isinstance(obj, dict) else None
            if event_id:
                ids.add(str(event_id))
    return ids


def read_event_match_lists(repo_root: Path) -> dict[str, list[dict[str, Any]]]:
    """Load cached /v2/events/matches listings keyed by vlr_event_id."""
    path = event_matches_jsonl_path(repo_root)
    by_event: dict[str, list[dict[str, Any]]] = {}
    if not path.exists():
        return by_event
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                continue
            event_id = str(obj.get("vlr_event_id") or "")
            matches = obj.get("matches")
            if event_id and isinstance(matches, list):
                by_event[event_id] = [row for row in matches if isinstance(row, dict)]
    return by_event


def event_ids_from_jsonl(repo_root: Path) -> list[str]:
    """Event ids from events.jsonl so matches extract does not re-page /v2/events."""
    ids: list[str] = []
    seen: set[str] = set()
    for row in read_event_rows_jsonl(repo_root):
        event_id = str(row.get("vlr_event_id") or "")
        if event_id and event_id not in seen:
            seen.add(event_id)
            ids.append(event_id)
    return ids
