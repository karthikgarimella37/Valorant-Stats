# Later work

> Durable list of work we will do **after** the incremental VLR pipelines. Not current focus.  
> Daily nudge: Cursor rule `.cursor/rules/later-work.mdc` + `PROJECT_STATUS.md` **Later nudge date**.

Do **not** start these unless the user asks.

---

## 1. Modify `dim_economy`

Current seed is coarse buy bands (`pistol` / `eco` / `semi` / `force` / `full`).  
Revisit grain and bands so round loadout credits join cleanly (`fact_round_economy_detail.economy_code`).

---

## 2. Close the VLR load (small, no re-scrape)

History is already in jsonl / warehouse. Do **not** scrape every match again.

1. Confirm `dim_matches` / `dim_teams` / `dim_players` are upserted from the jsonl already on disk.
2. Leftover `-1` grain ids are known anomalies (TBD teams, unmatched scoreboard tags). Leave them until a dedicated cleanup.
3. Optionally refetch only empty-detail / 429 rows (~3.5%), not every match.

Incremental jobs (`vlr_daily`) do not replace this one-shot close-out.

---

## 3. Knowledge-graph column agent (website chatbot)

After some fact tables are populated:

- Agent that writes a description for every **table** and **column** in `vlr`.
- Those descriptions become context for a knowledge graph.
- An MCP server reads the graph to answer chatbot questions on the analytics website.

Do this only when facts exist so descriptions match real grains and metrics.
