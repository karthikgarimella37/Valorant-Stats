-- Why: one player per vlr_player_id. Python ensure ADDs /v2/player columns (no DROP).
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_dim_players_row_number;

CREATE TABLE IF NOT EXISTS vlr.dim_players (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_dim_players_row_number'),
    vlr_player_id TEXT NOT NULL UNIQUE,
    rib_player_id BIGINT,
    ign TEXT,
    full_name TEXT,
    first_name TEXT,
    last_name TEXT,
    country_flag TEXT,
    country_name TEXT,
    image_url TEXT,
    player_href TEXT,
    vlr_team_id TEXT,
    current_team_name TEXT,
    current_team_joined TEXT,
    social_links_json JSONB,
    teams_json JSONB,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now()
);
