"""Why: small 4-step VLR DAGs — watermark, in-memory extract, merge, watermark write."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from dagster import AssetExecutionContext, MetadataValue, asset, define_asset_job

from backend.vlr.dim.historical import apply_events_schema
from backend.vlr.dim.matches import apply_matches_schema
from backend.vlr.dim.players import apply_players_schema
from backend.vlr.dim.teams import apply_teams_schema
from backend.vlr.fact.tables import FACT_SPECS
from backend.vlr.ops.extract import (
    extract_events_since,
    extract_facts_since,
    extract_matches_since,
    extract_players_since,
    extract_teams_since,
    merge_events,
    merge_facts,
    merge_matches,
    merge_players,
    merge_teams,
)
from backend.vlr.ops.run import (
    clear_stash,
    max_source_now_if_live,
    parse_since,
    step_check_watermark,
    step_update_watermark,
)
from backend.vlr.ops.specs import FACTS_LEAD_TABLE
from backend.vlr.ops.watermarks import ensure_watermarks_table

REPO_ROOT = Path(__file__).resolve().parents[3]


def _parse_dt(raw: Any) -> datetime | None:
    """ISO strings from the previous asset back into aware UTC."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _meta(payload: dict[str, Any]) -> dict[str, Any]:
    """Dagster metadata without dumping in-memory rows into the UI."""
    skip = {"rows", "extra"}
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if key in skip:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value
        elif isinstance(value, dict):
            out[key] = MetadataValue.json(value)
        elif isinstance(value, list):
            out[f"{key}_n"] = len(value)
    if "row_count" in payload:
        out["row_count"] = payload.get("row_count")
    return out


def _extract_payload(context: AssetExecutionContext, wm: dict[str, Any], extract_fn: Callable) -> dict[str, Any]:
    """Step 2: pull since watermark into memory. Volume must stay small."""
    since = parse_since(wm)
    context.log.info(
        "=== STEP %s: extract since=%s bootstrap=%s overlap_hours=%s note=%s ===",
        context.asset_key.to_user_string(),
        since.isoformat(),
        wm.get("bootstrap"),
        wm.get("overlap_hours"),
        wm.get("lookback_note"),
    )
    result = extract_fn(since, run_id=context.run_id)
    max_source_at = max_source_now_if_live(result.max_source_at, result.has_live)
    payload = {
        **wm,
        "rows": result.rows,
        "row_count": result.row_count,
        "has_live": result.has_live,
        "max_source_at": max_source_at.isoformat(),
        "extra": result.extra,
    }
    context.add_output_metadata(_meta(payload))
    context.log.info(
        "extract done pipeline=%s rows=%s has_live=%s max_source_at=%s extra_keys=%s",
        wm.get("pipeline_name"),
        result.row_count,
        result.has_live,
        max_source_at.isoformat(),
        list(result.extra),
    )
    return payload


def _merge_payload(context: AssetExecutionContext, extracted: dict[str, Any], merge_fn: Callable) -> dict[str, Any]:
    """Step 3: upsert in-memory rows. On failure write status=failed and do not advance the cursor."""
    rows = extracted.get("rows") or []
    context.log.info(
        "=== STEP %s: merge table=%s rows=%s ===",
        context.asset_key.to_user_string(),
        extracted.get("table_name"),
        len(rows),
    )
    try:
        loaded = merge_fn(rows)
    except Exception as exc:
        context.log.exception(
            "merge failed pipeline=%s table=%s",
            extracted.get("pipeline_name"),
            extracted.get("table_name"),
        )
        step_update_watermark(
            pipeline_name=str(extracted["pipeline_name"]),
            table_name=str(extracted["table_name"]),
            last_source_at=None,
            row_count=None,
            dagster_run_id=context.run_id,
            dagster_job_name=context.job_name,
            status="failed",
            error_text=f"{type(exc).__name__}: {exc}",
        )
        raise
    if isinstance(loaded, dict):
        fact_counts = {spec.table: int(loaded.get(spec.table, 0)) for spec in FACT_SPECS}
        row_count = sum(fact_counts.values())
        counts = fact_counts
    else:
        row_count = int(loaded)
        counts = {str(extracted["table_name"]): row_count}
    payload = {
        **{key: value for key, value in extracted.items() if key != "rows"},
        "row_count": row_count,
        "counts": counts,
        "merge_status": "success",
    }
    context.add_output_metadata(_meta(payload))
    context.log.info(
        "merge done pipeline=%s upserted=%s counts=%s",
        extracted.get("pipeline_name"),
        row_count,
        counts,
    )
    return payload


