# W3-T01 dbt: проект, sources, staging, ядро моделей

> До первого шага прочитай `README.md` этой папки: протокол, стоп-условия, отчёт.

| | |
|---|---|
| Спека | `07-w3-spec.md`, карточка W3-T01; решения D3, D4, D5, D6, D13; D14 из README плана |
| Коммит | `dbt: project, staging and core models` |
| Оценка | A: 1.5 ч; B: 1 ч |
| Часть A | любая среда |
| Часть B | только локально: первый `dbt build` создаёт схему `lake.gold` |

## Цель

Проект dbt `marketplace` строит в `lake.gold` staging-views над silver и ядро: `int_orders_enriched`, `fct_orders`, `fct_order_items`, `dim_customers` (грейн `customer_unique_id`), `dim_products`, `dim_sellers`; повторный прогон обходится без DROP.

## Вход

```bash
git log --oneline -1                            # коммит W3-T00
ls dbt                                          # README.md
make dbt-parse >/dev/null 2>&1; echo "exit $?"   # exit 2: dbt_project.yml ещё нет
uv run dbt --version | grep -E 'installed|trino' # 1.10.23 и trino 1.10.4
```

## Файлы

- Создать в `dbt/`: `dbt_project.yml`, `profiles.yml`, `.sqlfluff`, `macros/trino__reset_csv_table.sql`, `seeds/category_translation.csv`, `seeds/_seeds.yml`, `tests/generic/unique_combination.sql`, `models/staging/_sources.yml`, `models/staging/_staging.yml`, `models/staging/stg_{orders,order_items,payments,reviews,customers,sellers,products}.sql`, `models/intermediate/int_orders_enriched.sql`, `models/intermediate/_intermediate.yml`, `models/marts/{fct_orders,fct_order_items,dim_customers,dim_products,dim_sellers}.sql`, `models/marts/_core.yml`.
- Изменить: `dbt/README.md`, `Makefile`, `.github/workflows/ci.yml`, `ARCHITECTURE.md`, `docs/planning/00-mini-architecture-review.md`.

## Что задача даёт следующим

- Модели и колонки, на которых стоят витрины W3-T02: `fct_orders` (в том числе `purchase_date`, `order_status`, `is_delivered`, `is_late`, `delivery_days`, `items_count`, `items_value`, `payment_value`, `updated_at`), `fct_order_items` (`seller_state`, `product_category`, `is_deleted`, `price`, `freight_value`), `stg_reviews`.
- Generic-тест `unique_combination(columns)`; `make dbt-build`; lint dbt из каталога `dbt/`.

## Часть A. Код

### A1. Проект, профили, линтер

`+on_table_exists: replace` задаётся до первого прогона (D6): умолчание `rename` уже на втором прогоне делает DROP бэкапа.

<!-- file: dbt/dbt_project.yml -->
```yaml
name: marketplace
version: "1.0.0"
profile: lakehouse

model-paths: ["models"]
seed-paths: ["seeds"]
test-paths: ["tests"]
macro-paths: ["macros"]

flags:
  # dbt would write .user.yml into the profiles directory, which Airflow mounts read-only.
  send_anonymous_usage_stats: false
  # Trino is plain http here: the flag only silences dbt-trino's warning on every connection.
  require_certificate_validation: true

models:
  marketplace:
    # dbt-trino's default `rename` drops the backup table on every run; on Lakekeeper a drop is a
    # soft delete that keeps the files for 7 days. `replace` is CREATE OR REPLACE TABLE (D6).
    +on_table_exists: replace
    staging:
      +materialized: view
    intermediate:
      +materialized: view
    marts:
      +materialized: table
```

<!-- file: dbt/profiles.yml -->
```yaml
# No secrets here: Trino runs without authentication, on 127.0.0.1 only.
lakehouse:
  target: dev
  outputs:
    dev:
      type: trino
      method: none
      user: dbt
      host: "{{ env_var('TRINO_HOST', '127.0.0.1') }}"
      port: "{{ env_var('TRINO_PORT', '8080') | as_number }}"
      database: lake
      schema: gold
      threads: 2
    # dbt parse in CI: never connects.
    ci:
      type: trino
      method: none
      user: dbt
      host: "{{ env_var('TRINO_HOST', '127.0.0.1') }}"
      port: "{{ env_var('TRINO_PORT', '8080') | as_number }}"
      database: lake
      schema: gold
      threads: 2
```

