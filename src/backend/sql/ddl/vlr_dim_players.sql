-- Why: unique players from event roster lists (thin; no /v2/player yet).
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_dim_players_row_number;

CREATE TABLE IF NOT EXISTS vlr.dim_players (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_dim_players_row_number'),
    vlr_player_id TEXT NOT NULL UNIQUE,
    ign TEXT,
    vlr_team_id TEXT,
    country_flag TEXT,
    country_name TEXT,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now()
);
