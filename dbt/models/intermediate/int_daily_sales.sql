-- Grain: purchase_date, seller_state, over every date: the full recompute that mart_daily_sales
-- filters to the changed dates, and its test compares against.
-- An order counts in the state of every seller among its items, deleted items included, so a
-- canceled order keeps its state and its canceled GMV in the same row. An order that never had
-- an item counts in 'unknown'. orders_count summed over states exceeds the orders of the day
-- when an order has sellers in several states.
with

orders as (
    select
        order_id,
        purchase_date,
        order_status,
        updated_at
    from {{ ref('fct_orders') }}
),

items as (
    select
        order_id,
        price,
        freight_value,
        is_deleted,
        coalesce(seller_state, 'unknown') as seller_state
    from {{ ref('fct_order_items') }}
),

order_states as (
    select distinct
        o.order_id,
        o.purchase_date,
        o.order_status,
        o.updated_at,
        coalesce(i.seller_state, 'unknown') as seller_state
    from orders as o
    left join items as i on o.order_id = i.order_id
),

orders_per_state as (
    select
        purchase_date,
        seller_state,
        count(*) as orders_count,
        count_if(order_status = 'canceled') as canceled_orders,
        max(updated_at) as source_updated_at
    from order_states
    group by purchase_date, seller_state
),

-- GMV: live items of orders that are neither canceled nor unavailable. Canceled GMV: every item
-- of a canceled order, deleted ones included (D8).
items_per_state as (
    select
        o.purchase_date,
        i.seller_state,
        count_if(
            not i.is_deleted and o.order_status not in ('canceled', 'unavailable')
        ) as items_count,
        sum(
            case
                when not i.is_deleted and o.order_status not in ('canceled', 'unavailable')
                    then i.price
            end
        ) as gmv,
        sum(
            case
                when not i.is_deleted and o.order_status not in ('canceled', 'unavailable')
                    then i.freight_value
            end
        ) as freight_value,
        sum(case when o.order_status = 'canceled' then i.price end) as canceled_gmv
    from orders as o
    inner join items as i on o.order_id = i.order_id
    group by o.purchase_date, i.seller_state
)

select
    s.purchase_date,
    s.seller_state,
    s.orders_count,
    s.canceled_orders,
    s.source_updated_at,
    coalesce(i.items_count, 0) as items_count,
    coalesce(i.gmv, 0) as gmv,
    coalesce(i.freight_value, 0) as freight_value,
    coalesce(i.canceled_gmv, 0) as canceled_gmv
from orders_per_state as s
left join items_per_state as i
    on s.purchase_date = i.purchase_date and s.seller_state = i.seller_state
