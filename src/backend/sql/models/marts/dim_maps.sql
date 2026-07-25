{{ config(materialized='table') }}

with dummy_data as (
    select
        cast(null as integer) as map_id,
        cast(null as varchar(100)) as map_name,
        cast(null as varchar(50)) as map_type,
        cast(null as date) as release_date,
        cast(null as timestamp) as created_at
)

select * from dummy_data where map_id is not null
