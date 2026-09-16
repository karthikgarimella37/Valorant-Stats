# Project Status

> Session-agnostic source of truth. Updated by agents via the `session-continuity` skill. Commit and push this file so every new Cursor chat starts with current context.

**Last updated:** 2026-09-16  
**Updated by:** fact composite keys + parallel load + post-load migrate script  
**Later nudge date:** 2026-09-16

---

## Aim

Build a web app for Valorant esports stats covering Regionals, Masters, Champions, and lower leagues — data pipeline (Dagster + dbt + Docker) feeding visualizations (Gradio or TypeScript).

## Current focus

- Fact tables: future extract/load uses composite unique keys. Current concat load is finishing; adhoc `migrate_concat_keys --wait` converts warehouse uniques after it.

## Status

| Area | State | Notes |
|------|--------|-------|
| Overall | In progress | Dims catalog done. Match details still scraping. Facts loading |
| Data sources | Validated | Self-hosted vlrggapi `/v2` via AWS IP rotator overlay |
| Orchestration | In progress | Job `vlr_facts` (extract jsonl → parallel load on composite unique) |
| Dim tables | **Done** (catalog). Teams/players jsonl exist; rematerialize later if needed |
| Fact tables | Load in progress | Live run still on concat `fact_key`. Next runs + migrate script use composite unique |
| Frontend / viz | Not started | Graphs in `DATA_MODEL.md` |
| Deferred | Documented | `LATER.md` (economy dim, watermarks, KG agent) |

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

## Next up

- [ ] Let current `facts_load` finish; migrate script (`--wait`) drops `fact_key` unique
- [ ] Let `vlr_matches` finish; upsert `vlr.dim_matches`; refetch empty-detail 429 rows
- [ ] Optional: rematerialize `vlr_teams` / `vlr_players` from existing jsonl
- [ ] Incremental watermarks — see `LATER.md` (not now)
- [ ] Rewrite `dim_economy` — see `LATER.md` (not now)
- [ ] KG column-description agent — see `LATER.md` (after facts have rows)
- [ ] dbt view `fact_match_half_round_stats`
- [ ] rib overlay: `fact_player_vs_player_kills`
- [ ] Build viz

## Open questions / blockers

- Keep `docker compose up -d --build vlrggapi` running before `vlr_events` / `vlr_matches`
- Match details still incomplete in `matches.jsonl` (~3.5% when last noted)
- Map scoreboard has no player id; `vlr_player_id` is resolved from teams/players/events jsonl
- `round_economy` is usually empty until economy-tab scrape is on the landing
- Round `win_method_code` is null on current `/v2` rounds
- Series 2K/1vX only attach to **map 1** (VLR does not split them per map)

## Session log

| Date | Session summary |
|------|-----------------|
| 2026-09-15 | dim_weapons Fandom catalog |
| 2026-09-15 | Dims marked done. `LATER.md` + daily nudge. Fact backend (`vlr_facts`) coded, not run |
| 2026-09-15 | Fact unique keys → composite (not concat). Performance table left on `fact_key` while its load runs |
| 2026-09-16 | Future facts load = composite unique + parallel tables. Adhoc migrate waits for concat load then swaps keys |
