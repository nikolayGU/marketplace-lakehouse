-- Grain: seller_id, purchase_month. A seller's orders are those with any item of the seller,
-- deleted items included, so an order canceled before shipping still counts against the seller.
with

orders as (
    select
        order_id,
        order_status,
        is_delivered,
        is_late,
        date_trunc('month', purchase_date) as purchase_month
    from {{ ref('fct_orders') }}
),

items as (
    select
        order_id,
        seller_id,
        price,
        is_deleted
    from {{ ref('fct_order_items') }}
),

live_reviews as (
    select
        order_id,
        review_score
    from {{ ref('stg_reviews') }}
    where not is_deleted
),

seller_orders as (
    select distinct
        i.seller_id,
        o.order_id,
        o.purchase_month,
        o.order_status,
        o.is_delivered,
        o.is_late
    from items as i
    inner join orders as o on i.order_id = o.order_id
),

seller_gmv as (
    select
        i.seller_id,
        o.purchase_month,
        sum(
            case
                when not i.is_deleted and o.order_status not in ('canceled', 'unavailable')
                    then i.price
            end
        ) as gmv
    from items as i
    inner join orders as o on i.order_id = o.order_id
    group by i.seller_id, o.purchase_month
),

seller_reviews as (
    select
        so.seller_id,
        so.purchase_month,
        avg(r.review_score) as avg_review_score
    from seller_orders as so
    inner join live_reviews as r on so.order_id = r.order_id
    group by so.seller_id, so.purchase_month
),

seller_order_stats as (
    select
        seller_id,
        purchase_month,
        count(*) as orders_count,
        count_if(is_delivered) as delivered_orders,
        count_if(is_delivered and is_late) as late_orders,
        count_if(order_status = 'canceled') as canceled_orders
    from seller_orders
    group by seller_id, purchase_month
)

select
    s.seller_id,
    s.purchase_month,
    s.orders_count,
    r.avg_review_score,
    coalesce(g.gmv, 0) as gmv,
    {{ safe_divide('s.late_orders', 's.delivered_orders') }} as late_rate,
    {{ safe_divide('s.canceled_orders', 's.orders_count') }} as cancellation_rate
from seller_order_stats as s
left join seller_gmv as g
    on s.seller_id = g.seller_id and s.purchase_month = g.purchase_month
left join seller_reviews as r
    on s.seller_id = r.seller_id and s.purchase_month = r.purchase_month