def _write_payload(context: AssetExecutionContext, merged: dict[str, Any]) -> dict[str, Any]:
    """Step 4: always write the watermark after a successful merge."""
    context.log.info(
        "=== STEP %s: update watermark pipeline=%s table=%s row_count=%s ===",
        context.asset_key.to_user_string(),
        merged.get("pipeline_name"),
        merged.get("table_name"),
        merged.get("row_count"),
    )
    last_source_at = _parse_dt(merged.get("max_source_at"))
    counts = merged.get("counts") if merged.get("pipeline_name") == "vlr_facts" else None
    out = step_update_watermark(
        pipeline_name=str(merged["pipeline_name"]),
        table_name=str(merged["table_name"]),
        last_source_at=last_source_at,
        row_count=merged.get("row_count"),
        dagster_run_id=context.run_id,
        dagster_job_name=context.job_name,
        status="success",
        counts=counts,
    )
    context.add_output_metadata(_meta(out))
    return out


def _run_one(
    context: AssetExecutionContext,
    *,
    pipeline_name: str,
    table_name: str,
    schema_fn: Callable,
    extract_fn: Callable,
    merge_fn: Callable,
) -> dict[str, Any]:
    """Run the four steps in order inside vlr_daily so events finish before matches."""
    context.log.info("[inc] daily pipeline start %s table=%s", pipeline_name, table_name)
    schema_fn(REPO_ROOT)
    wm = step_check_watermark(pipeline_name, table_name)
    extracted = _extract_payload(context, wm, extract_fn)
    merged = _merge_payload(context, extracted, merge_fn)
    written = _write_payload(context, merged)
    context.log.info("[inc] daily pipeline done %s %s", pipeline_name, written)
    return written


@asset(group_name="vlr_inc")
def ops_watermarks_schema(context: AssetExecutionContext) -> str:
    """Create vlr.ops_pipeline_watermarks and seed one row per known table."""
    context.log.info("=== STEP ops_watermarks_schema: ensure vlr.ops_pipeline_watermarks ===")
    path = ensure_watermarks_table(REPO_ROOT)
    context.add_output_metadata({"sql_path": MetadataValue.path(str(path))})
    context.log.info("watermark table ready path=%s", path)
    return str(path)


@asset(group_name="vlr_inc", deps=[ops_watermarks_schema])
def vlr_events_wm_read(context: AssetExecutionContext) -> dict[str, Any]:
    """Step 1 events: last_source_at minus 1 hour (whole day for date-only event dates)."""
    apply_events_schema(REPO_ROOT)
    payload = step_check_watermark("vlr_events", "dim_events")
    context.add_output_metadata(_meta(payload))
    return payload


@asset(group_name="vlr_inc")
def vlr_events_extract(context: AssetExecutionContext, vlr_events_wm_read: dict[str, Any]) -> dict[str, Any]:
    """Step 2 events: live+upcoming always, completed until older than since, keep rows in memory."""
    return _extract_payload(context, vlr_events_wm_read, extract_events_since)


@asset(group_name="vlr_inc")
def vlr_events_merge(context: AssetExecutionContext, vlr_events_extract: dict[str, Any]) -> dict[str, Any]:
    """Step 3 events: upsert vlr.dim_events from the in-memory extract."""
    return _merge_payload(context, vlr_events_extract, merge_events)


@asset(group_name="vlr_inc")
def vlr_events_wm_write(context: AssetExecutionContext, vlr_events_merge: dict[str, Any]) -> dict[str, Any]:
    """Step 4 events: advance last_source_at only after a successful merge."""
    return _write_payload(context, vlr_events_merge)


@asset(group_name="vlr_inc", deps=[ops_watermarks_schema])
def vlr_matches_wm_read(context: AssetExecutionContext) -> dict[str, Any]:
    """Step 1 matches: same timestamptz clock; date-only match_date keeps the whole since day."""
    apply_matches_schema(REPO_ROOT)
    payload = step_check_watermark("vlr_matches", "dim_matches")
    context.add_output_metadata(_meta(payload))
    return payload


@asset(group_name="vlr_inc")
def vlr_matches_extract(context: AssetExecutionContext, vlr_matches_wm_read: dict[str, Any]) -> dict[str, Any]:
    """Step 2 matches: list recent/live events, fetch details, keep them in memory for facts."""
    return _extract_payload(context, vlr_matches_wm_read, extract_matches_since)


