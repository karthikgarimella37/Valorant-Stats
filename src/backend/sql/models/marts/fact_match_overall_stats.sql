{{ config(materialized='table') }}

with dummy_data as (
    select
        cast(null as integer) as stat_id,
        cast(null as integer) as match_id,
        cast(null as integer) as team_id,
        cast(null as integer) as map_id,
        cast(null as integer) as rounds_won,
        cast(null as integer) as rounds_lost,
        cast(null as integer) as total_kills,
        cast(null as integer) as total_deaths,
        cast(null as integer) as total_assists,
        cast(null as decimal(8,2)) as total_acs,
        cast(null as decimal(8,2)) as total_adr,
        cast(null as integer) as first_kills,
        cast(null as integer) as first_deaths,
        cast(null as integer) as clutches_won,
        cast(null as integer) as clutches_attempted,
        cast(null as timestamp) as created_at
)

select * from dummy_data where stat_id is not null
