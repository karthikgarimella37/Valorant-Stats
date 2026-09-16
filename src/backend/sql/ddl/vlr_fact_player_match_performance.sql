-- Why: one player on one map game (KAST/HS/FK/2K/1vX). Composite unique (vlr_match_id, map_game_number, vlr_team_id, vlr_player_id).
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_fact_player_match_performance_row_number;

CREATE TABLE IF NOT EXISTS vlr.fact_player_match_performance (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_fact_player_match_performance_row_number'),

    vlr_match_id TEXT NOT NULL,
    vlr_event_id TEXT,
    match_date TEXT,
    map_name TEXT,
    map_game_number INTEGER NOT NULL,
    player_name TEXT,
    vlr_team_id TEXT NOT NULL,
    vlr_player_id TEXT NOT NULL,
    agent_name TEXT,
    kast DOUBLE PRECISION,
    hs_pct DOUBLE PRECISION,
    first_kills INTEGER,
    first_deaths INTEGER,
    fk_diff INTEGER,
    multi_k2 INTEGER,
    multi_k3 INTEGER,
    multi_k4 INTEGER,
    multi_k5 INTEGER,
    clutch_v1 INTEGER,
    clutch_v2 INTEGER,
    clutch_v3 INTEGER,
    clutch_v4 INTEGER,
    clutch_v5 INTEGER,
    econ INTEGER,
    plants INTEGER,
    defuses INTEGER,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_vlr_fact_player_match_performance_grain UNIQUE (vlr_match_id, map_game_number, vlr_team_id, vlr_player_id)
);
