-- Why: one player on one map game (box score). Composite unique (vlr_match_id, map_game_number, vlr_team_id, vlr_player_id).
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_fact_match_overall_stats_row_number;

CREATE TABLE IF NOT EXISTS vlr.fact_match_overall_stats (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_fact_match_overall_stats_row_number'),

    vlr_match_id TEXT NOT NULL,
    vlr_event_id TEXT,
    match_date TEXT,
    map_name TEXT,
    map_game_number INTEGER NOT NULL,
    player_name TEXT,
    vlr_team_id TEXT NOT NULL,
    vlr_player_id TEXT NOT NULL,
    agent_name TEXT,
    kills INTEGER,
    deaths INTEGER,
    assists INTEGER,
    plus_minus INTEGER,
    acs DOUBLE PRECISION,
    adr DOUBLE PRECISION,
    rating DOUBLE PRECISION,
    rounds_played INTEGER,
    is_winner BOOLEAN,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_vlr_fact_match_overall_stats_grain UNIQUE (vlr_match_id, map_game_number, vlr_team_id, vlr_player_id)
);
