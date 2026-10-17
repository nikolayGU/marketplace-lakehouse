-- Grain: order_id. Every join starts from the order and is a left join: an order without items
-- (canceled or unavailable before anything was picked) must stay, with zero counts.
with

orders as (
    select
        order_id,
        customer_id,
        order_status,
        order_purchase_timestamp,
        order_approved_at,
        order_delivered_carrier_date,
        order_delivered_customer_date,
        order_estimated_delivery_date,
        updated_at
    from {{ ref('stg_orders') }}
    where not is_deleted
),

customers as (
    select
        customer_id,
        customer_unique_id,
        customer_city,
        customer_state
    from {{ ref('stg_customers') }}
    where not is_deleted
),

-- Values count live items only; updated_at covers deleted ones too, since deleting an item
-- changes the order for the marts.
items as (
    select
        order_id,
        count_if(not is_deleted) as items_count,
        sum(case when not is_deleted then price end) as items_value,
        sum(case when not is_deleted then freight_value end) as freight_value,
        max(updated_at) as updated_at
    from {{ ref('stg_order_items') }}
    group by order_id
),

payments as (
    select
        order_id,
        sum(payment_value) as payment_value,
        max(payment_installments) as payment_installments_max,
        max(updated_at) as updated_at
    from {{ ref('stg_payments') }}
    where not is_deleted
    group by order_id
)

select
    o.order_id,
    o.customer_id,
    c.customer_unique_id,
    c.customer_city,
    c.customer_state,
    o.order_status,
    o.order_purchase_timestamp,
    o.order_approved_at,
    o.order_delivered_carrier_date,
    o.order_delivered_customer_date,
    o.order_estimated_delivery_date,
    p.payment_installments_max,
    o.updated_at as order_updated_at,
    i.updated_at as items_updated_at,
    p.updated_at as payments_updated_at,
    coalesce(i.items_count, 0) as items_count,
    coalesce(i.items_value, 0) as items_value,
    coalesce(i.freight_value, 0) as freight_value,
    coalesce(p.payment_value, 0) as payment_value
from orders as o
left join customers as c on o.customer_id = c.customer_id
left join items as i on o.order_id = i.order_id
left join payments as p on o.order_id = p.order_id
