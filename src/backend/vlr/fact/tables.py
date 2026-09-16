"""Column lists, types, and composite unique grains for vlr fact tables."""

from __future__ import annotations

from typing import NamedTuple

STAMP = ("insert_date", "update_date")
STAMP_TYPES = {"insert_date": "TIMESTAMPTZ", "update_date": "TIMESTAMPTZ"}
BASE_TYPES = {
    "row_number": "BIGINT",
    "vlr_match_id": "TEXT",
    "vlr_event_id": "TEXT",
    "match_date": "TEXT",
    **STAMP_TYPES,
}

# facts_load is mid-run: performance is writing now; these still upsert on fact_key after it.
# Unfreeze all but performance after that job finishes, then drop concat keys.
FROZEN_FACT_TABLES = frozenset(
    {
        "fact_player_match_performance",
        "fact_round_results",
        "fact_map_game_results",
        "fact_series_team_result",
        "fact_match_economy",
        "fact_round_economy_detail",
        "fact_map_veto",
    }
)

OVERALL_COLS = (
    "vlr_match_id",
    "vlr_event_id",
    "match_date",
    "map_name",
    "map_game_number",
    "player_name",
    "vlr_team_id",
    "vlr_player_id",
    "agent_name",
    "kills",
    "deaths",
    "assists",
    "plus_minus",
    "acs",
    "adr",
    "rating",
    "rounds_played",
    "is_winner",
    *STAMP,
)
OVERALL_UNIQUE = ("vlr_match_id", "map_game_number", "vlr_team_id", "vlr_player_id")
OVERALL_TYPES = {
    **BASE_TYPES,
    "map_name": "TEXT",
    "map_game_number": "INTEGER",
    "player_name": "TEXT",
    "vlr_team_id": "TEXT",
    "vlr_player_id": "TEXT",
    "agent_name": "TEXT",
    "kills": "INTEGER",
    "deaths": "INTEGER",
    "assists": "INTEGER",
    "plus_minus": "INTEGER",
    "acs": "DOUBLE PRECISION",
    "adr": "DOUBLE PRECISION",
    "rating": "DOUBLE PRECISION",
    "rounds_played": "INTEGER",
    "is_winner": "BOOLEAN",
    **STAMP_TYPES,
}

PERFORMANCE_COLS = (
    "fact_key",
    "vlr_match_id",
    "vlr_event_id",
    "match_date",
    "map_name",
    "map_game_number",
    "player_name",
    "vlr_team_id",
    "agent_name",
    "kast",
    "hs_pct",
    "first_kills",
    "first_deaths",
    "fk_diff",
    "multi_k2",
    "multi_k3",
    "multi_k4",
    "multi_k5",
    "clutch_v1",
    "clutch_v2",
    "clutch_v3",
    "clutch_v4",
    "clutch_v5",
    "econ",
    "plants",
    "defuses",
    *STAMP,
)
PERFORMANCE_UNIQUE = ("fact_key",)
PERFORMANCE_TYPES = {
    **BASE_TYPES,
    "fact_key": "TEXT",
    "map_name": "TEXT",
    "map_game_number": "INTEGER",
    "player_name": "TEXT",
    "vlr_team_id": "TEXT",
    "agent_name": "TEXT",
    "kast": "DOUBLE PRECISION",
    "hs_pct": "DOUBLE PRECISION",
    "first_kills": "INTEGER",
    "first_deaths": "INTEGER",
    "fk_diff": "INTEGER",
    "multi_k2": "INTEGER",
    "multi_k3": "INTEGER",
    "multi_k4": "INTEGER",
    "multi_k5": "INTEGER",
    "clutch_v1": "INTEGER",
    "clutch_v2": "INTEGER",
    "clutch_v3": "INTEGER",
    "clutch_v4": "INTEGER",
    "clutch_v5": "INTEGER",
    "econ": "INTEGER",
    "plants": "INTEGER",
    "defuses": "INTEGER",
    **STAMP_TYPES,
}

ROUND_COLS = (
    "fact_key",
    "vlr_match_id",
    "vlr_event_id",
    "match_date",
    "map_name",
    "map_game_number",
    "round_number",
    "winning_vlr_team_id",
    "losing_vlr_team_id",
    "is_attack_win",
    "win_method_code",
    *STAMP,
)
ROUND_UNIQUE = ("vlr_match_id", "map_game_number", "round_number")
ROUND_TYPES = {
    **BASE_TYPES,
    "fact_key": "TEXT",
    "map_name": "TEXT",
    "map_game_number": "INTEGER",
    "round_number": "INTEGER",
    "winning_vlr_team_id": "TEXT",
    "losing_vlr_team_id": "TEXT",
    "is_attack_win": "BOOLEAN",
    "win_method_code": "INTEGER",
    **STAMP_TYPES,
}

MAP_GAME_COLS = (
    "fact_key",
    "vlr_match_id",
    "vlr_event_id",
    "match_date",
    "map_name",
    "map_game_number",
    "vlr_team_id",
    "rounds_won",
    "rounds_lost",
    "attack_rounds_won",
    "defense_rounds_won",
    "overtime_rounds_won",
    "duration_sec",
    "is_winner",
    "is_map_pick",
    *STAMP,
)
MAP_GAME_UNIQUE = ("vlr_match_id", "map_game_number", "vlr_team_id")
MAP_GAME_TYPES = {
    **BASE_TYPES,
    "fact_key": "TEXT",
    "map_name": "TEXT",
    "map_game_number": "INTEGER",
    "vlr_team_id": "TEXT",
    "rounds_won": "INTEGER",
    "rounds_lost": "INTEGER",
    "attack_rounds_won": "INTEGER",
    "defense_rounds_won": "INTEGER",
    "overtime_rounds_won": "INTEGER",
    "duration_sec": "INTEGER",
    "is_winner": "BOOLEAN",
    "is_map_pick": "BOOLEAN",
    **STAMP_TYPES,
}

