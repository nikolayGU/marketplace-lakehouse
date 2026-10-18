-- Grain: purchase_month, customer_state. On time: delivered no later than the estimated date,
-- by calendar date (D8). A delivered order without a delivery date is delivered, not on time.
select
    date_trunc('month', purchase_date) as purchase_month,
    customer_state,
    count_if(is_delivered) as delivered_orders,
    count_if(is_delivered and not is_late) as on_time_orders,
    {{ safe_divide('count_if(is_delivered and not is_late)', 'count_if(is_delivered)') }}
        as on_time_rate,
    avg(case when is_delivered then delivery_days end) as avg_delivery_days,
    approx_percentile(case when is_delivered then delivery_days end, 0.9) as p90_delivery_days
from {{ ref('fct_orders') }}
group by date_trunc('month', purchase_date), customer_state
