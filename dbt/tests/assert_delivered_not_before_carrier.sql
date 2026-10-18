-- Known in the source: 23 orders reached the customer before the carrier got them (2026-10-09).
{{
    config(
        warn_if='>0',
        error_if='>' ~ var('delivered_before_carrier_error_if', 100)
    )
}}

select
    order_id,
    order_delivered_carrier_date,
    order_delivered_customer_date
from {{ ref('fct_orders') }}
where order_delivered_customer_date < order_delivered_carrier_date