sqlfluff 4.3 не принимает смену templater во вложенном `.sqlfluff`, поэтому для dbt он запускается из каталога `dbt/` (шаг A6).

<!-- file: dbt/.sqlfluff -->
```ini
# Linted from this directory (make lint runs `cd dbt && sqlfluff lint ...`): sqlfluff 4 refuses
# to switch the templater in a .sqlfluff below the working directory.
[sqlfluff]
dialect = trino
templater = jinja
max_line_length = 100

[sqlfluff:templater:jinja]
apply_dbt_builtins = True
load_macros_from_path = macros

[sqlfluff:rules:capitalisation.keywords]
capitalisation_policy = lower
```

Проверка: `make dbt-parse` → код 0 и предупреждение `Configuration paths exist in your dbt_project.yml file which do not apply to any resources` (моделей ещё нет).

### A2. Seed и макрос D14

Seed это копия сэмпла с переводом строк LF (в `data/sample` CRLF, байты данных те же). Из `data/raw` в git ничего не идёт.

<!-- exec -->
```bash
mkdir -p dbt/seeds
tr -d '\r' < data/sample/product_category_name_translation.csv > dbt/seeds/category_translation.csv
```

Проверка: `wc -l dbt/seeds/category_translation.csv` → `72` (заголовок и 71 строка); `head -1` → `product_category_name,product_category_name_english`.

<!-- file: dbt/seeds/_seeds.yml -->
```yaml
seeds:
  - name: category_translation
    description: >
      Portuguese product category to English, 71 rows, a copy of
      data/sample/product_category_name_translation.csv (D5).
    config:
      column_types:
        product_category_name: varchar
        product_category_name_english: varchar
    columns:
      - name: product_category_name
        data_tests: [unique, not_null]
```

dbt-trino 1.10.4 на каждой загрузке seed делает DROP и CREATE. Макрос проекта с тем же именем перехватывает dispatch и возвращает поведение dbt-core: TRUNCATE и INSERT, DROP только при `--full-refresh` (D14).

<!-- file: dbt/macros/trino__reset_csv_table.sql -->
```sql
{#- dbt-trino 1.10 drops and recreates a seed table on every load. On Lakekeeper a drop is a soft
    delete that keeps the files for 7 days, so each dbt build would leave a dropped copy behind.
    Without --full-refresh, fall back to dbt's own behaviour: truncate the table, insert again
    (D14). -#}
{% macro trino__reset_csv_table(model, full_refresh, old_relation, agate_table) %}
    {{ return(dbt.default__reset_csv_table(model, full_refresh, old_relation, agate_table)) }}
{% endmacro %}
```

<!-- file: dbt/tests/generic/unique_combination.sql -->
```sql
{% test unique_combination(model, columns) %}

select
    {{ columns | join(', ') }},
    count(*) as copies
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1

{% endtest %}
```

### A3. Sources и staging

Freshness только у четырёх таблиц, которые меняет реплеер; `customers`, `sellers`, `products` загружены один раз. Staging ничего не фильтрует и отдаёт `is_deleted` (D4).

<!-- file: dbt/models/staging/_sources.yml -->
```yaml
sources:
  - name: silver
    description: >
      Current state of the source tables, merged from bronze by silver_upsert (ADR-021). Deleted
      rows stay with `_is_deleted = true`; `_updated_at` is when silver merged the row, not a
      business time.
    database: lake
    schema: silver
    loaded_at_field: _updated_at
    tables:
      # Only the replayer's tables get freshness: customers, sellers and products were loaded
      # once, and their _updated_at stays at that first load.
      - name: orders
        freshness: &replayed
          warn_after: {count: 30, period: minute}
          error_after: {count: 2, period: hour}
      - name: order_items
        freshness: *replayed
      - name: payments
        freshness: *replayed
      - name: reviews
        freshness: *replayed
      - name: customers
      - name: sellers
      - name: products
```

<!-- file: dbt/models/staging/stg_orders.sql -->
```sql
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
```

<!-- file: dbt/models/staging/stg_order_items.sql -->
```sql
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
```

