-- Known in the source: pc_gamer and portateis_cozinha_e_preparadores_de_alimentos have no English
-- name in the translation file (2026-10-09); dim_products keeps the Portuguese one.
{{
    config(
        warn_if='>0',
        error_if='>' ~ var('untranslated_categories_error_if', 5)
    )
}}

select distinct p.product_category_name
from {{ ref('dim_products') }} as p
left join {{ ref('category_translation') }} as t
    on p.product_category_name = t.product_category_name
where
    p.product_category_name is not null
    and t.product_category_name is null