SERIES_COLS = (
    "vlr_match_id",
    "vlr_event_id",
    "match_date",
    "vlr_team_id",
    "maps_won",
    "maps_lost",
    "is_winner",
    *STAMP,
)
SERIES_UNIQUE = ("vlr_match_id", "vlr_team_id")
SERIES_TYPES = {
    **BASE_TYPES,
    "vlr_team_id": "TEXT",
    "maps_won": "INTEGER",
    "maps_lost": "INTEGER",
    "is_winner": "BOOLEAN",
    **STAMP_TYPES,
}

ECONOMY_COLS = (
    "vlr_match_id",
    "vlr_event_id",
    "match_date",
    "vlr_team_id",
    "pistol_played",
    "pistol_won",
    "eco_played",
    "eco_won",
    "semi_eco_played",
    "semi_eco_won",
    "semi_buy_played",
    "semi_buy_won",
    "full_buy_played",
    "full_buy_won",
    *STAMP,
)
ECONOMY_UNIQUE = ("vlr_match_id", "vlr_team_id")
ECONOMY_TYPES = {
    **BASE_TYPES,
    "vlr_team_id": "TEXT",
    "pistol_played": "INTEGER",
    "pistol_won": "INTEGER",
    "eco_played": "INTEGER",
    "eco_won": "INTEGER",
    "semi_eco_played": "INTEGER",
    "semi_eco_won": "INTEGER",
    "semi_buy_played": "INTEGER",
    "semi_buy_won": "INTEGER",
    "full_buy_played": "INTEGER",
    "full_buy_won": "INTEGER",
    **STAMP_TYPES,
}

ROUND_ECO_COLS = (
    "vlr_match_id",
    "vlr_event_id",
    "match_date",
    "map_name",
    "map_game_number",
    "round_number",
    "vlr_team_id",
    "economy_code",
    "bank",
    "loadout",
    "is_pistol_round",
    "is_winner",
    "is_attack",
    *STAMP,
)
ROUND_ECO_UNIQUE = ("vlr_match_id", "map_game_number", "round_number", "vlr_team_id")
ROUND_ECO_TYPES = {
    **BASE_TYPES,
    "map_name": "TEXT",
    "map_game_number": "INTEGER",
    "round_number": "INTEGER",
    "vlr_team_id": "TEXT",
    "economy_code": "TEXT",
    "bank": "INTEGER",
    "loadout": "INTEGER",
    "is_pistol_round": "BOOLEAN",
    "is_winner": "BOOLEAN",
    "is_attack": "BOOLEAN",
    **STAMP_TYPES,
}

VETO_COLS = (
    "vlr_match_id",
    "vlr_event_id",
    "match_date",
    "map_name",
    "team_tag",
    "action_order",
    "is_ban",
    "is_pick",
    "is_decider",
    *STAMP,
)
VETO_UNIQUE = ("vlr_match_id", "action_order")
VETO_TYPES = {
    **BASE_TYPES,
    "map_name": "TEXT",
    "team_tag": "TEXT",
    "action_order": "INTEGER",
    "is_ban": "BOOLEAN",
    "is_pick": "BOOLEAN",
    "is_decider": "BOOLEAN",
    **STAMP_TYPES,
}


class FactSpec(NamedTuple):
    """One fact table: jsonl stem, warehouse name, DDL, columns, types, composite unique."""

    stem: str
    table: str
    sql_name: str
    columns: tuple[str, ...]
    types: dict[str, str]
    unique_cols: tuple[str, ...]


FACT_SPECS: tuple[FactSpec, ...] = (
    FactSpec("overall", "fact_match_overall_stats", "vlr_fact_match_overall_stats.sql", OVERALL_COLS, OVERALL_TYPES, OVERALL_UNIQUE),
    FactSpec("performance", "fact_player_match_performance", "vlr_fact_player_match_performance.sql", PERFORMANCE_COLS, PERFORMANCE_TYPES, PERFORMANCE_UNIQUE),
    FactSpec("rounds", "fact_round_results", "vlr_fact_round_results.sql", ROUND_COLS, ROUND_TYPES, ROUND_UNIQUE),
    FactSpec("map_games", "fact_map_game_results", "vlr_fact_map_game_results.sql", MAP_GAME_COLS, MAP_GAME_TYPES, MAP_GAME_UNIQUE),
    FactSpec("series", "fact_series_team_result", "vlr_fact_series_team_result.sql", SERIES_COLS, SERIES_TYPES, SERIES_UNIQUE),
    FactSpec("economy", "fact_match_economy", "vlr_fact_match_economy.sql", ECONOMY_COLS, ECONOMY_TYPES, ECONOMY_UNIQUE),
    FactSpec("round_economy", "fact_round_economy_detail", "vlr_fact_round_economy_detail.sql", ROUND_ECO_COLS, ROUND_ECO_TYPES, ROUND_ECO_UNIQUE),
    FactSpec("vetos", "fact_map_veto", "vlr_fact_map_veto.sql", VETO_COLS, VETO_TYPES, VETO_UNIQUE),
)
