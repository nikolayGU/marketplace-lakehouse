select
    order_id,
    customer_id,
    order_status,
    order_purchase_timestamp,
    order_approved_at,
    order_delivered_carrier_date,
    order_delivered_customer_date,
    order_estimated_delivery_date,
    _is_deleted as is_deleted,
    _updated_at as updated_at
from {{ source('silver', 'orders') }}
