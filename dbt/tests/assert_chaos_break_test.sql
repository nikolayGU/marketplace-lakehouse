-- Chaos 9 (OPERATIONS.md): fails only under --vars '{chaos_break_test: true}'. dbt build then
-- skips every model after fct_orders, and the marts keep their previous version.
select order_id
from {{ ref('fct_orders') }}
where {{ 'true' if var('chaos_break_test', false) else 'false' }}
