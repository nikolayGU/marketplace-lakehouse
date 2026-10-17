{#- dbt-trino 1.10 drops and recreates a seed table on every load. On Lakekeeper a drop is a soft
    delete that keeps the files for 7 days, so each dbt build would leave a dropped copy behind.
    Without --full-refresh, fall back to dbt's own behaviour: truncate the table, insert again
    (D14). -#}
{% macro trino__reset_csv_table(model, full_refresh, old_relation, agate_table) %}
    {{ return(dbt.default__reset_csv_table(model, full_refresh, old_relation, agate_table)) }}
{% endmacro %}
