"""Shared schema + upsert so each dim module does not copy SQL plumbing."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from backend.database_connectors.supabase_connectors import SupabaseConnector
from backend.vlr.dim.util import utc_now

logger = logging.getLogger(__name__)

DDL_DIR = Path("src") / "backend" / "sql" / "ddl"


def apply_dim_schema(
    repo_root: Path,
    sql_name: str,
    table: str,
    dim_types: dict[str, str],
    indexes: tuple[str, ...] = (),
) -> Path:
    """Create-if-missing + ADD/ALTER columns (no DROP) for one vlr dim."""
    sql_path = repo_root / DDL_DIR / sql_name
    logger.info("[dims] Ensuring schema table=%s file=%s", table, sql_path)
    connector = SupabaseConnector()
    connector.execute_sql_file(sql_path)
    connector.ensure_table_columns("vlr", table, dim_types)
    for stmt in indexes:
        connector.execute(stmt)
    logger.info("[dims] Schema ready table=%s", table)
    return sql_path


def stamp_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Set insert/update timestamps so seed and jsonl rows share one clock."""
    now = utc_now()
    for row in rows:
        row.setdefault("insert_date", now)
        row["update_date"] = now
    return rows


def upsert_dim_rows(
    rows: list[dict[str, Any]],
    *,
    table: str,
    columns: tuple[str, ...],
    conflict_column: str | tuple[str, ...],
    jsonb_columns: tuple[str, ...] = (),
    batch_size: int = 1000,
    on_conflict: str = "update",
    max_cpu_pct: int | None = None,
    min_sleep_sec: float = 0.0,
) -> int:
    """Batch upsert on one column or a composite unique key; keep row_number on re-run."""
    if not rows:
        logger.info("[dims] Load skip empty table=%s", table)
        return 0
    connector = SupabaseConnector()
    conflict_cols = (conflict_column,) if isinstance(conflict_column, str) else tuple(conflict_column)
    update_columns = [c for c in columns if c not in {*conflict_cols, "insert_date"}]
    logger.info("[dims] Load start table=%s rows=%s", table, len(rows))
    total = connector.upsert_rows(
        rows,
        schema="vlr",
        table=table,
        columns=columns,
        conflict_column=conflict_column,
        update_columns=update_columns,
        jsonb_columns=jsonb_columns,
        batch_size=batch_size,
        on_conflict=on_conflict,
        max_cpu_pct=max_cpu_pct,
        min_sleep_sec=min_sleep_sec,
    )
    logger.info("[dims] Load done table=%s upserted=%s", table, total)
    return total
