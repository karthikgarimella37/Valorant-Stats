# Project Status

> Session-agnostic source of truth. Updated by agents via the `session-continuity` skill. Commit and push this file so every new Cursor chat starts with current context.

**Last updated:** 2026-09-15  
**Updated by:** fact composite unique keys (performance load frozen)  
**Later nudge date:** 2026-09-15

---

## Aim

Build a web app for Valorant esports stats covering Regionals, Masters, Champions, and lower leagues — data pipeline (Dagster + dbt + Docker) feeding visualizations (Gradio or TypeScript).

## Current focus

- Fact tables: composite unique keys (not concat `fact_key`). `fact_player_match_performance` is still loading — do not rematerialize `vlr_facts` or ALTER that table.

## Status

| Area | State | Notes |
|------|--------|-------|
| Overall | In progress | Dims catalog done. Match details still scraping. Facts coded, not loaded |
| Data sources | Validated | Self-hosted vlrggapi `/v2` via AWS IP rotator overlay |
| Orchestration | In progress | Job `vlr_facts` added (extract jsonl → load). Not executed |
| Dim tables | **Done** (catalog). Teams/players jsonl exist; rematerialize later if needed |
| Fact tables | Load in progress | Performance upserts on `fact_key`. Other tables: composite unique on next extract/load |
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
- [x] Fact unique keys: composite grain columns; overall uses `vlr_player_id` (join from landings)

## Next up

- [ ] Discuss fact grains; then run `vlr_facts` when the user says so
- [ ] Let `vlr_matches` finish; upsert `vlr.dim_matches`; refetch empty-detail 429 rows
- [ ] Optional: rematerialize `vlr_teams` / `vlr_players` from existing jsonl
- [ ] Incremental watermarks — see `LATER.md` (not now)
- [ ] Rewrite `dim_economy` — see `LATER.md` (not now)
- [ ] KG column-description agent — see `LATER.md` (after facts have rows)
- [ ] dbt view `fact_match_half_round_stats`
- [ ] rib overlay: `fact_player_vs_player_kills`
- [ ] Build viz

## Open questions / blockers

- **Do not run** `vlr_facts` until discussed
- Keep `docker compose up -d --build vlrggapi` running before `vlr_events` / `vlr_matches`
- Match details still incomplete in `matches.jsonl` (~3.5% when last noted)
- Scoreboard facts use `player_name` (no VLR player id on the map scoreboard)
- `round_economy` is usually empty until economy-tab scrape is on the landing
- Round `win_method_code` is null on current `/v2` rounds
- Series 2K/1vX only attach to **map 1** (VLR does not split them per map)

## Session log

| Date | Session summary |
|------|-----------------|
| 2026-09-15 | dim_weapons Fandom catalog |
| 2026-09-15 | Dims marked done. `LATER.md` + daily nudge. Fact backend (`vlr_facts`) coded, not run |
