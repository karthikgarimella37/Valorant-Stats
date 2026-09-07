-- Why: historical event load needs a stable vlr.dim_events shape (business key + row_number).
-- DROP so an older list-only dim_events (id/name/prizepool) does not block the new columns.
CREATE SCHEMA IF NOT EXISTS vlr;

DROP TABLE IF EXISTS vlr.dim_events CASCADE;
CREATE SEQUENCE IF NOT EXISTS vlr.seq_dim_events_row_number;

CREATE TABLE vlr.dim_events (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_dim_events_row_number'),
    vlr_event_id TEXT NOT NULL UNIQUE,
    parent_vlr_event_id TEXT,
    vct_region_code TEXT,
    region_code TEXT,
    event_name TEXT,
    series TEXT,
    subtitle TEXT,
    short_name TEXT,
    slug TEXT,
    event_tier TEXT,
    status TEXT,
    dates_text TEXT,
    start_date DATE,
    end_date DATE,
    prize_pool NUMERIC,
    prize_pool_currency TEXT,
    prize_pool_text TEXT,
    location TEXT,
    logo_url TEXT,
    url TEXT,
    participating_team_count INTEGER,
    prize_placement_count INTEGER,
    prizes_json JSONB,
    teams_json JSONB,
    standings_json JSONB,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_vlr_dim_events_status ON vlr.dim_events (status);
CREATE INDEX IF NOT EXISTS idx_vlr_dim_events_vct ON vlr.dim_events (vct_region_code);
CREATE INDEX IF NOT EXISTS idx_vlr_dim_events_region ON vlr.dim_events (region_code);
