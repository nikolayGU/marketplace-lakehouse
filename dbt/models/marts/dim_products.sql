-- 610 products have no category, and two categories have no English name (data/raw, 2026-10-09).
select
    p.product_id,
    p.product_category_name,
    p.product_name_length,
    p.product_description_length,
    p.product_photos_qty,
    p.product_weight_g,
    p.product_length_cm,
    p.product_height_cm,
    p.product_width_cm,
    coalesce(t.product_category_name_english, p.product_category_name, 'unknown')
        as product_category
from {{ ref('stg_products') }} as p
left join {{ ref('category_translation') }} as t
    on p.product_category_name = t.product_category_name
where not p.is_deleted
