-- Grain: customer_unique_id, the person (D3). Only customers with an order in silver: the loader
-- puts every customer into shop.customers up front, including those of orders still to come.
with

orders as (
    select
        order_id,
        customer_id,
        order_purchase_timestamp
    from {{ ref('stg_orders') }}
    where not is_deleted
),

customers as (
    select
        customer_id,
        customer_unique_id,
        customer_zip_code_prefix,
        customer_city,
        customer_state
    from {{ ref('stg_customers') }}
    where not is_deleted
),

customer_orders as (
    select
        c.customer_unique_id,
        c.customer_zip_code_prefix,
        c.customer_city,
        c.customer_state,
        o.order_purchase_timestamp,
        -- The address of the latest order; equal purchase times go to the larger customer_id.
        row_number() over (
            partition by c.customer_unique_id
            order by o.order_purchase_timestamp desc, c.customer_id desc, o.order_id desc
        ) as recency
    from orders as o
    inner join customers as c on o.customer_id = c.customer_id
),

stats as (
    select
        customer_unique_id,
        count(*) as orders_count,
        min(order_purchase_timestamp) as first_order_ts,
        max(order_purchase_timestamp) as last_order_ts
    from customer_orders
    group by customer_unique_id
)

select
    s.customer_unique_id,
    latest.customer_zip_code_prefix,
    latest.customer_city,
    latest.customer_state,
    s.orders_count,
    s.first_order_ts,
    s.last_order_ts,
    s.orders_count > 1 as is_repeat
from stats as s
inner join customer_orders as latest
    on s.customer_unique_id = latest.customer_unique_id and latest.recency = 1
