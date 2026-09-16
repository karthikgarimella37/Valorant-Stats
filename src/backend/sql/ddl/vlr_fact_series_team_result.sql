-- Why: one team on one series (maps won/lost, series winner). Composite unique (vlr_match_id, vlr_team_id).
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_fact_series_team_result_row_number;

CREATE TABLE IF NOT EXISTS vlr.fact_series_team_result (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_fact_series_team_result_row_number'),

    vlr_match_id TEXT NOT NULL,
    vlr_event_id TEXT,
    match_date TEXT,
    vlr_team_id TEXT NOT NULL,
    maps_won INTEGER,
    maps_lost INTEGER,
    is_winner BOOLEAN,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_vlr_fact_series_team_result_grain UNIQUE (vlr_match_id, vlr_team_id)
);
