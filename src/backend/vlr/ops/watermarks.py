"""Why: one TIMESTAMPTZ cursor per pipeline+table so every DAG starts from the same clock."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.config.env import load_project_env
from backend.database_connectors.supabase_connectors import SupabaseConnector
from backend.vlr.ops.specs import WATERMARK_SPECS, WatermarkSpec, spec_for

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[4]
DDL_NAME = "vlr_ops_pipeline_watermarks.sql"
TABLE = "ops_pipeline_watermarks"
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class Watermark:
    """In-memory cursor after a warehouse read (None fields mean first run)."""

    pipeline_name: str
    table_name: str
    source_name: str
    last_source_at: datetime | None
    last_success_at: datetime | None
    last_attempt_at: datetime | None
    status: str
    row_count: int | None
    bootstrap: bool
    overlap_hours: float
    lookback_note: str
    since: datetime


def _utc(value: datetime | None) -> datetime | None:
    """Normalize DB timestamps to aware UTC so timedelta math does not explode."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso_seconds(value: datetime | None) -> str | None:
    """Log/JSON clock with seconds (watermark lookback is last_source_at minus 1 hour)."""
    stamped = _utc(value)
    if stamped is None:
        return None
    return stamped.isoformat(timespec="seconds")


def _safe_table(name: str) -> str:
    """Reject anything that is not a SQL identifier before interpolating a table name."""
    if not _IDENT_RE.match(name):
        raise ValueError(f"Unsafe table name {name!r}")
    return name


def ensure_watermarks_table(repo_root: Path | None = None) -> Path:
    """Create vlr.ops_pipeline_watermarks and seed one row per known table (no overwrite)."""
    load_project_env(repo_root)
    root = Path(repo_root or REPO_ROOT)
    sql_path = root / "src" / "backend" / "sql" / "ddl" / DDL_NAME
    logger.info("[watermark] Ensure table start path=%s", sql_path)
    connector = SupabaseConnector()
    connector.execute_sql_file(sql_path)
    seeded = 0
    for spec in WATERMARK_SPECS:
        connector.execute(
            """
            INSERT INTO vlr.ops_pipeline_watermarks (
                pipeline_name, table_name, source_name, status
            ) VALUES (%s, %s, %s, 'never_run')
            ON CONFLICT (pipeline_name, table_name) DO NOTHING
            """,
            (spec.pipeline_name, spec.table_name, spec.source_name),
        )
        seeded += 1
    logger.info("[watermark] Ensure table done specs=%s path=%s", seeded, sql_path)
    return sql_path


def _bootstrap_days() -> int:
    """First incremental run with an empty table looks back this many days, not all history."""
    return max(1, int(os.getenv("VLR_INC_BOOTSTRAP_DAYS", "7")))


def bootstrap_last_source_at(table_name: str) -> datetime:
    """Seed `since` from MAX(update_date) so the first incremental run does not rescan history.

    update_date is the warehouse load clock, not match_date: a 2023 match loaded yesterday
    must not rewind the cursor to 2023.
    """
    table = _safe_table(table_name)
    connector = SupabaseConnector()
    logger.info("[watermark] Bootstrap MAX(update_date) table=vlr.%s", table)
    try:
        row = connector.fetch_one(f"SELECT MAX(update_date) FROM vlr.{table}")
    except Exception:
        logger.exception("[watermark] Bootstrap query failed table=vlr.%s; using %s-day lookback", table, _bootstrap_days())
        return datetime.now(timezone.utc) - timedelta(days=_bootstrap_days())
    raw = row[0] if row else None
    stamped = _utc(raw) if isinstance(raw, datetime) else None
    if stamped is None:
        since = datetime.now(timezone.utc) - timedelta(days=_bootstrap_days())
        logger.info(
            "[watermark] Bootstrap empty table=vlr.%s using VLR_INC_BOOTSTRAP_DAYS=%s since=%s",
            table,
            _bootstrap_days(),
            iso_seconds(since),
        )
        return since
    logger.info("[watermark] Bootstrap table=vlr.%s max_update_date=%s", table, iso_seconds(stamped))
    return stamped


def compute_since(spec: WatermarkSpec, last_source_at: datetime | None) -> tuple[datetime, bool]:
    """Apply the 1-hour overlap (or skip it) and say whether this was a bootstrap."""
    if last_source_at is None:
        return bootstrap_last_source_at(spec.table_name), True
    overlap = timedelta(hours=spec.overlap_hours)
    since = last_source_at - overlap
    logger.info(
        "[watermark] since pipeline=%s table=%s last_source_at=%s overlap_hours=%s since=%s date_only=%s note=%s",
        spec.pipeline_name,
        spec.table_name,
        last_source_at.isoformat(),
        spec.overlap_hours,
        since.isoformat(),
        spec.date_only,
        spec.lookback_note,
    )
    return since, False


