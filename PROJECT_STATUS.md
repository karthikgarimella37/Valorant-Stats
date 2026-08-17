# Project Status

> Session-agnostic source of truth. Updated by agents via the `session-continuity` skill. Commit and push this file so every new Cursor chat starts with current context.

**Last updated:** 2026-08-17  
**Updated by:** ribgg.ipynb static agent/map/weapon catalog cells

---

## Aim

Build a web app for Valorant esports stats covering Regionals, Masters, Champions, and lower leagues — data pipeline (Dagster + dbt + Docker) feeding visualizations (Gradio or TypeScript).

## Current focus

- Continue data exploration / ingestion from rib.gg and related APIs (`ribgg.ipynb`)
- Static Agents / Maps / Weapons catalog now pulled in the notebook via valorant-api.com (rib.gg has no catalog)
- Advance remaining dimension tables after Matches

## Status

| Area | State | Notes |
|------|--------|-------|
| Overall | In progress | Pipeline + schema design underway; frontend not started |
| Data sources | In progress | rib.gg match/RSC routes work; no agent/map/weapon catalog; valorant-api.com used for static game data |
| Dim tables | Partial | Matches done; Agents/Maps/Weapons catalog explored; Events, Players, Teams, Economy, Date pending |
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
- [x] `ribgg.ipynb` cells for agents (abilities), maps (coords/callouts), guns (fire rate/accuracy) via valorant-api.com after rib.gg catalog 404s

## Next up

- [ ] Finish remaining dim tables (Events, Players, Teams, Economy, Date; static Agents/Maps/Weapons as needed)
- [ ] Implement fact tables (match overall, half-round, player performance, PvP kills, economy)
- [ ] Wire Dagster + dbt for load/test
- [ ] Build viz: player profile, match report, team comparison, map dashboard

## Open questions / blockers

- rib.gg has no static agent/map/weapon catalog; VLR also lacks abilities / map coords / gun stats
- Weapons data may still be incomplete for *round-level* rib match use (catalog is separate)
- Choose Gradio vs TypeScript for the web UI when ready

## Session log

| Date | Session summary |
|------|-----------------|
| 2026-08-17 | Created `PROJECT_STATUS.md` and session-continuity skill/rule so future chats load aim + status automatically |
| 2026-08-17 | Added `ENGINEERING_STANDARDS.md` + always-on rule/skill for concise simple English and service coding standards |
| 2026-08-17 | Extended standards: process logs for Dagster, parallelization default, optimize for Supabase analytics |
| 2026-08-17 | Added `ribgg.ipynb` static catalog cells; rib.gg 404s, so agents/maps/guns come from valorant-api.com |
