{{ config(materialized='table') }}

with dummy_data as (
    select
        cast(null as integer) as player_id,
        cast(null as varchar(255)) as player_name,
        cast(null as varchar(100)) as player_tag,
        cast(null as varchar(255)) as real_name,
        cast(null as varchar(100)) as country,
        cast(null as integer) as team_id,
        cast(null as varchar(50)) as role,
        cast(null as timestamp) as created_at,
        cast(null as timestamp) as updated_at
)

select * from dummy_data where player_id is not null
