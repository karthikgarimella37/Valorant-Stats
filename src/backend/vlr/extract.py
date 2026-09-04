"""Land VLR catalog dims from self-hosted vlrggapi /v2 into data/vlr/... parquet."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from backend.api_connectors.vlr_v2_connector import RANKING_REGIONS, VlrV2Connector, vlr_api_base
from backend.vlr.regions import (
    LOCAL_REGIONS,
    LOCAL_TO_VCT,
    VCT_REGIONS,
    normalize_region_code,
    split_event_region,
)

logger = logging.getLogger(__name__)

# Back-compat alias: local ranking codes only (not VCT circuits).
REGION_SEED = LOCAL_REGIONS

_EVENT_ID_RE = re.compile(r"/event/(\d+)")
_MATCH_ID_RE = re.compile(r"vlr\.gg/(\d+)")
_WIN_METHOD_CODES = {
    "elim": 1,
    "elimination": 1,
    "kill": 1,
    "boom": 2,
    "explode": 2,
    "spike": 2,
    "defuse": 3,
    "defused": 3,
    "time": 4,
    "expired": 4,
}


def landing_dir_for(repo_root: Path, entity: str, run_date: date | None = None) -> Path:
    """Build partition path so each extract run lands under data/vlr/<entity>/dt=YYYY-MM-DD."""
    run_date = run_date or date.today()
    path = Path(repo_root) / "data" / "vlr" / entity / f"dt={run_date.isoformat()}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_parquet(df: pl.DataFrame, path: Path) -> Path:
    """Write one parquet landing so Dagster/Supabase load from a stable file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)
    logger.info("Wrote %s rows x %s cols -> %s", df.height, df.width, path)
    return path


def _event_id_from_url(url_path: str | None) -> str | None:
    """Parse vlr event id from event list url_path."""
    if not url_path:
        return None
    match = _EVENT_ID_RE.search(url_path)
    return match.group(1) if match else None


def _match_id_from_url(url: str | None) -> str | None:
    """Parse vlr match id from a match page URL when the payload omits match_id."""
    if not url:
        return None
    match = _MATCH_ID_RE.search(url)
    return match.group(1) if match else None


def _to_int(value: Any) -> int | None:
    """Parse VLR scoreboard strings like '+9' or '24' into ints for fact columns."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    text = str(value).strip().replace(",", "").replace("+", "")
    if text.endswith("%"):
        text = text[:-1]
    try:
        return int(float(text))
    except ValueError:
        return None


def _to_float(value: Any) -> float | None:
    """Parse ACS/ADR/rating/percent strings into numerics for fact columns."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip().replace(",", "").replace("+", "")
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except ValueError:
        return None


def _win_method_code(raw: Any) -> int | None:
    """Map VLR round win method text to DATA_MODEL codes (1=elim, 2=boom, 3=defuse, 4=time)."""
    if not raw:
        return None
    key = str(raw).strip().lower()
    return _WIN_METHOD_CODES.get(key)


def _other_team_id(winner_id: str | None, team_1_id: str | None, team_2_id: str | None) -> str | None:
    """Resolve the losing team so round facts can later split attack vs defense."""
    if not winner_id:
        return None
    if winner_id == team_1_id:
        return team_2_id
    if winner_id == team_2_id:
        return team_1_id
    return None


def _empty_df(schema: dict[str, pl.DataType]) -> pl.DataFrame:
    """Keep a typed empty landing so Dagster load can skip or create an empty table."""
    return pl.DataFrame(schema=schema)


