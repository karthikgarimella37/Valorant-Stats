-- Why: seed buy-type bands so round loadout credits can join a dim, not free text.
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_dim_economy_row_number;

CREATE TABLE IF NOT EXISTS vlr.dim_economy (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_dim_economy_row_number'),
    economy_code TEXT NOT NULL UNIQUE,
    economy_name TEXT NOT NULL,
    min_loadout INTEGER,
    max_loadout INTEGER,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now()
);
