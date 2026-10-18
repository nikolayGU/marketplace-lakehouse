-- Known in the source: payments differ from items plus freight by more than 0.01 for 287 orders
-- that are neither canceled nor unavailable (2026-10-09). Canceled and unavailable orders are
-- left out: their items were deleted or never existed, their payments were not. warn above 0,
-- error above the threshold: growth past it means our pipeline lost items or payments.
{{
    config(
        warn_if='>0',
        error_if='>' ~ var('payments_mismatch_error_if', 1000)
    )
}}

select
    order_id,
    order_status,
    payment_value,
    items_value,
    freight_value
from {{ ref('fct_orders') }}
where
    order_status not in ('canceled', 'unavailable')
    and abs(payment_value - (items_value + freight_value)) > 0.01
