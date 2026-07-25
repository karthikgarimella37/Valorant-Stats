{{ config(materialized='table') }}

with dummy_data as (
    select
        cast(null as integer) as performance_id,
        cast(null as integer) as match_id,
        cast(null as integer) as player_id,
        cast(null as integer) as team_id,
        cast(null as integer) as map_id,
        cast(null as integer) as agent_id,
        cast(null as integer) as kills,
        cast(null as integer) as deaths,
        cast(null as integer) as assists,
        cast(null as decimal(8,2)) as acs,
        cast(null as decimal(8,2)) as adr,
        cast(null as decimal(5,2)) as hs_percentage,
        cast(null as integer) as first_kills,
        cast(null as integer) as first_deaths,
        cast(null as integer) as fkfd_diff,
        cast(null as decimal(4,2)) as rating,
        cast(null as timestamp) as created_at
)

select * from dummy_data where performance_id is not null
