-- Why: VLR map names plus location, Alpha/Omega Earth, lat/lon, radar x/y bounds.
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_dim_maps_row_number;

CREATE TABLE IF NOT EXISTS vlr.dim_maps (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_dim_maps_row_number'),
    map_name TEXT NOT NULL UNIQUE,
    country_name TEXT,
    location_name TEXT,
    earth_name TEXT,
    coordinates_text TEXT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    spike_sites TEXT,
    map_features TEXT,
    description TEXT,
    release_date TEXT,
    minimap_url TEXT,
    splash_url TEXT,
    list_view_icon_url TEXT,
    x_multiplier DOUBLE PRECISION,
    y_multiplier DOUBLE PRECISION,
    x_scalar DOUBLE PRECISION,
    y_scalar DOUBLE PRECISION,
    min_x DOUBLE PRECISION,
    min_y DOUBLE PRECISION,
    max_x DOUBLE PRECISION,
    max_y DOUBLE PRECISION,
    valorant_api_uuid TEXT,
    liquipedia_url TEXT,
    callouts_json JSONB,
    features_json JSONB,
    infobox_json JSONB,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now()
);
