-- VLR.gg star schema for Supabase
-- Runtime loads may CREATE/REPLACE from parquet; this documents expected shapes.

CREATE SCHEMA IF NOT EXISTS vlr;

CREATE TABLE IF NOT EXISTS vlr.dim_events (
    id TEXT PRIMARY KEY,
    name TEXT,
    status TEXT,
    prizepool TEXT,
    dates_raw TEXT,
    start_date TEXT,
    end_date TEXT,
    country TEXT,
    img TEXT,
    url TEXT
);

CREATE TABLE IF NOT EXISTS vlr.dim_teams (
    id TEXT PRIMARY KEY,
    name TEXT,
    url TEXT,
    img TEXT,
    country TEXT
);

CREATE TABLE IF NOT EXISTS vlr.dim_players (
    id TEXT PRIMARY KEY,
    name TEXT,
    url TEXT,
    country TEXT,
    country_code TEXT,
    team_id TEXT,
    team_tag TEXT
);

CREATE TABLE IF NOT EXISTS vlr.dim_agents (
    name TEXT PRIMARY KEY,
    image_url TEXT
);

CREATE TABLE IF NOT EXISTS vlr.dim_maps (
    name TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS vlr.dim_matches (
    match_id TEXT PRIMARY KEY,
    event_id TEXT,
    event_name TEXT,
    event_stage TEXT,
    team1_id TEXT,
    team2_id TEXT,
    team1_name TEXT,
    team2_name TEXT,
    team1_logo TEXT,
    team2_logo TEXT,
    team1_score BIGINT,
    team2_score BIGINT,
    match_date TEXT,
    patch TEXT,
    note TEXT,
    url TEXT,
    best_of BIGINT
);

CREATE TABLE IF NOT EXISTS vlr.fact_match_maps (
    match_id TEXT,
    map_game_id TEXT,
    map_number BIGINT,
    map_name TEXT,
    team1_name TEXT,
    team2_name TEXT,
    team1_rounds BIGINT,
    team2_rounds BIGINT,
    pick_side BIGINT,
    duration TEXT
);

CREATE TABLE IF NOT EXISTS vlr.fact_map_pickban (
    match_id TEXT,
    order_index BIGINT,
    action TEXT,
    map_name TEXT,
    team_name TEXT,
    team_id TEXT,
    raw TEXT
);

CREATE TABLE IF NOT EXISTS vlr.fact_player_overview (
    match_id TEXT,
    map_game_id TEXT,
    map_name TEXT,
    player_id TEXT,
    player_name TEXT,
    team_tag TEXT,
    agent_name TEXT,
    rating DOUBLE PRECISION,
    acs DOUBLE PRECISION,
    kills BIGINT,
    deaths BIGINT,
    assists BIGINT,
    plus_minus DOUBLE PRECISION,
    kast DOUBLE PRECISION,
    adr DOUBLE PRECISION,
    hs_pct DOUBLE PRECISION,
    fk BIGINT,
    fd BIGINT,
    fk_fd_diff DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS vlr.fact_player_performance (
    match_id TEXT,
    map_name TEXT,
    row_player TEXT,
    col_player TEXT,
    value_raw TEXT
);

CREATE TABLE IF NOT EXISTS vlr.fact_player_economy (
    match_id TEXT,
    map_name TEXT,
    row_type TEXT,
    team_name TEXT,
    raw_cells TEXT
);

CREATE TABLE IF NOT EXISTS vlr.fact_rounds (
    match_id TEXT,
    map_game_id TEXT,
    map_name TEXT,
    round_number BIGINT,
    score_after TEXT,
    winner_side BIGINT,
    win_type TEXT
);

CREATE INDEX IF NOT EXISTS idx_vlr_matches_event ON vlr.dim_matches(event_id);
CREATE INDEX IF NOT EXISTS idx_vlr_overview_match ON vlr.fact_player_overview(match_id);
CREATE INDEX IF NOT EXISTS idx_vlr_rounds_match ON vlr.fact_rounds(match_id);
CREATE INDEX IF NOT EXISTS idx_vlr_match_maps_match ON vlr.fact_match_maps(match_id);
