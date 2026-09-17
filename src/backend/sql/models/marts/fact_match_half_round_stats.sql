{{ config(materialized='materialized_view', schema='vlr') }}

-- Team × map × side (attack/defense) round wins for the map dashboard.
-- Grain: one team on one map game on one side. Source: vlr.fact_round_results (Python upsert).

with rounds as (
    select
        r.vlr_match_id,
        r.vlr_event_id,
        r.map_name,
        r.map_game_number,
        r.round_number,
        r.winning_vlr_team_id,
        r.losing_vlr_team_id,
        r.is_attack_win
    from {{ source('vlr', 'fact_round_results') }} as r
),

sides as (
    select
        vlr_match_id,
        vlr_event_id,
        map_name,
        map_game_number,
        winning_vlr_team_id as vlr_team_id,
        is_attack_win as is_attack,
        true as is_win
    from rounds
    union all
    select
        vlr_match_id,
        vlr_event_id,
        map_name,
        map_game_number,
        losing_vlr_team_id as vlr_team_id,
        not is_attack_win as is_attack,
        false as is_win
    from rounds
    where losing_vlr_team_id is not null
      and losing_vlr_team_id <> '-1'
)

select
    vlr_match_id,
    vlr_event_id,
    map_name,
    map_game_number,
    vlr_team_id,
    is_attack,
    count(*)::int as rounds_played,
    sum(case when is_win then 1 else 0 end)::int as rounds_won
from sides
where vlr_team_id is not null
  and vlr_team_id <> '-1'
group by 1, 2, 3, 4, 5, 6
