{{ config(materialized='table') }}

-- rib.gg /events column shape (loaded at runtime by rib_gg Dagster job from parquet)
with dummy_data as (
    select
        cast(null as bigint) as id,
        cast(null as varchar) as name,
        cast(null as varchar) as short_name,
        cast(null as varchar) as description,
        cast(null as varchar) as format_md,
        cast(null as varchar) as events_md,
        cast(null as varchar) as logo_url,
        cast(null as bigint) as region_id,
        cast(null as bigint) as country_id,
        cast(null as timestamp) as start_date,
        cast(null as timestamp) as end_date,
        cast(null as double precision) as prize_pool,
        cast(null as varchar) as prize_pool_currency,
        cast(null as varchar) as url,
        cast(null as varchar) as image_url,
        cast(null as varchar) as livestream_link,
        cast(null as bigint) as winner_stage_count,
        cast(null as bigint) as loser_stage_count,
        cast(null as boolean) as live,
        cast(null as bigint) as rank,
        cast(null as varchar) as pmt_json,
        cast(null as boolean) as parent,
        cast(null as bigint) as parent_id,
        cast(null as varchar) as child_label,
        cast(null as varchar) as keywords,
        cast(null as varchar) as slug,
        cast(null as bigint) as series_count,
        cast(null as bigint) as importance,
        cast(null as varchar) as type,
        cast(null as varchar) as liquipedia_slug,
        cast(null as varchar) as vct_regions,
        cast(null as varchar) as divisions,
        cast(null as varchar) as t3_subdivision,
        cast(null as varchar) as region,
        cast(null as varchar) as country
)

select * from dummy_data where id is not null
