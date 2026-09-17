"""Extract rib match JSON, parse overlay facts, upsert into schema vlr. Batched so Supabase CPU stays bounded."""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from backend.config.env import load_project_env
from backend.database_connectors.supabase_connectors import SupabaseConnector
from backend.rib_gg.extract_matches import extract_rib_matches
from backend.rib_gg.join import build_crosswalk, player_lookup
from backend.rib_gg.parse import parse_landed_match
from backend.rib_gg.paths import (
    REPO_ROOT,
    crosswalk_jsonl_path,
    fact_jsonl_path,
    facts_dir,
    match_json_path,
    matches_jsonl_path,
)
from backend.rib_gg.tables import FACT_SPECS, FactSpec
from backend.vlr.dim.load import apply_dim_schema, stamp_rows, upsert_dim_rows
from backend.vlr.fact.util import coalesce_id

logger = logging.getLogger(__name__)

DEFAULT_LOAD_WORKERS = 4


def _root(repo_root: Path | None) -> Path:
    """CLI and Dagster share one repo root."""
    return Path(repo_root or REPO_ROOT)


def _grain_tuple(row: dict[str, Any], unique_cols: tuple[str, ...]) -> tuple[Any, ...] | None:
    """Skip rows missing a non-id unique col; coalesce rib *_id grain cols to -1."""
    for col in unique_cols:
        if col.endswith("_id"):
            row[col] = coalesce_id(row.get(col))
    values = tuple(row.get(col) for col in unique_cols)
    if any(value is None or value == "" for value in values):
        return None
    return values


def apply_rib_facts_schema(repo_root: Path | None = None) -> None:
    """Create-if-missing overlay tables and composite uniques."""
    load_project_env(repo_root)
    root = _root(repo_root)
    logger.info("[rib_facts] Schema start tables=%s", len(FACT_SPECS))
    for spec in FACT_SPECS:
        apply_dim_schema(root, spec.sql_name, spec.table, spec.types)
    logger.info("[rib_facts] Schema done")


def _match_ids(root: Path) -> list[str]:
    """Prefer matches.jsonl index; fall back to json/matches/*.json."""
    path = matches_jsonl_path(root)
    ids: list[str] = []
    seen: set[str] = set()
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                match_id = str(obj.get("rib_match_id") or "").strip()
                if match_id and match_id not in seen:
                    seen.add(match_id)
                    ids.append(match_id)
    json_dir = root / "data" / "rib_gg" / "json" / "matches"
    if json_dir.exists():
        for file_path in sorted(json_dir.glob("*.json")):
            match_id = file_path.stem
            if match_id not in seen:
                seen.add(match_id)
                ids.append(match_id)
    return ids


def parse_rib_facts(repo_root: Path | None = None) -> dict[str, int]:
    """Join to VLR, explode landed JSON into fact jsonl. No HTTP."""
    load_project_env(repo_root)
    root = _root(repo_root)
    logger.info("=== rib_facts PARSE START matches=%s ===", len(ids))
    crosswalk = build_crosswalk(root)
    lookup = player_lookup(root)
    buckets: dict[str, dict[tuple[Any, ...], dict[str, Any]]] = {spec.stem: {} for spec in FACT_SPECS}
    unique_by_stem = {spec.stem: spec.unique_cols for spec in FACT_SPECS}
    ids = _match_ids(root)
    scanned = 0
    skipped_grain = 0
    for match_id in ids:
        scanned += 1
        if scanned % 50 == 0:
            logger.info("[rib_facts] Parse progress matches=%s/%s", scanned, len(ids))
        path = match_json_path(root, match_id)
        if not path.exists():
            logger.warning("[rib_facts] Missing match json id=%s", match_id)
            continue
        try:
            parsed = parse_landed_match(root, match_id, cross=crosswalk.get(match_id), player_ids=lookup)
        except Exception:
            logger.exception("[rib_facts] Parse failed id=%s", match_id)
            continue
        logger.info(
            "[rib_facts] Parse match %s/%s id=%s rows rounds=%s players=%s eco=%s kills=%s events=%s snapshots=%s",
            scanned,
            len(ids),
            match_id,
            len(parsed.get("rounds") or []),
            len(parsed.get("round_players") or []),
            len(parsed.get("round_economy") or []),
            len(parsed.get("kills") or []),
            len(parsed.get("replay_events") or []),
            len(parsed.get("snapshots") or []),
        )
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
    for match_id, row in crosswalk.items():
        grain = _grain_tuple(dict(row), unique_by_stem["crosswalk"])
        if grain is None:
            skipped_grain += 1
            continue
        buckets["crosswalk"][grain] = row
    facts_dir(root).mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {
        "matches_scanned": scanned,
        "skipped_incomplete_grain": skipped_grain,
        "crosswalk_joined": sum(1 for row in crosswalk.values() if row.get("vlr_match_id")),
        "crosswalk_total": len(crosswalk),
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
        logger.info("[rib_facts] Landed %s rows=%s path=%s", spec.table, len(rows), out)
    crosswalk_jsonl_path(root).write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, default=str) for row in crosswalk.values())
        + ("\n" if crosswalk else "")
    )
    logger.info("=== rib_facts PARSE DONE %s ===", counts)
    return counts


