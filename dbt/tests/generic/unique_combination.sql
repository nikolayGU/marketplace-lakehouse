{% test unique_combination(model, columns) %}

select
    {{ columns | join(', ') }},
    count(*) as copies
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1

{% endtest %}
