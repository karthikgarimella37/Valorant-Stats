-- Why: one team on one round bank/loadout/buy tier from rib Economy tab.
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_fact_rib_round_economy_row_number;

CREATE TABLE IF NOT EXISTS vlr.fact_rib_round_economy (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_fact_rib_round_economy_row_number'),
    rib_match_id TEXT NOT NULL,
    rib_map_id TEXT NOT NULL,
    rib_event_id TEXT,
    rib_team_id TEXT NOT NULL,
    vlr_match_id TEXT,
    vlr_event_id TEXT,
    vlr_team_id TEXT,
    match_date TEXT,
    map_name TEXT,
    map_game_number INTEGER,
    round_number INTEGER NOT NULL,
    bank INTEGER,
    loadout INTEGER,
    buy_tier TEXT,
    leftover_json JSONB,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_vlr_fact_rib_round_economy_grain UNIQUE (rib_match_id, rib_map_id, round_number, rib_team_id)
);
