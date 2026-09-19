# dbt

dbt-trino project over `lake.silver`, writing `lake.gold`.

- `models/staging`: `stg_<table>` views, rename + cast, filter `_deleted`.
- `models/intermediate`: `int_orders_enriched` (orders + items + payments + customer + seller).
- `models/marts`: `fct_orders`, `fct_order_items`, `dim_customers`, `dim_products`, `dim_sellers`,
  `mart_daily_sales` (incremental merge), `mart_seller_performance`, `mart_delivery_sla`.
- `seeds`: `geolocation.csv`, `product_category_translation.csv`.
- `tests`: singular tests for business rules (payments sum equals order value, delivered after shipped).
- `profiles.yml`: targets `dev` (Trino on 127.0.0.1:8080) and `ci` (parse only).
