{% test value_in_range(model, column_name, min_value, max_value=none) %}

{# A null is not out of range: silver rejects a live row without a required value, and a deleted
   row may hold a null. Deleted rows are checked: canceled GMV sums their price. #}
select {{ column_name }}
from {{ model }}
where
    {{ column_name }} < {{ min_value }}
    {%- if max_value is not none %}
    or {{ column_name }} > {{ max_value }}
    {%- endif %}

{% endtest %}
