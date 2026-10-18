-- fct_orders is referenced only in the incremental branch, which dbt does not see when parsing.
-- depends_on: {{ ref('fct_orders') }}
{{
    config(
        materialized='incremental',
        incremental_strategy='delete+insert',
        unique_key='purchase_date',
        on_schema_change='fail'
    )
}}

select
    d.purchase_date,
    d.seller_state,
    d.orders_count,
    d.canceled_orders,
    d.source_updated_at,
    d.items_count,
    d.gmv,
    d.freight_value,
    d.canceled_gmv
from {{ ref('int_daily_sales') }} as d
{% if is_incremental() %}
    -- Every purchase date with an order that changed since the last run, all its states at once:
    -- delete+insert removes the date's old rows, so a group that has no rows any more goes too
    -- (D7). A change arrives days after the purchase, so filtering by purchase_date would miss it.
    where d.purchase_date in (
        select o.purchase_date
        from {{ ref('fct_orders') }} as o
        where o.updated_at > (
            select coalesce(max(t.source_updated_at), timestamp '1970-01-01 00:00:00 UTC')
            from {{ this }} as t
        )
    )
{% endif %}
