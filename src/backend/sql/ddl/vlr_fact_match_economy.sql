-- Why: one team on one series (pistol/eco/full buy played vs won). Composite unique (vlr_match_id, vlr_team_id).
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_fact_match_economy_row_number;

CREATE TABLE IF NOT EXISTS vlr.fact_match_economy (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_fact_match_economy_row_number'),

    vlr_match_id TEXT NOT NULL,
    vlr_event_id TEXT,
    match_date TEXT,
    vlr_team_id TEXT NOT NULL,
    pistol_played INTEGER,
    pistol_won INTEGER,
    eco_played INTEGER,
    eco_won INTEGER,
    semi_eco_played INTEGER,
    semi_eco_won INTEGER,
    semi_buy_played INTEGER,
    semi_buy_won INTEGER,
    full_buy_played INTEGER,
    full_buy_won INTEGER,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_vlr_fact_match_economy_grain UNIQUE (vlr_match_id, vlr_team_id)
);
