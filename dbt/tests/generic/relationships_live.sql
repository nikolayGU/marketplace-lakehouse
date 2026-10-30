{% test relationships_live(model, column_name, to, field) %}

{# Staging keeps deleted rows (D4). A live row has to point at a live row: the built-in
   relationships would accept a deleted parent, and a deleted row, whose parent is gone or deleted
   too, is not an error at all. #}
select child.{{ column_name }}
from {{ model }} as child
where
    not child.is_deleted
    and child.{{ column_name }} is not null
    and not exists (
        select 1
        from {{ to }} as parent
        where parent.{{ field }} = child.{{ column_name }} and not parent.is_deleted
    )

{% endtest %}
