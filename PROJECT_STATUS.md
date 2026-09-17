# Project Status

> Session-agnostic source of truth. Updated by agents via the `session-continuity` skill. Commit and push this file so every new Cursor chat starts with current context.

**Last updated:** 2026-09-17  
**Updated by:** rib_facts snapshot table + match 270 run  
**Later nudge date:** 2026-09-17

---

## Aim

Build a web app for Valorant esports stats covering Regionals, Masters, Champions, and lower leagues — data pipeline (Dagster + dbt + Docker) feeding visualizations (Gradio or TypeScript).

## Current focus

- Run **rib_facts** for match 270 so snapshots land in `vlr.fact_rib_replay_snapshot`. Incremental VLR (`vlr_daily`) stays next after that.

## Status

| Area | State | Notes |
|------|--------|-------|
| Overall | In progress | Dims catalog done. Match details still scraping. Facts loading |
| Data sources | Validated | Self-hosted vlrggapi `/v2` via AWS IP rotator overlay |
| Orchestration | In progress | 4-step inc jobs + `vlr_daily`; cursor `vlr.ops_pipeline_watermarks` |
| Dim tables | Catalog done | Daily events/matches/teams/players are incremental upserts |
| Fact tables | Live in `vlr` | Incremental `vlr_facts` parses in-memory match details |
| rib overlay | Running | Snapshots now a warehouse table; first job uses `RIB_MATCH_IDS=270` |
| Frontend / viz | Not started | Graphs in `DATA_MODEL.md` |
| Deferred | Documented | `LATER.md` (economy dim, close VLR load, KG, dbt on live facts) |

## Done

- [x] Repo scaffolding (Dagster, src, notebooks, schemas)
- [x] Session continuity + engineering standards + `LATER.md` daily nudge
- [x] `DATA_MODEL.md` snowflake contract
- [x] Historical events / matches extract jobs; match details still filling
- [x] Dim catalogs: date, regions, economy seed, agents, maps, weapons
- [x] Dim teams/players **code** + `teams.jsonl` / player extract job
- [x] Fact **backend** (DDL + parse + load + job `vlr_facts`)
- [x] Fact unique keys: composite grain columns; `vlr_player_id` from landings
- [x] Fact load parallel across tables (`VLR_FACT_LOAD_WORKERS`, default 8)
- [x] Adhoc `backend.vlr.fact.migrate_concat_keys` (wait for live load, then swap uniques)
- [x] rib overlay backend: rotator connector, JSON land, parse, fuzzy join, DDL, job `rib_facts`
- [x] Incremental VLR DAGs: `vlr.ops_pipeline_watermarks`, 4-step jobs, `vlr_daily`
- [x] `vlr.fact_rib_replay_snapshot` (position ticks go to Supabase, not JSON-only)

## Next up

- [ ] First `vlr_daily` (or `vlr_events`) run against live vlrggapi + Supabase
- [ ] First `rib_facts` run: `RIB_MATCH_IDS=270` then full crawl
- [ ] Close the VLR load (jsonl upsert + leftover `-1` / empty-detail ~3.5%) — `LATER.md`
- [ ] dbt on live `vlr` facts (not dummy `valorant` stubs) — `LATER.md`
- [ ] Rewrite `dim_economy` — `LATER.md`
- [ ] KG column-description agent — `LATER.md`
- [ ] Build viz

## Open questions / blockers

- Keep `docker compose up -d --build vlrggapi` running before incremental VLR jobs
- Match details still incomplete in `matches.jsonl` (~3.5% empty-detail/429) — do not re-scrape all matches
- Map scoreboard has no player id; incremental facts resolve `vlr_player_id` from warehouse dims
- Dummy dbt marts still live in schema `valorant`; live tables are schema `vlr`
- `round_economy` is usually empty until economy-tab scrape is on the landing
- Round `win_method_code` is null on current `/v2` rounds
- Series 2K/1vX only attach to **map 1** (VLR does not split them per map)
- VLR has **team** ATK/DEF halves already (`fact_map_game_results` + `fact_round_results`). Player ATK/DEF K/D is HTML-only (wrapper reads `.mod-both`)
- rib `be-prod.rib.gg` is stale; live routes are `rib.gg` RSC + `/api/matches/{id}/replay-data`
- First rib extract: `VLR_USE_IP_ROTATOR=1` and `RIB_MATCH_IDS` for a smoke test before crawling all events

## Session log

| Date | Session summary |
|------|-----------------|
| 2026-09-15 | dim_weapons Fandom catalog |
| 2026-09-15 | Dims marked done. `LATER.md` + daily nudge. Fact backend (`vlr_facts`) coded, not run |
| 2026-09-15 | Fact unique keys → composite (not concat). Performance table left on `fact_key` while its load runs |
| 2026-09-16 | Future facts load = composite unique + parallel tables. Adhoc migrate waits for concat load then swaps keys |
| 2026-09-16 | Half data already in VLR facts. Next extract = rib roundStats + full replay JSON, fuzzy-join to VLR |
| 2026-09-16 | rib overlay coded: job `rib_facts`, JSON land + parse + batched load, snapshots stay on disk |
| 2026-09-17 | Added `fact_rib_replay_snapshot`; snapshots upsert to Supabase. Running `rib_facts` on match 270 |
| 2026-09-17 | Incremental VLR DAGs: watermark table, 4-step jobs, `vlr_daily` |
| 2026-09-17 | `fact_rib_replay_snapshot` confirmed; rib 429 retries + in-process `rib_facts` logs; rerun match 270 |