def read_watermark(pipeline_name: str, table_name: str | None = None) -> Watermark:
    """Load the cursor for one pipeline+table; bootstrap `since` when last_source_at is null."""
    spec = spec_for(pipeline_name, table_name)
    logger.info(
        "[watermark] Read start pipeline=%s table=%s overlap_hours=%s",
        spec.pipeline_name,
        spec.table_name,
        spec.overlap_hours,
    )
    connector = SupabaseConnector()
    row = connector.fetch_one(
        """
        SELECT last_source_at, last_success_at, last_attempt_at, status, row_count
        FROM vlr.ops_pipeline_watermarks
        WHERE pipeline_name = %s AND table_name = %s
        """,
        (spec.pipeline_name, spec.table_name),
    )
    last_source_at = _utc(row[0]) if row else None
    last_success_at = _utc(row[1]) if row else None
    last_attempt_at = _utc(row[2]) if row else None
    status = str(row[3]) if row and row[3] else "missing"
    row_count = int(row[4]) if row and row[4] is not None else None
    since, bootstrap = compute_since(spec, last_source_at)
    wm = Watermark(
        pipeline_name=spec.pipeline_name,
        table_name=spec.table_name,
        source_name=spec.source_name,
        last_source_at=last_source_at,
        last_success_at=last_success_at,
        last_attempt_at=last_attempt_at,
        status=status,
        row_count=row_count,
        bootstrap=bootstrap,
        overlap_hours=spec.overlap_hours,
        date_only=spec.date_only,
        lookback_note=spec.lookback_note,
        since=since,
    )
    logger.info(
        "[watermark] Read done pipeline=%s table=%s status=%s last_source_at=%s last_success_at=%s "
        "bootstrap=%s since=%s previous_row_count=%s",
        wm.pipeline_name,
        wm.table_name,
        wm.status,
        wm.last_source_at.isoformat() if wm.last_source_at else None,
        wm.last_success_at.isoformat() if wm.last_success_at else None,
        wm.bootstrap,
        wm.since.isoformat(),
        wm.row_count,
    )
    return wm


def write_watermark(
    *,
    pipeline_name: str,
    table_name: str,
    source_name: str | None = None,
    last_source_at: datetime | None,
    row_count: int | None,
    dagster_run_id: str | None,
    dagster_job_name: str | None,
    status: str,
    error_text: str | None = None,
) -> None:
    """Always persist the attempt. Success may advance last_source_at; failure never does."""
    spec = spec_for(pipeline_name, table_name)
    now = datetime.now(timezone.utc)
    success = status == "success"
    source = source_name or spec.source_name
    logger.info(
        "[watermark] Write start pipeline=%s table=%s status=%s row_count=%s last_source_at=%s "
        "run_id=%s job=%s error=%s",
        pipeline_name,
        table_name,
        status,
        row_count,
        last_source_at.isoformat() if last_source_at else None,
        dagster_run_id,
        dagster_job_name,
        (error_text or "")[:300],
    )
    connector = SupabaseConnector()
    connector.execute(
        """
        INSERT INTO vlr.ops_pipeline_watermarks (
            pipeline_name, table_name, source_name,
            last_source_at, last_success_at, last_attempt_at,
            row_count, dagster_run_id, dagster_job_name, status, error_text, update_date
        ) VALUES (
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (pipeline_name, table_name) DO UPDATE SET
            source_name = EXCLUDED.source_name,
            last_source_at = CASE
                WHEN EXCLUDED.status = 'success' AND EXCLUDED.last_source_at IS NOT NULL
                THEN GREATEST(
                    COALESCE(vlr.ops_pipeline_watermarks.last_source_at, EXCLUDED.last_source_at),
                    EXCLUDED.last_source_at
                )
                ELSE vlr.ops_pipeline_watermarks.last_source_at
            END,
            last_success_at = CASE
                WHEN EXCLUDED.status = 'success' THEN EXCLUDED.last_success_at
                ELSE vlr.ops_pipeline_watermarks.last_success_at
            END,
            last_attempt_at = EXCLUDED.last_attempt_at,
            row_count = CASE
                WHEN EXCLUDED.status = 'success' THEN EXCLUDED.row_count
                ELSE vlr.ops_pipeline_watermarks.row_count
            END,
            dagster_run_id = EXCLUDED.dagster_run_id,
            dagster_job_name = EXCLUDED.dagster_job_name,
            status = EXCLUDED.status,
            error_text = EXCLUDED.error_text,
            update_date = EXCLUDED.update_date
        """,
        (
            pipeline_name,
            table_name,
            source,
            last_source_at if success else None,
            now if success else None,
            now,
            row_count if success else None,
            dagster_run_id,
            dagster_job_name,
            status,
            (error_text or "")[:2000] or None,
            now,
        ),
    )
    logger.info("[watermark] Write done pipeline=%s table=%s status=%s", pipeline_name, table_name, status)


def write_pipeline_watermarks(
    *,
    pipeline_name: str,
    last_source_at: datetime | None,
    counts: dict[str, int],
    dagster_run_id: str | None,
    dagster_job_name: str | None,
    status: str,
    error_text: str | None = None,
) -> None:
    """Facts (and any multi-table job) write one cursor per table, same last_source_at."""
    specs = [spec for spec in WATERMARK_SPECS if spec.pipeline_name == pipeline_name]
    logger.info(
        "[watermark] Write pipeline=%s tables=%s status=%s counts=%s",
        pipeline_name,
        [spec.table_name for spec in specs],
        status,
        counts,
    )
    for spec in specs:
        write_watermark(
            pipeline_name=pipeline_name,
            table_name=spec.table_name,
            source_name=spec.source_name,
            last_source_at=last_source_at,
            row_count=counts.get(spec.table_name),
            dagster_run_id=dagster_run_id,
            dagster_job_name=dagster_job_name,
            status=status,
            error_text=error_text,
        )


def watermark_to_meta(wm: Watermark) -> dict[str, Any]:
    """Small JSON-safe dict for Dagster metadata and step payloads."""
    return {
        "pipeline_name": wm.pipeline_name,
        "table_name": wm.table_name,
        "source_name": wm.source_name,
        "last_source_at": wm.last_source_at.isoformat() if wm.last_source_at else None,
        "last_success_at": wm.last_success_at.isoformat() if wm.last_success_at else None,
        "status": wm.status,
        "bootstrap": wm.bootstrap,
        "overlap_hours": wm.overlap_hours,
        "date_only": wm.date_only,
        "lookback_note": wm.lookback_note,
        "since": wm.since.isoformat(),
        "previous_row_count": wm.row_count,
    }
