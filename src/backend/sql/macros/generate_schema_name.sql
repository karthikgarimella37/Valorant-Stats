{% macro generate_schema_name(custom_schema_name, node) -%}
    {# Why: live marts must land in schema vlr next to Python-loaded tables, not valorant_vlr. #}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
