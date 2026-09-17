"""Why: every incremental DAG uses the same four steps with the same log shape."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from backend.vlr.ops.watermarks import (
    ensure_watermarks_table,
    iso_seconds,
    read_watermark,
    watermark_to_meta,
    write_pipeline_watermarks,
    write_watermark,
)
from backend.vlr.ops.specs import WATERMARK_SPECS

logger = logging.getLogger(__name__)

# In-process handoff so facts/teams/players reuse match rows from the same Dagster run.
_STASH: dict[str, dict[str, Any]] = {}


def stash(run_id: str, key: str, value: Any) -> None:
    """Keep incremental payloads in memory for later steps of this Dagster run."""
    size = len(value) if hasattr(value, "__len__") and not isinstance(value, (str, bytes)) else 1
    _STASH.setdefault(run_id, {})[key] = value
    logger.info("[inc] stash run_id=%s key=%s n=%s", run_id, key, size)


def peek_stash(run_id: str, key: str) -> Any | None:
    """Read a stashed payload without dropping it (teams and facts both need match rows)."""
    value = _STASH.get(run_id, {}).get(key)
    if value is None:
        logger.info("[inc] stash miss run_id=%s key=%s", run_id, key)
        return None
    size = len(value) if hasattr(value, "__len__") and not isinstance(value, (str, bytes)) else 1
    logger.info("[inc] stash hit run_id=%s key=%s n=%s", run_id, key, size)
    return value


def clear_stash(run_id: str) -> None:
    """Drop run-local memory after the daily chain finishes."""
    dropped = _STASH.pop(run_id, None)
    logger.info("[inc] stash clear run_id=%s keys=%s", run_id, list(dropped or {}))


def step_check_watermark(pipeline_name: str, table_name: str | None = None) -> dict[str, Any]:
    """Step 1: ensure the ops table exists, then read last_source_at and compute since."""
    logger.info("[inc] === STEP check_watermark pipeline=%s table=%s ===", pipeline_name, table_name)
    path = ensure_watermarks_table()
    wm = read_watermark(pipeline_name, table_name)
    payload = watermark_to_meta(wm)
    payload["ddl_path"] = str(path)
    logger.info("[inc] check_watermark done %s", payload)
    return payload


def parse_since(payload: dict[str, Any]) -> datetime:
    """Rebuild the since timestamp the extract step received from check_watermark."""
    raw = payload.get("since")
    if not raw:
        raise RuntimeError("check_watermark payload missing since")
    value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def step_update_watermark(
    *,
    pipeline_name: str,
    table_name: str,
    last_source_at: datetime | None,
    row_count: int | None,
    dagster_run_id: str | None,
    dagster_job_name: str | None,
    status: str,
    error_text: str | None = None,
    counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Step 4: persist the cursor. Always runs after merge; failure must not advance last_source_at."""
    logger.info(
        "[inc] === STEP update_watermark pipeline=%s table=%s status=%s row_count=%s ===",
        pipeline_name,
        table_name,
        status,
        row_count,
    )
    if counts is not None:
        write_pipeline_watermarks(
            pipeline_name=pipeline_name,
            last_source_at=last_source_at,
            counts=counts,
            dagster_run_id=dagster_run_id,
            dagster_job_name=dagster_job_name,
            status=status,
            error_text=error_text,
        )
    else:
        write_watermark(
            pipeline_name=pipeline_name,
            table_name=table_name,
            last_source_at=last_source_at,
            row_count=row_count,
            dagster_run_id=dagster_run_id,
            dagster_job_name=dagster_job_name,
            status=status,
            error_text=error_text,
        )
    out = {
        "pipeline_name": pipeline_name,
        "table_name": table_name,
        "status": status,
        "row_count": row_count,
        "last_source_at": iso_seconds(last_source_at),
        "counts": counts or {},
    }
    logger.info("[inc] update_watermark done %s", out)
    return out


def run_full_refresh(
    *,
    pipeline_name: str,
    table_name: str,
    fn: Callable[[], Any],
    dagster_run_id: str | None,
    dagster_job_name: str | None,
    extra_tables: dict[str, int] | None = None,
) -> Any:
    """Catalog path: no source event time, so skip minus-1h, upsert the small full set, then write wm."""
    wm_meta = step_check_watermark(pipeline_name, table_name)
    logger.info(
        "[inc] === STEP extract+merge (full refresh) pipeline=%s table=%s reason=%s ===",
        pipeline_name,
        table_name,
        wm_meta.get("lookback_note"),
    )
    try:
        result = fn()
        known = {spec.table_name for spec in WATERMARK_SPECS if spec.pipeline_name == pipeline_name}
        if extra_tables is not None:
            counts = extra_tables
            row_count = sum(extra_tables.values())
        elif isinstance(result, dict):
            counts = {
                str(key): int(value)
                for key, value in result.items()
                if str(key) in known and isinstance(value, int)
            }
            if "loaded" in result and isinstance(result["loaded"], int):
                row_count = int(result["loaded"])
            elif table_name in counts:
                row_count = counts[table_name]
            elif counts:
                row_count = sum(counts.values())
            else:
                row_count = sum(int(value) for value in result.values() if isinstance(value, int))
        elif isinstance(result, int):
            counts = {table_name: result}
            row_count = result
        else:
            counts = {table_name: 0}
            row_count = 0
        now = datetime.now(timezone.utc)
        fan_out = bool(counts) and set(counts).issubset(known) and len(known) > 1
        logger.info(
            "[inc] full refresh merge done pipeline=%s table=%s row_count=%s counts=%s fan_out=%s",
            pipeline_name,
            table_name,
            row_count,
            counts,
            fan_out,
        )
        step_update_watermark(
            pipeline_name=pipeline_name,
            table_name=table_name,
            last_source_at=now,
            row_count=row_count,
            dagster_run_id=dagster_run_id,
            dagster_job_name=dagster_job_name,
            status="success",
            counts=counts if fan_out else None,
        )
        return result
    except Exception as exc:
        logger.exception("[inc] full refresh failed pipeline=%s table=%s", pipeline_name, table_name)
        step_update_watermark(
            pipeline_name=pipeline_name,
            table_name=table_name,
            last_source_at=None,
            row_count=None,
            dagster_run_id=dagster_run_id,
            dagster_job_name=dagster_job_name,
            status="failed",
            error_text=f"{type(exc).__name__}: {exc}",
        )
        raise


def max_source_now_if_live(max_source_at: datetime | None, has_live: bool) -> datetime:
    """Live/upcoming rows have no final source time; pin the cursor to now so the next run re-reads them."""
    now = datetime.now(timezone.utc)
    if has_live:
        logger.info("[inc] live/upcoming rows present; last_source_at=now %s", now.isoformat())
        return now
    if max_source_at is None:
        logger.info("[inc] no source timestamps; last_source_at=now %s", now.isoformat())
        return now
    logger.info("[inc] last_source_at from extracted rows %s", max_source_at.isoformat())
    return max_source_at
