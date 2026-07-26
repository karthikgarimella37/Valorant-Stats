{{ config(materialized='table') }}

-- Phase 2: populate from /matches/{id}/details
with dummy_data as (
    select
        cast(null as bigint) as id,
        cast(null as bigint) as match_id,
        cast(null as bigint) as team_id,
        cast(null as bigint) as map_id,
        cast(null as bigint) as rounds_won,
        cast(null as bigint) as rounds_lost,
        cast(null as bigint) as total_kills,
        cast(null as bigint) as total_deaths,
        cast(null as bigint) as total_assists,
        cast(null as double precision) as total_acs,
        cast(null as double precision) as total_adr
)

select * from dummy_data where id is not null
