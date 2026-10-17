select
    order_id,
    order_item_id,
    product_id,
    seller_id,
    shipping_limit_date,
    price,
    freight_value,
    _is_deleted as is_deleted,
    _updated_at as updated_at
from {{ source('silver', 'order_items') }}