@asset(group_name="vlr_inc")
def vlr_matches_merge(context: AssetExecutionContext, vlr_matches_extract: dict[str, Any]) -> dict[str, Any]:
    """Step 3 matches: upsert vlr.dim_matches from the in-memory extract."""
    return _merge_payload(context, vlr_matches_extract, merge_matches)


@asset(group_name="vlr_inc")
def vlr_matches_wm_write(context: AssetExecutionContext, vlr_matches_merge: dict[str, Any]) -> dict[str, Any]:
    """Step 4 matches: write last_source_at (now if any live series)."""
    return _write_payload(context, vlr_matches_merge)


@asset(group_name="vlr_inc", deps=[ops_watermarks_schema])
def vlr_teams_wm_read(context: AssetExecutionContext) -> dict[str, Any]:
    """Step 1 teams: cursor for dim_teams; overlap 1 hour on last_source_at."""
    apply_teams_schema(REPO_ROOT)
    payload = step_check_watermark("vlr_teams", "dim_teams")
    context.add_output_metadata(_meta(payload))
    return payload


@asset(group_name="vlr_inc")
def vlr_teams_extract(context: AssetExecutionContext, vlr_teams_wm_read: dict[str, Any]) -> dict[str, Any]:
    """Step 2 teams: /v2/team for ids on the matches just pulled (or warehouse since)."""
    return _extract_payload(context, vlr_teams_wm_read, extract_teams_since)


@asset(group_name="vlr_inc")
def vlr_teams_merge(context: AssetExecutionContext, vlr_teams_extract: dict[str, Any]) -> dict[str, Any]:
    """Step 3 teams: upsert vlr.dim_teams from in-memory profiles."""
    return _merge_payload(context, vlr_teams_extract, merge_teams)


@asset(group_name="vlr_inc")
def vlr_teams_wm_write(context: AssetExecutionContext, vlr_teams_merge: dict[str, Any]) -> dict[str, Any]:
    """Step 4 teams: persist last_source_at after merge."""
    return _write_payload(context, vlr_teams_merge)


@asset(group_name="vlr_inc", deps=[ops_watermarks_schema])
def vlr_players_wm_read(context: AssetExecutionContext) -> dict[str, Any]:
    """Step 1 players: cursor for dim_players; overlap 1 hour."""
    apply_players_schema(REPO_ROOT)
    payload = step_check_watermark("vlr_players", "dim_players")
    context.add_output_metadata(_meta(payload))
    return payload


@asset(group_name="vlr_inc")
def vlr_players_extract(context: AssetExecutionContext, vlr_players_wm_read: dict[str, Any]) -> dict[str, Any]:
    """Step 2 players: /v2/player for roster ids from the teams just pulled."""
    return _extract_payload(context, vlr_players_wm_read, extract_players_since)


@asset(group_name="vlr_inc")
def vlr_players_merge(context: AssetExecutionContext, vlr_players_extract: dict[str, Any]) -> dict[str, Any]:
    """Step 3 players: upsert vlr.dim_players from in-memory profiles."""
    return _merge_payload(context, vlr_players_extract, merge_players)


@asset(group_name="vlr_inc")
def vlr_players_wm_write(context: AssetExecutionContext, vlr_players_merge: dict[str, Any]) -> dict[str, Any]:
    """Step 4 players: persist last_source_at after merge."""
    return _write_payload(context, vlr_players_merge)


@asset(group_name="vlr_inc", deps=[ops_watermarks_schema])
def vlr_facts_wm_read(context: AssetExecutionContext) -> dict[str, Any]:
    """Step 1 facts: one cursor (lead table fact_match_overall_stats) shared across all vlr fact tables."""
    context.log.info("[inc] skip facts DDL on incremental; vlr.fact_* must already exist")
    payload = step_check_watermark("vlr_facts", FACTS_LEAD_TABLE)
    context.add_output_metadata(_meta(payload))
    return payload


@asset(group_name="vlr_inc")
def vlr_facts_extract(context: AssetExecutionContext, vlr_facts_wm_read: dict[str, Any]) -> dict[str, Any]:
    """Step 2 facts: reuse in-memory match details from this run, or re-fetch ids since the cursor."""
    return _extract_payload(context, vlr_facts_wm_read, extract_facts_since)


@asset(group_name="vlr_inc")
def vlr_facts_merge(context: AssetExecutionContext, vlr_facts_extract: dict[str, Any]) -> dict[str, Any]:
    """Step 3 facts: parse in memory and upsert every vlr.fact_* table."""
    return _merge_payload(context, vlr_facts_extract, merge_facts)


