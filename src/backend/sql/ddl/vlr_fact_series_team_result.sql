-- Why: one team on one series (maps won/lost, series winner). Grain keys TEXT; metrics/binary only besides keys.
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_fact_series_team_result_row_number;

CREATE TABLE IF NOT EXISTS vlr.fact_series_team_result (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_fact_series_team_result_row_number'),

    fact_key TEXT NOT NULL UNIQUE,
    vlr_match_id TEXT NOT NULL,
    vlr_event_id TEXT,
    match_date TEXT,
    vlr_team_id TEXT,
    maps_won INTEGER,
    maps_lost INTEGER,
    is_winner BOOLEAN,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now()
);
