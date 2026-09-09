# Dagster Orchestration

This is a separate Dagster project. Run it from **this directory**, not the repo root.

The repo root `.venv` has Dagster installed, but it does **not** include the
`dagster_orchestration` package. If you start Dagster from the root, imports like
`dagster_orchestration.definitions` will fail.

## Start the UI

```bash
cd dagster_orchestration
./dev.sh
```

Or without the script:

```bash
cd dagster_orchestration
uv sync
uv run dg dev
```

## Run the sample dbt job from the CLI

```bash
cd dagster_orchestration
uv run dagster job execute -m dagster_orchestration.definitions -j dbt_select_one_plus_ten_job
```

## Run the rib.gg extract → parquet → Supabase job

Job: `rib_gg_star_schema_job`

Flow: probe endpoints → extract teams/events/series → normalize (explode matches/maps/players) → load `valorant.dim_*` from parquet.

```bash
cd dagster_orchestration
uv run dagster job execute -m dagster_orchestration.definitions -j rib_gg_star_schema_job
```

Parquet / NDJSON land under `data/rib_gg/<entity>/dt=YYYY-MM-DD/` (gitignored).

Optional env vars:

- `RIB_RUN_DATE=YYYY-MM-DD` — landing partition date (default: today)
- `RIB_ENRICH_PLAYERS_VIA_API=true` — also fetch `/teams/{id}` for players (slow)
- `RIB_MAX_TEAM_DETAILS=200` — cap for API player enrichment
- `DBT_SUPABASE_SCHEMA=valorant` — target Postgres schema

## Seed dim_date (no VLR scrape)

Job: `vlr_date`

Calendar 2020-01-01 through 2030-12-31 into `vlr.dim_date`. Does not call vlr.gg.

```bash
cd dagster_orchestration
uv run dagster job execute -m dagster_orchestration.definitions -j vlr_date
```

Optional: `VLR_DATE_START=2020-01-01` `VLR_DATE_END=2030-12-31`

Join match/event text dates on `project_date` (`2026/7/8`). Filter ranges with `year`, `year_month`, `year_quarter`, `iso_week_num`, or `full_date BETWEEN …`.

## Historical VLR jobs (Dagster)

Jobs: `vlr_events` then `vlr_matches`.

Launch from the UI or CLI. Extracts refuse to start unless `docker logs vlrggapi` shows `Ready endpoints=` > 0 (AWS IPs). Do not scrape vlr.gg from the host IP.

```bash
# from repo root — rotator overlay
docker compose up -d --build vlrggapi
docker logs vlrggapi | grep vlrggapi_rotator
# expect: Ready endpoints=1 (or more)

cd dagster_orchestration
./dev.sh
# Jobs → vlr_events → Materialize
# Jobs → vlr_matches → Materialize
```

CLI:

```bash
cd dagster_orchestration
uv run dagster job execute -m dagster_orchestration.definitions -j vlr_events
uv run dagster job execute -m dagster_orchestration.definitions -j vlr_matches
```

`vlr_events`: ensure `vlr.dim_events` → `data/vlr/events.jsonl` → upsert.  
`vlr_matches`: ensure `vlr.dim_matches` → `data/vlr/matches.jsonl` (dim + full match JSON) → upsert.

Needs: vlrggapi on `http://127.0.0.1:3001` with AWS rotator, and working Supabase env.

Optional env vars:

- `VLR_EVENT_DETAIL_WORKERS` (default `12`)
- `VLR_EVENT_PAGE_WORKERS` (default `8`)
- `VLR_EVENT_PAGE_DELAY_SEC` (default `0.2`)
- `VLR_MAX_EVENTS` / `VLR_MAX_MATCHES` — cap for a smoke run
- `VLR_EVENT_SKIP_EXISTING=1` — skip ids already in `events.jsonl`
- `VLR_MATCH_EVENT_WORKERS` / `VLR_MATCH_WORKERS` (default `8`)
- `VLR_API_CONCURRENCY` (default `3`) — max in-flight `/v2` calls; keeps VLR 429s down
- `VLR_MATCH_SKIP_EXISTING=1` — skip ids already in `matches.jsonl`
- `VLR_REQUIRE_ROTATOR=0` — only for local debug; do not use for a full scrape

## Run the VLR.gg extract → parquet → Supabase job

Job: `vlr_star_schema_job`

Flow: completed events (orlandomm API) → scrape `/event/matches/{id}/` → scrape match overview/performance/economy → load `vlr.*`.

```bash
cd dagster_orchestration
# smoke test first
export VLR_EVENT_PAGE_START=1 VLR_EVENT_PAGE_END=1 VLR_MAX_MATCHES=3
uv run dagster job execute -m dagster_orchestration.definitions -j vlr_star_schema_job
```

Optional env vars:

- `VLR_EVENT_PAGE_START` / `VLR_EVENT_PAGE_END` (default `1` / `59`)
- `VLR_EVENT_STATUS` (default `completed`)
- `VLR_API_MAX_WORKERS` (default `10`) — parallel orlandomm API pages
- `VLR_HTML_MAX_WORKERS` (default `3`) — parallel www.vlr.gg scrapes
- `VLR_PARALLEL` (default `1`) — set `0` to force sequential
- `VLR_REQUEST_DELAY_SEC` (default `0.35`)
- `VLR_MAX_MATCHES` — cap match detail scrapes for testing
- `VLR_RUN_DATE=YYYY-MM-DD` — landing partition date

Parquet lands under `data/vlr/<entity>/dt=YYYY-MM-DD/` (gitignored). Checkpoints live in `data/vlr/_checkpoints/`.

## If you must launch from the repo root

Use the Dagster subproject environment and point at the definitions file:

```bash
uv run --directory dagster_orchestration dagster dev \
  -f src/dagster_orchestration/definitions.py \
  -d .
```
