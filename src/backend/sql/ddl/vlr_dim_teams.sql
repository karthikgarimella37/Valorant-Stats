-- Why: unique orgs from event rosters + match team ids (thin; no /v2/team yet).
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_dim_teams_row_number;

CREATE TABLE IF NOT EXISTS vlr.dim_teams (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_dim_teams_row_number'),
    vlr_team_id TEXT NOT NULL UNIQUE,
    team_name TEXT,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now()
);
