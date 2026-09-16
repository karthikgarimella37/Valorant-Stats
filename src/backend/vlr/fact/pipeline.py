"""Parse matches.jsonl into vlr fact jsonl and upsert into schema vlr. Do not scrape."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from backend.config.env import load_project_env
from backend.database_connectors.supabase_connectors import SupabaseConnector
from backend.vlr.dim.load import apply_dim_schema, stamp_rows, upsert_dim_rows
from backend.vlr.dim.util import matches_jsonl_path
from backend.vlr.fact.parse import parse_match_facts
from backend.vlr.fact.player_ids import load_player_id_lookup
from backend.vlr.fact.tables import FACT_SPECS, FROZEN_FACT_TABLES, FactSpec
from backend.vlr.fact.util import REPO_ROOT, fact_jsonl_path, facts_dir

logger = logging.getLogger(__name__)


def _root(repo_root: Path | None) -> Path:
    """CLI and Dagster share one repo root."""
    return Path(repo_root or REPO_ROOT)


def _grain_tuple(row: dict[str, Any], unique_cols: tuple[str, ...]) -> tuple[Any, ...] | None:
    """Composite grain for jsonl dedupe; skip rows missing any unique column."""
    values = tuple(row.get(col) for col in unique_cols)
    if any(value is None or value == "" for value in values):
        return None
    return values


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
    connector.execute(
        f"""
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
    )


def apply_facts_schema(repo_root: Path | None = None) -> None:
    """Create-if-missing fact tables; ADD columns (no DROP). Skip the in-flight performance table."""
    load_project_env(repo_root)
    root = _root(repo_root)
    logger.info("[facts] Schema start tables=%s", len(FACT_SPECS))
    connector = SupabaseConnector()
    for spec in FACT_SPECS:
        if spec.table in FROZEN_FACT_TABLES:
            logger.info("[facts] Schema skip in-flight table=%s", spec.table)
            continue
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


def load_facts(repo_root: Path | None = None) -> dict[str, int]:
    """Upsert landed fact jsonl on the composite grain. Performance stays on fact_key."""
    load_project_env(repo_root)
    logger.info("[facts] Load start")
    apply_facts_schema(repo_root)
    root = _root(repo_root)
    counts: dict[str, int] = {}
    for spec in FACT_SPECS:
        path = fact_jsonl_path(root, spec.stem)
        if not path.exists():
            logger.warning("[facts] Load skip missing jsonl table=%s path=%s", spec.table, path)
            counts[spec.table] = 0
            continue
        rows: list[dict[str, Any]] = []
        with path.open() as handle:
            for line in handle:
                if not line.strip():
                    continue
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
        stamp_rows(rows)
        # String fact_key keeps the in-flight upsert contract if this module reloads.
        conflict: str | tuple[str, ...]
        if spec.table in FROZEN_FACT_TABLES:
            conflict = "fact_key"
        else:
            conflict = spec.unique_cols
        counts[spec.table] = upsert_dim_rows(
            rows,
            table=spec.table,
            columns=spec.columns,
            conflict_column=conflict,
        )
        logger.info("[facts] Load progress table=%s upserted=%s", spec.table, counts[spec.table])
    logger.info("[facts] Load done %s", counts)
    return counts


def run_facts(repo_root: Path | None = None) -> dict[str, int]:
    """Schema is applied on load. Extract lands jsonl; load upserts. Caller must opt in."""
    extracted = extract_facts(repo_root)
    loaded = load_facts(repo_root)
    return {**{f"extracted_{k}": v for k, v in extracted.items()}, **{f"loaded_{k}": v for k, v in loaded.items()}}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    print("Fact backend is ready. Do not extract/load until discussed. Job: vlr_facts")
