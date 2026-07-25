{{ config(materialized='table') }}

with dummy_data as (
    select
        cast(null as integer) as agent_id,
        cast(null as varchar(100)) as agent_name,
        cast(null as varchar(50)) as agent_type,
        cast(null as timestamp) as created_at
)

select * from dummy_data where agent_id is not null
