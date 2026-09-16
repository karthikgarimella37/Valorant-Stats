"""Parse matches.jsonl into vlr fact jsonl and upsert into schema vlr. Do not scrape."""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from backend.config.env import load_project_env
from backend.database_connectors.supabase_connectors import SupabaseConnector
from backend.vlr.dim.load import apply_dim_schema, stamp_rows, upsert_dim_rows
from backend.vlr.dim.util import matches_jsonl_path
from backend.vlr.fact.parse import parse_match_facts
from backend.vlr.fact.player_ids import load_player_id_lookup
from backend.vlr.fact.tables import FACT_SPECS, FactSpec
from backend.vlr.fact.util import REPO_ROOT, coalesce_id, fact_jsonl_path, facts_dir

logger = logging.getLogger(__name__)

DEFAULT_LOAD_WORKERS = 1


def _root(repo_root: Path | None) -> Path:
    """CLI and Dagster share one repo root."""
    return Path(repo_root or REPO_ROOT)


def _grain_id_cols(unique_cols: tuple[str, ...]) -> tuple[str, ...]:
    """Unique columns that are source ids (never null; missing → -1)."""
    return tuple(col for col in unique_cols if col.endswith("_id"))


def _fill_row_ids(row: dict[str, Any], unique_cols: tuple[str, ...]) -> dict[str, Any]:
    """COALESCE(NULLIF(trim(id), ''), '-1') on grain id columns."""
    for col in _grain_id_cols(unique_cols):
        row[col] = coalesce_id(row.get(col))
    return row


def _grain_tuple(row: dict[str, Any], unique_cols: tuple[str, ...]) -> tuple[Any, ...] | None:
    """Composite grain for jsonl dedupe; id blanks become -1; skip if a non-id key is missing."""
    _fill_row_ids(row, unique_cols)
    values = tuple(row.get(col) for col in unique_cols)
    if any(value is None or value == "" for value in values):
        return None
    return values


def _fill_null_grain_ids(connector: SupabaseConnector, spec: FactSpec) -> None:
    """Replace warehouse null/blank grain ids with -1, then NOT NULL."""
    id_cols = _grain_id_cols(spec.unique_cols)
    extra = tuple(
        col
        for col in spec.columns
        if col.endswith("_id") and col not in id_cols and col != "vlr_event_id"
    )
    cols = id_cols + extra
    if not cols:
        return
    logger.info("[facts] Fill null ids table=%s cols=%s", spec.table, cols)
    sets = ", ".join(f"{col} = COALESCE(NULLIF(BTRIM({col}), ''), '-1')" for col in cols)
    where = " OR ".join(f"{col} IS NULL OR BTRIM({col}) = ''" for col in cols)
    with connector._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '10min'")
            cur.execute(f"UPDATE vlr.{spec.table} SET {sets} WHERE {where}")
            updated = cur.rowcount
            for col in cols:
                cur.execute(f"ALTER TABLE vlr.{spec.table} ALTER COLUMN {col} SET NOT NULL")
        conn.commit()
    logger.info("[facts] Fill null ids done table=%s updated=%s", spec.table, updated)


