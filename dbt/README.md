# dbt

dbt-trino project `marketplace` over `lake.silver`, writing every model to `lake.gold` (Trino on
Lakekeeper). Run it from the repo root: `make dbt-parse` (no warehouse), `make dbt-build` (seed,
run, test; needs `make start`).

- `models/staging`: `stg_<table>` views over the seven silver tables. Columns renamed, no filter:
  deleted rows stay with `is_deleted`, and each consumer decides (D4 of
  `docs/planning/07-w3-spec.md`). `updated_at` is when silver merged the row, not a business time.
- `models/intermediate`: `int_orders_enriched` (order, customer, live item and payment
  aggregates) and `int_daily_sales` (daily sales over every date, the full recompute).
- `models/marts`: `fct_orders`, `fct_order_items` (deleted items included), `dim_customers`
  (grain `customer_unique_id`, D3), `dim_products`, `dim_sellers`, `mart_daily_sales`
  (incremental, delete+insert by purchase date, D7), `mart_delivery_sla`,
  `mart_seller_performance`.
- `seeds/category_translation.csv`: Portuguese category to English, 71 rows. Geolocation is not
  modelled (D5).
- `macros`: `safe_divide`; `trino__reset_csv_table`, which makes a seed reload truncate the table
  instead of dropping it (D14).
- `tests/generic`: `unique_combination.sql` (uniqueness of a composite key),
  `relationships_live.sql` (a live row points at a live row of its parent) and
  `value_in_range.sql` (a lower and an optional upper bound), without packages.
- `profiles.yml`: target `dev` (Trino at `TRINO_HOST`:`TRINO_PORT`, default 127.0.0.1:8080) and
  `ci` (parse only). No secrets: Trino has no authentication and listens on 127.0.0.1.

Every table model is `CREATE OR REPLACE TABLE` (`on_table_exists: replace`, D6): the rename
default would drop a backup table on every run, and on Lakekeeper a drop keeps the files for 7
days. The only drops dbt does are its own: the temporary `mart_daily_sales__dbt_tmp` on every
incremental run (D13).

SQL is linted from this directory: `cd dbt && uv run sqlfluff lint models macros tests`.

Tests: keys and relationships on every model. Staging relationships compare live rows with live
parents at severity `warn`: silver merges each table in a commit of its own, `order_items` before
`orders`, so a child can precede its parent for one run; the hard comparison of keys is `make
reconcile` and `dq_checks`. Ranges (`price`, `freight_value`, `review_score`) and `payment_type`
are errors, and `assert_gold_has_no_deleted_entities` holds D4. Then
`assert_mart_daily_sales_matches_full_recompute` (D7); four tests on known anomalies of the
source (`tests/assert_*.sql`), each warning above 0 and failing above a threshold from a dbt var,
with the number and the date in its description (`tests/_tests.yml`). `make dbt-docs` writes the
docs, the metric glossary of `models/docs.md` included, to `target/`.

Freshness: `dbt source freshness` checks `orders`, `order_items`, `payments` and `reviews`, the
tables the replayer changes (`_updated_at`; warn after 30 minutes, error after 2 hours).
`customers`, `sellers` and `products` were loaded once and are not checked. With the replay
stopped, a warn after 30 minutes and an error with exit code 1 after 2 hours mean "no traffic",
not a broken pipeline.
