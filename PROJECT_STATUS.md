# Project Status

> Session-agnostic source of truth. Updated by agents via the `session-continuity` skill. Commit and push this file so every new Cursor chat starts with current context.

**Last updated:** 2026-08-18  
**Updated by:** source rule (rib then VLR), dim_regions/dim_country, facts deferred

---

## Aim

Build a web app for Valorant esports stats covering Regionals, Masters, Champions, and lower leagues — data pipeline (Dagster + dbt + Docker) feeding visualizations (Gradio or TypeScript).

## Current focus

- Implement **dims** from `DATA_MODEL.md` (Matches extract exists; add region, country, then remaining dims)
- Do **not** lock fact columns yet — define facts later from real rib/VLR extracts
- `fact_match_half_round_stats` will be a **view**, not a loaded table

## Status

| Area | State | Notes |
|------|--------|-------|
| Overall | In progress | Dim contract updated; facts deferred; frontend not started |
| Data sources | In progress | **rib.gg first**, **vlr.gg for gaps + previous years**; no valorant-api.com; VLR has no round data |
| Dim tables | Partial | Matches extract done; region/country added to model; warehouse still stubs |
| Fact tables | Deferred | Names listed in `DATA_MODEL.md`; columns not locked; half-round = view |
| Orchestration | In progress | Dagster project present |
| Frontend / viz | Not started | Graphs listed in `DATA_MODEL.md` / `Valorant API.md` |
| Session process | Done | Status + standards markdown; always-on Cursor rules/skills |

## Done

- [x] Repo scaffolding (Dagster, src, notebooks, schemas)
- [x] rib.gg endpoint discovery (`rib_discovery_results.json`, notes in `Valorant API.md`)
- [x] Matches dimension marked done (extract)
- [x] Session continuity process (`PROJECT_STATUS.md`, skill, rule)
- [x] Engineering standards (`ENGINEERING_STANDARDS.md`, rule, skill)
- [x] `DATA_MODEL.md` snowflake dim contract: sequences, FKs, rib-then-VLR sources, Dagster order
- [x] Source rule: rib.gg first, vlr.gg fallback, no valorant-api.com
- [x] `dim_regions` + `dim_country` added to the model
- [x] Half-round stats marked as a dbt view

## Next up

- [ ] Load remaining dims per `DATA_MODEL.md` (regions, country, events, players, teams, economy, date, agents/maps/weapons from VLR)
- [ ] VLR extract for previous-year matches (no round grain)
- [ ] Define fact tables organically from extracts
- [ ] Wire Dagster + dbt for dim upserts/tests
- [ ] Build viz after facts exist

## Open questions / blockers

- VLR will not provide abilities, map coordinates, or gun fire-rate/accuracy
- Weapons still incomplete for round-level rib kills
- Choose Gradio vs TypeScript for the web UI when ready

## Session log

| Date | Session summary |
|------|-----------------|
| 2026-08-17 | Created `PROJECT_STATUS.md` and session-continuity skill/rule so future chats load aim + status automatically |
| 2026-08-17 | Added `ENGINEERING_STANDARDS.md` + always-on rule/skill for concise simple English and service coding standards |
| 2026-08-17 | Extended standards: process logs for Dagster, parallelization default, optimize for Supabase analytics |
| 2026-08-17 | Added `ribgg.ipynb` static catalog cells (later dropped valorant-api.com as a source) |
| 2026-08-18 | Added `DATA_MODEL.md` snowflake dim/fact contract |
| 2026-08-18 | Switched fallback to VLR; added dim_regions/dim_country; half-round = view; facts deferred |
