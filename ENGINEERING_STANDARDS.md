# Engineering Standards

> Always-on reference for this repo. Every Cursor chat must follow this file when writing or changing code. Prefer simple technical English. Keep chat replies short.

**Last updated:** 2026-08-17

**Pipeline goal:** Fast, scalable extract → transform → load → dbt into **Supabase**, so analytics read from the warehouse. Prefer **parallel work** and **optimized functions** everywhere they help.

---

## 1. Chat and language (every session)

### Language
- Use **simple technical English**. Short words. Clear meaning.
- Avoid jargon stacks, filler, and long preambles.
- Prefer: “Extract teams from rib.gg into parquet.” over “We will proceed to orchestrate an ingestion workflow…”

### Reply style
- Be **concise**. Lead with the answer or change.
- Use short bullets for steps or decisions.
- Do not restate the whole task unless needed.
- Do not dump large unrelated explanations.
- When code is the deliverable, show only what matters; link to files instead of pasting walls of code.

### Before writing code in chat
1. Read `PROJECT_STATUS.md` (aim / focus).
2. Read the matching section of **this file** for the service you touch (extraction, Dagster, dbt, or shared Python).
3. Match existing folder layout and naming in the repo.

---

## 2. Universal rules (all code)

### Every function needs a reason
- Every new function, method, asset, model, macro, or class **must** say **why it exists** (not only what it does).
- Put the reason in a short docstring (or SQL header comment for dbt).
- Private helpers (`_name`) still need one line: why they exist.

**Good**
```python
def landing_dir_for(repo_root: Path, entity: str, run_date: date | None = None) -> Path:
    """Build partition path so each extract run lands under data/<source>/<entity>/dt=YYYY-MM-DD."""
```

**Bad**
```python
def landing_dir_for(repo_root, entity, run_date=None):
    # makes a path
```

### Naming
| Kind | Style | Example |
|------|--------|---------|
| Modules / files | `snake_case.py` | `ribs_connector.py` |
| Packages / dirs | `snake_case` | `api_connectors/` |
| Functions / methods | `snake_case`, verb-first | `fetch_all_pages`, `normalize_record` |
| Classes | `PascalCase`, noun | `RibsConnector`, `RibExtractPipeline` |
| Constants | `UPPER_SNAKE` | `BASE_URL`, `JSON_SCALAR_KEYS` |
| Env vars | `UPPER_SNAKE` | `SUPABASE_DB_HOST`, `RIB_RUN_DATE` |
| dbt models | `snake_case` with layer prefix | `dim_teams`, `fact_match_economy`, `stg_rib_series` |
| Dagster assets / jobs | `snake_case` | `rib_gg_extract_teams`, `rib_gg_star_schema_job` |

### Function creation
- One clear job per function. If it needs “and”, split it.
- Prefer pure transforms; put I/O (HTTP, DB, filesystem) at edges.
- Use type hints on public functions.
- Raise clear errors; do not swallow exceptions without logging + re-raise or explicit handling.
- Do not add a function “just in case”. Only add what the current task needs, with a stated reason.
- Design for speed: vectorized Polars/SQL where possible; avoid row-by-row Python on large data.

### Class creation
- Use a class when you need shared state or a stable API surface (connector, pipeline, session factory).
- Prefer a module-level function if there is no state.
- Keep `__init__` for wiring (config, clients), not heavy work.
- Public methods: short docstring with **why**.

### Process logging (required at every level)

Goal: any Dagster run log should show **where** work is and **what** failed, without guessing.

- Every process-level function (fetch, extract, normalize, land, load, dbt step) must log:
  1. **Start** — what process is running (include a tag like `[extract_teams]` or `=== STEP asset_name ===`)
  2. **Progress** — useful counts (pages, rows, workers, paths) on long work
  3. **Done** — outcome + key metrics (rows written, path, duration if easy)
  4. **Error** — `logger.exception` / `context.log.exception` with enough context to find the failing call
- Use `logger = logging.getLogger(__name__)` in `src/backend/...`.
- In Dagster assets: `context.log.info` / `.warning` / `.error` / `.exception`. Backend loggers still run inside the same run — keep tags consistent so both layers are searchable.
- Log the **process name**, not vague messages (`"Starting teams fetch from rib.gg..."` not `"working..."`).
- Do not log secrets, tokens, or full credentials. Truncate huge payloads.
- Tiny pure helpers (e.g. `camel_to_snake`) do not need start/done logs; anything that does I/O, multi-step work, or parallel pools **does**.

