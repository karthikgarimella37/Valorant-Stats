-- Why: one org per vlr_team_id. Python ensure ADDs profile columns (no DROP).
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_dim_teams_row_number;

CREATE TABLE IF NOT EXISTS vlr.dim_teams (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_dim_teams_row_number'),
    vlr_team_id TEXT NOT NULL UNIQUE,
    rib_team_id BIGINT,
    region_code TEXT,
    country_name TEXT,
    country_flag TEXT,
    team_name TEXT,
    team_code TEXT,
    logo_url TEXT,
    team_href TEXT,
    division TEXT,
    current_roster_json JSONB,
    coaches_json JSONB,
    assistant_coaches_json JSONB,
    coach_vlr_player_id TEXT,
    social_links_json JSONB,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now()
);
