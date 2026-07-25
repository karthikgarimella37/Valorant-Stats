{{ config(materialized='table') }}

with dummy_data as (
    select
        cast(null as integer) as match_id,
        cast(null as varchar(50)) as vlr_match_id,
        cast(null as integer) as event_id,
        cast(null as integer) as team1_id,
        cast(null as integer) as team2_id,
        cast(null as timestamp) as match_date,
        cast(null as varchar(20)) as match_format,
        cast(null as varchar(20)) as match_status,
        cast(null as integer) as winner_team_id,
        cast(null as varchar(20)) as final_score,
        cast(null as timestamp) as created_at,
        cast(null as timestamp) as updated_at
)

select * from dummy_data where match_id is not null
