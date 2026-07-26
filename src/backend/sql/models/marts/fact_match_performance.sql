{{ config(materialized='table') }}

-- Phase 2: populate from /matches/{id}/details
with dummy_data as (
    select
        cast(null as bigint) as id,
        cast(null as bigint) as match_id,
        cast(null as bigint) as player_id,
        cast(null as bigint) as team_id,
        cast(null as bigint) as map_id,
        cast(null as bigint) as agent_id,
        cast(null as bigint) as kills,
        cast(null as bigint) as deaths,
        cast(null as bigint) as assists,
        cast(null as double precision) as acs,
        cast(null as double precision) as adr,
        cast(null as double precision) as hs_percentage,
        cast(null as double precision) as rating
)

select * from dummy_data where id is not null
