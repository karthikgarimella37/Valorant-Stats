-- Why: one warehouse cursor per pipeline + table so every incremental DAG
-- reads/writes the same clock (last_source_at) instead of JSON files.
CREATE SCHEMA IF NOT EXISTS vlr;

CREATE SEQUENCE IF NOT EXISTS vlr.seq_ops_pipeline_watermarks_row_number;

CREATE TABLE IF NOT EXISTS vlr.ops_pipeline_watermarks (
    row_number BIGINT PRIMARY KEY DEFAULT nextval('vlr.seq_ops_pipeline_watermarks_row_number'),
    pipeline_name TEXT NOT NULL,
    table_name TEXT NOT NULL,
    source_name TEXT NOT NULL,
    last_source_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    row_count BIGINT,
    dagster_run_id TEXT,
    dagster_job_name TEXT,
    status TEXT NOT NULL DEFAULT 'never_run',
    error_text TEXT,
    insert_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_vlr_ops_pipeline_watermarks_pipeline_table UNIQUE (pipeline_name, table_name)
);

CREATE INDEX IF NOT EXISTS idx_vlr_ops_pipeline_watermarks_status
    ON vlr.ops_pipeline_watermarks (status);
CREATE INDEX IF NOT EXISTS idx_vlr_ops_pipeline_watermarks_table
    ON vlr.ops_pipeline_watermarks (table_name);
