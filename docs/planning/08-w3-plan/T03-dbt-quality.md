# W3-T03 DQ-тесты на источник, freshness, docs и глоссарий

> До первого шага прочитай `README.md` этой папки: протокол, стоп-условия, отчёт.

| | |
|---|---|
| Спека | `07-w3-spec.md`, карточка W3-T03; решение D8 |
| Коммит | `dbt: source anomaly tests, docs and glossary` |
| Оценка | A: 1 ч; B: 0.5 ч |
| Часть A | любая среда |
| Часть B | только локально; порция реплея 30 с (около 6 виртуальных часов) |

## Цель

Тест отличает «сломался пайплайн» (error) от «так в источнике» (warn с порогом и причиной). У каждой известной аномалии Olist singular-тест с `warn_if: '>0'` и `error_if` из переменной dbt выше замера; `accepted_values` статусов как контракт источника; глоссарий D8 в dbt docs.

Почему не `severity: warn`: с ним dbt-core 1.10.23 игнорирует `error_if`, тест не падает никогда (`dbt/task/test.py`: ошибка только при `severity == ERROR`).

## Вход

```bash
git log --oneline -1                               # коммит W3-T02
ls dbt/tests                                       # _tests.yml, generic, тест полного пересчёта
```

## Файлы

- Создать в `dbt/`: `tests/assert_payments_match_order_value.sql`, `tests/assert_delivered_not_before_carrier.sql`, `tests/assert_products_have_category.sql`, `tests/assert_categories_have_translation.sql`, `models/docs.md`.
- Перезаписать целиком: `dbt/tests/_tests.yml`, `dbt/models/staging/_staging.yml`, `dbt/models/marts/_core.yml`, `dbt/models/marts/_marts.yml`, `dbt/README.md`.
- Изменить: `Makefile`.

## Часть A. Код

### A1. Тесты на аномалии источника

Числа в комментариях и описаниях замерены 09.10 на живом gold; часть B их перемеряет. Платежи считаются только у заказов не `canceled` и не `unavailable`: у них позиции удалены или их не было, а платежи остались (по всем заказам расхождений 1 045, по остальным 287).

<!-- file: dbt/tests/assert_payments_match_order_value.sql -->
```sql
-- Known in the source: payments differ from items plus freight by more than 0.01 for 287 orders
-- that are neither canceled nor unavailable (2026-10-09). Canceled and unavailable orders are
-- left out: their items were deleted or never existed, their payments were not. warn above 0,
-- error above the threshold: growth past it means our pipeline lost items or payments.
{{
    config(
        warn_if='>0',
        error_if='>' ~ var('payments_mismatch_error_if', 1000)
    )
}}

select
    order_id,
    order_status,
    payment_value,
    items_value,
    freight_value
from {{ ref('fct_orders') }}
where
    order_status not in ('canceled', 'unavailable')
    and abs(payment_value - (items_value + freight_value)) > 0.01
```

<!-- file: dbt/tests/assert_delivered_not_before_carrier.sql -->
```sql
-- Known in the source: 23 orders reached the customer before the carrier got them (2026-10-09).
{{
    config(
        warn_if='>0',
        error_if='>' ~ var('delivered_before_carrier_error_if', 100)
    )
}}

select
    order_id,
    order_delivered_carrier_date,
    order_delivered_customer_date
from {{ ref('fct_orders') }}
where order_delivered_customer_date < order_delivered_carrier_date
```

<!-- file: dbt/tests/assert_products_have_category.sql -->
```sql
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
```

<!-- file: dbt/tests/assert_categories_have_translation.sql -->
```sql
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
```

<!-- file: dbt/tests/_tests.yml -->
```yaml
data_tests:
  - name: assert_mart_daily_sales_matches_full_recompute
    description: >
      The incremental mart_daily_sales equals int_daily_sales, its full recompute (D7). Error on
      any row.
  - name: assert_payments_match_order_value
    description: >
      Source anomaly. Payments differ from items plus freight by more than 0.01 for 287 orders
      that are neither canceled nor unavailable (2026-10-09). warn above 0, error above
      var payments_mismatch_error_if (default 1000, about 1% of orders).
  - name: assert_delivered_not_before_carrier
    description: >
      Source anomaly. 23 orders reached the customer before the carrier got them (2026-10-09).
      warn above 0, error above var delivered_before_carrier_error_if (default 100).
  - name: assert_products_have_category
    description: >
      Source anomaly. 610 products without a category (2026-10-09); products never change during
      the replay. warn above 0, error above var products_without_category_error_if (default 700).
  - name: assert_categories_have_translation
    description: >
      Source anomaly. 2 categories without an English name (2026-10-09). warn above 0, error
      above var untranslated_categories_error_if (default 5).
```