<!-- file: dbt/models/staging/stg_payments.sql -->
```sql
select
    order_id,
    payment_sequential,
    payment_type,
    payment_installments,
    payment_value,
    _is_deleted as is_deleted,
    _updated_at as updated_at
from {{ source('silver', 'payments') }}
```

<!-- file: dbt/models/staging/stg_reviews.sql -->
```sql
select
    review_id,
    order_id,
    review_score,
    review_comment_title,
    review_comment_message,
    review_creation_date,
    review_answer_timestamp,
    _is_deleted as is_deleted,
    _updated_at as updated_at
from {{ source('silver', 'reviews') }}
```

<!-- file: dbt/models/staging/stg_customers.sql -->
```sql
select
    customer_id,
    customer_unique_id,
    customer_zip_code_prefix,
    customer_city,
    customer_state,
    _is_deleted as is_deleted,
    _updated_at as updated_at
from {{ source('silver', 'customers') }}
```

<!-- file: dbt/models/staging/stg_sellers.sql -->
```sql
select
    seller_id,
    seller_zip_code_prefix,
    seller_city,
    seller_state,
    _is_deleted as is_deleted,
    _updated_at as updated_at
from {{ source('silver', 'sellers') }}
```

<!-- file: dbt/models/staging/stg_products.sql -->
```sql
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
```

Аргументы generic-тестов пишутся под `arguments:`: dbt-core 1.10.23 иначе выдаёт предупреждение об устаревании.

<!-- file: dbt/models/staging/_staging.yml -->
```yaml
models:
  - name: stg_orders
    description: One row per order in silver, deleted ones included (`is_deleted`, D4).
    columns:
      - name: order_id
        data_tests: [unique, not_null]
  - name: stg_order_items
    description: >
      One row per order item, deleted ones included: the replayer deletes the items of an order
      canceled before shipping, and canceled GMV is counted from them (D4, D8).
    data_tests:
      - unique_combination:
          arguments:
            columns: [order_id, order_item_id]
    columns:
      - name: order_id
        data_tests: [not_null]
      - name: order_item_id
        data_tests: [not_null]
  - name: stg_payments
    description: One row per payment of an order.
    data_tests:
      - unique_combination:
          arguments:
            columns: [order_id, payment_sequential]
    columns:
      - name: order_id
        data_tests: [not_null]
      - name: payment_sequential
        data_tests: [not_null]
  - name: stg_reviews
    description: >
      One row per review and order: review_id repeats across orders in the source
      (oltp/migrations/001_schema.sql). Removed reviews stay with `is_deleted`.
    data_tests:
      - unique_combination:
          arguments:
            columns: [review_id, order_id]
    columns:
      - name: review_id
        data_tests: [not_null]
      - name: order_id
        data_tests: [not_null]
  - name: stg_customers
    description: >
      One row per customer_id. Olist issues a customer_id per order; the person is
      customer_unique_id (D3).
    columns:
      - name: customer_id
        data_tests: [unique, not_null]
  - name: stg_sellers
    description: One row per seller.
    columns:
      - name: seller_id
        data_tests: [unique, not_null]
  - name: stg_products
    description: One row per product; `lenght` columns renamed to `length`.
    columns:
      - name: product_id
        data_tests: [unique, not_null]
```

### A4. Intermediate и ядро

Все соединения от заказа `left join`: у 765 заказов нет живых позиций, `inner join` их потерял бы. Агрегаты через `coalesce(..., 0)`.

