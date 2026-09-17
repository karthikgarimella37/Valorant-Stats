-- Why: fuzzy rib series → VLR series so overlay facts can carry both ids.
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_fact_rib_match_crosswalk_row_number;

CREATE TABLE IF NOT EXISTS vlr.fact_rib_match_crosswalk (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_fact_rib_match_crosswalk_row_number'),
    rib_match_id TEXT NOT NULL,
    rib_event_id TEXT,
    vlr_match_id TEXT,
    vlr_event_id TEXT,
    match_date TEXT,
    event_name TEXT,
    team_a_name TEXT,
    team_b_name TEXT,
    join_method TEXT,
    join_score DOUBLE PRECISION,
    has_replay BOOLEAN,
    leftover_json JSONB,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_vlr_fact_rib_match_crosswalk_grain UNIQUE (rib_match_id)
);