### A2. Статусы, глоссарий, описания

`accepted_values` со severity error: новый статус от реплеера это нарушение контракта источника, а не аномалия.

<!-- file: dbt/models/staging/_staging.yml -->
```yaml
models:
  - name: stg_orders
    description: One row per order in silver, deleted ones included (`is_deleted`, D4).
    columns:
      - name: order_id
        data_tests: [unique, not_null]
      - name: order_status
        description: >
          A contract of the source: a status outside the eight of the dataset is an error, not
          a warning.
        data_tests:
          - accepted_values:
              arguments:
                values:
                  - created
                  - approved
                  - invoiced
                  - processing
                  - shipped
                  - delivered
                  - canceled
                  - unavailable
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

<!-- file: dbt/models/docs.md -->
```markdown
{% docs purchase_date %}
The date of `order_purchase_timestamp`: business time, shifted so that the last day of the
dataset is "today". Every date in the marts is a purchase date, never a processing time.
{% enddocs %}

{% docs gmv %}
GMV: the sum of `price` over live (not deleted) items of orders whose status is neither
`canceled` nor `unavailable`. Freight is a separate metric, `freight_value`.
{% enddocs %}

{% docs aov %}
AOV: GMV divided by the number of orders that are neither `canceled` nor `unavailable` and have at
least one live item.
{% enddocs %}

{% docs canceled_gmv %}
Canceled GMV: the sum of `price` over every item of `canceled` orders, deleted items included
(the replayer deletes the items of an order canceled before shipping).
{% enddocs %}

{% docs on_time_rate %}
On-time rate: the share of `delivered` orders with
`date(order_delivered_customer_date) <= date(order_estimated_delivery_date)`. A delivered order
without a delivery date counts as delivered and not on time.
{% enddocs %}

{% docs cancellation_rate %}
Cancellation rate: the share of `canceled` orders among all orders of the same purchase date
(in mart_seller_performance: of the same seller and purchase month).
{% enddocs %}

{% docs review_score %}
Review score: the average `review_score` of reviews that were not removed.
{% enddocs %}
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
      - name: purchase_date
        description: "{{ doc('purchase_date') }}"
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

<!-- file: dbt/models/marts/_marts.yml -->
```yaml
models:
  - name: mart_daily_sales
    description: >
      Sales per purchase date and seller state, incremental: delete+insert of every purchase date
      with an order changed since the last run (D7). An order counts in the state of each of its
      sellers, deleted items included; an order that never had an item counts in 'unknown'. So
      orders_count summed over states can exceed the orders of the day. Check against silver:
      `select sum(i.price) from lake.silver.order_items i join lake.silver.orders o
      on i.order_id = o.order_id where not i._is_deleted and not o._is_deleted
      and o.order_status not in ('canceled', 'unavailable')` equals sum(gmv)
      (12 845 420.13 on 2026-10-09).
    data_tests:
      - unique_combination:
          arguments:
            columns: [purchase_date, seller_state]
    columns:
      - name: purchase_date
        description: "{{ doc('purchase_date') }}"
        data_tests: [not_null]
      - name: seller_state
        data_tests: [not_null]
      - name: gmv
        description: "{{ doc('gmv') }}"
      - name: canceled_gmv
        description: "{{ doc('canceled_gmv') }}"
      - name: source_updated_at
        description: The latest fct_orders.updated_at among the orders of the row; the watermark.
  - name: mart_delivery_sla
    description: Delivery against the estimated date, per purchase month and customer state.
    data_tests:
      - unique_combination:
          arguments:
            columns: [purchase_month, customer_state]
    columns:
      - name: purchase_month
        data_tests: [not_null]
      - name: customer_state
        data_tests: [not_null]
      - name: on_time_rate
        description: "{{ doc('on_time_rate') }}"
      - name: p90_delivery_days
        description: approx_percentile of delivery_days over delivered orders.
  - name: mart_seller_performance
    description: >
      Orders, GMV, reviews, lateness and cancellations per seller and purchase month. A seller's
      orders are those with any of its items, deleted items included.
    data_tests:
      - unique_combination:
          arguments:
            columns: [seller_id, purchase_month]
    columns:
      - name: seller_id
        data_tests: [not_null]
      - name: purchase_month
        data_tests: [not_null]
      - name: gmv
        description: "{{ doc('gmv') }}"
      - name: avg_review_score
        description: "{{ doc('review_score') }}"
      - name: cancellation_rate
        description: "{{ doc('cancellation_rate') }}"
```

