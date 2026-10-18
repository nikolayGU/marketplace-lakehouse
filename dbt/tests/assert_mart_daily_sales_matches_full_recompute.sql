-- mart_daily_sales, built incrementally, equals a full recompute over every date. Catches a wrong
-- watermark or a group left behind by delete+insert; a rerun without changes only proves
-- idempotency (D7). Expected: no rows.
with

mart as (
    select
        purchase_date,
        seller_state,
        orders_count,
        canceled_orders,
        source_updated_at,
        items_count,
        gmv,
        freight_value,
        canceled_gmv
    from {{ ref('mart_daily_sales') }}
),

full_recompute as (
    select
        purchase_date,
        seller_state,
        orders_count,
        canceled_orders,
        source_updated_at,
        items_count,
        gmv,
        freight_value,
        canceled_gmv
    from {{ ref('int_daily_sales') }}
),

only_in_mart as (
    select * from mart
    except
    select * from full_recompute
),

only_in_full_recompute as (
    select * from full_recompute
    except
    select * from mart
)

select
    'only in mart' as side,
    purchase_date,
    seller_state,
    orders_count,
    canceled_orders,
    source_updated_at,
    items_count,
    gmv,
    freight_value,
    canceled_gmv
from only_in_mart
union all
select
    'only in full recompute' as side,
    purchase_date,
    seller_state,
    orders_count,
    canceled_orders,
    source_updated_at,
    items_count,
    gmv,
    freight_value,
    canceled_gmv
from only_in_full_recompute
