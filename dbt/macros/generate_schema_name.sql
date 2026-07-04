{# Use the configured schema name verbatim (staging/intermediate/marts)
   instead of dbt's default "<target>_<custom>" concatenation — the pytest
   suite and BI queries address schemas by their plain names. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
