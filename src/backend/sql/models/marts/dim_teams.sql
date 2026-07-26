{{ config(materialized='table') }}

-- rib.gg /teams column shape
with dummy_data as (
    select
        cast(null as bigint) as id,
        cast(null as varchar) as name,
        cast(null as varchar) as short_name,
        cast(null as varchar) as description,
        cast(null as varchar) as website_url,
        cast(null as varchar) as logo_url,
        cast(null as bigint) as country_id,
        cast(null as varchar) as liquipedia_slug,
        cast(null as varchar) as twitter_url,
        cast(null as varchar) as twitch_url,
        cast(null as varchar) as vlr_url,
        cast(null as varchar) as youtube_url,
        cast(null as timestamp) as founded_date,
        cast(null as bigint) as region_id,
        cast(null as bigint) as rank,
        cast(null as bigint) as region_rank,
        cast(null as varchar) as aliases,
        cast(null as varchar) as vct_region,
        cast(null as varchar) as division,
        cast(null as varchar) as grid_team_id
)

select * from dummy_data where id is not null
