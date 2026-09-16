-- Why: one round of one map game (winner + attack/defense). Composite unique (vlr_match_id, map_game_number, round_number).
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_fact_round_results_row_number;

CREATE TABLE IF NOT EXISTS vlr.fact_round_results (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_fact_round_results_row_number'),

    vlr_match_id TEXT NOT NULL,
    vlr_event_id TEXT,
    match_date TEXT,
    map_name TEXT,
    map_game_number INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    winning_vlr_team_id TEXT,
    losing_vlr_team_id TEXT,
    is_attack_win BOOLEAN,
    win_method_code INTEGER,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_vlr_fact_round_results_grain UNIQUE (vlr_match_id, map_game_number, round_number)
);
