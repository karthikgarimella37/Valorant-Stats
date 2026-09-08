-- Why: create vlr.dim_matches if missing. Python ensure adds/alters columns (no DROP).
-- Grain: one VLR series (BO1/BO3/BO5). Codes, not FKs, until dim_teams/dim_date exist.
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_dim_matches_row_number;

CREATE TABLE IF NOT EXISTS vlr.dim_matches (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_dim_matches_row_number'),
    vlr_match_id TEXT NOT NULL UNIQUE,
    vlr_event_id TEXT,
    vlr_team_1_id TEXT,
    vlr_team_2_id TEXT,
    team_1_name TEXT,
    team_2_name TEXT,
    event_series TEXT,
    best_of INTEGER,
    team_1_score INTEGER,
    team_2_score INTEGER,
    match_date TEXT,
    match_date_text TEXT,
    match_note TEXT,
    match_patch TEXT,
    n_maps INTEGER,
    is_completed BOOLEAN,
    has_stats BOOLEAN,
    has_vod BOOLEAN,
    has_rib_replay BOOLEAN NOT NULL DEFAULT FALSE,
    rib_match_id BIGINT,
    url TEXT,
    status TEXT,
    map_vetos TEXT,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now()
);
