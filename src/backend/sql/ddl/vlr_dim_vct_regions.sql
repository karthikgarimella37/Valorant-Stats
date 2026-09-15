-- Why: one row per VCT international circuit (not local ranking codes).
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_dim_vct_regions_row_number;

CREATE TABLE IF NOT EXISTS vlr.dim_vct_regions (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_dim_vct_regions_row_number'),
    vct_region_code TEXT NOT NULL UNIQUE,
    vct_region_name TEXT NOT NULL,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now()
);