<!-- file: dbt/models/intermediate/int_orders_enriched.sql -->
```sql
-- Grain: order_id. Every join starts from the order and is a left join: an order without items
-- (canceled or unavailable before anything was picked) must stay, with zero counts.
with

orders as (
    select
        order_id,
        customer_id,
        order_status,
        order_purchase_timestamp,
        order_approved_at,
        order_delivered_carrier_date,
        order_delivered_customer_date,
        order_estimated_delivery_date,
        updated_at
    from {{ ref('stg_orders') }}
    where not is_deleted
),

customers as (
    select
        customer_id,
        customer_unique_id,
        customer_city,
        customer_state
    from {{ ref('stg_customers') }}
    where not is_deleted
),

-- Values count live items only; updated_at covers deleted ones too, since deleting an item
-- changes the order for the marts.
items as (
    select
        order_id,
        count_if(not is_deleted) as items_count,
        sum(case when not is_deleted then price end) as items_value,
        sum(case when not is_deleted then freight_value end) as freight_value,
        max(updated_at) as updated_at
    from {{ ref('stg_order_items') }}
    group by order_id
),

payments as (
    select
        order_id,
        sum(payment_value) as payment_value,
        max(payment_installments) as payment_installments_max,
        max(updated_at) as updated_at
    from {{ ref('stg_payments') }}
    where not is_deleted
    group by order_id
)

select
    o.order_id,
    o.customer_id,
    c.customer_unique_id,
    c.customer_city,
    c.customer_state,
    o.order_status,
    o.order_purchase_timestamp,
    o.order_approved_at,
    o.order_delivered_carrier_date,
    o.order_delivered_customer_date,
    o.order_estimated_delivery_date,
    p.payment_installments_max,
    o.updated_at as order_updated_at,
    i.updated_at as items_updated_at,
    p.updated_at as payments_updated_at,
    coalesce(i.items_count, 0) as items_count,
    coalesce(i.items_value, 0) as items_value,
    coalesce(i.freight_value, 0) as freight_value,
    coalesce(p.payment_value, 0) as payment_value
from orders as o
left join customers as c on o.customer_id = c.customer_id
left join items as i on o.order_id = i.order_id
left join payments as p on o.order_id = p.order_id
```

<!-- file: dbt/models/intermediate/_intermediate.yml -->
```yaml
models:
  - name: int_orders_enriched
    description: >
      One row per live order with its customer, aggregates of live items and payments, and the
      processing times of the order, its items (deleted ones too) and payments.
    columns:
      - name: order_id
        data_tests: [unique, not_null]
```

`greatest()` в Trino возвращает null, если null хотя бы один аргумент; `updated_at` это водяной знак W3-T02, поэтому каждый аргумент через `coalesce`.

<!-- file: dbt/models/marts/fct_orders.sql -->
```sql
-- Grain: order_id, live orders of silver. Dates come from order_purchase_timestamp (business
-- time); updated_at is processing time and serves only as the watermark of mart_daily_sales.
select
    order_id,
    customer_id,
    customer_unique_id,
    customer_city,
    customer_state,
    order_status,
    order_purchase_timestamp,
    order_approved_at,
    order_delivered_carrier_date,
    order_delivered_customer_date,
    order_estimated_delivery_date,
    items_count,
    items_value,
    freight_value,
    payment_value,
    payment_installments_max,
    cast(order_purchase_timestamp as date) as purchase_date,
    order_status = 'delivered' as is_delivered,
    order_status = 'canceled' as is_canceled,
    date_diff(
        'day',
        cast(order_purchase_timestamp as date),
        cast(order_delivered_customer_date as date)
    ) as delivery_days,
    -- Null unless delivered: lateness is defined only for a delivered order (D8).
    case
        when order_status = 'delivered'
            then
                cast(order_delivered_customer_date as date)
                > cast(order_estimated_delivery_date as date)
    end as is_late,
    -- greatest() is null if any argument is: an order without items or payments still needs one.
    greatest(
        order_updated_at,
        coalesce(items_updated_at, order_updated_at),
        coalesce(payments_updated_at, order_updated_at)
    ) as updated_at
from {{ ref('int_orders_enriched') }}
```

<!-- file: dbt/models/marts/fct_order_items.sql -->
```sql
-- Grain: order_id, order_item_id. Deleted items stay with is_deleted: canceled GMV counts them
-- (D4, D8). The left join keeps an item whose order is missing; the relationships test fails then.
select
    i.order_id,
    i.order_item_id,
    i.product_id,
    i.seller_id,
    i.shipping_limit_date,
    i.price,
    i.freight_value,
    i.is_deleted,
    o.order_status,
    o.purchase_date,
    p.product_category,
    s.seller_state,
    i.updated_at
from {{ ref('stg_order_items') }} as i
left join {{ ref('fct_orders') }} as o on i.order_id = o.order_id
left join {{ ref('dim_products') }} as p on i.product_id = p.product_id
left join {{ ref('dim_sellers') }} as s on i.seller_id = s.seller_id
```

