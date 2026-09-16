"""Parse matches.jsonl into vlr fact jsonl and upsert into schema vlr. Do not scrape."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from backend.config.env import load_project_env
from backend.database_connectors.supabase_connectors import SupabaseConnector
from backend.vlr.dim.load import apply_dim_schema, stamp_rows, upsert_dim_rows
from backend.vlr.dim.util import json_dumps, matches_jsonl_path
from backend.vlr.fact.parse import parse_match_facts
from backend.vlr.fact.tables import FACT_SPECS
from backend.vlr.fact.util import REPO_ROOT, fact_jsonl_path, facts_dir

logger = logging.getLogger(__name__)


def _root(repo_root: Path | None) -> Path:
    """CLI and Dagster share one repo root."""
    return Path(repo_root or REPO_ROOT)


def apply_facts_schema(repo_root: Path | None = None) -> None:
    """Create-if-missing all fact tables; ADD columns (no DROP). Unique fact_key."""
    load_project_env(repo_root)
    root = _root(repo_root)
    logger.info("[facts] Schema start tables=%s", len(FACT_SPECS))
    connector = SupabaseConnector()
    for _stem, table, sql_name, _cols, types in FACT_SPECS:
        apply_dim_schema(root, sql_name, table, types)
        connector.execute(
            f'CREATE UNIQUE INDEX IF NOT EXISTS uq_vlr_{table}_fact_key '
            f"ON vlr.{table} (fact_key)"
        )
    logger.info("[facts] Schema done")


def extract_facts(repo_root: Path | None = None) -> dict[str, int]:
    """One serial pass over matches.jsonl (single file). Land fact jsonl only."""
    load_project_env(repo_root)
    root = _root(repo_root)
    path = matches_jsonl_path(root)
    if not path.exists():
        raise FileNotFoundError(f"matches.jsonl missing at {path}. Do not run until details exist.")
    logger.info("[facts] Extract start source=%s", path)
    buckets: dict[str, dict[str, dict[str, Any]]] = {stem: {} for stem, *_ in FACT_SPECS}
    scanned = 0
    used = 0
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
            parsed = parse_match_facts(obj)
            if not parsed["overall"] and not parsed["series"]:
                continue
            used += 1
            for stem, rows in parsed.items():
                dest = buckets.get(stem)
                if dest is None:
                    continue
                for row in rows:
                    dest[row["fact_key"]] = row
    facts_dir(root).mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {"matches_scanned": scanned, "matches_with_detail": used}
    for stem, table, _sql, _cols, _types in FACT_SPECS:
        rows = stamp_rows(list(buckets[stem].values()))
        out = fact_jsonl_path(root, stem)
        with out.open("w", encoding="utf-8") as handle:
            for row in rows:
                payload = dict(row)
                for key in ("insert_date", "update_date"):
                    stamp = payload.get(key)
                    if hasattr(stamp, "isoformat"):
                        payload[key] = stamp.isoformat()
                handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        counts[table] = len(rows)
        logger.info("[facts] Landed %s rows=%s path=%s", table, len(rows), out)
    logger.info("[facts] Extract done %s", counts)
    return counts


def load_facts(repo_root: Path | None = None) -> dict[str, int]:
    """Upsert landed fact jsonl on fact_key. Keep row_number on re-run."""
    load_project_env(repo_root)
    logger.info("[facts] Load start")
    apply_facts_schema(repo_root)
    root = _root(repo_root)
    counts: dict[str, int] = {}
    for stem, table, _sql, cols, _types in FACT_SPECS:
        path = fact_jsonl_path(root, stem)
        if not path.exists():
            logger.warning("[facts] Load skip missing jsonl table=%s path=%s", table, path)
            counts[table] = 0
            continue
        rows: list[dict[str, Any]] = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
        stamp_rows(rows)
        counts[table] = upsert_dim_rows(
            rows,
            table=table,
            columns=cols,
            conflict_column="fact_key",
        )
        logger.info("[facts] Load progress table=%s upserted=%s", table, counts[table])
    logger.info("[facts] Load done %s", counts)
    return counts


def run_facts(repo_root: Path | None = None) -> dict[str, int]:
    """Schema is applied on load. Extract lands jsonl; load upserts. Caller must opt in."""
    extracted = extract_facts(repo_root)
    loaded = load_facts(repo_root)
    return {**{f"extracted_{k}": v for k, v in extracted.items()}, **{f"loaded_{k}": v for k, v in loaded.items()}}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print(extract_facts())
