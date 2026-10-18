{#- A share or an average that is null, not an error, when the denominator is zero. -#}
{% macro safe_divide(numerator, denominator) -%}
    cast({{ numerator }} as double) / nullif({{ denominator }}, 0)
{%- endmacro %}
