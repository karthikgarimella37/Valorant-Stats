"""Seed vlr.dim_date so analytics can filter any year / quarter / month / week / range."""

from __future__ import annotations

import calendar
import logging
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from backend.config.env import load_project_env
from backend.database_connectors.supabase_connectors import SupabaseConnector
from backend.vlr.dim.util import format_project_date, utc_now

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_START = date(2020, 1, 1)
DEFAULT_END = date(2030, 12, 31)

DIM_COLS = (
    "date_key",
    "full_date",
    "project_date",
    "year",
    "quarter",
    "month",
    "day",
    "day_of_year",
    "day_of_week",
    "week_of_year",
    "iso_year",
    "week_of_month",
    "month_name",
    "month_short",
    "day_name",
    "day_short",
    "year_month",
    "year_month_text",
    "year_quarter",
    "year_quarter_text",
    "year_half",
    "year_half_text",
    "iso_week_num",
    "iso_week_key",
    "decade",
    "days_in_month",
    "week_start",
    "week_end",
    "month_start",
    "month_end",
    "quarter_start",
    "quarter_end",
    "half_start",
    "half_end",
    "year_start",
    "year_end",
    "is_weekend",
    "is_week_start",
    "is_week_end",
    "is_month_start",
    "is_month_end",
    "is_quarter_start",
    "is_quarter_end",
    "is_half_start",
    "is_half_end",
    "is_year_start",
    "is_year_end",
    "insert_date",
    "update_date",
)
DIM_TYPES = {
    "row_number": "BIGINT",
    "date_key": "INTEGER",
    "full_date": "DATE",
    "project_date": "TEXT",
    "year": "INTEGER",
    "quarter": "INTEGER",
    "month": "INTEGER",
    "day": "INTEGER",
    "day_of_year": "INTEGER",
    "day_of_week": "INTEGER",
    "week_of_year": "INTEGER",
    "iso_year": "INTEGER",
    "week_of_month": "INTEGER",
    "month_name": "TEXT",
    "month_short": "TEXT",
    "day_name": "TEXT",
    "day_short": "TEXT",
    "year_month": "INTEGER",
    "year_month_text": "TEXT",
    "year_quarter": "INTEGER",
    "year_quarter_text": "TEXT",
    "year_half": "INTEGER",
    "year_half_text": "TEXT",
    "iso_week_num": "INTEGER",
    "iso_week_key": "TEXT",
    "decade": "INTEGER",
    "days_in_month": "INTEGER",
    "week_start": "DATE",
    "week_end": "DATE",
    "month_start": "DATE",
    "month_end": "DATE",
    "quarter_start": "DATE",
    "quarter_end": "DATE",
    "half_start": "DATE",
    "half_end": "DATE",
    "year_start": "DATE",
    "year_end": "DATE",
    "is_weekend": "BOOLEAN",
    "is_week_start": "BOOLEAN",
    "is_week_end": "BOOLEAN",
    "is_month_start": "BOOLEAN",
    "is_month_end": "BOOLEAN",
    "is_quarter_start": "BOOLEAN",
    "is_quarter_end": "BOOLEAN",
    "is_half_start": "BOOLEAN",
    "is_half_end": "BOOLEAN",
    "is_year_start": "BOOLEAN",
    "is_year_end": "BOOLEAN",
    "insert_date": "TIMESTAMPTZ",
    "update_date": "TIMESTAMPTZ",
}


def _root(repo_root: Path | None) -> Path:
    """Resolve the git root so the parquet landing stays under data/vlr."""
    return Path(repo_root or REPO_ROOT)