<!-- file: dbt/models/marts/dim_customers.sql -->
```sql
-- Grain: customer_unique_id, the person (D3). Only customers with an order in silver: the loader
-- puts every customer into shop.customers up front, including those of orders still to come.
with

orders as (
    select
        order_id,
        customer_id,
        order_purchase_timestamp
    from {{ ref('stg_orders') }}
    where not is_deleted
),

customers as (
    select
        customer_id,
        customer_unique_id,
        customer_zip_code_prefix,
        customer_city,
        customer_state
    from {{ ref('stg_customers') }}
    where not is_deleted
),

customer_orders as (
    select
        c.customer_unique_id,
        c.customer_zip_code_prefix,
        c.customer_city,
        c.customer_state,
        o.order_purchase_timestamp,
        -- The address of the latest order; equal purchase times go to the larger customer_id.
        row_number() over (
            partition by c.customer_unique_id
            order by o.order_purchase_timestamp desc, c.customer_id desc, o.order_id desc
        ) as recency
    from orders as o
    inner join customers as c on o.customer_id = c.customer_id
),

stats as (
    select
        customer_unique_id,
        count(*) as orders_count,
        min(order_purchase_timestamp) as first_order_ts,
        max(order_purchase_timestamp) as last_order_ts
    from customer_orders
    group by customer_unique_id
)

select
    s.customer_unique_id,
    latest.customer_zip_code_prefix,
    latest.customer_city,
    latest.customer_state,
    s.orders_count,
    s.first_order_ts,
    s.last_order_ts,
    s.orders_count > 1 as is_repeat
from stats as s
inner join customer_orders as latest
    on s.customer_unique_id = latest.customer_unique_id and latest.recency = 1
```

<!-- file: dbt/models/marts/dim_products.sql -->
```sql
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
```

<!-- file: dbt/models/marts/dim_sellers.sql -->
```sql
select
    seller_id,
    seller_zip_code_prefix,
    seller_city,
    seller_state
from {{ ref('stg_sellers') }}
where not is_deleted
```

<!-- file: dbt/models/marts/_core.yml -->
```yaml
models:
  - name: fct_orders
    description: >
      One row per live order. 765 orders have no live item (2026-10-09): 735 never had one, 30
      lost all of them when the order was canceled.
    columns:
      - name: order_id
        data_tests: [unique, not_null]
      - name: customer_unique_id
        description: The person; customer_id is issued per order (D3).
        data_tests:
          - not_null
          - relationships:
              arguments:
                to: ref('dim_customers')
                field: customer_unique_id
      - name: is_late
        description: >
          Delivered after the estimated date, by calendar date. Null unless the order is
          delivered and has a delivery date.
      - name: delivery_days
        description: Calendar days from purchase to delivery to the customer.
      - name: items_value
        description: Sum of price over live items.
      - name: updated_at
        description: >
          The latest silver merge time of the order, its items (deleted ones too) and payments.
          Processing time: the watermark of mart_daily_sales, never a date for reports.
  - name: fct_order_items
    description: One row per order item, deleted items included (`is_deleted`).
    data_tests:
      - unique_combination:
          arguments:
            columns: [order_id, order_item_id]
    columns:
      - name: order_id
        data_tests:
          - not_null
          - relationships:
              arguments:
                to: ref('fct_orders')
                field: order_id
      - name: order_item_id
        data_tests: [not_null]
      - name: product_id
        data_tests:
          - relationships:
              arguments:
                to: ref('dim_products')
                field: product_id
      - name: seller_id
        data_tests:
          - relationships:
              arguments:
                to: ref('dim_sellers')
                field: seller_id
  - name: dim_customers
    description: >
      One row per person (customer_unique_id) with at least one order in silver (D3); the address
      is the one of the latest order.
    columns:
      - name: customer_unique_id
        data_tests: [unique, not_null]
  - name: dim_products
    description: One row per product; product_category is English, else Portuguese, else unknown.
    columns:
      - name: product_id
        data_tests: [unique, not_null]
  - name: dim_sellers
    description: One row per seller.
    columns:
      - name: seller_id
        data_tests: [unique, not_null]
```

