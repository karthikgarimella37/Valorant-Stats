{{ config(materialized='table') }}

-- Phase 1 stub: agent IDs appear on matches; list endpoint unverified
with dummy_data as (
    select
        cast(null as bigint) as id,
        cast(null as varchar) as name,
        cast(null as varchar) as agent_type
)

select * from dummy_data where id is not null
