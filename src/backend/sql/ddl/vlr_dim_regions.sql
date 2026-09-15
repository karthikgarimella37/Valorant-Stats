-- Why: one row per local VLR ranking code; vct_region_code joins to dim_vct_regions.
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_dim_regions_row_number;

CREATE TABLE IF NOT EXISTS vlr.dim_regions (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_dim_regions_row_number'),
    region_code TEXT NOT NULL UNIQUE,
    region_name TEXT NOT NULL,
    vct_region_code TEXT,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now()
);