### A3. `make dbt-docs` и README

<!-- edit: Makefile -->
Найти:
```makefile
dbt-build: ## seed, run and test lake.gold through Trino on 127.0.0.1:8080 (needs make start)
	cd dbt && uv run dbt build --profiles-dir . --target dev
```
Заменить на:
```makefile
dbt-build: ## seed, run and test lake.gold through Trino on 127.0.0.1:8080 (needs make start)
	cd dbt && uv run dbt build --profiles-dir . --target dev

dbt-docs: ## dbt docs generate into dbt/target (needs Trino)
	cd dbt && uv run dbt docs generate --profiles-dir . --target dev
```

<!-- edit: Makefile -->
Найти:
```makefile
dbt-parse dbt-build
```
Заменить на:
```makefile
dbt-parse dbt-build dbt-docs
```

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
  aggregates) and `int_daily_sales` (daily sales over every date, the full recompute).
- `models/marts`: `fct_orders`, `fct_order_items` (deleted items included), `dim_customers`
  (grain `customer_unique_id`, D3), `dim_products`, `dim_sellers`, `mart_daily_sales`
  (incremental, delete+insert by purchase date, D7), `mart_delivery_sla`,
  `mart_seller_performance`.
- `seeds/category_translation.csv`: Portuguese category to English, 71 rows. Geolocation is not
  modelled (D5).
- `macros`: `safe_divide`; `trino__reset_csv_table`, which makes a seed reload truncate the table
  instead of dropping it (D14).
- `tests/generic/unique_combination.sql`: uniqueness of a composite key, without packages.
- `profiles.yml`: target `dev` (Trino at `TRINO_HOST`:`TRINO_PORT`, default 127.0.0.1:8080) and
  `ci` (parse only). No secrets: Trino has no authentication and listens on 127.0.0.1.

Every table model is `CREATE OR REPLACE TABLE` (`on_table_exists: replace`, D6): the rename
default would drop a backup table on every run, and on Lakekeeper a drop keeps the files for 7
days. The only drops dbt does are its own: the temporary `mart_daily_sales__dbt_tmp` on every
incremental run (D13).

SQL is linted from this directory: `cd dbt && uv run sqlfluff lint models macros tests`.

Tests: keys and relationships on every model; `assert_mart_daily_sales_matches_full_recompute`
(D7); four tests on known anomalies of the source (`tests/assert_*.sql`), each warning above 0
and failing above a threshold from a dbt var, with the number and the date in its description
(`tests/_tests.yml`). `make dbt-docs` writes the docs, the metric glossary of `models/docs.md`
included, to `target/`.

