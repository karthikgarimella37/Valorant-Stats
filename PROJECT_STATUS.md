# Project Status

> Session-agnostic source of truth. Updated by agents via the `session-continuity` skill. Commit and push this file so every new Cursor chat starts with current context.

**Last updated:** 2026-08-27  
**Updated by:** VLR fact landings + half-round dbt view

---

## Aim

Build a web app for Valorant esports stats covering Regionals, Masters, Champions, and lower leagues — data pipeline (Dagster + dbt + Docker) feeding visualizations (Gradio or TypeScript).

## Current focus

- Smoke `vlr_star_schema_job` (`docker compose up vlrggapi`, then extract → `vlr.*` → half-round view)
- rib overlay (replay kills) when a match can join `vlr_match_id`

## Status

| Area | State | Notes |
|------|--------|-------|
| Overall | In progress | Dims + VLR facts land to parquet; warehouse smoke not run |
| Data sources | In progress | **Self-hosted vlrggapi** (`/v2`) is the VLR wrapper; rib overlay via fuzzy join |
| Orchestration | In progress | `vlr_star_schema_job` now includes facts + half-round dbt view |
| Dim tables | Partial | Regions → events/teams + match/player/agent/map parquet; warehouse unproven |
| Fact tables | Partial | overall / rounds / performance / economy parquet; half-round is dbt view; PvP kills rib-only |
| Frontend / viz | Not started | Graphs and dashboards listed in `Valorant API.md` |
| Session process | Done | Status + standards markdown; always-on Cursor rules/skills; auto-commit hook |

## Done

- [x] Repo scaffolding (Dagster, src, notebooks, schemas)
- [x] rib.gg endpoint discovery (`rib_discovery_results.json`, notes in `Valorant API.md`)
- [x] Matches dimension marked done
- [x] Session continuity process (`PROJECT_STATUS.md`, skill, rule)
- [x] Engineering standards (`ENGINEERING_STANDARDS.md`, rule, skill): simple English, concise chat, why-docstrings, dbt/Dagster/extract practices
- [x] Standards require process logging, parallelization by default, and optimized path into Supabase analytics
- [x] `ribgg.ipynb` cells for agents (abilities), maps (coords/callouts), guns (fire rate/accuracy) via valorant-api.com after rib.gg catalog 404s
- [x] Snowflake schema tracker `DATA_MODEL.md`: dim/fact grains, sequences, FKs, API insert sources, Dagster order
- [x] `docker-compose.yml`: vlrggapi + dagster-webserver + dagster-daemon; Dagster `VLR_API_BASE=http://vlrggapi:3001`
- [x] `src/backend/vlr/extract.py` + `VlrV2Connector`; Dagster assets: regions → events → teams / match queue → details → Supabase
- [x] Always-on Cursor `afterFileEdit` hook: `git add` + commit (no push; skips `.env`)
- [x] VLR facts from `/v2/match/details`: overall stats, round results, performance, team economy win %
- [x] dbt view `fact_match_half_round_stats` over `vlr.fact_round_results`

## Next up

- [ ] `docker compose up vlrggapi` and materialize `vlr_star_schema_job` (smoke load into Supabase)
- [ ] Seed `dim_economy` / `dim_date` if still needed
- [ ] `fact_round_economy_detail` when round bank/loadout exists
- [ ] rib overlay: replay kills when `vlr_match_id` can join
- [ ] Build viz: player profile, match report, team comparison, map dashboard

## Open questions / blockers

- `vlr.orlandomm.net` / public vlrggapi Vercel are down — **self-host** `vlrggapi` in Compose
- rib overlay join: fuzzy (event name + team names + date)
- Choose Gradio vs TypeScript for the web UI when ready

## Session log

| Date | Session summary |
|------|-----------------|
| 2026-08-17 | Created `PROJECT_STATUS.md` and session-continuity skill/rule so future chats load aim + status automatically |
| 2026-08-17 | Added `ENGINEERING_STANDARDS.md` + always-on rule/skill for concise simple English and service coding standards |
| 2026-08-17 | Extended standards: process logs for Dagster, parallelization default, optimize for Supabase analytics |
| 2026-08-17 | Added `ribgg.ipynb` static catalog cells; rib.gg 404s, so agents/maps/guns come from valorant-api.com |
| 2026-08-18 | Added `DATA_MODEL.md` snowflake dim/fact contract, sequences, FKs, and Dagster insert map |
| 2026-08-27 | Flipped source to VLR-primary + rib overlay; added dim_regions/country; half-round is a view |
| 2026-08-27 | Added vlrggapi extract (`VLR_API_BASE`), Docker compose, and always-on auto-commit hook |
| 2026-08-27 | Landed VLR facts from match/details; added dbt half-round view |