def date_parquet_path(repo_root: Path) -> Path:
    """Single parquet of dim_date rows so load can replay without regenerating."""
    path = Path(repo_root) / "data" / "vlr" / "dim_date.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _parse_env_date(name: str, fallback: date) -> date:
    """Read VLR_DATE_START / VLR_DATE_END as ISO dates."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return fallback
    return date.fromisoformat(raw)


def _month_end(year: int, month: int) -> date:
    """Last calendar day of a month for month/quarter/half end bounds."""
    return date(year, month, calendar.monthrange(year, month)[1])


def format_date_row(day: date, *, now=None) -> dict[str, Any]:
    """Build one dim_date row with period keys and start/end bounds for range filters."""
    iso = day.isocalendar()
    quarter = (day.month - 1) // 3 + 1
    half = 1 if day.month <= 6 else 2
    q_start_month = 3 * (quarter - 1) + 1
    week_start = day - timedelta(days=iso.weekday - 1)
    week_end = week_start + timedelta(days=6)
    month_start = date(day.year, day.month, 1)
    month_end = _month_end(day.year, day.month)
    quarter_start = date(day.year, q_start_month, 1)
    quarter_end = _month_end(day.year, q_start_month + 2)
    half_start = date(day.year, 1 if half == 1 else 7, 1)
    half_end = _month_end(day.year, 6 if half == 1 else 12)
    year_start = date(day.year, 1, 1)
    year_end = date(day.year, 12, 31)
    stamp = now or utc_now()
    return {
        "date_key": day.year * 10000 + day.month * 100 + day.day,
        "full_date": day,
        "project_date": format_project_date(day),
        "year": day.year,
        "quarter": quarter,
        "month": day.month,
        "day": day.day,
        "day_of_year": day.timetuple().tm_yday,
        "day_of_week": iso.weekday,
        "week_of_year": iso.week,
        "iso_year": iso.year,
        "week_of_month": (day.day - 1) // 7 + 1,
        "month_name": day.strftime("%B"),
        "month_short": day.strftime("%b"),
        "day_name": day.strftime("%A"),
        "day_short": day.strftime("%a"),
        "year_month": day.year * 100 + day.month,
        "year_month_text": f"{day.year}/{day.month}",
        "year_quarter": day.year * 10 + quarter,
        "year_quarter_text": f"{day.year}-Q{quarter}",
        "year_half": half,
        "year_half_text": f"{day.year}-H{half}",
        "iso_week_num": iso.year * 100 + iso.week,
        "iso_week_key": f"{iso.year}-W{iso.week:02d}",
        "decade": (day.year // 10) * 10,
        "days_in_month": month_end.day,
        "week_start": week_start,
        "week_end": week_end,
        "month_start": month_start,
        "month_end": month_end,
        "quarter_start": quarter_start,
        "quarter_end": quarter_end,
        "half_start": half_start,
        "half_end": half_end,
        "year_start": year_start,
        "year_end": year_end,
        "is_weekend": iso.weekday >= 6,
        "is_week_start": iso.weekday == 1,
        "is_week_end": iso.weekday == 7,
        "is_month_start": day == month_start,
        "is_month_end": day == month_end,
        "is_quarter_start": day == quarter_start,
        "is_quarter_end": day == quarter_end,
        "is_half_start": day == half_start,
        "is_half_end": day == half_end,
        "is_year_start": day == year_start,
        "is_year_end": day == year_end,
        "insert_date": stamp,
        "update_date": stamp,
    }


def seed_dates(repo_root: Path | None = None) -> list[dict[str, Any]]:
    """Generate one row per day and land parquet. Serial: one calendar, no I/O to parallelize."""
    load_project_env(repo_root)
    repo_root = _root(repo_root)
    start = _parse_env_date("VLR_DATE_START", DEFAULT_START)
    end = _parse_env_date("VLR_DATE_END", DEFAULT_END)
    if end < start:
        raise ValueError(f"VLR_DATE_END {end} is before VLR_DATE_START {start}")
    logger.info("[dates] Seed start=%s end=%s", format_project_date(start), format_project_date(end))
    now = utc_now()
    rows: list[dict[str, Any]] = []
    day = start
    while day <= end:
        rows.append(format_date_row(day, now=now))
        day += timedelta(days=1)
        if len(rows) % 1000 == 0:
            logger.info("[dates] Generated %s/%s", len(rows), (end - start).days + 1)
    path = date_parquet_path(repo_root)
    import polars as pl

    pl.DataFrame(rows).write_parquet(path)
    logger.info("[dates] Seed done rows=%s path=%s", len(rows), path)
    return rows


def rows_from_dates_landing(repo_root: Path | None = None) -> list[dict[str, Any]]:
    """Read generated parquet so load does not rebuild the calendar."""
    import polars as pl

    path = date_parquet_path(_root(repo_root))
    if not path.exists():
        raise FileNotFoundError(f"dim_date parquet missing at {path}. Run seed_dates first.")
    logger.info("[dates] Reading landing parquet path=%s", path)
    return pl.read_parquet(path).to_dicts()


def load_dates(rows: list[dict[str, Any]]) -> int:
    """Upsert calendar rows on date_key so a re-seed keeps row_number."""
    logger.info("[dates] Load start rows=%s", len(rows))
    connector = SupabaseConnector()
    count = connector.upsert_rows(
        rows,
        schema="vlr",
        table="dim_date",
        columns=DIM_COLS,
        conflict_column="date_key",
        update_columns=[c for c in DIM_COLS if c not in {"date_key", "insert_date"}],
        jsonb_columns=(),
    )
    logger.info("[dates] Load done upserted=%s", count)
    return count


def apply_dates_schema(repo_root: Path | None = None) -> Path:
    """Create vlr.dim_date if missing; ADD / ALTER columns if the shape drifted."""
    load_project_env(repo_root)
    repo_root = _root(repo_root)
    sql_path = repo_root / "src" / "backend" / "sql" / "ddl" / "vlr_dim_date.sql"
    logger.info("[dates] Ensuring schema %s", sql_path)
    connector = SupabaseConnector()
    connector.execute_sql_file(sql_path)
    connector.ensure_table_columns("vlr", "dim_date", DIM_TYPES)
    for stmt in (
        "CREATE INDEX IF NOT EXISTS idx_vlr_dim_date_year ON vlr.dim_date (year)",
        "CREATE INDEX IF NOT EXISTS idx_vlr_dim_date_year_month ON vlr.dim_date (year_month)",
        "CREATE INDEX IF NOT EXISTS idx_vlr_dim_date_year_quarter ON vlr.dim_date (year_quarter)",
        "CREATE INDEX IF NOT EXISTS idx_vlr_dim_date_iso_week ON vlr.dim_date (iso_week_num)",
    ):
        connector.execute(stmt)
    logger.info("[dates] Schema ready (create-if-missing + alter, no drop)")
    return sql_path


def run_dates(repo_root: Path | None = None) -> dict[str, int]:
    """End-to-end dim_date: ensure table, generate calendar, upsert."""
    apply_dates_schema(repo_root)
    rows = seed_dates(repo_root)
    loaded = load_dates(rows)
    return {"extracted": len(rows), "loaded": loaded}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(run_dates())