Freshness: `dbt source freshness` checks `orders`, `order_items`, `payments` and `reviews`, the
tables the replayer changes (`_updated_at`; warn after 30 minutes, error after 2 hours).
`customers`, `sellers` and `products` were loaded once and are not checked. With the replay
stopped, a warn after 30 minutes and an error with exit code 1 after 2 hours mean "no traffic",
not a broken pipeline.
```

### A4. Статические проверки

```bash
make lint && make test 2>&1 | tail -1 && make dbt-parse
cd dbt && uv run dbt ls --profiles-dir . --target ci --resource-type test | grep -c marketplace; cd ..   # 53
```

## Часть B. Живая проверка

Предусловия: W3-T02 B прошла; стек поднят; реплеер не играет; Airflow не запущен. `q` как в W3-T01 B.

### B1. Замер аномалий на живом gold

```bash
q "select count(*) from gold.fct_orders where order_status not in ('canceled', 'unavailable') and abs(payment_value - (items_value + freight_value)) > 0.01"
q "select count(*) from gold.fct_orders where order_delivered_customer_date < order_delivered_carrier_date"
q "select count(*) from gold.dim_products where product_category_name is null"
q "select count(distinct p.product_category_name) from gold.dim_products p left join gold.category_translation t on p.product_category_name = t.product_category_name where p.product_category_name is not null and t.product_category_name is null"
```
Ожидается около 287, 23, 610, 2. Другие числа: замени их и дату в комментарии теста и в `dbt/tests/_tests.yml`. Число выше порога `error_if` по умолчанию (1000, 100, 700, 5): стоп, это поломка у нас, не в источнике.

### B2. Сборка

```bash
make dbt-build 2>&1 | tail -1
```
Ожидается: `Done. PASS=67 WARN=4 ERROR=0 SKIP=0 NO-OP=0 TOTAL=71`. Четыре WARN это тесты аномалий, у каждого в описании число, дата и причина.

### B3. Freshness сразу после трафика

```bash
make replay-burst SECONDS=30
make verify
cd dbt && uv run dbt source freshness --profiles-dir .; echo "exit $?"; cd ..
```
Ожидается: `verify ok`; freshness PASS по `orders`, `order_items`, `payments`, `reviews` и `exit 0`; у `customers`, `sellers`, `products` freshness не проверяется. Если за порцию не поменялась одна из четырёх таблиц, у неё WARN и `exit 0`: это допустимо, запиши в отчёт.

### B4. Тест умеет падать

```bash
cd dbt
uv run dbt test --profiles-dir . --select assert_payments_match_order_value --vars '{payments_mismatch_error_if: 0}'; echo "exit $?"
uv run dbt test --profiles-dir . --select assert_payments_match_order_value; echo "exit $?"
cd ..
```
Ожидается: первый `ERROR` и `exit 1`, второй `WARN` и `exit 0`.

### B5. Docs

```bash
make dbt-docs
ls dbt/target/index.html
python3 -c "import json; d = json.load(open('dbt/target/catalog.json')); print(sorted(k.split('.')[-1] for k in d['nodes']))"
```
Ожидается: файл есть; в списке 17 моделей и seed `category_translation`.

## Готово, когда

- `make dbt-build` код 0; WARN только у четырёх тестов аномалий, у каждого число, дата и причина (B2).
- Сразу после порции реплея и merge `dbt source freshness` код 0 и PASS по таблицам реплея (B3).
- Тест платежей падает с `--vars '{payments_mismatch_error_if: 0}'` (код 1) и предупреждает без неё (код 0) (B4).
- `make dbt-docs`: есть `dbt/target/index.html`, в `catalog.json` все модели gold (B5).

## Если не так

| Симптом | Причина | Что делать |
|---|---|---|
| B2: `ERROR` у теста аномалии | число выше порога | стоп; число и запрос в отчёт |
| B2: `ERROR` у `accepted_values` | в silver новый статус | стоп; `q "select order_status, count(*) from silver.orders group by 1"` в отчёт |
| B4: первая команда `exit 0` | в тесте `severity: warn` или нет `error_if` | сравни файл с блоком плана |
| B3: `exit 1` у freshness | трафика не было дольше 2 часов | повтори B3 после порции; снова: стоп |

## Ловушки

- Порог на глаз либо вечно красный, либо ничего не ловит: сначала замер (B1), потом порог.
- `accepted_values` с severity warn пропустит новый статус от реплеера; это контракт источника, поэтому error.

## Blast radius и пайплайн

Нет: только тесты и описания. Порция реплея тратит около 6 виртуальных часов.

## Отчёт: что собрать

Четыре числа B1, хвост B2, вывод freshness B3 и `virtual_now`, коды B4, список B5, `git diff --stat`.

## Коммит

```bash
git add dbt Makefile
git commit -m "dbt: source anomaly tests, docs and glossary"
```