**Good**
```python
logger.info("[extract_series] Starting parallel series fetch workers=%s...", self.max_workers)
# ... work ...
logger.info("[extract_series] Done rows=%s path=%s", len(rows), path)
```

**Bad**
```python
# silent function; failure only appears as a generic Dagster stack trace
```

### Parallelization (required wherever it helps)

Parallel work is a **default**, not an optional nicety. Build for a fast, scalable pipeline into Supabase.

- Prefer parallel for: paginated HTTP, multi-entity extract, multi-file normalize/load, independent API/scrape items, independent dbt-selectable stages when safe.
- Default tool for I/O-bound work: `concurrent.futures.ThreadPoolExecutor` + `as_completed` (match `ribs_connector` / `vlr_connector`).
- Make `max_workers` configurable (constructor arg or env); log `workers=` at start.
- Log parallel progress (`page x/y`, `done/total`) so Dagster runs show movement.
- Keep thread-safe progress (locks) when shared counters are logged.
- Respect rate limits / retries; parallel must not ignore 429/backoff.
- Do **not** parallelize tiny CPU work where overhead > gain, or steps that must stay strictly ordered (e.g. schema create before load).
- When adding a loop over many independent items, ask: “Can this use a thread pool?” If yes, do it.
- Document why a step stays serial (ordering, single connection, API rule).

### Optimization (fast path to Supabase analytics)

- Batch I/O: paginate with sensible page size; bulk load parquet → Supabase (avoid per-row inserts when bulk exists).
- Prefer Polars for land/transform; push heavy joins/aggregations to **dbt/SQL in Supabase**.
- Land once, reuse partitions (`dt=YYYY-MM-DD`); make restarts cheap (NDJSON/parquet checkpoints where already used).
- Avoid loading full datasets into memory twice; stream or land intermediate files for large extracts.
- Tune workers and page size with env vars; do not hardcode only.
- Target outcome: Dagster jobs finish quickly enough to refresh analytics tables that apps query from Supabase.

### File structure
```
src/backend/
  api_connectors/          # HTTP clients (rib.gg, vlr, gateways)
  database_connectors/     # Supabase / DB clients
  rib_gg/                  # rib.gg normalize + land parquet/ndjson
  vlr/                     # vlr extract / scrape transforms
  sql/                     # dbt project (own .venv)
dagster_orchestration/     # Dagster defs, assets, jobs only
data/<source>/<entity>/dt=YYYY-MM-DD/   # landing zone (gitignored)
```
- Do not put extract logic inside Dagster modules beyond orchestration glue.
- Do not put dbt SQL under `dagster_orchestration/`.
- Notebooks (`*.ipynb`) are for exploration; production paths go under `src/backend/`.

### Code style (Python)
- `from __future__ import annotations` in new modules when useful.
- Module logger: `logger = logging.getLogger(__name__)`.
- No secrets in code or markdown. Use `.env` / `src/config/.env`.
- Prefer `pathlib.Path` over string paths.
- Prefer Polars for tabular landings in extract code (match existing `rib_gg/extract.py`).
- Keep imports ordered: stdlib → third party → local.
- Match surrounding file style when editing.

### Comments
- Prefer why-docstrings over narrating every line.
- Comment only non-obvious constraints (rate limits, API quirks, partition rules).

---

## 3. Data extraction

**Owns:** API/scrape fetch, normalize, land files under `data/`.

### Layout
| Piece | Location |
|-------|----------|
| HTTP / API client | `src/backend/api_connectors/<source>_connector.py` |
| Transform + land | `src/backend/<source>/extract.py` (e.g. `rib_gg`, `vlr`) |
| Landing files | `data/<source>/<entity>/dt=YYYY-MM-DD/` |

### Standards
- Connectors: retries, timeouts, pagination, **parallel page/item fetch**, clear start/progress/done logs. No business transforms beyond parse JSON.
- Extract modules: camelCase → snake_case; nest complex objects as JSON strings when exploding would explode schema.
- Partition by `dt=YYYY-MM-DD`. Respect `RIB_RUN_DATE` / source-equivalent env when set.
- Idempotent landings where practical (same run date overwrites or replaces cleanly).
- Do not commit large parquet/ndjson dumps (already gitignored under `data/`).
- Rate limits / politeness: use existing gateway/retry helpers; do not hammer APIs.
- Every public extract/connector function: docstring with **why** + process logs when the function runs a real pipeline step.
- Large multi-record fetches **must** use a worker pool unless a written comment explains why serial is required.

