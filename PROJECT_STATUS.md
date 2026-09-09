# Project Status

> Session-agnostic source of truth. Updated by agents via the `session-continuity` skill. Commit and push this file so every new Cursor chat starts with current context.

**Last updated:** 2026-09-08  
**Updated by:** Added `vlr.dim_date` seed job (`vlr_date`); matches extract still running

---

## Aim

Build a web app for Valorant esports stats covering Regionals, Masters, Champions, and lower leagues — data pipeline (Dagster + dbt + Docker) feeding visualizations (Gradio or TypeScript).

## Current focus

- Let `vlr_matches` keep running
- Seed `vlr.dim_date` via job `vlr_date` (no vlr.gg)
- Next static seeds: `dim_vct_regions`, `dim_regions`, `dim_economy`, agents/maps/weapons

## Status

| Area | State | Notes |
|------|--------|-------|
| Overall | In progress | Events done. Match lists done. Match details still scraping |
| Data sources | Validated | Self-hosted vlrggapi `/v2` via AWS IP rotator overlay |
| Orchestration | In progress | Jobs `vlr_events`, `vlr_matches` |
| Dim tables | In progress | Events landed; matches landing; `dim_date` seed job ready |
| Fact tables | Blocked on matches | Parse `matches.jsonl` after details finish |
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
- [x] Historical events: `extract_events` / `load_events` / job `vlr_events`
- [x] `vlr.dim_events` DDL is create-if-missing (no DROP); Python ADD/ALTER columns
- [x] Single landing file `data/vlr/events.jsonl` (2980 events)
- [x] Historical matches: `extract_matches` / `load_matches` / job `vlr_matches`
- [x] `data/vlr/matches.jsonl` stores dim row + listing + full match detail for later facts
- [x] Extracts fail unless vlrggapi rotator `Ready endpoints=` > 0
- [x] Project calendar dates: `YYYY/M/D` no pad (example `2026/7/8`)
- [x] `vlr.dim_date` generated calendar (2020–2030) + job `vlr_date`

## Next up

- [x] Seed `vlr.dim_date` (job `vlr_date`, 2020–2030, range-filter columns)
- [ ] Seed remaining static tables: `dim_vct_regions`, `dim_regions`, `dim_economy`, `dim_agents`, `dim_maps`, `dim_weapons`
- [ ] Optional no-API parse: unique teams/players from `events.jsonl` `teams_json` (28k team rows, player flags)
- [ ] Let `vlr_matches` finish; then upsert `vlr.dim_matches` and refetch empty-detail 429 rows
- [ ] Parse facts from `matches.jsonl` (overall / rounds / performance / economy)
- [ ] `/v2/team` + `/v2/rankings` enrich after matches is done (do not compete for 429 budget now)
- [ ] Incremental extract via `vlr_watermarks` after historical
- [ ] Fork/patch vlrggapi: Attack/Defend, event_id on match, labeled performance
- [ ] rib overlay: replay kills when `vlr_match_id` can join
- [ ] Build viz

## Open questions / blockers

- Keep `docker compose up -d --build vlrggapi` running before `vlr_events` / `vlr_matches`
- Matches list phase: **2980/2980** events in `event_matches.jsonl` (**107,429** series)
- Match details (~21:34): **~3,800 / 107,429** in `matches.jsonl` (~3.5%); ~164 list-only after 429
- Matches defaults: 8 event-list workers, 8 detail workers (env-tunable)
- Rotator: `VLR_USE_IP_ROTATOR=1` + keys in `src/config/.env`. Compose defaults `VLR_IP_ROTATOR_REGIONS=us-east-1`
- **API gaps:** Attack/Defend player stats; labeled 2K/1vX/ECON; prize points/note; match `event_id` on detail
- rib overlay join: fuzzy (event name + team names + date)

## Session log

| Date | Session summary |
|------|-----------------|
| 2026-08-17 | Created `PROJECT_STATUS.md` and session-continuity skill/rule |
| 2026-08-17 | Added `ENGINEERING_STANDARDS.md` + always-on rule/skill |
| 2026-08-18 | Added `DATA_MODEL.md` snowflake contract |
| 2026-08-27 | VLR-primary + rib overlay; vlrggapi extract; facts + half-round view |
| 2026-08-29 | Probed match 742485; JSON + watermarks; economy bank scrape; smarter auto-commit |
| 2026-09-04 | Split VCT circuits from local ranking codes |
| 2026-09-07 | Historical events Dagster job: schema, per-id JSON, upsert `vlr.dim_events` |
| 2026-09-07 | Events jsonl + date format + schema ensure + env/rotator (no extract run) |
| 2026-09-07 | Documented Dagster as the run path for historical events |
| 2026-09-07 | Extract failed: no vlrggapi on :3001; started `docker compose up -d vlrggapi` |
| 2026-09-07 | Catalog 503: serial pages + long backoff on 502/503 |
| 2026-09-07 | Dropped AWS IP rotator; official vlrggapi + serial scrape (free) |
| 2026-09-08 | Matches pipeline + short names (`vlr_events`, `vlr_matches`); require AWS rotator |
| 2026-09-08 | Match lists complete; details ~3.5% + 429s. Next parallel: static seed dims |
| 2026-09-08 | `vlr.dim_date` seed job `vlr_date` with year/quarter/month/week range columns |
