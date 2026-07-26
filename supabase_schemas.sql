-- VALORANT Stats — rib.gg aligned schema for Supabase
-- Tables: valorant.dim_* (Phase 1). Fact tables are Phase 2 (/matches/{id}/details).
-- Runtime loads may CREATE/REPLACE tables from parquet schemas; this file documents the expected shape.

CREATE SCHEMA IF NOT EXISTS valorant;

-- Events (/v1/events)
CREATE TABLE IF NOT EXISTS valorant.dim_events (
    id BIGINT PRIMARY KEY,
    name TEXT,
    short_name TEXT,
    description TEXT,
    format_md TEXT,
    events_md TEXT,
    logo_url TEXT,
    region_id BIGINT,
    country_id BIGINT,
    start_date TIMESTAMP,
    end_date TIMESTAMP,
    prize_pool DOUBLE PRECISION,
    prize_pool_currency TEXT,
    url TEXT,
    image_url TEXT,
    livestream_link TEXT,
    winner_stage_count BIGINT,
    loser_stage_count BIGINT,
    live BOOLEAN,
    rank BIGINT,
    pmt_json TEXT,
    parent BOOLEAN,
    parent_id BIGINT,
    child_label TEXT,
    keywords TEXT,
    slug TEXT,
    series_count BIGINT,
    importance BIGINT,
    type TEXT,
    liquipedia_slug TEXT,
    vct_regions TEXT,
    divisions TEXT,
    t3_subdivision TEXT,
    region TEXT,
    country TEXT
);

-- Teams (/v1/teams/all or /v1/teams)
CREATE TABLE IF NOT EXISTS valorant.dim_teams (
    id BIGINT PRIMARY KEY,
    name TEXT,
    short_name TEXT,
    description TEXT,
    website_url TEXT,
    logo_url TEXT,
    country_id BIGINT,
    liquipedia_slug TEXT,
    twitter_url TEXT,
    twitch_url TEXT,
    vlr_url TEXT,
    youtube_url TEXT,
    founded_date TIMESTAMP,
    region_id BIGINT,
    rank BIGINT,
    region_rank BIGINT,
    aliases TEXT,
    vct_region TEXT,
    division TEXT,
    grid_team_id TEXT
);

-- Series / BO fixtures (/v1/series) — not individual maps
CREATE TABLE IF NOT EXISTS valorant.dim_series (
    id BIGINT PRIMARY KEY,
    event_id BIGINT,
    team1_id BIGINT,
    team2_id BIGINT,
    team1_score BIGINT,
    team2_score BIGINT,
    start_date TIMESTAMP,
    best_of BIGINT,
    stage TEXT,
    bracket TEXT,
    completed BOOLEAN,
    live BOOLEAN,
    win_condition TEXT,
    vlr_id TEXT,
    vod_url TEXT,
    ggbet_id TEXT,
    pmt_status TEXT,
    pmt_reddit_url TEXT,
    pmt_json TEXT,
    pickban TEXT,
    grid_series_id TEXT,
    liquipedia_slug TEXT,
    event_livestream_link TEXT,
    event_name TEXT,
    event_slug TEXT,
    event_child_label TEXT,
    event_logo_url TEXT,
    event_region_id BIGINT,
    parent_event_id BIGINT,
    parent_event_name TEXT,
    parent_event_slug TEXT,
    parent_event_livestream_link TEXT
);

-- Map-level matches (exploded from series.matches[])
CREATE TABLE IF NOT EXISTS valorant.dim_matches (
    id BIGINT PRIMARY KEY,
    patch_id BIGINT,
    series_id BIGINT,
    series_match_number BIGINT,
    riot_id TEXT,
    map_id BIGINT,
    start_date TIMESTAMP,
    length_millis BIGINT,
    completed BOOLEAN,
    riot_season_id TEXT,
    riot_game_mode TEXT,
    no_riot_data BOOLEAN,
    region TEXT,
    live BOOLEAN,
    ready_to_display BOOLEAN,
    attacking_first_team_number BIGINT,
    red_team_number BIGINT,
    winning_team_number BIGINT,
    win_condition TEXT,
    teams_inverted_in_stream BOOLEAN,
    team1_score BIGINT,
    team2_score BIGINT,
    vlr_id TEXT,
    vod_url TEXT,
    cn_vod_url TEXT,
    team1_player_ids TEXT,
    team2_player_ids TEXT,
    team1_agent_ids TEXT,
    team2_agent_ids TEXT
);

-- Maps (distinct match.map objects)
CREATE TABLE IF NOT EXISTS valorant.dim_maps (
    id BIGINT PRIMARY KEY,
    name TEXT,
    riot_id TEXT,
    riot_name TEXT,
    images TEXT,
    ow_name TEXT,
    geo_data TEXT,
    display_data TEXT
);

-- Players (from nested team payloads; no public /players list)
CREATE TABLE IF NOT EXISTS valorant.dim_players (
    id BIGINT PRIMARY KEY,
    ign TEXT,
    first_name TEXT,
    last_name TEXT,
    bio TEXT,
    country_id BIGINT,
    instagram_url TEXT,
    liquipedia_slug TEXT,
    twitch_url TEXT,
    twitter_url TEXT,
    youtube_url TEXT,
    image_url TEXT,
    firestore_id TEXT,
    previous_riot_player_ids TEXT,
    ufa TEXT,
    rfa TEXT,
    metafy_url TEXT,
    custom_url TEXT,
    grid_player_id TEXT,
    team_player_history_id BIGINT,
    team_id BIGINT,
    start_date TIMESTAMP,
    role TEXT,
    igl BOOLEAN
);

-- Agents (Phase 1 stub — fill when /agents list works or via static backfill)
CREATE TABLE IF NOT EXISTS valorant.dim_agents (
    id BIGINT PRIMARY KEY,
    name TEXT,
    agent_type TEXT
);

-- Phase 2 fact tables (populated from /matches/{id}/details)
CREATE TABLE IF NOT EXISTS valorant.fact_match_overall_stats (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT,
    team_id BIGINT,
    map_id BIGINT,
    rounds_won BIGINT,
    rounds_lost BIGINT,
    total_kills BIGINT,
    total_deaths BIGINT,
    total_assists BIGINT,
    total_acs DOUBLE PRECISION,
    total_adr DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS valorant.fact_match_performance (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT,
    player_id BIGINT,
    team_id BIGINT,
    map_id BIGINT,
    agent_id BIGINT,
    kills BIGINT,
    deaths BIGINT,
    assists BIGINT,
    acs DOUBLE PRECISION,
    adr DOUBLE PRECISION,
    hs_percentage DOUBLE PRECISION,
    rating DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS valorant.fact_match_economy (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT,
    player_id BIGINT,
    team_id BIGINT,
    map_id BIGINT,
    total_spent BIGINT,
    equipment_value BIGINT,
    money_saved BIGINT
);

CREATE INDEX IF NOT EXISTS idx_dim_series_event ON valorant.dim_series(event_id);
CREATE INDEX IF NOT EXISTS idx_dim_series_teams ON valorant.dim_series(team1_id, team2_id);
CREATE INDEX IF NOT EXISTS idx_dim_matches_series ON valorant.dim_matches(series_id);
CREATE INDEX IF NOT EXISTS idx_dim_matches_map ON valorant.dim_matches(map_id);
CREATE INDEX IF NOT EXISTS idx_dim_players_team ON valorant.dim_players(team_id);
