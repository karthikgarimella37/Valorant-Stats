-- Fail if round results repeat the same match/map/round.
select vlr_match_id, map_game_number, round_number
from {{ source('vlr', 'fact_round_results') }}
group by 1, 2, 3
having count(*) > 1
