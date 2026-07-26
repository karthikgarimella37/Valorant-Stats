{{ config(materialized='table') }}

-- Distinct map objects nested under series.matches[].map
with dummy_data as (
    select
        cast(null as bigint) as id,
        cast(null as varchar) as name,
        cast(null as varchar) as riot_id,
        cast(null as varchar) as riot_name,
        cast(null as varchar) as images,
        cast(null as varchar) as ow_name,
        cast(null as varchar) as geo_data,
        cast(null as varchar) as display_data
)

select * from dummy_data where id is not null
