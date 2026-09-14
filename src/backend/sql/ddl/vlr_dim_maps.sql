-- Why: distinct VLR map names from match details (no world coordinates).
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_dim_maps_row_number;

CREATE TABLE IF NOT EXISTS vlr.dim_maps (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_dim_maps_row_number'),
    map_name TEXT NOT NULL UNIQUE,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now()
);
