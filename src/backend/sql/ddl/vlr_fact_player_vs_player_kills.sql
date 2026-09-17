-- Why: one kill from rib replay (time, weapon, positions). Snapshots stay in JSON files.
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_fact_player_vs_player_kills_row_number;

CREATE TABLE IF NOT EXISTS vlr.fact_player_vs_player_kills (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_fact_player_vs_player_kills_row_number'),
    rib_match_id TEXT NOT NULL,
    rib_map_id TEXT NOT NULL,
    rib_event_id TEXT,
    vlr_match_id TEXT,
    vlr_event_id TEXT,
    match_date TEXT,
    map_name TEXT,
    map_game_number INTEGER,
    round_number INTEGER NOT NULL,
    event_index INTEGER NOT NULL,
    t_ms DOUBLE PRECISION,
    weapon_name TEXT,
    killer_rib_player_id TEXT,
    killer_rib_actor_id TEXT,
    killer_vlr_player_id TEXT,
    victim_rib_player_id TEXT,
    victim_rib_actor_id TEXT,
    victim_vlr_player_id TEXT,
    killer_x DOUBLE PRECISION,
    killer_y DOUBLE PRECISION,
    victim_x DOUBLE PRECISION,
    victim_y DOUBLE PRECISION,
    leftover_json JSONB,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_vlr_fact_player_vs_player_kills_grain UNIQUE (rib_match_id, rib_map_id, round_number, event_index)
);
