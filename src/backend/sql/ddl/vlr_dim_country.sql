-- Why: distinct country names/flags seen on VLR event rosters.
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_dim_country_row_number;

CREATE TABLE IF NOT EXISTS vlr.dim_country (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_dim_country_row_number'),
    country_name TEXT NOT NULL UNIQUE,
    country_flag TEXT,
    region_code TEXT,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now()
);
