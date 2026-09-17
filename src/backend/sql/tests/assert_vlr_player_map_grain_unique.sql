-- Fail if any live VLR fact table has duplicate composite grain keys.
select vlr_match_id, map_game_number, vlr_team_id, vlr_player_id
from {{ source('vlr', 'fact_match_overall_stats') }}
group by 1, 2, 3, 4
having count(*) > 1

union all

select vlr_match_id, map_game_number, vlr_team_id, vlr_player_id
from {{ source('vlr', 'fact_player_match_performance') }}
group by 1, 2, 3, 4
having count(*) > 1
