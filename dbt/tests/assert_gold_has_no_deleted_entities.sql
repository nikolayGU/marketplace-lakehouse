-- D4: staging keeps deleted rows and every consumer drops them. These models hold live entities
-- only; fct_order_items keeps deleted items on purpose (D8) and is not checked. The replayer
-- deletes items and reviews, never these entities, so a row here is a lost filter, not a race with
-- a silver merge that runs while dbt does. Expected: no rows.
select
    'fct_orders' as model,
    f.order_id as entity_key
from {{ ref('fct_orders') }} as f
inner join {{ ref('stg_orders') }} as o on f.order_id = o.order_id
where o.is_deleted

union all

-- A deleted customer gives its order no customer_unique_id (int_orders_enriched).
select
    'fct_orders customer' as model,
    f.order_id as entity_key
from {{ ref('fct_orders') }} as f
inner join {{ ref('stg_customers') }} as c on f.customer_id = c.customer_id
where c.is_deleted and f.customer_unique_id is not null

union all

select
    'dim_products' as model,
    d.product_id as entity_key
from {{ ref('dim_products') }} as d
inner join {{ ref('stg_products') }} as p on d.product_id = p.product_id
where p.is_deleted

union all

select
    'dim_sellers' as model,
    d.seller_id as entity_key
from {{ ref('dim_sellers') }} as d
inner join {{ ref('stg_sellers') }} as s on d.seller_id = s.seller_id
where s.is_deleted

union all

-- A person stays only through a live customer with a live order (dim_customers).
select
    'dim_customers' as model,
    d.customer_unique_id as entity_key
from {{ ref('dim_customers') }} as d
where not exists (
    select 1
    from {{ ref('stg_orders') }} as o
    inner join {{ ref('stg_customers') }} as c on o.customer_id = c.customer_id
    where
        c.customer_unique_id = d.customer_unique_id
        and not o.is_deleted
        and not c.is_deleted
)
