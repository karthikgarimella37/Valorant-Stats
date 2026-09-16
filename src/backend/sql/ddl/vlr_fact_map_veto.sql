-- Why: one veto action (ban/pick/decider) on a series. Composite unique (vlr_match_id, action_order).
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_fact_map_veto_row_number;

CREATE TABLE IF NOT EXISTS vlr.fact_map_veto (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_fact_map_veto_row_number'),

    vlr_match_id TEXT NOT NULL,
    vlr_event_id TEXT,
    match_date TEXT,
    map_name TEXT,
    team_tag TEXT,
    action_order INTEGER NOT NULL,
    is_ban BOOLEAN,
    is_pick BOOLEAN,
    is_decider BOOLEAN,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_vlr_fact_map_veto_grain UNIQUE (vlr_match_id, action_order)
);
