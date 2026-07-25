{{ config(materialized='table') }}

with dummy_data as (
    select
        cast(null as integer) as team_id,
        cast(null as varchar(255)) as team_name,
        cast(null as varchar(10)) as team_tag,
        cast(null as varchar(100)) as region,
        cast(null as varchar(100)) as country,
        cast(null as text) as logo_url,
        cast(null as timestamp) as created_at,
        cast(null as timestamp) as updated_at
)

select * from dummy_data where team_id is not null
