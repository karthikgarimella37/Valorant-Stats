"""
Transform rib.gg JSON payloads into snake_case parquet landings and normalized dims.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import polars as pl

from backend.api_connectors.ribs_connector import RibsConnector

logger = logging.getLogger(__name__)

_CAMEL_1 = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_2 = re.compile(r"([a-z0-9])([A-Z])")

# Nested fields stored as JSON strings rather than exploded columns.
JSON_SCALAR_KEYS = {
    "images",
    "geo_data",
    "display_data",
    "pickban",
    "pmt_json",
    "aliases",
    "previous_riot_player_ids",
    "keywords",
    "vct_regions",
    "divisions",
    "region",
    "country",
    "team1",
    "team2",
    "matches",
    "players",
    "members",
    "map",
}


def camel_to_snake(name: str) -> str:
    name = _CAMEL_1.sub(r"\1_\2", name)
    return _CAMEL_2.sub(r"\1_\2", name).lower()


def _json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, default=str)


def normalize_record(record: dict[str, Any], *, json_keys: set[str] | None = None) -> dict[str, Any]:
    """Convert keys to snake_case and serialize selected nested values to JSON strings."""
    json_keys = json_keys or JSON_SCALAR_KEYS
    out: dict[str, Any] = {}
    for key, value in record.items():
        snake = camel_to_snake(key)
        if isinstance(value, (dict, list)) or snake in json_keys:
            out[snake] = _json_dumps(value) if value is not None else None
        else:
            out[snake] = value
    return out


def records_to_dataframe(records: Iterable[dict[str, Any]]) -> pl.DataFrame:
    rows = [normalize_record(r) for r in records]
    if not rows:
        return pl.DataFrame()
    return pl.DataFrame(rows, infer_schema_length=None, strict=False)


def landing_dir_for(repo_root: Path, entity: str, run_date: date | None = None) -> Path:
    run_date = run_date or date.today()
    path = repo_root / "data" / "rib_gg" / entity / f"dt={run_date.isoformat()}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_parquet(df: pl.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path)
    logger.info("Wrote %s rows x %s cols -> %s", df.height, df.width, path)
    return path


def write_ndjson(records: list[dict[str, Any]], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, default=str))
            handle.write("\n")
    logger.info("Wrote %s NDJSON records -> %s", len(records), path)
    return path


def read_ndjson(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def players_from_teams(team_payloads: list[dict[str, Any]]) -> pl.DataFrame:
    """Extract player/member rows from team detail payloads."""
    players_by_id: dict[Any, dict[str, Any]] = {}
    for team in team_payloads:
        if not isinstance(team, dict):
            continue
        team_id = team.get("id")
        for key in ("players", "members"):
            people = team.get(key) or []
            if not isinstance(people, list):
                continue
            for person in people:
                if not isinstance(person, dict) or person.get("id") is None:
                    continue
                row = normalize_record(person)
                row.setdefault("team_id", team_id)
                players_by_id[person["id"]] = row

    if not players_by_id:
        return pl.DataFrame()
    return pl.DataFrame(list(players_by_id.values()), infer_schema_length=None, strict=False)


def explode_series_payload(
    series_records: list[dict[str, Any]],
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """
    Split nested series payloads into dim_series, dim_matches, dim_maps, dim_players.
    Players are harvested from nested team1/team2 when present (no extra API calls).
    """
    series_rows: list[dict[str, Any]] = []
    match_rows: list[dict[str, Any]] = []
    maps_by_id: dict[Any, dict[str, Any]] = {}
    team_payloads: list[dict[str, Any]] = []

    for series in series_records:
        series_copy = dict(series)
        matches = series_copy.pop("matches", None) or []
        team1 = series_copy.pop("team1", None)
        team2 = series_copy.pop("team2", None)
        for team in (team1, team2):
            if isinstance(team, dict):
                team_payloads.append(team)
        series_rows.append(normalize_record(series_copy))

        if not isinstance(matches, list):
            continue

        for match in matches:
            if not isinstance(match, dict):
                continue
            match_copy = dict(match)
            map_obj = match_copy.pop("map", None)
            if isinstance(map_obj, dict) and map_obj.get("id") is not None:
                maps_by_id[map_obj["id"]] = normalize_record(map_obj)
            normalized_match = normalize_record(match_copy)
            # Keep series_id if API omitted it.
            normalized_match.setdefault("series_id", series.get("id"))
            match_rows.append(normalized_match)

    series_df = pl.DataFrame(series_rows, infer_schema_length=None, strict=False) if series_rows else pl.DataFrame()
    matches_df = pl.DataFrame(match_rows, infer_schema_length=None, strict=False) if match_rows else pl.DataFrame()
    maps_df = (
        pl.DataFrame(list(maps_by_id.values()), infer_schema_length=None, strict=False)
        if maps_by_id
        else pl.DataFrame()
    )
    players_df = players_from_teams(team_payloads)
    return series_df, matches_df, maps_df, players_df


class RibExtractPipeline:
    """Fetch rib.gg resources and persist parquet landings."""

    def __init__(
        self,
        repo_root: Path,
        connector: RibsConnector | None = None,
        run_date: date | None = None,
    ):
        self.repo_root = Path(repo_root)
        self.connector = connector or RibsConnector()
        self.run_date = run_date or date.today()

    def _entity_path(self, entity: str, filename: str = "data.parquet") -> Path:
        return landing_dir_for(self.repo_root, entity, self.run_date) / filename

    def extract_teams(self) -> Path:
        logger.info("[extract_teams] Starting teams fetch from rib.gg...")
        teams = self.connector.get_all_teams()
        logger.info("[extract_teams] Received %s team records; converting to DataFrame...", len(teams))
        df = records_to_dataframe(teams)
        logger.info(
            "[extract_teams] DataFrame shape=%s columns=%s",
            df.shape,
            list(df.columns),
        )
        path = write_parquet(df, self._entity_path("dim_teams"))
        logger.info("[extract_teams] Done -> %s", path)
        return path

    def extract_events(self) -> Path:
        logger.info("[extract_events] Starting events fetch from rib.gg...")
        events = self.connector.get_all_events(parallel=False)
        logger.info("[extract_events] Received %s event records; converting to DataFrame...", len(events))
        df = records_to_dataframe(events)
        logger.info(
            "[extract_events] DataFrame shape=%s columns=%s",
            df.shape,
            list(df.columns),
        )
        path = write_parquet(df, self._entity_path("dim_events"))
        logger.info("[extract_events] Done -> %s", path)
        return path

    def extract_series_raw(self) -> tuple[Path, Path, list[dict[str, Any]]]:
        logger.info("[extract_series] Starting parallel series fetch (this can take several minutes)...")
        series = self.connector.get_all_series(parallel=True)
        logger.info("[extract_series] Received %s series records; writing NDJSON + parquet...", len(series))
        # NDJSON keeps original nested API shape for the normalize step.
        ndjson_path = write_ndjson(series, self._entity_path("series_raw", "data.ndjson"))
        # Parquet landing for inspection / backup (nested fields as JSON strings).
        parquet_path = write_parquet(
            records_to_dataframe(series),
            self._entity_path("series_raw", "data.parquet"),
        )
        logger.info(
            "[extract_series] Done. ndjson=%s parquet=%s",
            ndjson_path,
            parquet_path,
        )
        return parquet_path, ndjson_path, series

    def normalize_star_from_series(
        self,
        series_records: list[dict[str, Any]],
        *,
        enrich_players_via_api: bool = False,
        max_team_details: int | None = 200,
    ) -> dict[str, Path]:
        """
        Explode series into dim_series / dim_matches / dim_maps / dim_players.

        Players are primarily taken from nested team1/team2 on series rows.
        Optional API enrichment fetches /teams/{id} for additional player coverage.
        """
        logger.info(
            "[normalize] Exploding %s series records into dims (enrich_players_via_api=%s)...",
            len(series_records),
            enrich_players_via_api,
        )
        series_df, matches_df, maps_df, players_df = explode_series_payload(series_records)
        logger.info(
            "[normalize] Explode counts: series=%s matches=%s maps=%s players=%s",
            series_df.height,
            matches_df.height,
            maps_df.height,
            players_df.height,
        )
        paths = {
            "dim_series": write_parquet(series_df, self._entity_path("dim_series")),
            "dim_matches": write_parquet(matches_df, self._entity_path("dim_matches")),
            "dim_maps": write_parquet(maps_df, self._entity_path("dim_maps")),
        }

        if enrich_players_via_api:
            team_ids: list[int] = []
            for series in series_records:
                for key in ("team1Id", "team2Id"):
                    value = series.get(key)
                    if isinstance(value, int):
                        team_ids.append(value)
            unique_ids = sorted(set(team_ids))
            if max_team_details is not None:
                unique_ids = unique_ids[:max_team_details]

            logger.info(
                "[normalize] Enriching players via /teams/{id} for %s teams...",
                len(unique_ids),
            )
            team_details: list[dict[str, Any]] = []
            for i, team_id in enumerate(unique_ids, start=1):
                try:
                    team_details.append(self.connector.get_team(team_id))
                    if i % 25 == 0 or i == len(unique_ids):
                        logger.info(
                            "[normalize] Team detail progress %s/%s",
                            i,
                            len(unique_ids),
                        )
                except Exception:
                    logger.exception("Failed to fetch team %s", team_id)

            api_players = players_from_teams(team_details)
            logger.info("[normalize] API player rows=%s", api_players.height)
            if players_df.is_empty():
                players_df = api_players
            elif not api_players.is_empty():
                players_df = pl.concat([players_df, api_players], how="diagonal_relaxed").unique(
                    subset=["id"], keep="last"
                )

        paths["dim_players"] = write_parquet(players_df, self._entity_path("dim_players"))
        logger.info("[normalize] Done. Wrote: %s", {k: str(v) for k, v in paths.items()})
        return paths