### Naming examples
- `RibsConnector.fetch_resource_pages` — why: page through a list endpoint without loading all into one call site.
- `normalize_record` — why: stable snake_case schema for parquet + dbt.
- `landing_dir_for` — why: consistent partition path for runs.

---

## 4. Dagster

**Owns:** schedule/order of extract → load → dbt. Thin orchestration only.

### Layout
| Piece | Location |
|-------|----------|
| Definitions / assets / jobs | `dagster_orchestration/src/dagster_orchestration/` |
| Run from | `dagster_orchestration/` (see that folder’s README) |

### Standards
- Assets do one stage: probe, extract entity, load table, run dbt select, etc.
- Heavy logic lives in `src/backend/...`. Assets call into those modules.
- Name assets/jobs after pipeline + stage: `rib_gg_extract_teams`, `rib_gg_star_schema_job`.
- At asset entry: log `=== STEP <asset_name>: <short what> ===` so run timelines are scannable.
- Log via `context.log`; on failure use `context.log.exception`. Surface `MetadataValue` (row counts, paths, run date, workers).
- Fail loud on missing required env vars (`_get_required_env_var` pattern).
- Subprocess helpers (dbt CLI) must stream logs and raise on non-zero exit.
- Every asset function docstring: **why this asset exists in the graph** (dependency / stage reason).
- Do not embed SQL model bodies in Dagster Python.
- Prefer assets/jobs that unlock parallel extract of independent entities (teams/events/series) when the graph allows.

### Job design
- One job = one clear pipeline story (e.g. rib.gg star schema; vlr star schema; single dbt smoke job).
- Keep smoke/sample jobs separate from full production jobs.
- End state of production jobs: analytics-ready tables in Supabase for downstream apps.

---

## 5. dbt

**Owns:** SQL models, tests, docs for warehouse tables (Supabase/Postgres).

### Layout
| Piece | Location |
|-------|----------|
| Project | `src/backend/sql/` |
| Models | `models/staging/`, `models/marts/` |
| Own venv | `src/backend/sql/.venv` (Python 3.13; see `src/backend/sql/README.md`) |

### Naming
- Staging: `stg_<source>_<entity>` (views).
- Marts dims: `dim_<entity>` (tables).
- Marts facts: `fact_<grain_or_process>` (tables).
- Columns: `snake_case`. Keys: `<entity>_id` when clear; keep source `id` only if documented.

### Standards
- Each `.sql` model starts with a short header comment: **why this model exists** and grain.
- Use `{{ config(...) }}` only when overriding project defaults.
- Prefer CTEs with clear names (`source_rows`, `cleaned`, `final`).
- No `SELECT *` in marts unless the model is a thin pass-through that is documented.
- Add tests for primary key uniqueness and not-null on keys when a model is real (not dummy scaffold).
- Materialization: staging = view, marts = table (see `dbt_project.yml`).
- Target schema via `DBT_SUPABASE_SCHEMA` (default `valorant`).
- Dummy scaffold models must stay obvious (`dummy_data` + filter) until replaced with real sources — do not pretend they are production.
- Optimize SQL for warehouse reads: filter early, select needed columns, index-friendly join keys (`*_id`).
- Use `DBT_THREADS` for parallel model builds when running dbt from Dagster/CLI.
- Dagster dbt steps must stream CLI output into `context.log` so failures show the failing model fast.

### Example header
```sql
-- dim_teams: one row per team for joins from series/matches facts.
{{ config(materialized='table') }}
```

---

## 6. Checklist before finishing a change

- [ ] Read the service section above that applies
- [ ] New functions/classes/models include a **why** docstring or SQL header
- [ ] Process-level functions log start / progress / done / error (Dagster-visible)
- [ ] Independent multi-item I/O uses parallel workers unless serial is justified in a comment
- [ ] Hot paths are optimized (batch I/O, Polars/SQL, no needless row loops)
- [ ] Names match the tables in this file
- [ ] Files sit in the correct folder
- [ ] No secrets committed
- [ ] `PROJECT_STATUS.md` updated if focus/done/next changed
- [ ] Chat reply stayed short and in simple technical English

---

## 7. Where to look next

| Need | File |
|------|------|
| Aim / current work | `PROJECT_STATUS.md` |
| rib.gg / VLR API notes | `Valorant API.md` |
| dbt env commands | `src/backend/sql/README.md` |
| Dagster run commands | `dagster_orchestration/README.md` |
