-- Why: one player on one round (weapon/armor/loadout + ACS/K/A/damage/HS%). Grain (rib_match_id, rib_map_id, round_number, rib_player_id).
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_fact_rib_round_player_row_number;

CREATE TABLE IF NOT EXISTS vlr.fact_rib_round_player (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_fact_rib_round_player_row_number'),
    rib_match_id TEXT NOT NULL,
    rib_map_id TEXT NOT NULL,
    rib_event_id TEXT,
    rib_team_id TEXT,
    rib_player_id TEXT NOT NULL,
    rib_actor_id TEXT,
    vlr_match_id TEXT,
    vlr_event_id TEXT,
    vlr_team_id TEXT,
    vlr_player_id TEXT,
    match_date TEXT,
    map_name TEXT,
    map_game_number INTEGER,
    round_number INTEGER NOT NULL,
    player_name TEXT,
    agent_name TEXT,
    side TEXT,
    weapon_name TEXT,
    armor_hp INTEGER,
    armor_name TEXT,
    loadout INTEGER,
    leftover_credits INTEGER,
    acs DOUBLE PRECISION,
    kills INTEGER,
    deaths INTEGER,
    assists INTEGER,
    damage INTEGER,
    hs_pct DOUBLE PRECISION,
    is_alive BOOLEAN,
    is_first_kill BOOLEAN,
    leftover_json JSONB,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_vlr_fact_rib_round_player_grain UNIQUE (rib_match_id, rib_map_id, round_number, rib_player_id)
);
