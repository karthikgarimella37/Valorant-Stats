-- Why: one round of one rib map (winner, win type, attacker). Grain (rib_match_id, rib_map_id, round_number).
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_fact_rib_round_row_number;

CREATE TABLE IF NOT EXISTS vlr.fact_rib_round (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_fact_rib_round_row_number'),
    rib_match_id TEXT NOT NULL,
    rib_map_id TEXT NOT NULL,
    rib_event_id TEXT,
    vlr_match_id TEXT,
    vlr_event_id TEXT,
    match_date TEXT,
    map_name TEXT,
    map_game_number INTEGER,
    round_number INTEGER NOT NULL,
    winning_rib_team_id TEXT,
    winning_vlr_team_id TEXT,
    losing_rib_team_id TEXT,
    losing_vlr_team_id TEXT,
    win_type TEXT,
    is_attack_win BOOLEAN,
    mvp_agent TEXT,
    leftover_json JSONB,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_vlr_fact_rib_round_grain UNIQUE (rib_match_id, rib_map_id, round_number)
);
