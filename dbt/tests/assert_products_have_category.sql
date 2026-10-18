-- Known in the source: 610 products have no category (2026-10-09). Products are loaded once and
-- the replayer never changes them, so a different number means a broken load.
{{
    config(
        warn_if='>0',
        error_if='>' ~ var('products_without_category_error_if', 700)
    )
}}

select product_id
from {{ ref('dim_products') }}
where product_category_name is null
