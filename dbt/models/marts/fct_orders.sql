-- Grain: order_id, live orders of silver. Dates come from order_purchase_timestamp (business
-- time); updated_at is processing time and serves only as the watermark of mart_daily_sales.
select
    order_id,
    customer_id,
    customer_unique_id,
    customer_city,
    customer_state,
    order_status,
    order_purchase_timestamp,
    order_approved_at,
    order_delivered_carrier_date,
    order_delivered_customer_date,
    order_estimated_delivery_date,
    items_count,
    items_value,
    freight_value,
    payment_value,
    payment_installments_max,
    cast(order_purchase_timestamp as date) as purchase_date,
    order_status = 'delivered' as is_delivered,
    order_status = 'canceled' as is_canceled,
    date_diff(
        'day',
        cast(order_purchase_timestamp as date),
        cast(order_delivered_customer_date as date)
    ) as delivery_days,
    -- Null unless delivered: lateness is defined only for a delivered order (D8).
    case
        when order_status = 'delivered'
            then
                cast(order_delivered_customer_date as date)
                > cast(order_estimated_delivery_date as date)
    end as is_late,
    -- greatest() is null if any argument is: an order without items or payments still needs one.
    greatest(
        order_updated_at,
        coalesce(items_updated_at, order_updated_at),
        coalesce(payments_updated_at, order_updated_at)
    ) as updated_at
from {{ ref('int_orders_enriched') }}
