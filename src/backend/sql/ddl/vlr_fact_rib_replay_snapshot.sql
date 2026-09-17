-- Why: one replay position tick (type=snapshot). Grain (rib_match_id, rib_map_id, round_number, snapshot_index).
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_fact_rib_replay_snapshot_row_number;

CREATE TABLE IF NOT EXISTS vlr.fact_rib_replay_snapshot (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_fact_rib_replay_snapshot_row_number'),
    rib_match_id TEXT NOT NULL,
    rib_map_id TEXT NOT NULL,
    rib_event_id TEXT,
    vlr_match_id TEXT,
    vlr_event_id TEXT,
    match_date TEXT,
    map_name TEXT,
    map_game_number INTEGER,
    round_number INTEGER NOT NULL,
    snapshot_index INTEGER NOT NULL,
    t_ms DOUBLE PRECISION,
    actor_rib_player_id TEXT,
    actor_rib_actor_id TEXT,
    actor_vlr_player_id TEXT,
    pos_x DOUBLE PRECISION,
    pos_y DOUBLE PRECISION,
    view_x DOUBLE PRECISION,
    view_y DOUBLE PRECISION,
    leftover_json JSONB,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_vlr_fact_rib_replay_snapshot_grain UNIQUE (rib_match_id, rib_map_id, round_number, snapshot_index)
);
