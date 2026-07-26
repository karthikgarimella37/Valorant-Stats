{{ config(materialized='table') }}

-- Phase 2: populate from /matches/{id}/details
with dummy_data as (
    select
        cast(null as bigint) as id,
        cast(null as bigint) as match_id,
        cast(null as bigint) as player_id,
        cast(null as bigint) as team_id,
        cast(null as bigint) as map_id,
        cast(null as bigint) as total_spent,
        cast(null as bigint) as equipment_value,
        cast(null as bigint) as money_saved
)

select * from dummy_data where id is not null
