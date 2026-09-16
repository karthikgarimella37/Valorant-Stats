# Later work

> Durable list of work we will do **after** facts are in `vlr`. Not current focus.  
> Daily nudge: Cursor rule `.cursor/rules/later-work.mdc` + `PROJECT_STATUS.md` **Later nudge date**.

Do **not** start these unless the user asks.

---

## 1. Modify `dim_economy`

Current seed is coarse buy bands (`pistol` / `eco` / `semi` / `force` / `full`).  
Revisit grain and bands so round loadout credits join cleanly (`fact_round_economy_detail.economy_code`).

---

## 2. Incremental pipelines + watermark ops table

After historical matches finish:

1. Catch-up: events from the last few days; confirm every listed match has detail.
2. Then watermark so the next run continues from that point.

New table (suggested name `vlr.ops_pipeline_watermarks`):

| Column | Why |
|--------|-----|
| `pipeline_name` | Job / extract name (`vlr_events`, `vlr_matches`, `vlr_facts`, …) |
| `table_name` | Warehouse table that run updated |
| `source_name` | `vlrggapi` / `fandom` / `liquipedia` / jsonl |
| `last_source_at` | Newest event/match timestamp consumed from the source |
| `last_success_at` | When this pipeline last completed successfully |
| `last_attempt_at` | When this pipeline last ran (success or fail) |
| `row_count` | Rows upserted on last success |
| `dagster_run_id` | Dagster run id |
| `dagster_job_name` | Job name |
| `status` | `success` / `failed` / `partial` |
| `error_text` | Short fail reason |
| `row_number` / `insert_date` / `update_date` | Same as other `vlr` tables |

**Rule:** every pipeline gets an extra **watermark update step that always runs** after the load (success or fail).

**Logs:** start / progress / done / error on **every** pipeline step (already required in `ENGINEERING_STANDARDS.md`; tighten when this lands).

Existing JSON cursor `data/vlr/watermarks.json` can seed the first warehouse rows.

---

## 3. Knowledge-graph column agent (website chatbot)

After some fact tables are populated:

- Agent that writes a description for every **table** and **column** in `vlr`.
- Those descriptions become context for a knowledge graph.
- An MCP server reads the graph to answer chatbot questions on the analytics website.

Do this only when facts exist so descriptions match real grains and metrics.
