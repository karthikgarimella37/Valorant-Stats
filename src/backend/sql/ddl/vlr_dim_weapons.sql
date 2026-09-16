-- Why: Fandom weapon catalog (quote, images, TTK/spread). Extra fire stats in JSONB.
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_dim_weapons_row_number;

CREATE TABLE IF NOT EXISTS vlr.dim_weapons (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_dim_weapons_row_number'),
    weapon_name TEXT NOT NULL UNIQUE,
    weapon_type TEXT,
    credits INTEGER,
    wall_penetration TEXT,
    length TEXT,
    creator TEXT,
    quote TEXT,
    image_url TEXT,
    icon_url TEXT,
    killfeed_icon_url TEXT,
    fire_rate DOUBLE PRECISION,
    magazine_size INTEGER,
    fandom_url TEXT,
    rib_weapon_id TEXT,
    fire_stats_json JSONB,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now()
);
