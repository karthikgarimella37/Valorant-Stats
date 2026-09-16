-- Why: VLR scoreboard names plus kit catalog (abilities, costs, portraits).
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_dim_agents_row_number;

CREATE TABLE IF NOT EXISTS vlr.dim_agents (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_dim_agents_row_number'),
    agent_name TEXT NOT NULL UNIQUE,
    role_name TEXT,
    description TEXT,
    real_name TEXT,
    country_name TEXT,
    release_date TEXT,
    image_url TEXT,
    portrait_url TEXT,
    role_icon_url TEXT,
    valorant_api_uuid TEXT,
    liquipedia_url TEXT,
    ability_c_name TEXT,
    ability_c_cost INTEGER,
    ability_q_name TEXT,
    ability_q_cost INTEGER,
    ability_e_name TEXT,
    ability_e_cost INTEGER,
    ultimate_name TEXT,
    ultimate_orbs INTEGER,
    abilities_json JSONB,
    tags_json JSONB,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now()
);
