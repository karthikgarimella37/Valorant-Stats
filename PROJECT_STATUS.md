# Project Status

> Session-agnostic source of truth. Updated by agents via the `session-continuity` skill. Commit and push this file so every new Cursor chat starts with current context.

**Last updated:** 2026-09-07  
**Updated by:** Historical Dagster job for all VLR events → dim_events

---

## Aim

Build a web app for Valorant esports stats covering Regionals, Masters, Champions, and lower leagues — data pipeline (Dagster + dbt + Docker) feeding visualizations (Gradio or TypeScript).

## Current focus

- Run / finish `vlr_historical_events_job` (schema → JSON under `data/vlr/events` → `vlr.dim_events`)
- Next historical dims after events: teams, then matches/facts

## Status

| Area | State | Notes |
|------|--------|-------|
| Overall | In progress | Historical events pipeline is the first full warehouse load |
| Data sources | Validated | Self-hosted vlrggapi `/v2` |
| Orchestration | In progress | New job `vlr_historical_events_job`; old `vlr_star_schema_job` still parquet-based |
| Dim tables | In progress | `vlr.dim_events` DDL + extract/load; other dims still parquet/stub |
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
- [x] `src/backend/sql/ddl/vlr_dim_events.sql` (row_number PK, `vlr_event_id` unique)

## Next up

- [ ] Confirm historical events load completed (all JSON + Supabase row count)
- [ ] Historical teams pipeline (`vlr/dim` + `dim_teams`)
- [ ] Incremental extract via `vlr_watermarks` after historical
- [ ] Land `fact_round_economy_detail` from `maps[].round_economy`
- [ ] Fork/patch vlrggapi: Attack/Defend, event_id on match, labeled performance
- [ ] rib overlay: replay kills when `vlr_match_id` can join
- [ ] Build viz

## Open questions / blockers

- Historical events needs local vlrggapi (`VLR_API_BASE`) and working Supabase env (pooler user currently ENOTFOUND)
- Catalog saw **2980** events; detail fetch must use ~4 workers (12 workers 502’d vlrggapi)
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
| 2026-09-07 | Historical events Dagster job: schema, `data/vlr/events/<id>.json`, upsert `vlr.dim_events` |
