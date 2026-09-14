-- Why: rib.gg weapon catalog (VLR match JSON has no gun names). Extra stats in JSONB.
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_dim_weapons_row_number;

CREATE TABLE IF NOT EXISTS vlr.dim_weapons (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_dim_weapons_row_number'),
    weapon_name TEXT NOT NULL UNIQUE,
    rib_weapon_id TEXT,
    weapon_type TEXT,
    credits INTEGER,
    fire_rate DOUBLE PRECISION,
    magazine_size INTEGER,
    image_url TEXT,
    stats_json JSONB,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now()
);
