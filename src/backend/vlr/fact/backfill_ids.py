"""Fill missing fact vlr_team_id / vlr_player_id from dims and landings. CPU-capped batches."""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from psycopg2.extras import execute_values

from backend.config.env import load_project_env
from backend.database_connectors.supabase_connectors import SupabaseConnector
from backend.vlr.dim.util import matches_jsonl_path
from backend.vlr.fact.parse import parse_match_facts
from backend.vlr.fact.player_ids import load_player_id_lookup
from backend.vlr.fact.util import REPO_ROOT, UNKNOWN_ID

logger = logging.getLogger(__name__)

PLAYER_TABLES = ("fact_match_overall_stats", "fact_player_match_performance")
TEAM_TABLES = (
    "fact_match_economy",
    "fact_series_team_result",
    "fact_map_game_results",
    "fact_match_overall_stats",
    "fact_player_match_performance",
    "fact_round_economy_detail",
)


def _root(repo_root: Path | None) -> Path:
    """CLI uses the same repo root as Dagster."""
    return Path(repo_root or REPO_ROOT)


def _pause(batch_sec: float, *, max_cpu_pct: int, min_sleep_sec: float) -> float:
    """Sleep so this process's average duty cycle stays at max_cpu_pct."""
    duty = max(10, min(90, max_cpu_pct)) / 100.0
    pause = batch_sec * (1.0 - duty) / duty
    pause = max(pause, min_sleep_sec)
    if pause > 0:
        time.sleep(pause)
    return pause


def _missing_id_sql(col: str) -> str:
    """Null, blank, or the -1 anomaly marker."""
    return f"({col} IS NULL OR BTRIM({col}) = '' OR {col} = '{UNKNOWN_ID}')"


def _fill_other_team(connector: SupabaseConnector, table: str, *, by_map: bool = False) -> int:
    """When a match already has one real team id, the -1 row is the other dim_matches team."""
    sql = f"""
        UPDATE vlr.{table} AS t
        SET vlr_team_id = CASE
            WHEN known.vlr_team_id = m.vlr_team_1_id THEN m.vlr_team_2_id
            WHEN known.vlr_team_id = m.vlr_team_2_id THEN m.vlr_team_1_id
            ELSE t.vlr_team_id
        END
        FROM vlr.dim_matches AS m, vlr.{table} AS known
        WHERE t.vlr_match_id = m.vlr_match_id
          AND known.vlr_match_id = t.vlr_match_id
          {map_join.replace("AND known.map_game_number = t.map_game_number", "AND known.map_game_number = t.map_game_number") if by_map else ""}
          AND NOT {_missing_id_sql("known.vlr_team_id")}
          AND {_missing_id_sql("t.vlr_team_id")}
          AND m.vlr_team_1_id IS NOT NULL
          AND m.vlr_team_2_id IS NOT NULL
          AND known.vlr_team_id IN (m.vlr_team_1_id, m.vlr_team_2_id)
          AND NOT EXISTS (
            SELECT 1 FROM vlr.{table} AS x
            WHERE x.vlr_match_id = t.vlr_match_id
              {map_exist}
              AND x.vlr_team_id = CASE
                    WHEN known.vlr_team_id = m.vlr_team_1_id THEN m.vlr_team_2_id
                    ELSE m.vlr_team_1_id
                  END
          )
    """
    with connector._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '10min'")
            cur.execute(sql)
            n = cur.rowcount
        conn.commit()
    logger.info("[backfill] Other-team table=%s updated=%s", table, n)
    return n


def backfill_team_ids(connector: SupabaseConnector) -> dict[str, int]:
    """Fill -1 team ids when the other side of the match is already known."""
    counts: dict[str, int] = {}
    counts["fact_match_economy"] = _fill_other_team(connector, "fact_match_economy")
    counts["fact_series_team_result"] = _fill_other_team(connector, "fact_series_team_result")
    counts["fact_map_game_results"] = _fill_other_team(connector, "fact_map_game_results", by_map=True)
    counts["fact_round_economy_detail"] = _fill_other_team(
        connector, "fact_round_economy_detail", by_map=True
    )
    return counts


