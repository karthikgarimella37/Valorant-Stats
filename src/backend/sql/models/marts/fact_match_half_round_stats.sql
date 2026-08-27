{{ config(materialized='view') }}

-- Team × map × side (attack/defense) round wins for the map dashboard.
-- VLR has no player-level attack/defense K/D; this view is the substitute.

with rounds as (
    select
        r.match_id,
        r.event_id,
        r.map_id,
        r.map_game_number,
        r.round_number,
        r.winning_team_id,
        r.losing_team_id,
        r.is_attack_win
    from {{ source('vlr', 'fact_round_results') }} as r
),

sides as (
    select
        match_id,
        event_id,
        map_id,
        map_game_number,
        winning_team_id as team_id,
        is_attack_win as is_attack,
        true as is_win
    from rounds
    union all
    select
        match_id,
        event_id,
        map_id,
        map_game_number,
        losing_team_id as team_id,
        not is_attack_win as is_attack,
        false as is_win
    from rounds
    where losing_team_id is not null
)

select
    match_id,
    event_id,
    map_id,
    map_game_number,
    team_id,
    is_attack,
    count(*)::int as rounds_played,
    sum(case when is_win then 1 else 0 end)::int as rounds_won
from sides
where team_id is not null
group by 1, 2, 3, 4, 5, 6