@asset(group_name="vlr_inc")
def vlr_facts_wm_write(context: AssetExecutionContext, vlr_facts_merge: dict[str, Any]) -> dict[str, Any]:
    """Step 4 facts: write the same last_source_at onto every vlr fact watermark row."""
    out = _write_payload(context, vlr_facts_merge)
    clear_stash(context.run_id)
    return out


@asset(group_name="vlr_inc", deps=[ops_watermarks_schema])
def vlr_daily_run(context: AssetExecutionContext) -> dict[str, Any]:
    """Daily chain in one process: events → matches → teams → players → facts (stash match rows for facts)."""
    context.log.info("=== STEP vlr_daily_run: events → matches → teams → players → facts ===")
    results = {
        "vlr_events": _run_one(
            context,
            pipeline_name="vlr_events",
            table_name="dim_events",
            schema_fn=apply_events_schema,
            extract_fn=extract_events_since,
            merge_fn=merge_events,
        ),
        "vlr_matches": _run_one(
            context,
            pipeline_name="vlr_matches",
            table_name="dim_matches",
            schema_fn=apply_matches_schema,
            extract_fn=extract_matches_since,
            merge_fn=merge_matches,
        ),
        "vlr_teams": _run_one(
            context,
            pipeline_name="vlr_teams",
            table_name="dim_teams",
            schema_fn=apply_teams_schema,
            extract_fn=extract_teams_since,
            merge_fn=merge_teams,
        ),
        "vlr_players": _run_one(
            context,
            pipeline_name="vlr_players",
            table_name="dim_players",
            schema_fn=apply_players_schema,
            extract_fn=extract_players_since,
            merge_fn=merge_players,
        ),
        "vlr_facts": _run_one(
            context,
            pipeline_name="vlr_facts",
            table_name=FACTS_LEAD_TABLE,
            schema_fn=apply_facts_schema,
            extract_fn=extract_facts_since,
            merge_fn=merge_facts,
        ),
    }
    clear_stash(context.run_id)
    context.add_output_metadata({key: MetadataValue.json(value) for key, value in results.items()})
    context.log.info("=== STEP vlr_daily_run done pipelines=%s ===", list(results))
    return results


VLR_INC_ASSETS = [
    ops_watermarks_schema,
    vlr_events_wm_read,
    vlr_events_extract,
    vlr_events_merge,
    vlr_events_wm_write,
    vlr_matches_wm_read,
    vlr_matches_extract,
    vlr_matches_merge,
    vlr_matches_wm_write,
    vlr_teams_wm_read,
    vlr_teams_extract,
    vlr_teams_merge,
    vlr_teams_wm_write,
    vlr_players_wm_read,
    vlr_players_extract,
    vlr_players_merge,
    vlr_players_wm_write,
    vlr_facts_wm_read,
    vlr_facts_extract,
    vlr_facts_merge,
    vlr_facts_wm_write,
    vlr_daily_run,
]

vlr_events_inc = define_asset_job(
    "vlr_events",
    selection=[ops_watermarks_schema, vlr_events_wm_read, vlr_events_extract, vlr_events_merge, vlr_events_wm_write],
)
vlr_matches_inc = define_asset_job(
    "vlr_matches",
    selection=[ops_watermarks_schema, vlr_matches_wm_read, vlr_matches_extract, vlr_matches_merge, vlr_matches_wm_write],
)
vlr_teams_inc = define_asset_job(
    "vlr_teams",
    selection=[ops_watermarks_schema, vlr_teams_wm_read, vlr_teams_extract, vlr_teams_merge, vlr_teams_wm_write],
)
vlr_players_inc = define_asset_job(
    "vlr_players",
    selection=[ops_watermarks_schema, vlr_players_wm_read, vlr_players_extract, vlr_players_merge, vlr_players_wm_write],
)
vlr_facts_inc = define_asset_job(
    "vlr_facts",
    selection=[ops_watermarks_schema, vlr_facts_wm_read, vlr_facts_extract, vlr_facts_merge, vlr_facts_wm_write],
)
vlr_daily = define_asset_job(
    "vlr_daily",
    selection=[ops_watermarks_schema, vlr_daily_run],
)

VLR_INC_JOBS = [
    vlr_events_inc,
    vlr_matches_inc,
    vlr_teams_inc,
    vlr_players_inc,
    vlr_facts_inc,
    vlr_daily,
]
