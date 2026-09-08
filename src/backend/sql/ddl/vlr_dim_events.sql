-- Why: create vlr.dim_events if missing. Python ensure adds/alters columns (no DROP).
-- Indexes are created after column ensure so an older table can be altered first.
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_dim_events_row_number;

CREATE TABLE IF NOT EXISTS vlr.dim_events (
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
    start_date TEXT,
    end_date TEXT,
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