Проверка: `make dbt-parse` → код 0; `cd dbt && uv run dbt ls --profiles-dir . --target ci --resource-type model | grep -c marketplace` → `13`.

### A5. Makefile и CI

<!-- edit: Makefile -->
Найти:
```makefile
	uv run yamllint -c .yamllint docker observability airflow .github
	@paths=$$(ls -d dbt/models oltp/migrations 2>/dev/null || true); \
	  [ -n "$$paths" ] && uv run sqlfluff lint $$paths || echo "no SQL directories yet"
	$(COMPOSE) --profile '*' config -q
```
Заменить на:
```makefile
	uv run yamllint -c .yamllint docker observability airflow .github
	uv run sqlfluff lint oltp/migrations
	cd dbt && uv run sqlfluff lint models macros tests
	$(COMPOSE) --profile '*' config -q
```

<!-- edit: Makefile -->
Найти:
```makefile
dbt-parse: ## dbt parse without a warehouse
	cd dbt && uv run dbt parse --profiles-dir . --target ci
```
Заменить на:
```makefile
dbt-parse: ## dbt parse without a warehouse
	cd dbt && uv run dbt parse --profiles-dir . --target ci

dbt-build: ## seed, run and test lake.gold through Trino on 127.0.0.1:8080 (needs make start)
	cd dbt && uv run dbt build --profiles-dir . --target dev
```

<!-- edit: Makefile -->
Найти:
```makefile
test-spark dbt-parse
```
Заменить на:
```makefile
test-spark dbt-parse dbt-build
```

<!-- edit: .github/workflows/ci.yml -->
Найти:
```yaml
      # dbt/models is still empty, and git does not carry empty directories, so a fresh
      # checkout has no such path. Lint whatever SQL directories the checkout actually has.
      - name: sqlfluff
        run: |
          paths=$(ls -d dbt/models oltp/migrations 2>/dev/null || true)
          [ -n "$paths" ] && uv run sqlfluff lint $paths || echo "no SQL directories yet"
```
Заменить на:
```yaml
      - run: uv run sqlfluff lint oltp/migrations
      # dbt/.sqlfluff switches to the jinja templater, which sqlfluff takes only from the
      # working directory.
      - run: uv run sqlfluff lint models macros tests
        working-directory: dbt
      - run: make dbt-parse
```

<!-- edit: .github/workflows/ci.yml -->
Найти:
```yaml
# Re-enable as the pieces land: `dbt parse` with W3-T01, the airflow image build with W3-T04,
# hadolint with W5-T02.
```
Заменить на:
```yaml
# Re-enable as the pieces land: the airflow image build and hadolint with W5-T02.
```

### A6. Статические проверки

```bash
make lint                       # код 0, в выводе sqlfluff для oltp/migrations и для dbt
make test 2>&1 | tail -1        # 127 passed, 62 skipped
make dbt-parse; echo "exit $?"  # exit 0
```

### A7. Документация

<!-- file: dbt/README.md -->
```markdown
# dbt

dbt-trino project `marketplace` over `lake.silver`, writing every model to `lake.gold` (Trino on
Lakekeeper). Run it from the repo root: `make dbt-parse` (no warehouse), `make dbt-build` (seed,
run, test; needs `make start`).

- `models/staging`: `stg_<table>` views over the seven silver tables. Columns renamed, no filter:
  deleted rows stay with `is_deleted`, and each consumer decides (D4 of
  `docs/planning/07-w3-spec.md`). `updated_at` is when silver merged the row, not a business time.
- `models/intermediate`: `int_orders_enriched` (order, customer, live item and payment
  aggregates).
- `models/marts`: `fct_orders`, `fct_order_items` (deleted items included), `dim_customers`
  (grain `customer_unique_id`, D3), `dim_products`, `dim_sellers`.
- `seeds/category_translation.csv`: Portuguese category to English, 71 rows. Geolocation is not
  modelled (D5).
- `macros/trino__reset_csv_table.sql`: a seed reload truncates the table instead of dropping it
  (D14).
- `tests/generic/unique_combination.sql`: uniqueness of a composite key, without packages.
- `profiles.yml`: target `dev` (Trino at `TRINO_HOST`:`TRINO_PORT`, default 127.0.0.1:8080) and
  `ci` (parse only). No secrets: Trino has no authentication and listens on 127.0.0.1.

Every table model is `CREATE OR REPLACE TABLE` (`on_table_exists: replace`, D6): the rename
default would drop a backup table on every run, and on Lakekeeper a drop keeps the files for 7
days.

SQL is linted from this directory: `cd dbt && uv run sqlfluff lint models macros tests`.
```

