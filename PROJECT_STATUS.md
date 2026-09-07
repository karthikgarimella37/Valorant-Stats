# Project Status

> Session-agnostic source of truth. Updated by agents via the `session-continuity` skill. Commit and push this file so every new Cursor chat starts with current context.

**Last updated:** 2026-09-07  
**Updated by:** Clarify historical events runs via Dagster job

---

## Aim

Build a web app for Valorant esports stats covering Regionals, Masters, Champions, and lower leagues — data pipeline (Dagster + dbt + Docker) feeding visualizations (Gradio or TypeScript).

## Current focus

- Run historical events through Dagster (`vlr_historical_events_job` in the UI or `dagster job execute`)
- Flow: ensure `vlr.dim_events` → append `data/vlr/events.jsonl` → upsert
- Next historical dims after events: teams, then matches/facts

## Status

| Area | State | Notes |
|------|--------|-------|
| Overall | In progress | Historical events pipeline is the first full warehouse load |
| Data sources | Validated | Self-hosted vlrggapi `/v2` |
| Orchestration | In progress | Job `vlr_historical_events_job`; old `vlr_star_schema_job` still parquet-based |
| Dim tables | In progress | `vlr.dim_events` create-if-missing + alter; other dims still parquet/stub |
| Fact tables | Partial | Round bank on match JSON; fact historical folder stub only |
| Frontend / viz | Not started | Graphs and dashboards listed in `Valorant API.md` |
| Session process | Done | Status + standards markdown; always-on Cursor rules/skills; auto-commit hook |

## Done

- [x] Repo scaffolding (Dagster, src, notebooks, schemas)
- [x] rib.gg endpoint discovery (`rib_discovery_results.json`, notes in `Valorant API.md`)
- [x] Session continuity + engineering standards
- [x] `DATA_MODEL.md` snowflake contract
- [x] vlrggapi probe, JSON landings, watermarks, economy bank scrape
- [x] Regions split: VCT circuits vs local ranking codes
- [x] `src/backend/vlr/dim/` + `fact/` extract layout
- [x] Historical events extract (`dim/historical.py`) and job `vlr_historical_events_job`
- [x] `vlr.dim_events` DDL is create-if-missing (no DROP); Python ADD/ALTER columns
- [x] Single landing file `data/vlr/events.jsonl` (one insert row per event, append)
- [x] Event logs: `N/total Event Name (start–end)`
- [x] Load every repo `.env`; AWS keys drive IP rotator (`AWS_*` or `VLR_AWS_*`)
- [x] Project calendar dates: `YYYY/M/D` no pad (example `2026/7/8`)

## Next up

- [ ] Materialize `vlr_historical_events_job` in Dagster when API + Supabase work
- [ ] Confirm historical events load completed (jsonl + Supabase row count)
- [ ] Historical teams pipeline (`vlr/dim` + `dim_teams`)
- [ ] Incremental extract via `vlr_watermarks` after historical
- [ ] Land `fact_round_economy_detail` from `maps[].round_economy`
- [ ] Fork/patch vlrggapi: Attack/Defend, event_id on match, labeled performance
- [ ] rib overlay: replay kills when `vlr_match_id` can join
- [ ] Build viz

## Open questions / blockers

- Historical events needs local vlrggapi (`VLR_API_BASE`) and working Supabase env (pooler user previously ENOTFOUND)
- Catalog saw **2980** events; detail fetch must use ~4 workers (12 workers 502’d vlrggapi)
- IP rotator uses AWS keys for **www.vlr.gg**. Local `/v2` (`127.0.0.1`) is not rotated; rotator mounts if `VLR_API_BASE` is a vlr.gg host
- **API gaps:** Attack/Defend player stats; labeled 2K/1vX/ECON; prize points/note; match `event_id`
- rib overlay join: fuzzy (event name + team names + date)

## Session log

| Date | Session summary |
|------|-----------------|
| 2026-08-17 | Created `PROJECT_STATUS.md` and session-continuity skill/rule |
| 2026-08-17 | Added `ENGINEERING_STANDARDS.md` + always-on rule/skill |
| 2026-08-18 | Added `DATA_MODEL.md` snowflake dim/fact contract |
| 2026-08-27 | VLR-primary + rib overlay; vlrggapi extract; facts + half-round view |
| 2026-08-29 | Probed match 742485; JSON + watermarks; economy bank scrape; smarter auto-commit |
| 2026-09-04 | Split VCT circuits from local ranking codes |
| 2026-09-07 | Historical events Dagster job: schema, per-id JSON, upsert `vlr.dim_events` |
| 2026-09-07 | Events jsonl + date format + schema ensure + env/rotator (no extract run) |
| 2026-09-07 | Documented Dagster as the run path for `vlr_historical_events_job` |
