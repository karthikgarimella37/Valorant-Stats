{{ config(materialized='table') }}

-- rib.gg /series column shape (BO fixture grain)
with dummy_data as (
    select
        cast(null as bigint) as id,
        cast(null as bigint) as event_id,
        cast(null as bigint) as team1_id,
        cast(null as bigint) as team2_id,
        cast(null as bigint) as team1_score,
        cast(null as bigint) as team2_score,
        cast(null as timestamp) as start_date,
        cast(null as bigint) as best_of,
        cast(null as varchar) as stage,
        cast(null as varchar) as bracket,
        cast(null as boolean) as completed,
        cast(null as boolean) as live,
        cast(null as varchar) as win_condition,
        cast(null as varchar) as vlr_id,
        cast(null as varchar) as vod_url,
        cast(null as varchar) as ggbet_id,
        cast(null as varchar) as pmt_status,
        cast(null as varchar) as pmt_reddit_url,
        cast(null as varchar) as pmt_json,
        cast(null as varchar) as pickban,
        cast(null as varchar) as grid_series_id,
        cast(null as varchar) as liquipedia_slug,
        cast(null as varchar) as event_livestream_link,
        cast(null as varchar) as event_name,
        cast(null as varchar) as event_slug,
        cast(null as varchar) as event_child_label,
        cast(null as varchar) as event_logo_url,
        cast(null as bigint) as event_region_id,
        cast(null as bigint) as parent_event_id,
        cast(null as varchar) as parent_event_name,
        cast(null as varchar) as parent_event_slug,
        cast(null as varchar) as parent_event_livestream_link
)

select * from dummy_data where id is not null
