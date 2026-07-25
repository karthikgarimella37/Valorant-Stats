{{ config(materialized='table') }}

with dummy_data as (
    select
        cast(null as integer) as event_id,
        cast(null as varchar(255)) as event_name,
        cast(null as varchar(100)) as event_type,
        cast(null as date) as start_date,
        cast(null as date) as end_date,
        cast(null as varchar(255)) as location,
        cast(null as decimal(15,2)) as prize_pool,
        cast(null as timestamp) as created_at,
        cast(null as timestamp) as updated_at
)

select * from dummy_data where event_id is not null
