-- Olist ships `lenght`; the source keeps it (oltp/migrations/001_schema.sql), staging fixes it.
select
    product_id,
    product_category_name,
    product_name_lenght as product_name_length,
    product_description_lenght as product_description_length,
    product_photos_qty,
    product_weight_g,
    product_length_cm,
    product_height_cm,
    product_width_cm,
    _is_deleted as is_deleted,
    _updated_at as updated_at
from {{ source('silver', 'products') }}
