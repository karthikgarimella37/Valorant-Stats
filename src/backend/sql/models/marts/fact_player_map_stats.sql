{{ config(materialized='view', schema='vlr') }}

-- One player on one map game: box score plus KAST/HS/FK. Website "start here" grain.
-- Does not copy Python upserts; joins live vlr fact tables.

select
    o.vlr_match_id,
    o.vlr_event_id,
    o.match_date,
    o.map_name,
    o.map_game_number,
    o.player_name,
    o.vlr_team_id,
    o.vlr_player_id,
    o.agent_name,
    o.kills,
    o.deaths,
    o.assists,
    o.plus_minus,
    o.acs,
    o.adr,
    o.rating,
    o.rounds_played,
    o.is_winner,
    p.kast,
    p.hs_pct,
    p.first_kills,
    p.first_deaths,
    p.fk_diff
from {{ source('vlr', 'fact_match_overall_stats') }} as o
left join {{ source('vlr', 'fact_player_match_performance') }} as p
    on o.vlr_match_id = p.vlr_match_id
   and o.map_game_number = p.map_game_number
   and o.vlr_team_id = p.vlr_team_id
   and o.vlr_player_id = p.vlr_player_id
