"""Column lists, types, and composite unique grains for rib overlay facts in schema vlr."""

from __future__ import annotations

from typing import NamedTuple

STAMP = ("insert_date", "update_date")
STAMP_TYPES = {"insert_date": "TIMESTAMPTZ", "update_date": "TIMESTAMPTZ"}
ID_TYPES = {
    "row_number": "BIGINT",
    "rib_match_id": "TEXT",
    "rib_map_id": "TEXT",
    "rib_event_id": "TEXT",
    "rib_team_id": "TEXT",
    "rib_player_id": "TEXT",
    "vlr_match_id": "TEXT",
    "vlr_event_id": "TEXT",
    "vlr_team_id": "TEXT",
    "vlr_player_id": "TEXT",
    "match_date": "TEXT",
    **STAMP_TYPES,
}

ROUND_COLS = (
    "rib_match_id",
    "rib_map_id",
    "rib_event_id",
    "vlr_match_id",
    "vlr_event_id",
    "match_date",
    "map_name",
    "map_game_number",
    "round_number",
    "winning_rib_team_id",
    "winning_vlr_team_id",
    "losing_rib_team_id",
    "losing_vlr_team_id",
    "win_type",
    "is_attack_win",
    "mvp_agent",
    "leftover_json",
    *STAMP,
)
ROUND_UNIQUE = ("rib_match_id", "rib_map_id", "round_number")
ROUND_TYPES = {
    **ID_TYPES,
    "map_name": "TEXT",
    "map_game_number": "INTEGER",
    "round_number": "INTEGER",
    "winning_rib_team_id": "TEXT",
    "winning_vlr_team_id": "TEXT",
    "losing_rib_team_id": "TEXT",
    "losing_vlr_team_id": "TEXT",
    "win_type": "TEXT",
    "is_attack_win": "BOOLEAN",
    "mvp_agent": "TEXT",
    "leftover_json": "JSONB",
}

ROUND_PLAYER_COLS = (
    "rib_match_id",
    "rib_map_id",
    "rib_event_id",
    "rib_team_id",
    "rib_player_id",
    "rib_actor_id",
    "vlr_match_id",
    "vlr_event_id",
    "vlr_team_id",
    "vlr_player_id",
    "match_date",
    "map_name",
    "map_game_number",
    "round_number",
    "player_name",
    "agent_name",
    "side",
    "weapon_name",
    "armor_hp",
    "armor_name",
    "loadout",
    "leftover_credits",
    "acs",
    "kills",
    "deaths",
    "assists",
    "damage",
    "hs_pct",
    "is_alive",
    "is_first_kill",
    "leftover_json",
    *STAMP,
)
ROUND_PLAYER_UNIQUE = ("rib_match_id", "rib_map_id", "round_number", "rib_player_id")
ROUND_PLAYER_TYPES = {
    **ID_TYPES,
    "rib_actor_id": "TEXT",
    "map_name": "TEXT",
    "map_game_number": "INTEGER",
    "round_number": "INTEGER",
    "player_name": "TEXT",
    "agent_name": "TEXT",
    "side": "TEXT",
    "weapon_name": "TEXT",
    "armor_hp": "INTEGER",
    "armor_name": "TEXT",
    "loadout": "INTEGER",
    "leftover_credits": "INTEGER",
    "acs": "DOUBLE PRECISION",
    "kills": "INTEGER",
    "deaths": "INTEGER",
    "assists": "INTEGER",
    "damage": "INTEGER",
    "hs_pct": "DOUBLE PRECISION",
    "is_alive": "BOOLEAN",
    "is_first_kill": "BOOLEAN",
    "leftover_json": "JSONB",
}

ROUND_ECO_COLS = (
    "rib_match_id",
    "rib_map_id",
    "rib_event_id",
    "rib_team_id",
    "vlr_match_id",
    "vlr_event_id",
    "vlr_team_id",
    "match_date",
    "map_name",
    "map_game_number",
    "round_number",
    "bank",
    "loadout",
    "buy_tier",
    "leftover_json",
    *STAMP,
)
ROUND_ECO_UNIQUE = ("rib_match_id", "rib_map_id", "round_number", "rib_team_id")
ROUND_ECO_TYPES = {
    **ID_TYPES,
    "map_name": "TEXT",
    "map_game_number": "INTEGER",
    "round_number": "INTEGER",
    "bank": "INTEGER",
    "loadout": "INTEGER",
    "buy_tier": "TEXT",
    "leftover_json": "JSONB",
}