def _read_fact_jsonl(spec: FactSpec, root: Path) -> list[dict[str, Any]]:
    """Load one overlay jsonl. Empty/missing → no upsert."""
    path = fact_jsonl_path(root, spec.stem)
    if not path.exists():
        logger.warning("[rib_facts] Load skip missing jsonl table=%s", spec.table)
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
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
    batch_size: int,
    max_cpu_pct: int,
    min_sleep_sec: float,
) -> tuple[str, int]:
    """Upsert one overlay table. Independent of other overlay tables."""
    rows = _read_fact_jsonl(spec, root)
    if not rows:
        logger.info("[rib_facts] Load skip empty table=%s", spec.table)
        return spec.table, 0
    logger.info("[rib_facts] Load START table=%s rows=%s batch=%s", spec.table, len(rows), batch_size)
    count = upsert_dim_rows(
        rows,
        table=spec.table,
        columns=spec.columns,
        conflict_column=spec.unique_cols,
        jsonb_columns=spec.jsonb_columns,
        batch_size=batch_size,
        on_conflict="update",
        max_cpu_pct=max_cpu_pct,
        min_sleep_sec=min_sleep_sec,
    )
    logger.info("[rib_facts] Load DONE table=%s upserted=%s", spec.table, count)
    return spec.table, count


def _stamp_dim_matches(repo_root: Path, crosswalk: dict[str, dict[str, Any]]) -> int:
    """Write rib_match_id / has_rib_replay onto vlr.dim_matches when the join hit."""
    pairs = [
        (row.get("vlr_match_id"), row.get("rib_match_id"), bool(row.get("has_replay")))
        for row in crosswalk.values()
        if row.get("vlr_match_id") and row.get("rib_match_id")
    ]
    if not pairs:
        return 0
    logger.info("[rib_facts] Stamp dim_matches start pairs=%s", len(pairs))
    connector = SupabaseConnector()
    updated = 0
    with connector._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '10min'")
            for vlr_match_id, rib_match_id, has_replay in pairs:
                cur.execute(
                    """
                    UPDATE vlr.dim_matches
                    SET rib_match_id = %s,
                        has_rib_replay = %s,
                        update_date = now()
                    WHERE vlr_match_id = %s
                    """,
                    (int(rib_match_id) if str(rib_match_id).isdigit() else rib_match_id, has_replay, vlr_match_id),
                )
                updated += cur.rowcount
        conn.commit()
    logger.info("[rib_facts] Stamp dim_matches done updated=%s", updated)
    return updated


def load_rib_facts(repo_root: Path | None = None) -> dict[str, int]:
    """Schema first (serial), then parallel upsert with sleep between batches."""
    load_project_env(repo_root)
    apply_rib_facts_schema(repo_root)
    root = _root(repo_root)
    workers = max(1, int(os.environ.get("RIB_FACT_LOAD_WORKERS", str(DEFAULT_LOAD_WORKERS))))
    batch_size = max(50, int(os.environ.get("RIB_FACT_BATCH_SIZE", "500")))
    max_cpu_pct = max(10, int(os.environ.get("RIB_FACT_MAX_CPU_PCT", "40")))
    min_sleep_sec = float(os.environ.get("RIB_FACT_MIN_SLEEP_SEC", "4"))
    logger.info(
        "[rib_facts] Load start tables=%s workers=%s batch=%s cpu=%s sleep=%s",
        len(FACT_SPECS),
        workers,
        batch_size,
        max_cpu_pct,
        min_sleep_sec,
    )
    counts: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                _load_one_table,
                spec,
                root,
                batch_size=batch_size,
                max_cpu_pct=max_cpu_pct,
                min_sleep_sec=min_sleep_sec,
            )
            for spec in FACT_SPECS
        ]
        for fut in as_completed(futures):
            table, count = fut.result()
            counts[table] = count
    crosswalk_path = crosswalk_jsonl_path(root)
    crosswalk: dict[str, dict[str, Any]] = {}
    if crosswalk_path.exists():
        with crosswalk_path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                obj = json.loads(line)
                if isinstance(obj, dict) and obj.get("rib_match_id"):
                    crosswalk[str(obj["rib_match_id"])] = obj
    try:
        counts["dim_matches_rib_ids"] = _stamp_dim_matches(root, crosswalk)
    except Exception:
        logger.exception("[rib_facts] dim_matches stamp failed (table may not exist yet)")
        counts["dim_matches_rib_ids"] = 0
    logger.info("[rib_facts] Load done %s", counts)
    return counts


def run_rib_facts(repo_root: Path | None = None) -> dict[str, int]:
    """Extract (HTTP) → parse jsonl → load. Use RIB_MATCH_IDS for a small first run."""
    extracted = extract_rib_matches(repo_root)
    parsed = parse_rib_facts(repo_root)
    loaded = load_rib_facts(repo_root)
    return {
        **{f"extracted_{k}": v for k, v in extracted.items()},
        **{f"parsed_{k}": v for k, v in parsed.items()},
        **{f"loaded_{k}": v for k, v in loaded.items()},
    }


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="rib.gg overlay extract / parse / load")
    parser.add_argument("step", choices=["extract", "parse", "load", "run"], help="Pipeline step")
    args = parser.parse_args()
    if args.step == "extract":
        print(extract_rib_matches())
    elif args.step == "parse":
        print(parse_rib_facts())
    elif args.step == "load":
        print(load_rib_facts())
    else:
        print(run_rib_facts())