class VlrExtractPipeline:
    """Fetch vlrggapi /v2 catalog and persist parquet for dim_regions, teams, events, matches."""

    def __init__(
        self,
        repo_root: Path,
        connector: VlrV2Connector | None = None,
        run_date: date | None = None,
    ):
        self.repo_root = Path(repo_root)
        self.connector = connector or VlrV2Connector()
        self.run_date = run_date or date.today()
        logger.info(
            "[vlr_extract] Pipeline ready base=%s run_date=%s",
            vlr_api_base(),
            self.run_date,
        )

    def _entity_path(self, entity: str) -> Path:
        return landing_dir_for(self.repo_root, entity, self.run_date) / "data.parquet"

    def extract_regions(self) -> Path:
        """Seed dim_regions so teams/events can FK a stable region_code."""
        logger.info("[extract_regions] Seeding %s VLR region codes...", len(REGION_SEED))
        rows = [
            {"id": code, "region_code": code, "region_name": name}
            for code, name in REGION_SEED
        ]
        path = write_parquet(pl.DataFrame(rows), self._entity_path("dim_regions"))
        logger.info("[extract_regions] Done path=%s", path)
        return path

    def extract_events(self) -> Path:
        """Page /v2/events into dim_events (needs dim_regions seed first in the job)."""
        query = os.getenv("VLR_EVENT_STATUS", "completed")
        page_start = int(os.getenv("VLR_EVENT_PAGE_START", "1"))
        page_end = int(os.getenv("VLR_EVENT_PAGE_END", "3"))
        pages = list(range(page_start, page_end + 1))
        logger.info(
            "[extract_events] Starting q=%s pages=%s-%s workers=%s base=%s",
            query,
            page_start,
            page_end,
            self.connector.max_workers,
            vlr_api_base(),
        )
        self.connector.health()

        def _page(page: int) -> tuple[int, list[dict[str, Any]]]:
            return page, self.connector.get_events_page(page, query)

        batches = self.connector.map_parallel(pages, _page, desc="events pages")
        batches.sort(key=lambda item: item[0])
        rows: list[dict[str, Any]] = []
        for page, segments in batches:
            if not segments:
                logger.info("[extract_events] Empty page=%s; later pages may still have rows", page)
                continue
            for segment in segments:
                url_path = segment.get("url_path") or segment.get("url") or ""
                event_id = segment.get("id") or _event_id_from_url(str(url_path))
                if not event_id:
                    continue
                rows.append(
                    {
                        "id": str(event_id),
                        "vlr_event_id": str(event_id),
                        "event_name": segment.get("title") or segment.get("name"),
                        "status": segment.get("status"),
                        "prize_pool_text": segment.get("prize"),
                        "dates_text": segment.get("dates"),
                        "region_code": segment.get("region"),
                        "url_path": url_path,
                    }
                )
        df = pl.DataFrame(rows) if rows else pl.DataFrame(
            schema={
                "id": pl.String,
                "vlr_event_id": pl.String,
                "event_name": pl.String,
                "status": pl.String,
                "prize_pool_text": pl.String,
                "dates_text": pl.String,
                "region_code": pl.String,
                "url_path": pl.String,
            }
        )
        if not df.is_empty():
            df = df.unique(subset=["vlr_event_id"], keep="first")
        path = write_parquet(df, self._entity_path("dim_events"))
        logger.info("[extract_events] Done rows=%s path=%s", df.height, path)
        return path

    def extract_teams(self) -> Path:
        """Pull teams from event details + rankings so dim_teams/dim_country follow dim_regions."""
        events_path = self._entity_path("dim_events")
        if not events_path.exists():
            raise RuntimeError("dim_events parquet missing; run extract_events first")
        events = pl.read_parquet(events_path)
        event_ids = [str(v) for v in events["vlr_event_id"].to_list() if v]
        max_events = os.getenv("VLR_MAX_EVENTS")
        if max_events:
            event_ids = event_ids[: int(max_events)]
        logger.info("[extract_teams] Fetching /v2/event/{{id}} for %s events...", len(event_ids))

        details = self.connector.map_parallel(
            event_ids,
            lambda event_id: (event_id, self.connector.get_event_detail(event_id)),
            desc="event details",
        )
        teams_by_id: dict[str, dict[str, Any]] = {}
        countries: set[str] = set()
        for event_id, detail in details:
            team_rows = []
            if isinstance(detail.get("teams"), list):
                team_rows = detail["teams"]
            prizes = detail.get("prizes") or []
            if isinstance(prizes, list):
                for prize in prizes:
                    team = prize.get("team") if isinstance(prize, dict) else None
                    if isinstance(team, dict) and team.get("id"):
                        team_rows.append(team)
            for team in team_rows:
                if not isinstance(team, dict) or not team.get("id"):
                    continue
                team_id = str(team["id"])
                country = team.get("region") or team.get("country")
                if country:
                    countries.add(str(country))
                teams_by_id[team_id] = {
                    "id": team_id,
                    "vlr_team_id": team_id,
                    "team_name": team.get("name"),
                    "logo_url": team.get("logo"),
                    "country_name": country,
                    "source_event_id": event_id,
                }

        logger.info("[extract_teams] Ranking scrape regions=%s (names/countries, ids often missing)", len(RANKING_REGIONS))
        ranking_batches = self.connector.map_parallel(
            list(RANKING_REGIONS),
            lambda region: (region, self.connector.get_rankings(region)),
            desc="rankings",
        )
        ranking_rows: list[dict[str, Any]] = []
        for region, segments in ranking_batches:
            for segment in segments:
                country = segment.get("country")
                if country:
                    countries.add(str(country))
                ranking_rows.append(
                    {
                        "team_name": segment.get("team"),
                        "country_name": country,
                        "region_code": region,
                        "rank": segment.get("rank"),
                        "logo_url": segment.get("logo"),
                    }
                )
        ranking_path = write_parquet(
            pl.DataFrame(ranking_rows) if ranking_rows else pl.DataFrame(),
            landing_dir_for(self.repo_root, "rankings_raw", self.run_date) / "data.parquet",
        )
        logger.info("[extract_teams] Rankings raw path=%s rows=%s", ranking_path, len(ranking_rows))

        team_rows = list(teams_by_id.values())
        teams_df = pl.DataFrame(team_rows) if team_rows else pl.DataFrame(
            schema={
                "id": pl.String,
                "vlr_team_id": pl.String,
                "team_name": pl.String,
                "logo_url": pl.String,
                "country_name": pl.String,
                "source_event_id": pl.String,
            }
        )
        teams_path = write_parquet(teams_df, self._entity_path("dim_teams"))

        country_rows = [{"id": name, "country_name": name} for name in sorted(countries)]
        write_parquet(
            pl.DataFrame(country_rows) if country_rows else pl.DataFrame(
                schema={"id": pl.String, "country_name": pl.String}
            ),
            self._entity_path("dim_country"),
        )
        logger.info("[extract_teams] Done teams=%s countries=%s", teams_df.height, len(countries))
        return teams_path

    def extract_event_matches(self) -> Path:
        """Queue series ids from /v2/events/matches for the match-detail step."""
        events_path = self._entity_path("dim_events")
        if not events_path.exists():
            raise RuntimeError("dim_events parquet missing; run extract_events first")
        event_ids = [str(v) for v in pl.read_parquet(events_path)["vlr_event_id"].to_list() if v]
        max_events = os.getenv("VLR_MAX_EVENTS")
        if max_events:
            event_ids = event_ids[: int(max_events)]
        logger.info("[extract_event_matches] Starting events=%s", len(event_ids))

        def _one(event_id: str) -> list[dict[str, Any]]:
            matches = self.connector.get_event_matches(event_id)
            rows: list[dict[str, Any]] = []
            for match in matches:
                match_id = match.get("match_id") or _match_id_from_url(str(match.get("url") or ""))
                if not match_id:
                    continue
                rows.append(
                    {
                        "id": str(match_id),
                        "match_id": str(match_id),
                        "vlr_event_id": event_id,
                        "event_series": match.get("event_series"),
                        "match_date": match.get("date"),
                        "teams_json": json.dumps(match.get("teams"), default=str),
                    }
                )
            return rows

        nested = self.connector.map_parallel(event_ids, _one, desc="event matches")
        rows = [row for batch in nested for row in batch]
        df = pl.DataFrame(rows) if rows else pl.DataFrame(
            schema={
                "id": pl.String,
                "match_id": pl.String,
                "vlr_event_id": pl.String,
                "event_series": pl.String,
                "match_date": pl.String,
                "teams_json": pl.String,
            }
        )
        if not df.is_empty():
            df = df.unique(subset=["match_id"], keep="first")
        path = write_parquet(df, self._entity_path("match_queue"))
        logger.info("[extract_event_matches] Done rows=%s path=%s", df.height, path)
        return path

    def extract_match_details(self) -> dict[str, Path]:
        """Fetch /v2/match/details once and land dims plus VLR facts for the warehouse."""
        queue_path = self._entity_path("match_queue")
        if not queue_path.exists():
            raise RuntimeError("match_queue parquet missing; run extract_event_matches first")
        queue_df = pl.read_parquet(queue_path)
        event_by_match = {
            str(match_id): str(event_id) if event_id is not None else None
            for match_id, event_id in zip(
                queue_df["match_id"].to_list(),
                queue_df["vlr_event_id"].to_list(),
            )
        }
        match_ids = [str(v) for v in queue_df["match_id"].to_list() if v]
        max_matches = os.getenv("VLR_MAX_MATCHES")
        if max_matches:
            match_ids = match_ids[: int(max_matches)]
        logger.info("[extract_match_details] Starting matches=%s", len(match_ids))

        payloads = self.connector.map_parallel(
            match_ids,
            lambda match_id: (match_id, self.connector.get_match_details(match_id)),
            desc="match details",
        )
        match_rows: list[dict[str, Any]] = []
        maps_by_name: dict[str, dict[str, Any]] = {}
        agents_by_name: dict[str, dict[str, Any]] = {}
        players_by_key: dict[str, dict[str, Any]] = {}
        overall_rows: list[dict[str, Any]] = []
        round_rows: list[dict[str, Any]] = []
        performance_rows: list[dict[str, Any]] = []
        economy_rows: list[dict[str, Any]] = []
        series_advanced: dict[str, dict[str, Any]] = {}

        for match_id, detail in payloads:
            teams = detail.get("teams") or []
            team_1 = teams[0] if isinstance(teams, list) and teams else {}
            team_2 = teams[1] if isinstance(teams, list) and len(teams) > 1 else {}
            team_1_id = str(team_1.get("id")) if team_1.get("id") else None
            team_2_id = str(team_2.get("id")) if team_2.get("id") else None
            event = detail.get("event") or {}
            event_id = event_by_match.get(str(match_id))
            match_rows.append(
                {
                    "id": str(match_id),
                    "match_id": str(match_id),
                    "vlr_event_id": event_id,
                    "event_name": event.get("name") if isinstance(event, dict) else None,
                    "event_series": event.get("series") if isinstance(event, dict) else None,
                    "status": detail.get("status"),
                    "match_date": detail.get("date"),
                    "team_1_id": team_1_id,
                    "team_1_name": team_1.get("name"),
                    "team_1_score": team_1.get("score"),
                    "team_2_id": team_2_id,
                    "team_2_name": team_2.get("name"),
                    "team_2_score": team_2.get("score"),
                    "map_vetos": detail.get("map_vetos"),
                    "n_maps": len(detail.get("maps") or []) if isinstance(detail.get("maps"), list) else None,
                }
            )

            performance = detail.get("performance") or {}
            if isinstance(performance, dict):
                for adv in performance.get("advanced_stats") or []:
                    if not isinstance(adv, dict) or not adv.get("player"):
                        continue
                    series_advanced[f"{match_id}|{adv['player']}"] = adv

            for eco in detail.get("economy") or []:
                if not isinstance(eco, dict):
                    continue
                team_name = eco.get("Team") or eco.get("team")
                if not team_name:
                    continue
                team_id = team_1_id if team_name == team_1.get("name") else team_2_id if team_name == team_2.get("name") else None
                economy_rows.append(
                    {
                        "id": f"{match_id}|{team_name}",
                        "match_id": str(match_id),
                        "event_id": event_id,
                        "team_id": team_id,
                        "team_name": team_name,
                        "pistol_win_pct": _to_float(eco.get("Pistol") or eco.get("pistol")),
                        "eco_win_pct": _to_float(eco.get("Eco") or eco.get("eco")),
                        "full_buy_win_pct": _to_float(eco.get("Full") or eco.get("full")),
                        "total_spent": None,
                        "equipment_value": None,
                        "money_saved": None,
                    }
                )

            maps = [row for row in (detail.get("maps") or []) if isinstance(row, dict)]
            for map_game_number, map_row in enumerate(maps, start=1):
                map_name = map_row.get("map_name") or map_row.get("name")
                if not map_name:
                    continue
                map_name = str(map_name)
                maps_by_name[map_name] = {"id": map_name, "name": map_name}
                score = map_row.get("score") or {}
                team1_total = _to_int((score.get("team1") or {}).get("total")) if isinstance(score, dict) else None
                team2_total = _to_int((score.get("team2") or {}).get("total")) if isinstance(score, dict) else None
                team1_won_map = (
                    team1_total is not None
                    and team2_total is not None
                    and team1_total > team2_total
                )

                players = map_row.get("players") or {}
                for side in ("team1", "team2"):
                    team_id = team_1_id if side == "team1" else team_2_id
                    is_winner = team1_won_map if side == "team1" else (
                        team1_total is not None
                        and team2_total is not None
                        and team2_total > team1_total
                    )
                    for player in players.get(side) or []:
                        if not isinstance(player, dict):
                            continue
                        ign = player.get("name")
                        if not ign:
                            continue
                        ign = str(ign)
                        agent = player.get("agent")
                        if agent:
                            agents_by_name[str(agent)] = {"id": str(agent), "name": str(agent)}
                        players_by_key[ign] = {
                            "id": ign,
                            "ign": ign,
                            "agent_name": agent,
                        }
                        row_id = f"{match_id}|{map_game_number}|{ign}"
                        overall_rows.append(
                            {
                                "id": row_id,
                                "match_id": str(match_id),
                                "event_id": event_id,
                                "map_id": map_name,
                                "map_game_number": map_game_number,
                                "player_id": ign,
                                "team_id": team_id,
                                "agent_id": str(agent) if agent else None,
                                "kills": _to_int(player.get("kills")),
                                "deaths": _to_int(player.get("deaths")),
                                "assists": _to_int(player.get("assists")),
                                "plus_minus": _to_int(player.get("kd_diff") or player.get("plus_minus")),
                                "acs": _to_float(player.get("acs")),
                                "adr": _to_float(player.get("adr")),
                                "rating": _to_float(player.get("rating")),
                                "rounds_played": (
                                    (team1_total or 0) + (team2_total or 0)
                                    if team1_total is not None and team2_total is not None
                                    else None
                                ),
                                "is_winner": is_winner,
                            }
                        )
                        adv = series_advanced.get(f"{match_id}|{ign}") or {}
                        # Series-level 2K/clutch counts from VLR sit on map 1 only so they are not summed per map.
                        use_series_adv = map_game_number == 1
                        performance_rows.append(
                            {
                                "id": row_id,
                                "match_id": str(match_id),
                                "event_id": event_id,
                                "map_id": map_name,
                                "map_game_number": map_game_number,
                                "player_id": ign,
                                "team_id": team_id,
                                "agent_id": str(agent) if agent else None,
                                "kast": _to_float(player.get("kast")),
                                "hs_pct": _to_float(player.get("hs_pct")),
                                "first_kills": _to_int(player.get("fk")),
                                "first_deaths": _to_int(player.get("fd")),
                                "multi_k2": _to_int(adv.get("2K")) if use_series_adv else None,
                                "multi_k3": _to_int(adv.get("3K")) if use_series_adv else None,
                                "multi_k4": _to_int(adv.get("4K")) if use_series_adv else None,
                                "multi_k5": _to_int(adv.get("5K")) if use_series_adv else None,
                                "clutch_v1": _to_int(adv.get("1v1") or adv.get("1V1")) if use_series_adv else None,
                                "clutch_v2": _to_int(adv.get("1v2") or adv.get("1V2")) if use_series_adv else None,
                                "clutch_v3": _to_int(adv.get("1v3") or adv.get("1V3")) if use_series_adv else None,
                                "clutch_v4": _to_int(adv.get("1v4") or adv.get("1V4")) if use_series_adv else None,
                                "clutch_v5": _to_int(adv.get("1v5") or adv.get("1V5")) if use_series_adv else None,
                            }
                        )

                for round_row in map_row.get("rounds") or []:
                    if not isinstance(round_row, dict):
                        continue
                    round_number = _to_int(round_row.get("round_num") or round_row.get("number"))
                    if round_number is None:
                        continue
                    winner_side = str(round_row.get("winner") or "").lower()
                    winning_team_id = team_1_id if winner_side in {"team1", "1"} else team_2_id if winner_side in {"team2", "2"} else None
                    side = str(round_row.get("side") or "").lower()
                    round_rows.append(
                        {
                            "id": f"{match_id}|{map_game_number}|{round_number}",
                            "match_id": str(match_id),
                            "event_id": event_id,
                            "map_id": map_name,
                            "map_game_number": map_game_number,
                            "round_number": round_number,
                            "winning_team_id": winning_team_id,
                            "losing_team_id": _other_team_id(winning_team_id, team_1_id, team_2_id),
                            "is_attack_win": side in {"t", "attack", "atk"},
                            "win_method_code": _win_method_code(round_row.get("method")),
                        }
                    )

        overall_schema = {
            "id": pl.String,
            "match_id": pl.String,
            "event_id": pl.String,
            "map_id": pl.String,
            "map_game_number": pl.Int64,
            "player_id": pl.String,
            "team_id": pl.String,
            "agent_id": pl.String,
            "kills": pl.Int64,
            "deaths": pl.Int64,
            "assists": pl.Int64,
            "plus_minus": pl.Int64,
            "acs": pl.Float64,
            "adr": pl.Float64,
            "rating": pl.Float64,
            "rounds_played": pl.Int64,
            "is_winner": pl.Boolean,
        }
        round_schema = {
            "id": pl.String,
            "match_id": pl.String,
            "event_id": pl.String,
            "map_id": pl.String,
            "map_game_number": pl.Int64,
            "round_number": pl.Int64,
            "winning_team_id": pl.String,
            "losing_team_id": pl.String,
            "is_attack_win": pl.Boolean,
            "win_method_code": pl.Int64,
        }
        performance_schema = {
            "id": pl.String,
            "match_id": pl.String,
            "event_id": pl.String,
            "map_id": pl.String,
            "map_game_number": pl.Int64,
            "player_id": pl.String,
            "team_id": pl.String,
            "agent_id": pl.String,
            "kast": pl.Float64,
            "hs_pct": pl.Float64,
            "first_kills": pl.Int64,
            "first_deaths": pl.Int64,
            "multi_k2": pl.Int64,
            "multi_k3": pl.Int64,
            "multi_k4": pl.Int64,
            "multi_k5": pl.Int64,
            "clutch_v1": pl.Int64,
            "clutch_v2": pl.Int64,
            "clutch_v3": pl.Int64,
            "clutch_v4": pl.Int64,
            "clutch_v5": pl.Int64,
        }
        economy_schema = {
            "id": pl.String,
            "match_id": pl.String,
            "event_id": pl.String,
            "team_id": pl.String,
            "team_name": pl.String,
            "pistol_win_pct": pl.Float64,
            "eco_win_pct": pl.Float64,
            "full_buy_win_pct": pl.Float64,
            "total_spent": pl.Int64,
            "equipment_value": pl.Int64,
            "money_saved": pl.Int64,
        }

        paths = {
            "dim_matches": write_parquet(
                pl.DataFrame(match_rows) if match_rows else pl.DataFrame(),
                self._entity_path("dim_matches"),
            ),
            "dim_maps": write_parquet(
                pl.DataFrame(list(maps_by_name.values())) if maps_by_name else pl.DataFrame(),
                self._entity_path("dim_maps"),
            ),
            "dim_agents": write_parquet(
                pl.DataFrame(list(agents_by_name.values())) if agents_by_name else pl.DataFrame(),
                self._entity_path("dim_agents"),
            ),
            "dim_players": write_parquet(
                pl.DataFrame(list(players_by_key.values())) if players_by_key else pl.DataFrame(),
                self._entity_path("dim_players"),
            ),
            "fact_match_overall_stats": write_parquet(
                pl.DataFrame(overall_rows) if overall_rows else _empty_df(overall_schema),
                self._entity_path("fact_match_overall_stats"),
            ),
            "fact_round_results": write_parquet(
                pl.DataFrame(round_rows) if round_rows else _empty_df(round_schema),
                self._entity_path("fact_round_results"),
            ),
            "fact_player_match_performance": write_parquet(
                pl.DataFrame(performance_rows) if performance_rows else _empty_df(performance_schema),
                self._entity_path("fact_player_match_performance"),
            ),
            "fact_match_economy": write_parquet(
                pl.DataFrame(economy_rows) if economy_rows else _empty_df(economy_schema),
                self._entity_path("fact_match_economy"),
            ),
        }
        logger.info(
            "[extract_match_details] Done maps=%s overall=%s rounds=%s performance=%s economy=%s",
            len(maps_by_name),
            len(overall_rows),
            len(round_rows),
            len(performance_rows),
            len(economy_rows),
        )
        logger.info("[extract_match_details] Paths=%s", {k: str(v) for k, v in paths.items()})
        return paths

    def entity_paths_for_load(self) -> dict[str, Path]:
        """Map warehouse table names to parquet landings for Supabase load."""
        names = (
            "dim_regions",
            "dim_country",
            "dim_teams",
            "dim_events",
            "dim_matches",
            "dim_players",
            "dim_agents",
            "dim_maps",
            "fact_match_overall_stats",
            "fact_round_results",
            "fact_player_match_performance",
            "fact_match_economy",
        )
        return {name: self._entity_path(name) for name in names}
