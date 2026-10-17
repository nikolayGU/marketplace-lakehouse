-- Grain: order_id, order_item_id. Deleted items stay with is_deleted: canceled GMV counts them
-- (D4, D8). The left join keeps an item whose order is missing; the relationships test fails then.
select
    i.order_id,
    i.order_item_id,
    i.product_id,
    i.seller_id,
    i.shipping_limit_date,
    i.price,
    i.freight_value,
    i.is_deleted,
    o.order_status,
    o.purchase_date,
    p.product_category,
    s.seller_state,
    i.updated_at
from {{ ref('stg_order_items') }} as i
left join {{ ref('fct_orders') }} as o on i.order_id = o.order_id
left join {{ ref('dim_products') }} as p on i.product_id = p.product_id
left join {{ ref('dim_sellers') }} as s on i.seller_id = s.seller_id