<!-- edit: ARCHITECTURE.md -->
Найти:
```markdown
   soft (`_deleted = true`). Late events never overwrite newer state. Re-running a batch yields
```
Заменить на:
```markdown
   soft (`_is_deleted = true`). Late events never overwrite newer state. Re-running a batch yields
```

<!-- edit: docs/planning/00-mini-architecture-review.md -->
Найти:
```markdown
Geolocation и перевод категорий грузятся как справочники в dbt seeds.
```
Заменить на:
```markdown
Перевод категорий грузится справочником в dbt seed (71 строка); geolocation не моделируется, витрины на уровне штата (D5 спеки W3).
```

<!-- edit: docs/planning/00-mini-architecture-review.md -->
Найти:
```markdown
удалённые строки фильтрует dbt, где именно, решает спека W3 (D4).
```
Заменить на:
```markdown
staging отдаёт удалённые строки с `is_deleted`, фильтрует модель-потребитель; `fct_order_items` хранит удалённые позиции, из них считается отменённый GMV (D4 спеки W3).
```

## Часть B. Живая проверка

Предусловия: стек поднят `make start`; реплеер не играет; Airflow не запущен.

Список soft-deleted таблиц Lakekeeper понадобится несколько раз; команда печатает `namespace.name` всех удалённых за 7 дней:

```bash
lk=http://127.0.0.1:8181
wid=$(curl -s "$lk/catalog/v1/config?warehouse=lake" | python3 -c 'import json, sys; print(json.load(sys.stdin)["defaults"]["prefix"])')
soft_deleted() { curl -s "$lk/management/v1/warehouse/$wid/deleted-tabulars" | python3 -c '
import json, sys
for t in json.load(sys.stdin)["tabulars"]:
    ns = t.get("namespace")
    print(".".join(ns) if isinstance(ns, list) else ns, t.get("name"))'; }
soft_deleted   # до первого прогона: пусто
```

`$COMPOSE` ниже: `docker compose --env-file .env -f docker/compose.yaml`.

### B1. Сначала views

Trino обещает views в REST-каталоге по Iceberg View spec, Lakekeeper 0.13.6 отдаёт эндпоинты views (проверено 09.10), но вместе их не запускали.

```bash
cd dbt && uv run dbt run --profiles-dir . --target dev --select stg_customers; cd ..
$COMPOSE exec -T trino trino --catalog lake --execute "select count(*) from gold.stg_customers"
```
Ожидается: `OK created sql view model gold.stg_customers`, затем `"99441"`. Ошибка создания view: стоп, решение владельца (обходной путь из спеки: staging как `ephemeral`).

### B2. Первый `make dbt-build`

```bash
make dbt-build 2>&1 | tail -3
```
Ожидается: `Completed successfully` и `Done. PASS=<n> WARN=0 ERROR=0 SKIP=0 NO-OP=0 TOTAL=<n>`, где `<n>` равно 51 (13 моделей, 1 seed, 37 тестов). Иное `TOTAL`: проверь, что все файлы A1-A4 на месте.

### B3. Числа равны silver

```bash
q() { $COMPOSE exec -T trino trino --catalog lake --output-format TSV --execute "$1"; }
q "select count(*) from gold.fct_orders"
q "select count(*) from silver.orders where not _is_deleted"
q "select count(*) from gold.dim_customers"
q "select count(distinct c.customer_unique_id) from silver.orders o join silver.customers c on c.customer_id = o.customer_id where not o._is_deleted and not c._is_deleted"
q "select count(*) from gold.fct_orders where items_count = 0"
```
Ожидается: первые два числа равны (09.10: 94 406), третье и четвёртое равны (09.10: 91 259), пятое около 765. Если пятое другое, исправь число и дату в описании `fct_orders` в `dbt/models/marts/_core.yml` и повтори `make dbt-parse`.