def backfill_economy_from_matches(
    connector: SupabaseConnector,
    root: Path,
    *,
    max_cpu_pct: int,
    min_sleep_sec: float,
    batch_size: int,
) -> int:
    """Re-resolve economy tags from matches.jsonl and replace leftover -1 team ids."""
    path = matches_jsonl_path(root)
    logger.info("[backfill] Economy jsonl start path=%s", path)
    rows: list[tuple[str, str]] = []
    scanned = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            scanned += 1
            if scanned % 2000 == 0:
                time.sleep(min_sleep_sec)
                logger.info("[backfill] Economy jsonl progress lines=%s pairs=%s", scanned, len(rows))
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            parsed = parse_match_facts(obj)
            for eco in parsed.get("economy") or []:
                team_id = eco.get("vlr_team_id")
                match_id = eco.get("vlr_match_id")
                if match_id and team_id and team_id != UNKNOWN_ID:
                    rows.append((str(match_id), str(team_id)))
    logger.info("[backfill] Economy jsonl done lines=%s pairs=%s", scanned, len(rows))
    if not rows:
        return 0
    unique: dict[tuple[str, str], tuple[str, str]] = {(m, t): (m, t) for m, t in rows}
    pairs = list(unique.values())
    total = 0
    with connector._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 0")
            cur.execute(
                """
                CREATE TEMP TABLE fact_economy_team_map (
                    vlr_match_id TEXT NOT NULL,
                    vlr_team_id TEXT NOT NULL,
                    PRIMARY KEY (vlr_match_id, vlr_team_id)
                )
                """
            )
            execute_values(
                cur,
                "INSERT INTO fact_economy_team_map (vlr_match_id, vlr_team_id) VALUES %s",
                pairs,
                page_size=1000,
            )
            conn.commit()
            lo = 0
            while lo < len(pairs):
                chunk = pairs[lo : lo + batch_size]
                match_ids = tuple({m for m, _ in chunk})
                started = time.monotonic()
                cur.execute(
                    f"""
                    UPDATE vlr.fact_match_economy AS t
                    SET vlr_team_id = m.vlr_team_id
                    FROM fact_economy_team_map AS m
                    WHERE t.vlr_match_id = m.vlr_match_id
                      AND t.vlr_match_id IN %s
                      AND {_missing_id_sql("t.vlr_team_id")}
                      AND NOT EXISTS (
                        SELECT 1 FROM vlr.fact_match_economy AS x
                        WHERE x.vlr_match_id = t.vlr_match_id
                          AND x.vlr_team_id = m.vlr_team_id
                      )
                    """,
                    (match_ids,),
                )
                conn.commit()
                n = cur.rowcount
                total += max(n, 0)
                batch_sec = time.monotonic() - started
                pause = _pause(batch_sec, max_cpu_pct=max_cpu_pct, min_sleep_sec=min_sleep_sec)
                lo += batch_size
                logger.info(
                    "[backfill] Economy team upserted=%s batch_sec=%.2f sleep=%.2f",
                    total,
                    batch_sec,
                    pause,
                )
    logger.info("[backfill] Economy from jsonl updated=%s", total)
    return total