KILLS_COLS = (
    "rib_match_id",
    "rib_map_id",
    "rib_event_id",
    "vlr_match_id",
    "vlr_event_id",
    "match_date",
    "map_name",
    "map_game_number",
    "round_number",
    "event_index",
    "t_ms",
    "weapon_name",
    "killer_rib_player_id",
    "killer_rib_actor_id",
    "killer_vlr_player_id",
    "victim_rib_player_id",
    "victim_rib_actor_id",
    "victim_vlr_player_id",
    "killer_x",
    "killer_y",
    "victim_x",
    "victim_y",
    "leftover_json",
    *STAMP,
)
KILLS_UNIQUE = ("rib_match_id", "rib_map_id", "round_number", "event_index")
KILLS_TYPES = {
    **ID_TYPES,
    "map_name": "TEXT",
    "map_game_number": "INTEGER",
    "round_number": "INTEGER",
    "event_index": "INTEGER",
    "t_ms": "DOUBLE PRECISION",
    "weapon_name": "TEXT",
    "killer_rib_player_id": "TEXT",
    "killer_rib_actor_id": "TEXT",
    "killer_vlr_player_id": "TEXT",
    "victim_rib_player_id": "TEXT",
    "victim_rib_actor_id": "TEXT",
    "victim_vlr_player_id": "TEXT",
    "killer_x": "DOUBLE PRECISION",
    "killer_y": "DOUBLE PRECISION",
    "victim_x": "DOUBLE PRECISION",
    "victim_y": "DOUBLE PRECISION",
    "leftover_json": "JSONB",
}

REPLAY_EVENT_COLS = (
    "rib_match_id",
    "rib_map_id",
    "rib_event_id",
    "vlr_match_id",
    "vlr_event_id",
    "match_date",
    "map_name",
    "map_game_number",
    "round_number",
    "event_index",
    "event_type",
    "t_ms",
    "actor_rib_player_id",
    "actor_rib_actor_id",
    "actor_vlr_player_id",
    "target_rib_player_id",
    "target_rib_actor_id",
    "target_vlr_player_id",
    "weapon_name",
    "ability_name",
    "pos_x",
    "pos_y",
    "leftover_json",
    *STAMP,
)
REPLAY_EVENT_UNIQUE = ("rib_match_id", "rib_map_id", "round_number", "event_index")
REPLAY_EVENT_TYPES = {
    **ID_TYPES,
    "map_name": "TEXT",
    "map_game_number": "INTEGER",
    "round_number": "INTEGER",
    "event_index": "INTEGER",
    "event_type": "TEXT",
    "t_ms": "DOUBLE PRECISION",
    "actor_rib_player_id": "TEXT",
    "actor_rib_actor_id": "TEXT",
    "actor_vlr_player_id": "TEXT",
    "target_rib_player_id": "TEXT",
    "target_rib_actor_id": "TEXT",
    "target_vlr_player_id": "TEXT",
    "weapon_name": "TEXT",
    "ability_name": "TEXT",
    "pos_x": "DOUBLE PRECISION",
    "pos_y": "DOUBLE PRECISION",
    "leftover_json": "JSONB",
}

CROSSWALK_COLS = (
    "rib_match_id",
    "rib_event_id",
    "vlr_match_id",
    "vlr_event_id",
    "match_date",
    "event_name",
    "team_a_name",
    "team_b_name",
    "join_method",
    "join_score",
    "has_replay",
    "leftover_json",
    *STAMP,
)
CROSSWALK_UNIQUE = ("rib_match_id",)
CROSSWALK_TYPES = {
    **ID_TYPES,
    "event_name": "TEXT",
    "team_a_name": "TEXT",
    "team_b_name": "TEXT",
    "join_method": "TEXT",
    "join_score": "DOUBLE PRECISION",
    "has_replay": "BOOLEAN",
    "leftover_json": "JSONB",
}


class FactSpec(NamedTuple):
    """One overlay fact: jsonl stem, warehouse name, DDL, columns, types, unique, jsonb."""

    stem: str
    table: str
    sql_name: str
    columns: tuple[str, ...]
    types: dict[str, str]
    unique_cols: tuple[str, ...]
    jsonb_columns: tuple[str, ...] = ("leftover_json",)


FACT_SPECS: tuple[FactSpec, ...] = (
    FactSpec("rounds", "fact_rib_round", "vlr_fact_rib_round.sql", ROUND_COLS, ROUND_TYPES, ROUND_UNIQUE),
    FactSpec(
        "round_players",
        "fact_rib_round_player",
        "vlr_fact_rib_round_player.sql",
        ROUND_PLAYER_COLS,
        ROUND_PLAYER_TYPES,
        ROUND_PLAYER_UNIQUE,
    ),
    FactSpec(
        "round_economy",
        "fact_rib_round_economy",
        "vlr_fact_rib_round_economy.sql",
        ROUND_ECO_COLS,
        ROUND_ECO_TYPES,
        ROUND_ECO_UNIQUE,
    ),
    FactSpec(
        "kills",
        "fact_player_vs_player_kills",
        "vlr_fact_player_vs_player_kills.sql",
        KILLS_COLS,
        KILLS_TYPES,
        KILLS_UNIQUE,
    ),
    FactSpec(
        "replay_events",
        "fact_rib_replay_event",
        "vlr_fact_rib_replay_event.sql",
        REPLAY_EVENT_COLS,
        REPLAY_EVENT_TYPES,
        REPLAY_EVENT_UNIQUE,
    ),
    FactSpec(
        "crosswalk",
        "fact_rib_match_crosswalk",
        "vlr_fact_rib_match_crosswalk.sql",
        CROSSWALK_COLS,
        CROSSWALK_TYPES,
        CROSSWALK_UNIQUE,
    ),
)
