"""Why: one list of pipeline/table/source rows so the watermark table and DAGs stay in sync."""

from __future__ import annotations

from dataclasses import dataclass

from backend.vlr.fact.tables import FACT_SPECS


@dataclass(frozen=True)
class WatermarkSpec:
    """One row in vlr.ops_pipeline_watermarks: which job owns which warehouse table."""

    pipeline_name: str
    table_name: str
    source_name: str
    overlap_hours: float
    lookback_note: str


# last_source_at is timestamptz with seconds. Next run starts at last_source_at minus 1 hour.
_VLR_LOOKBACK = (
    1.0,
    "minus 1 hour from last_source_at (timestamptz to the second); extract from that time onward",
)
# Catalogs have no source event time: full small upsert, watermark is last_success_at only.
_CATALOG = (
    0.0,
    "no source event time; full small upsert; watermark last_success_at only (no minus-1h)",
)
_RIB = (
    1.0,
    "rib overlay: minus 1 hour when that job is wired; row is seeded so the list is complete",
)

WATERMARK_SPECS: tuple[WatermarkSpec, ...] = (
    WatermarkSpec("vlr_events", "dim_events", "vlrggapi", *_VLR_LOOKBACK),
    WatermarkSpec("vlr_matches", "dim_matches", "vlrggapi", *_VLR_LOOKBACK),
    WatermarkSpec("vlr_teams", "dim_teams", "vlrggapi", *_VLR_LOOKBACK),
    WatermarkSpec("vlr_players", "dim_players", "vlrggapi", *_VLR_LOOKBACK),
    WatermarkSpec("vlr_date", "dim_date", "generated", *_CATALOG),
    WatermarkSpec("vlr_dims", "dim_vct_regions", "seed", *_CATALOG),
    WatermarkSpec("vlr_dims", "dim_regions", "seed", *_CATALOG),
    WatermarkSpec("vlr_dims", "dim_economy", "seed", *_CATALOG),
    WatermarkSpec("vlr_dims", "dim_country", "events.jsonl", *_CATALOG),
    WatermarkSpec("vlr_agents", "dim_agents", "valorant-api+liquipedia", *_CATALOG),
    WatermarkSpec("vlr_maps", "dim_maps", "valorant-api+liquipedia", *_CATALOG),
    WatermarkSpec("vlr_weapons", "dim_weapons", "valorant.fandom.com", *_CATALOG),
    *(
        WatermarkSpec("vlr_facts", spec.table, "vlrggapi", *_VLR_LOOKBACK)
        for spec in FACT_SPECS
    ),
    WatermarkSpec("rib_facts", "fact_rib_round", "rib.gg", *_RIB),
    WatermarkSpec("rib_facts", "fact_rib_round_player", "rib.gg", *_RIB),
    WatermarkSpec("rib_facts", "fact_rib_round_economy", "rib.gg", *_RIB),
    WatermarkSpec("rib_facts", "fact_player_vs_player_kills", "rib.gg", *_RIB),
    WatermarkSpec("rib_facts", "fact_rib_replay_event", "rib.gg", *_RIB),
    WatermarkSpec("rib_facts", "fact_rib_match_crosswalk", "rib.gg", *_RIB),
)

INC_PIPELINES: tuple[WatermarkSpec, ...] = tuple(
    spec
    for spec in WATERMARK_SPECS
    if spec.pipeline_name in {"vlr_events", "vlr_matches", "vlr_teams", "vlr_players"}
)

FACTS_LEAD_TABLE = "fact_match_overall_stats"


def spec_for(pipeline_name: str, table_name: str | None = None) -> WatermarkSpec:
    """Resolve the watermark row a DAG step should read/write."""
    if table_name:
        for spec in WATERMARK_SPECS:
            if spec.pipeline_name == pipeline_name and spec.table_name == table_name:
                return spec
        raise KeyError(f"No watermark spec pipeline={pipeline_name} table={table_name}")
    matches = [spec for spec in WATERMARK_SPECS if spec.pipeline_name == pipeline_name]
    if not matches:
        raise KeyError(f"No watermark spec pipeline={pipeline_name}")
    return matches[0]