def backfill_player_ids(
    connector: SupabaseConnector,
    root: Path,
    *,
    max_cpu_pct: int,
    min_sleep_sec: float,
    batch_size: int,
) -> dict[str, int]:
    """Fill vlr_player_id from IGN + team, then unique-ign, in row_number windows."""
    lookup = load_player_id_lookup(root)
    pairs = [(team_id, ign, player_id) for (team_id, ign), player_id in lookup.by_team_ign.items()]
    ign_pairs = list(lookup.by_ign.items())
    logger.info("[backfill] Player map team_ign=%s unique_ign=%s", len(pairs), len(ign_pairs))
    counts: dict[str, int] = {}
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
            conn.commit()
            for table in PLAYER_TABLES:
                cur.execute(f"SELECT COALESCE(MIN(row_number), 0), COALESCE(MAX(row_number), 0) FROM vlr.{table}")
                lo, hi = cur.fetchone()
                updated = 0
                start = lo
                logger.info("[backfill] Player table=%s row_number=%s..%s", table, lo, hi)
                while start <= hi:
                    stop = start + batch_size
                    started = time.monotonic()
                    cur.execute(
                        f"""
                        UPDATE vlr.{table} AS t
                        SET vlr_player_id = m.vlr_player_id
                        FROM fact_player_id_map AS m
                        WHERE t.row_number >= %s AND t.row_number < %s
                          AND {_missing_id_sql("t.vlr_player_id")}
                          AND t.vlr_team_id = m.vlr_team_id
                          AND lower(t.player_name) = m.ign_key
                          AND NOT EXISTS (
                            SELECT 1 FROM vlr.{table} AS x
                            WHERE x.vlr_match_id = t.vlr_match_id
                              AND x.map_game_number = t.map_game_number
                              AND x.vlr_team_id = t.vlr_team_id
                              AND x.vlr_player_id = m.vlr_player_id
                          )
                        """,
                        (start, stop),
                    )
                    updated += max(cur.rowcount, 0)
                    if ign_pairs:
                        cur.execute(
                            f"""
                            UPDATE vlr.{table} AS t
                            SET vlr_player_id = m.vlr_player_id
                            FROM fact_player_ign_map AS m
                            WHERE t.row_number >= %s AND t.row_number < %s
                              AND {_missing_id_sql("t.vlr_player_id")}
                              AND lower(t.player_name) = m.ign_key
                              AND NOT EXISTS (
                                SELECT 1 FROM vlr.{table} AS x
                                WHERE x.vlr_match_id = t.vlr_match_id
                                  AND x.map_game_number = t.map_game_number
                                  AND x.vlr_team_id = t.vlr_team_id
                                  AND x.vlr_player_id = m.vlr_player_id
                              )
                            """,
                            (start, stop),
                        )
                        updated += max(cur.rowcount, 0)
                    conn.commit()
                    batch_sec = time.monotonic() - started
                    pause = _pause(batch_sec, max_cpu_pct=max_cpu_pct, min_sleep_sec=min_sleep_sec)
                    logger.info(
                        "[backfill] Player table=%s through=%s/%s updated=%s batch_sec=%.2f sleep=%.2f",
                        table,
                        min(stop - 1, hi),
                        hi,
                        updated,
                        batch_sec,
                        pause,
                    )
                    start = stop
                counts[table] = updated
    logger.info("[backfill] Player done %s", counts)
    return counts


def _unresolved_counts(connector: SupabaseConnector) -> dict[str, Any]:
    """How many grain ids are still missing after the backfill."""
    out: dict[str, Any] = {}
    for table in TEAM_TABLES:
        row = connector.fetch_one(
            f"SELECT count(*) FROM vlr.{table} WHERE {_missing_id_sql('vlr_team_id')}"
        )
        out[f"{table}.team_missing"] = int(row[0]) if row else None
    for table in PLAYER_TABLES:
        row = connector.fetch_one(
            f"SELECT count(*) FROM vlr.{table} WHERE {_missing_id_sql('vlr_player_id')}"
        )
        out[f"{table}.player_missing"] = int(row[0]) if row else None
        sample = connector.fetch_all(
            f"""
            SELECT player_name, vlr_team_id, count(*) AS n
            FROM vlr.{table}
            WHERE {_missing_id_sql("vlr_player_id")}
            GROUP BY 1, 2
            ORDER BY n DESC
            LIMIT 8
            """
        )
        out[f"{table}.player_missing_sample"] = sample
    return out


def run_backfill(
    repo_root: Path | None = None,
    *,
    max_cpu_pct: int = 70,
    min_sleep_sec: float = 1.0,
    batch_size: int = 4000,
) -> dict[str, Any]:
    """Team ids from dim_matches + matches.jsonl, then player ids from landings."""
    load_project_env(repo_root)
    try:
        os.nice(10)
    except OSError:
        pass
    root = _root(repo_root)
    logger.info("[backfill] Start max_cpu_pct=%s batch=%s", max_cpu_pct, batch_size)
    connector = SupabaseConnector()
    team_counts = backfill_team_ids(connector)
    eco = backfill_economy_from_matches(
        connector,
        root,
        max_cpu_pct=max_cpu_pct,
        min_sleep_sec=min_sleep_sec,
        batch_size=batch_size,
    )
    player_counts = backfill_player_ids(
        connector,
        root,
        max_cpu_pct=max_cpu_pct,
        min_sleep_sec=min_sleep_sec,
        batch_size=batch_size,
    )
    leftover = _unresolved_counts(connector)
    result = {"team": team_counts, "economy_jsonl": eco, "player": player_counts, "leftover": leftover}
    logger.info("[backfill] Done %s", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill fact team/player ids with CPU cap.")
    parser.add_argument("--max-cpu-pct", type=int, default=70)
    parser.add_argument("--min-sleep-sec", type=float, default=1.0)
    parser.add_argument("--batch-size", type=int, default=4000)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    run_backfill(
        max_cpu_pct=args.max_cpu_pct,
        min_sleep_sec=args.min_sleep_sec,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
