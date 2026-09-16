-- Why: one team on one map game (rounds won, attack/defense halves, pick). Composite unique (vlr_match_id, map_game_number, vlr_team_id).
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_fact_map_game_results_row_number;

CREATE TABLE IF NOT EXISTS vlr.fact_map_game_results (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_fact_map_game_results_row_number'),

    vlr_match_id TEXT NOT NULL,
    vlr_event_id TEXT,
    match_date TEXT,
    map_name TEXT,
    map_game_number INTEGER NOT NULL,
    vlr_team_id TEXT NOT NULL,
    rounds_won INTEGER,
    rounds_lost INTEGER,
    attack_rounds_won INTEGER,
    defense_rounds_won INTEGER,
    overtime_rounds_won INTEGER,
    duration_sec INTEGER,
    is_winner BOOLEAN,
    is_map_pick BOOLEAN,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_vlr_fact_map_game_results_grain UNIQUE (vlr_match_id, map_game_number, vlr_team_id)
);
