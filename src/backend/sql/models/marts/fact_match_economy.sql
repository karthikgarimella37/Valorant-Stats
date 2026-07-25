{{ config(materialized='table') }}

with dummy_data as (
    select
        cast(null as integer) as economy_id,
        cast(null as integer) as match_id,
        cast(null as integer) as player_id,
        cast(null as integer) as team_id,
        cast(null as integer) as map_id,
        cast(null as integer) as total_spent,
        cast(null as integer) as equipment_value,
        cast(null as integer) as money_saved,
        cast(null as integer) as clutches_won,
        cast(null as integer) as clutches_attempted,
        cast(null as integer) as multi_kills,
        cast(null as timestamp) as created_at
)

select * from dummy_data where economy_id is not null
