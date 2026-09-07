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

## Run the historical VLR events job (Dagster)

Job: `vlr_historical_events_job`

This is the production path. Launch it from the Dagster UI or the CLI — do not run `python -m backend.vlr.dim.historical` for warehouse loads.

Flow: ensure `vlr.dim_events` → append `data/vlr/events.jsonl` → upsert `vlr.dim_events`.

```bash
cd dagster_orchestration
./dev.sh
# then Jobs → vlr_historical_events_job → Materialize
```

CLI:

```bash
cd dagster_orchestration
uv run dagster job execute -m dagster_orchestration.definitions -j vlr_historical_events_job
```

Needs: vlrggapi on `http://127.0.0.1:3001` and working Supabase env. No AWS / IP rotator (that is paid).

```bash
# from repo root
docker compose up -d vlrggapi
```

Optional env vars:

- `VLR_EVENT_DETAIL_WORKERS` (default `2`)
- `VLR_EVENT_PAGE_WORKERS` (default `1`) — keep at 1; parallel catalog trips vlrggapi’s circuit breaker
- `VLR_EVENT_PAGE_DELAY_SEC` (default `1.5`)
- `VLR_MAX_EVENTS` — cap for a smoke run
- `VLR_EVENT_SKIP_EXISTING=1` — skip ids already in `events.jsonl`

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
- `VLR_HTML_MAX_WORKERS` (default `3`, or `10` with IP rotator) — parallel www.vlr.gg scrapes
- `VLR_PARALLEL` (default `1`) — set `0` to force sequential
- `VLR_REQUEST_DELAY_SEC` (default `0.35`, or `0.1` with IP rotator)
- `VLR_MAX_MATCHES` — cap match detail scrapes for testing
- `VLR_RUN_DATE=YYYY-MM-DD` — landing partition date
- `VLR_USE_IP_ROTATOR=1` — route HTML via AWS API Gateway (`requests-ip-rotator`)
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` — IAM user with API Gateway access
- `VLR_IP_ROTATOR_REGIONS` — optional comma-separated AWS regions

Put AWS keys in any `.env` under the repo (never commit). `load_project_env` finds them. Gateways auto-shutdown via `atexit`.

Parquet lands under `data/vlr/<entity>/dt=YYYY-MM-DD/` (gitignored). Checkpoints live in `data/vlr/_checkpoints/`.

## If you must launch from the repo root

Use the Dagster subproject environment and point at the definitions file:

```bash
uv run --directory dagster_orchestration dagster dev \
  -f src/dagster_orchestration/definitions.py \
  -d .
```
