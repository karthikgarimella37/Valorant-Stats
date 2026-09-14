-- Why: distinct VLR agent names from match scoreboards.
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_dim_agents_row_number;

CREATE TABLE IF NOT EXISTS vlr.dim_agents (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_dim_agents_row_number'),
    agent_name TEXT NOT NULL UNIQUE,
    role_name TEXT,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now()
);
