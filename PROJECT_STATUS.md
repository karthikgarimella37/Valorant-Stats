# Project Status

> Session-agnostic source of truth. Updated by agents via the `session-continuity` skill. Commit and push this file so every new Cursor chat starts with current context.

**Last updated:** 2026-08-17  
**Updated by:** standards — logging, parallelization, Supabase speed

---

## Aim

Build a web app for Valorant esports stats covering Regionals, Masters, Champions, and lower leagues — data pipeline (Dagster + dbt + Docker) feeding visualizations (Gradio or TypeScript).

## Current focus

- Continue data exploration / ingestion from rib.gg and related APIs (`ribgg.ipynb`, `valorant-stats.ipynb`)
- Advance remaining dimension tables after Matches
- Follow `ENGINEERING_STANDARDS.md` for all new code

## Status

| Area | State | Notes |
|------|--------|-------|
| Overall | In progress | Pipeline + schema design underway; frontend not started |
| Data sources | In progress | rib.gg endpoints discovered; VLR/val.gg APIs noted |
| Dim tables | Partial | Matches marked done; Events, Players, Teams, Economy, Date pending |
| Fact tables | Not started | Match/player/economy fact tables planned |
| Orchestration | In progress | Dagster project present |
| Frontend / viz | Not started | Graphs and dashboards listed in `Valorant API.md` |
| Session process | Done | Status + standards markdown; always-on Cursor rules/skills |

## Done

- [x] Repo scaffolding (Dagster, src, notebooks, schemas)
- [x] rib.gg endpoint discovery (`rib_discovery_results.json`, notes in `Valorant API.md`)
- [x] Matches dimension marked done
- [x] Session continuity process (`PROJECT_STATUS.md`, skill, rule)
- [x] Engineering standards (`ENGINEERING_STANDARDS.md`, rule, skill): simple English, concise chat, why-docstrings, dbt/Dagster/extract practices
- [x] Standards require process logging, parallelization by default, and optimized path into Supabase analytics

## Next up

- [ ] Finish remaining dim tables (Events, Players, Teams, Economy, Date; static Agents/Maps/Weapons as needed)
- [ ] Implement fact tables (match overall, half-round, player performance, PvP kills, economy)
- [ ] Wire Dagster + dbt for load/test
- [ ] Build viz: player profile, match report, team comparison, map dashboard

## Open questions / blockers

- Weapons data may be incomplete for round-level use
- Choose Gradio vs TypeScript for the web UI when ready

## Session log

| Date | Session summary |
|------|-----------------|
| 2026-08-17 | Created `PROJECT_STATUS.md` and session-continuity skill/rule so future chats load aim + status automatically |
| 2026-08-17 | Added `ENGINEERING_STANDARDS.md` + always-on rule/skill for concise simple English and service coding standards |
| 2026-08-17 | Extended standards: process logs for Dagster, parallelization default, optimize for Supabase analytics |
