{{ config(materialized='table') }}

-- Players from nested team payloads (no public /players list on rib.gg)
with dummy_data as (
    select
        cast(null as bigint) as id,
        cast(null as varchar) as ign,
        cast(null as varchar) as first_name,
        cast(null as varchar) as last_name,
        cast(null as varchar) as bio,
        cast(null as bigint) as country_id,
        cast(null as varchar) as instagram_url,
        cast(null as varchar) as liquipedia_slug,
        cast(null as varchar) as twitch_url,
        cast(null as varchar) as twitter_url,
        cast(null as varchar) as youtube_url,
        cast(null as varchar) as image_url,
        cast(null as varchar) as firestore_id,
        cast(null as varchar) as previous_riot_player_ids,
        cast(null as varchar) as ufa,
        cast(null as varchar) as rfa,
        cast(null as varchar) as metafy_url,
        cast(null as varchar) as custom_url,
        cast(null as varchar) as grid_player_id,
        cast(null as bigint) as team_player_history_id,
        cast(null as bigint) as team_id,
        cast(null as timestamp) as start_date,
        cast(null as varchar) as role,
        cast(null as boolean) as igl
)

select * from dummy_data where id is not null