### B4. Второй прогон без DROP

```bash
q 'select count(*) from gold."fct_orders$snapshots"'
q 'select count(*) from gold."category_translation$snapshots"'
make dbt-build 2>&1 | tail -1
q 'select count(*) from gold."fct_orders$snapshots"'
q 'select count(*) from gold."category_translation$snapshots"'
q "select count(*) from gold.category_translation"
soft_deleted
```
Ожидается: снапшотов `fct_orders` на 1 больше (`CREATE OR REPLACE` в той же таблице); снапшотов `category_translation` больше на 2 (TRUNCATE и INSERT вместо DROP, D14); в seed 71 строка; `soft_deleted` пуст. В `soft_deleted` появилось что-то из `gold`: стоп, D14 или D6 не работает, в отчёт имя таблицы.

### B5. Финальные проверки

```bash
make lint && make test 2>&1 | tail -1 && make dbt-parse
```

## Готово, когда

- `make dbt-parse` код 0 локально; в CI шаг `make dbt-parse` есть.
- `make dbt-build` код 0, все тесты PASS (B2).
- `fct_orders` равен живым строкам `silver.orders`; `dim_customers` равен числу `customer_unique_id` живых заказов (B3).
- Заказов с `items_count = 0` около 765, число и дата записаны в описание `fct_orders` (B3).
- Повторный `make dbt-build`: снапшотов `fct_orders` на 1 больше, ничего из `gold` в soft-deleted (B4).
- `make lint` зелёный, sqlfluff разбирает `dbt/models` без ошибок.

## Если не так

| Симптом | Причина | Что делать |
|---|---|---|
| `make lint`: `Templater cannot be set in a .sqlfluff file in a subdirectory` | sqlfluff запущен из корня по `dbt/models` | шаг A5, первая правка Makefile |
| sqlfluff `ST06`, `LT05`, `RF02` в своём SQL | SQL перепечатан не как в плане | сравни с блоком плана; не отключай правила |
| `dbt parse`: `MissingArgumentsPropertyInGenericTestDeprecation` | тест без `arguments:` | перенеси аргументы под `arguments:` |
| B1: `Catalog ... does not support views` или похожее | views в связке Trino и Lakekeeper не работают | стоп, решение владельца |
| B2: `Database Error ... Table 'lake.silver.<t>' does not exist` | Trino не видит каталог | `make start`, повтори; снова: стоп |
| B2: тест `relationships` FAIL | расхождение данных | стоп, в отчёт скомпилированный SQL теста из `dbt/target/compiled` и его результат в Trino |
| B4: в `soft_deleted` есть `gold category_translation` | макрос D14 не подхватился | проверь путь `dbt/macros/trino__reset_csv_table.sql` и имя макроса; не помогло: стоп |
| B4: `TRUNCATE` не поддерживается | Iceberg-коннектор отказал | стоп, владелец выбирает альтернативу D14 |

## Ловушки

- `customer_id` в Olist свой у каждого заказа: по нему repeat rate ноль (D3).
- Фильтр `not is_deleted` в staging выбросит позиции отменённых заказов, а из них считается отменённый GMV (D4).
- `_updated_at` это время обработки в silver. Даты витрин только от `order_purchase_timestamp`.
- dbt пишет `target/` и `logs/` в каталог проекта; на хосте это не мешает (`.gitignore`), в Airflow пути уходят в `/tmp` (W3-T05a).

## Blast radius и пайплайн

Создаёт namespace `gold` в Lakekeeper и таблицы в нём. Модели без DROP: таблицы `CREATE OR REPLACE`, views `create or replace view`; повтор seed это TRUNCATE (D13, D14). Bronze и silver только читаются, checkpoint и offsets не затронуты. Ручной DROP чего угодно в `gold` только с «ок» владельца.

## Отчёт: что собрать

Вывод B1, хвост B2, пять чисел B3, числа снапшотов и вывод `soft_deleted` из B4, `git diff --stat`.

## Коммит

```bash
git add dbt Makefile .github/workflows/ci.yml ARCHITECTURE.md docs/planning/00-mini-architecture-review.md
git status --short dbt   # только файлы из списка; dbt/target и dbt/logs в .gitignore
git commit -m "dbt: project, staging and core models"
```
