"""Adhoc: after the current fact_key load finishes, swap concat unique for composite grain unique.

Does not scrape. Safe to re-run. Waits until vlr.fact_* inserts stop so it does not race the live load.
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from psycopg2.extras import execute_values

from backend.config.env import load_project_env
from backend.database_connectors.supabase_connectors import SupabaseConnector
from backend.vlr.dim.load import apply_dim_schema
from backend.vlr.fact.pipeline import _ensure_grain_unique, _retire_concat_key
from backend.vlr.fact.player_ids import load_player_id_lookup
from backend.vlr.fact.tables import FACT_SPECS
from backend.vlr.fact.util import REPO_ROOT, fact_jsonl_path

logger = logging.getLogger(__name__)

PLAYER_ID_TABLES = frozenset({"fact_match_overall_stats", "fact_player_match_performance"})


def _root(repo_root: Path | None) -> Path:
    """CLI uses the same repo root as Dagster."""
    return Path(repo_root or REPO_ROOT)


def _active_fact_queries(connector: SupabaseConnector) -> int:
    """How many other sessions are currently touching vlr.fact_* (the live load)."""
    row = connector.fetch_one(
        """
        SELECT count(*)
        FROM pg_stat_activity
        WHERE pid <> pg_backend_pid()
          AND state <> 'idle'
          AND query ILIKE '%%vlr%%fact_%%'
        """
    )
    return int(row[0]) if row else 0


def _table_has_rows(connector: SupabaseConnector, table: str) -> bool:
    """Cheap existence check so wait does not COUNT(*) large facts."""
    row = connector.fetch_one(f"SELECT EXISTS (SELECT 1 FROM vlr.{table} LIMIT 1)")
    return bool(row and row[0])


def _jsonl_has_rows(root: Path, stem: str) -> bool:
    """True when this fact jsonl exists and is not empty."""
    path = fact_jsonl_path(root, stem)
    return path.exists() and path.stat().st_size > 0


def load_still_running(connector: SupabaseConnector, root: Path) -> bool:
    """True until every non-empty fact jsonl has rows in the warehouse and inserts have stopped."""
    active = _active_fact_queries(connector)
    if active:
        logger.info("[migrate] Wait live queries=%s", active)
        return True
    pending: list[str] = []
    for spec in FACT_SPECS:
        if not _jsonl_has_rows(root, spec.stem):
            continue
        if not _table_has_rows(connector, spec.table):
            pending.append(spec.table)
    if pending:
        logger.info("[migrate] Wait tables with jsonl but no rows yet=%s", pending)
        return True
    return False


def wait_for_load(connector: SupabaseConnector, root: Path, *, idle_sec: int, poll_sec: int) -> None:
    """Block until the in-flight concat load is finished, then idle a bit to avoid a jsonl-read gap."""
    logger.info("[migrate] Wait start idle_sec=%s poll_sec=%s", idle_sec, poll_sec)
    while True:
        while load_still_running(connector, root):
            time.sleep(poll_sec)
        logger.info("[migrate] Warehouse looks complete; idle %ss to confirm load exited", idle_sec)
        deadline = time.monotonic() + idle_sec
        interrupted = False
        while time.monotonic() < deadline:
            if load_still_running(connector, root):
                logger.info("[migrate] Load still moving; reset idle wait")
                interrupted = True
                break
            time.sleep(min(poll_sec, 15))
        if not interrupted:
            logger.info("[migrate] Wait done")
            return


def _backfill_player_ids(connector: SupabaseConnector, root: Path) -> None:
    """Fill vlr_player_id from IGN + team using the same landing lookup as extract."""
    lookup = load_player_id_lookup(root)
    pairs = [(team_id, ign, player_id) for (team_id, ign), player_id in lookup.by_team_ign.items()]
    logger.info("[migrate] Player-id backfill start pairs=%s", len(pairs))
    if not pairs:
        logger.warning("[migrate] Player-id map empty; overall/performance grain unique may drop rows")
        return
    with connector._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 0")
            cur.execute(
                """
                CREATE TEMP TABLE fact_player_id_map (
                    vlr_team_id TEXT NOT NULL,
                    ign_key TEXT NOT NULL,
                    vlr_player_id TEXT NOT NULL,
                    PRIMARY KEY (vlr_team_id, ign_key)
                )
                """
            )
            execute_values(
                cur,
                "INSERT INTO fact_player_id_map (vlr_team_id, ign_key, vlr_player_id) VALUES %s",
                pairs,
                page_size=1000,
            )
            for table in PLAYER_ID_TABLES:
                logger.info("[migrate] Backfill vlr_player_id table=%s", table)
                cur.execute(
                    f"""
                    UPDATE vlr.{table} AS t
                    SET vlr_player_id = m.vlr_player_id
                    FROM fact_player_id_map AS m
                    WHERE t.vlr_player_id IS NULL
                      AND t.vlr_team_id = m.vlr_team_id
                      AND lower(t.player_name) = m.ign_key
                    """
                )
                logger.info("[migrate] Backfill by team+ign table=%s rows=%s", table, cur.rowcount)
            ign_pairs = list(lookup.by_ign.items())
            if ign_pairs:
                cur.execute(
                    """
                    CREATE TEMP TABLE fact_player_ign_map (
                        ign_key TEXT PRIMARY KEY,
                        vlr_player_id TEXT NOT NULL
                    )
                    """
                )
                execute_values(
                    cur,
                    "INSERT INTO fact_player_ign_map (ign_key, vlr_player_id) VALUES %s",
                    ign_pairs,
                    page_size=1000,
                )
                for table in PLAYER_ID_TABLES:
                    cur.execute(
                        f"""
                        UPDATE vlr.{table} AS t
                        SET vlr_player_id = m.vlr_player_id
                        FROM fact_player_ign_map AS m
                        WHERE t.vlr_player_id IS NULL
                          AND lower(t.player_name) = m.ign_key
                        """
                    )
                    logger.info("[migrate] Backfill by unique ign table=%s rows=%s", table, cur.rowcount)
        conn.commit()
    logger.info("[migrate] Player-id backfill done")


def _dedupe_grain(connector: SupabaseConnector, table: str, unique_cols: tuple[str, ...]) -> int:
    """Keep the lowest row_number per composite grain so UNIQUE can be added."""
    eqs = " AND ".join(f"a.{col} IS NOT DISTINCT FROM b.{col}" for col in unique_cols)
    sql = f"""
        DELETE FROM vlr.{table} a
        USING vlr.{table} b
        WHERE a.row_number > b.row_number
          AND {eqs}
    """
    logger.info("[migrate] Dedupe start table=%s", table)
    with connector._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 0")
            cur.execute(sql)
            deleted = cur.rowcount
        conn.commit()
    logger.info("[migrate] Dedupe done table=%s deleted=%s", table, deleted)
    return deleted


def _drop_null_grain(connector: SupabaseConnector, table: str, unique_cols: tuple[str, ...]) -> int:
    """Remove rows that cannot sit in a composite unique (NULL key parts)."""
    where = " OR ".join(f"{col} IS NULL" for col in unique_cols)
    sql = f"DELETE FROM vlr.{table} WHERE {where}"
    with connector._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 0")
            cur.execute(sql)
            deleted = cur.rowcount
        conn.commit()
    logger.info("[migrate] Drop null-grain table=%s deleted=%s", table, deleted)
    return deleted


def _drop_fact_key_column(connector: SupabaseConnector, table: str) -> None:
    """Drop the concat column after uniqueness lives on the grain columns."""
    logger.info("[migrate] Drop fact_key column table=%s", table)
    connector.execute(f"ALTER TABLE vlr.{table} DROP COLUMN IF EXISTS fact_key")


def migrate_table(connector: SupabaseConnector, spec) -> None:
    """One table: drop incomplete/dup grains, drop concat unique, add composite unique, drop fact_key."""
    logger.info("[migrate] Table start %s unique=%s", spec.table, spec.unique_cols)
    _drop_null_grain(connector, spec.table, spec.unique_cols)
    _dedupe_grain(connector, spec.table, spec.unique_cols)
    _retire_concat_key(connector, spec.table)
    _ensure_grain_unique(connector, spec)
    _drop_fact_key_column(connector, spec.table)
    logger.info("[migrate] Table done %s", spec.table)


def run_migrate(repo_root: Path | None = None, *, wait: bool, idle_sec: int, poll_sec: int) -> None:
    """Wait for the concat load, then convert every fact table to composite unique keys."""
    load_project_env(repo_root)
    root = _root(repo_root)
    logger.info("[migrate] Start wait=%s", wait)
    connector = SupabaseConnector()
    if wait:
        wait_for_load(connector, root, idle_sec=idle_sec, poll_sec=poll_sec)
    elif load_still_running(connector, root):
        raise RuntimeError("Fact load is still writing. Re-run with --wait or wait until facts_load finishes.")
    for spec in FACT_SPECS:
        apply_dim_schema(root, spec.sql_name, spec.table, spec.types)
    _backfill_player_ids(connector, root)
    for spec in FACT_SPECS:
        migrate_table(connector, spec)
    logger.info("[migrate] Done tables=%s", [spec.table for spec in FACT_SPECS])


def main() -> None:
    parser = argparse.ArgumentParser(description="Swap fact_key concat unique for composite grain unique.")
    parser.add_argument("--wait", action="store_true", help="Wait until the current facts_load finishes.")
    parser.add_argument("--idle-sec", type=int, default=60, help="Extra idle seconds after tables look complete.")
    parser.add_argument("--poll-sec", type=int, default=20, help="Seconds between wait polls.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    run_migrate(wait=args.wait, idle_sec=args.idle_sec, poll_sec=args.poll_sec)


if __name__ == "__main__":
    main()
