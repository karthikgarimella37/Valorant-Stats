# Project Status

> Session-agnostic source of truth. Updated by agents via the `session-continuity` skill. Commit and push this file so every new Cursor chat starts with current context.

**Last updated:** 2026-08-29  
**Updated by:** Auto-commit messages now describe staged file changes

---

## Aim

Build a web app for Valorant esports stats covering Regionals, Masters, Champions, and lower leagues — data pipeline (Dagster + dbt + Docker) feeding visualizations (Gradio or TypeScript).

## Current focus

- Use `/v2` JSON landings + `data/vlr/watermarks.json` as the extract source of truth
- Remap unlabeled performance keys; patch or fork vlrggapi for Attack/Defend and `event_id`
- Do **not** expand Docker until those gaps are handled in extract

## Status

| Area | State | Notes |
|------|--------|-------|
| Overall | In progress | Live probe of Gen.G vs T1: 29 fields OK, 12 gaps |
| Data sources | Validated | Self-hosted vlrggapi `/v2` is enough for header + All-stats + event + team + player |
| Orchestration | Paused | `vlr_star_schema_job` exists; next is incremental JSON via watermarks, then Dagster |
| Dim tables | Partial | Parquet extract exists; JSON landings started for 742485 / 2776 / 17 / 9196 |
| Fact tables | Partial | All-side overview + rounds + unlabeled advanced; **round bank is on match JSON** |
| Frontend / viz | Not started | Graphs and dashboards listed in `Valorant API.md` |
| Session process | Done | Status + standards markdown; always-on Cursor rules/skills; auto-commit hook |

## Done

- [x] Repo scaffolding (Dagster, src, notebooks, schemas)
- [x] rib.gg endpoint discovery (`rib_discovery_results.json`, notes in `Valorant API.md`)
- [x] Matches dimension marked done
- [x] Session continuity process (`PROJECT_STATUS.md`, skill, rule)
- [x] Engineering standards (`ENGINEERING_STANDARDS.md`, rule, skill)
- [x] `DATA_MODEL.md` snowflake contract
- [x] `docker-compose.yml` + `VlrV2Connector` + parquet extract + half-round dbt view
- [x] Live `/v2` probe vs [Gen.G vs T1 742485](https://www.vlr.gg/742485/gen-g-vs-t1-vct-2026-pacific-stage-2-lr2): event 2776, Gen.G 17, t3xture 9196
- [x] JSON landings: `data/vlr/json/{matches,events,teams,players}/<id>.json` (gitignored)
- [x] Watermark file: `data/vlr/watermarks.json` (`entity_type`, `entity_id`, `last_fetched_at`, `source_url`)
- [x] Probe script: `PYTHONPATH=src python src/backend/vlr/probe_api_coverage.py`
- [x] Unlabeled column remap: `src/backend/vlr/field_maps.py`
- [x] Per-round bank/loadout scrape: `scrape_economy.py` → `maps[].round_economy` (Lotus 18 + Split 24 on 742485)
- [x] Auto-commit subject/body from staged add/update/delete paths (no more fixed "after file change")

## Next up

- [ ] Apply `field_maps` in extract; join `event_id` from `/v2/events/matches` (not match details)
- [ ] Incremental extract: skip ids already in `vlr_watermarks` unless status changed
- [ ] Fork/patch vlrggapi parsers: event_id href, `.side.mod-t` / `.side.mod-ct`, thead labels, transaction date/role, prize points
- [ ] Land `fact_round_economy_detail` from `maps[].round_economy` (bank_credits + loadout_credits)
- [ ] Wire Dagster to JSON snapshots + watermark table (then Compose smoke)
- [ ] rib overlay: replay kills when `vlr_match_id` can join
- [ ] Build viz: player profile, match report, team comparison, map dashboard

## Open questions / blockers

- **API gaps (do not treat as present):** Attack/Defend player stats; labeled 2K/1vX/ECON; prize points/note; event standings tables; match `event_id` / team tag; transaction dates
- **Recoverable without a fork:** remap keys `"1"`–`"13"`; stage from `events/matches.event_series`; staff via `role`; event via `/v2/search`; **round bank via `scrape_economy`**
- `/v2` economy is still the buy-win table only; we fetch `/?game=all&tab=economy` ourselves
- `vlr.orlandomm.net` / public vlrggapi Vercel are down — **self-host** `vlrggapi` (`http://127.0.0.1:3001`)
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
| 2026-08-29 | Probed match 742485 / event 2776 / team 17 / player 9196; JSON landings + watermarks; 12 API gaps documented |
| 2026-08-29 | Scraped VLR economy-tab round bank into `742485.json` (`scrape_economy.py`) |
| 2026-08-29 | Auto-commit hook writes a change-based message from `git diff --cached --name-status` |
