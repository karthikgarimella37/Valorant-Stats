-- Why: one team on one round (bank/loadout). Composite unique (vlr_match_id, map_game_number, round_number, vlr_team_id).
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_fact_round_economy_detail_row_number;

CREATE TABLE IF NOT EXISTS vlr.fact_round_economy_detail (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_fact_round_economy_detail_row_number'),

    vlr_match_id TEXT NOT NULL,
    vlr_event_id TEXT,
    match_date TEXT,
    map_name TEXT,
    map_game_number INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    vlr_team_id TEXT NOT NULL,
    economy_code TEXT,
    bank INTEGER,
    loadout INTEGER,
    is_pistol_round BOOLEAN,
    is_winner BOOLEAN,
    is_attack BOOLEAN,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_vlr_fact_round_economy_detail_grain UNIQUE (vlr_match_id, map_game_number, round_number, vlr_team_id)
);
