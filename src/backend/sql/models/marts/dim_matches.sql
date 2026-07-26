{{ config(materialized='table') }}

-- Map-level matches exploded from series.matches[]
with dummy_data as (
    select
        cast(null as bigint) as id,
        cast(null as bigint) as patch_id,
        cast(null as bigint) as series_id,
        cast(null as bigint) as series_match_number,
        cast(null as varchar) as riot_id,
        cast(null as bigint) as map_id,
        cast(null as timestamp) as start_date,
        cast(null as bigint) as length_millis,
        cast(null as boolean) as completed,
        cast(null as varchar) as riot_season_id,
        cast(null as varchar) as riot_game_mode,
        cast(null as boolean) as no_riot_data,
        cast(null as varchar) as region,
        cast(null as boolean) as live,
        cast(null as boolean) as ready_to_display,
        cast(null as bigint) as attacking_first_team_number,
        cast(null as bigint) as red_team_number,
        cast(null as bigint) as winning_team_number,
        cast(null as varchar) as win_condition,
        cast(null as boolean) as teams_inverted_in_stream,
        cast(null as bigint) as team1_score,
        cast(null as bigint) as team2_score,
        cast(null as varchar) as vlr_id,
        cast(null as varchar) as vod_url,
        cast(null as varchar) as cn_vod_url,
        cast(null as varchar) as team1_player_ids,
        cast(null as varchar) as team2_player_ids,
        cast(null as varchar) as team1_agent_ids,
        cast(null as varchar) as team2_agent_ids
)

select * from dummy_data where id is not null