def _retire_concat_key(connector: SupabaseConnector, table: str) -> None:
    """Drop concatenated fact_key uniqueness so upsert can use the composite grain."""
    logger.info("[facts] Retire concat key table=%s", table)
    connector.execute(f'DROP INDEX IF EXISTS vlr.uq_vlr_{table}_fact_key')
    connector.execute(f'ALTER TABLE vlr.{table} DROP CONSTRAINT IF EXISTS {table}_fact_key_key')
    connector.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'vlr' AND table_name = '{table}' AND column_name = 'fact_key'
          ) THEN
            ALTER TABLE vlr.{table} ALTER COLUMN fact_key DROP NOT NULL;
          END IF;
        END $$;
        """
    )


def _ensure_grain_unique(connector: SupabaseConnector, spec: FactSpec) -> None:
    """Named UNIQUE on the grain columns (composite key, not a concat string)."""
    name = f"uq_vlr_{spec.table}_grain"
    cols = ", ".join(spec.unique_cols)
    logger.info("[facts] Ensure grain unique table=%s cols=%s", spec.table, spec.unique_cols)
    sql = f"""
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            JOIN pg_namespace n ON t.relnamespace = n.oid
            WHERE n.nspname = 'vlr' AND t.relname = '{spec.table}' AND c.conname = '{name}'
          ) THEN
            ALTER TABLE vlr.{spec.table} ADD CONSTRAINT {name} UNIQUE ({cols});
          END IF;
        END $$;
    """
    with connector._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 0")
            cur.execute(sql)
        conn.commit()


def apply_facts_schema(repo_root: Path | None = None) -> None:
    """Create-if-missing fact tables; ADD columns; composite unique on grain columns."""
    load_project_env(repo_root)
    root = _root(repo_root)
    logger.info("[facts] Schema start tables=%s", len(FACT_SPECS))
    connector = SupabaseConnector()
    for spec in FACT_SPECS:
        apply_dim_schema(root, spec.sql_name, spec.table, spec.types)
        _retire_concat_key(connector, spec.table)
        _ensure_grain_unique(connector, spec)
    logger.info("[facts] Schema done")


def extract_facts(repo_root: Path | None = None) -> dict[str, int]:
    """One serial pass over matches.jsonl (single file). Land fact jsonl only."""
    load_project_env(repo_root)
    root = _root(repo_root)
    path = matches_jsonl_path(root)
    if not path.exists():
        raise FileNotFoundError(f"matches.jsonl missing at {path}. Do not run until details exist.")
    logger.info("[facts] Extract start source=%s", path)
    player_ids = load_player_id_lookup(root)
    buckets: dict[str, dict[tuple[Any, ...], dict[str, Any]]] = {spec.stem: {} for spec in FACT_SPECS}
    unique_by_stem = {spec.stem: spec.unique_cols for spec in FACT_SPECS}
    scanned = 0
    used = 0
    skipped_grain = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            scanned += 1
            if scanned % 500 == 0:
                logger.info("[facts] Extract progress lines=%s used=%s", scanned, used)
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                logger.exception("[facts] Bad jsonl line=%s", scanned)
                continue
            if not isinstance(obj, dict):
                continue
            parsed = parse_match_facts(obj, player_ids=player_ids)
            if not parsed["overall"] and not parsed["series"]:
                continue
            used += 1
            for stem, rows in parsed.items():
                dest = buckets.get(stem)
                if dest is None:
                    continue
                unique_cols = unique_by_stem[stem]
                for row in rows:
                    grain = _grain_tuple(row, unique_cols)
                    if grain is None:
                        skipped_grain += 1
                        continue
                    dest[grain] = row
    facts_dir(root).mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {
        "matches_scanned": scanned,
        "matches_with_detail": used,
        "skipped_incomplete_grain": skipped_grain,
        "unresolved_player_ids": player_ids.unresolved,
    }
    for spec in FACT_SPECS:
        rows = stamp_rows(list(buckets[spec.stem].values()))
        out = fact_jsonl_path(root, spec.stem)
        with out.open("w", encoding="utf-8") as handle:
            for row in rows:
                payload = dict(row)
                for key in ("insert_date", "update_date"):
                    stamp = payload.get(key)
                    if hasattr(stamp, "isoformat"):
                        payload[key] = stamp.isoformat()
                handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        counts[spec.table] = len(rows)
        logger.info("[facts] Landed %s rows=%s path=%s", spec.table, len(rows), out)
    logger.info("[facts] Extract done %s", counts)
    return counts


def _read_fact_jsonl(spec: FactSpec, root: Path) -> list[dict[str, Any]]:
    """Load one fact jsonl into stamped rows. Empty file → empty list."""
    path = fact_jsonl_path(root, spec.stem)
    if not path.exists():
        logger.warning("[facts] Load skip missing jsonl table=%s path=%s", spec.table, path)
        return []
    rows: list[dict[str, Any]] = []
    with path.open() as handle:
        for line in handle:
            if not line.strip():
                continue
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
    return stamp_rows(rows)


def _load_one_table(
    spec: FactSpec,
    root: Path,
    *,
    on_conflict: str = "update",
    batch_size: int = 1000,
    max_cpu_pct: int | None = 60,
    min_sleep_sec: float = 4.0,
) -> tuple[str, int]:
    """Upsert one fact jsonl onto its composite unique. Independent of other fact tables."""
    rows = _read_fact_jsonl(spec, root)
    if not rows:
        return spec.table, 0
    count = upsert_dim_rows(
        rows,
        table=spec.table,
        columns=spec.columns,
        conflict_column=spec.unique_cols,
        batch_size=batch_size,
        on_conflict=on_conflict,
        max_cpu_pct=max_cpu_pct,
        min_sleep_sec=min_sleep_sec,
    )
    logger.info("[facts] Load progress table=%s upserted=%s", spec.table, count)
    return spec.table, count


def _copy_one_table(
    spec: FactSpec,
    root: Path,
    *,
    batch_size: int = 1000,
    max_cpu_pct: int = 60,
    min_sleep_sec: float = 4.0,
) -> tuple[str, int]:
    """COPY one empty-or-append fact jsonl. Fails if grain keys already exist."""
    rows = _read_fact_jsonl(spec, root)
    if not rows:
        return spec.table, 0
    logger.info("[facts] Copy start table=%s rows=%s", spec.table, len(rows))
    count = SupabaseConnector().copy_rows(
        rows,
        schema="vlr",
        table=spec.table,
        columns=spec.columns,
        batch_size=batch_size,
        max_cpu_pct=max_cpu_pct,
        min_sleep_sec=min_sleep_sec,
    )
    logger.info("[facts] Copy done table=%s rows=%s", spec.table, count)
    return spec.table, count


def load_one_fact_table(
    table: str,
    repo_root: Path | None = None,
    *,
    use_copy: bool = True,
    apply_schema: bool = True,
    batch_size: int = 1000,
    max_cpu_pct: int = 60,
    on_conflict: str = "update",
    min_sleep_sec: float = 4.0,
) -> tuple[str, int]:
    """Schema for one fact table, then COPY (default) or upsert that jsonl only."""
    load_project_env(repo_root)
    spec = next((item for item in FACT_SPECS if item.table == table), None)
    if spec is None:
        names = ", ".join(item.table for item in FACT_SPECS)
        raise ValueError(f"Unknown fact table {table!r}. Choose one of: {names}")
    root = _root(repo_root)
    connector = SupabaseConnector()
    if apply_schema:
        apply_dim_schema(root, spec.sql_name, spec.table, spec.types)
    _retire_concat_key(connector, spec.table)
    _ensure_grain_unique(connector, spec)
    if use_copy:
        return _copy_one_table(
            spec,
            root,
            batch_size=batch_size,
            max_cpu_pct=max_cpu_pct,
            min_sleep_sec=min_sleep_sec,
        )
    return _load_one_table(
        spec,
        root,
        on_conflict=on_conflict,
        batch_size=min(batch_size, 1000),
        max_cpu_pct=max_cpu_pct,
        min_sleep_sec=min_sleep_sec,
    )


def load_facts(repo_root: Path | None = None) -> dict[str, int]:
    """Schema first (serial), then upsert each fact table in parallel — they do not share rows."""
    load_project_env(repo_root)
    apply_facts_schema(repo_root)
    root = _root(repo_root)
    workers = max(1, int(os.environ.get("VLR_FACT_LOAD_WORKERS", str(DEFAULT_LOAD_WORKERS))))
    logger.info("[facts] Load start tables=%s workers=%s", len(FACT_SPECS), workers)
    counts: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_load_one_table, spec, root) for spec in FACT_SPECS]
        for fut in as_completed(futures):
            table, count = fut.result()
            counts[table] = count
    logger.info("[facts] Load done %s", counts)
    return counts


def run_facts(repo_root: Path | None = None) -> dict[str, int]:
    """Schema is applied on load. Extract lands jsonl; load upserts. Caller must opt in."""
    extracted = extract_facts(repo_root)
    loaded = load_facts(repo_root)
    return {**{f"extracted_{k}": v for k, v in extracted.items()}, **{f"loaded_{k}": v for k, v in loaded.items()}}


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Load one vlr fact table from jsonl (no Dagster UI).")
    parser.add_argument("--table", required=True, help="Warehouse table, e.g. fact_map_veto")
    parser.add_argument("--upsert", action="store_true", help="Use ON CONFLICT upsert instead of COPY")
    parser.add_argument("--insert-only", action="store_true", help="ON CONFLICT DO NOTHING (fill remaining rows)")
    parser.add_argument("--no-schema", action="store_true", help="Skip DDL; table must already exist")
    parser.add_argument("--batch-size", type=int, default=500, help="Rows per commit (keep small to cap CPU spikes)")
    parser.add_argument("--max-cpu-pct", type=int, default=40, help="Target average duty cycle; peak during a batch can still spike")
    parser.add_argument("--min-sleep-sec", type=float, default=5.0, help="Minimum idle seconds after every batch")
    args = parser.parse_args()
    use_copy = not args.upsert and not args.insert_only
    table, count = load_one_fact_table(
        args.table,
        use_copy=use_copy,
        apply_schema=not args.no_schema,
        batch_size=args.batch_size,
        max_cpu_pct=args.max_cpu_pct,
        on_conflict="nothing" if args.insert_only else "update",
        min_sleep_sec=args.min_sleep_sec,
    )
    print(f"{table} rows={count}")
