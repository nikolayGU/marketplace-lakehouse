# W3-T02 Витрины: `mart_daily_sales`, `mart_delivery_sla`, `mart_seller_performance`

> До первого шага прочитай `README.md` этой папки: протокол, стоп-условия, отчёт.

| | |
|---|---|
| Спека | `07-w3-spec.md`, карточка W3-T02; решения D7, D8, D13; D15 из README плана |
| Коммит | `dbt: marts and incremental daily sales` |
| Оценка | A: 1 ч; B: 1 ч |
| Часть A | любая среда |
| Часть B | только локально; порция реплея 60 с (около 12 виртуальных часов) |

## Цель

Три витрины по глоссарию D8; `mart_daily_sales` инкрементальная (`delete+insert` по `purchase_date`, D7) и после любой порции реплея равна полному пересчёту.

Устройство инкремента. Полный расчёт по всем датам живёт во view `int_daily_sales`. Витрина берёт из него только даты покупки заказов, изменившихся после её водяного знака (`max(source_updated_at)` по самой витрине), и `delete+insert` заменяет эти даты целиком, по всем штатам. Singular-тест сравнивает витрину с тем же view в обе стороны. Водяной знак корректен, потому что silver ставит `_updated_at = current_timestamp()` в каждом MERGE, а MERGE идут по очереди одним писателем: более поздний коммит всегда получает больший `_updated_at` (проверено по `streaming/spark_jobs/silver_upsert.py` 09.10).

Атрибуция по D15: заказ относится к штату каждого своего продавца, удалённые позиции тоже считаются; заказ без позиций вообще идёт в `unknown`.

## Вход

```bash
git log --oneline -1                                          # коммит W3-T01
ls dbt/models/marts                                           # _core.yml и пять моделей ядра
make dbt-parse >/dev/null 2>&1 && echo ok                     # ok
```

## Файлы

- Создать в `dbt/`: `macros/safe_divide.sql`, `models/intermediate/int_daily_sales.sql`, `models/marts/mart_daily_sales.sql`, `models/marts/mart_delivery_sla.sql`, `models/marts/mart_seller_performance.sql`, `models/marts/_marts.yml`, `tests/assert_mart_daily_sales_matches_full_recompute.sql`, `tests/_tests.yml`.
- Изменить: `dbt/models/intermediate/_intermediate.yml` (дописать), `dbt/README.md` (целиком), `ARCHITECTURE.md`.

## Что задача даёт следующим

- `mart_daily_sales` и тест `assert_mart_daily_sales_matches_full_recompute` (W3-T03 добавит описания, W3-T06 будет мерить снапшоты витрины).
- Макрос `safe_divide(a, b)`: null при нулевом делителе.

## Часть A. Код

### A1. Макрос

<!-- file: dbt/macros/safe_divide.sql -->
```sql
{#- A share or an average that is null, not an error, when the denominator is zero. -#}
{% macro safe_divide(numerator, denominator) -%}
    cast({{ numerator }} as double) / nullif({{ denominator }}, 0)
{%- endmacro %}
```

### A2. Полный расчёт и инкрементальная витрина

<!-- file: dbt/models/intermediate/int_daily_sales.sql -->
```sql
-- Grain: purchase_date, seller_state, over every date: the full recompute that mart_daily_sales
-- filters to the changed dates, and its test compares against.
-- An order counts in the state of every seller among its items, deleted items included, so a
-- canceled order keeps its state and its canceled GMV in the same row. An order that never had
-- an item counts in 'unknown'. orders_count summed over states exceeds the orders of the day
-- when an order has sellers in several states.
with

orders as (
    select
        order_id,
        purchase_date,
        order_status,
        updated_at
    from {{ ref('fct_orders') }}
),

items as (
    select
        order_id,
        price,
        freight_value,
        is_deleted,
        coalesce(seller_state, 'unknown') as seller_state
    from {{ ref('fct_order_items') }}
),

order_states as (
    select distinct
        o.order_id,
        o.purchase_date,
        o.order_status,
        o.updated_at,
        coalesce(i.seller_state, 'unknown') as seller_state
    from orders as o
    left join items as i on o.order_id = i.order_id
),

orders_per_state as (
    select
        purchase_date,
        seller_state,
        count(*) as orders_count,
        count_if(order_status = 'canceled') as canceled_orders,
        max(updated_at) as source_updated_at
    from order_states
    group by purchase_date, seller_state
),

-- GMV: live items of orders that are neither canceled nor unavailable. Canceled GMV: every item
-- of a canceled order, deleted ones included (D8).
items_per_state as (
    select
        o.purchase_date,
        i.seller_state,
        count_if(
            not i.is_deleted and o.order_status not in ('canceled', 'unavailable')
        ) as items_count,
        sum(
            case
                when not i.is_deleted and o.order_status not in ('canceled', 'unavailable')
                    then i.price
            end
        ) as gmv,
        sum(
            case
                when not i.is_deleted and o.order_status not in ('canceled', 'unavailable')
                    then i.freight_value
            end
        ) as freight_value,
        sum(case when o.order_status = 'canceled' then i.price end) as canceled_gmv
    from orders as o
    inner join items as i on o.order_id = i.order_id
    group by o.purchase_date, i.seller_state
)

select
    s.purchase_date,
    s.seller_state,
    s.orders_count,
    s.canceled_orders,
    s.source_updated_at,
    coalesce(i.items_count, 0) as items_count,
    coalesce(i.gmv, 0) as gmv,
    coalesce(i.freight_value, 0) as freight_value,
    coalesce(i.canceled_gmv, 0) as canceled_gmv
from orders_per_state as s
left join items_per_state as i
    on s.purchase_date = i.purchase_date and s.seller_state = i.seller_state
```

<!-- append: dbt/models/intermediate/_intermediate.yml -->
```yaml
  - name: int_daily_sales
    description: >
      mart_daily_sales computed over every date, as a view: the full recompute that the mart
      filters and that its test compares against.
    data_tests:
      - unique_combination:
          arguments:
            columns: [purchase_date, seller_state]
```

В инкрементальной ветке `coalesce` обязателен: у пустой витрины `max(...)` это null, и без него инкремент молча ничего не найдёт. `on_schema_change='fail'`: смена колонок требует осознанного `--full-refresh` (это `CREATE OR REPLACE`, D6).

<!-- file: dbt/models/marts/mart_daily_sales.sql -->
```sql
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
```

### A3. Две витрины-таблицы

<!-- file: dbt/models/marts/mart_delivery_sla.sql -->
```sql
-- Grain: purchase_month, customer_state. On time: delivered no later than the estimated date,
-- by calendar date (D8). A delivered order without a delivery date is delivered, not on time.
select
    date_trunc('month', purchase_date) as purchase_month,
    customer_state,
    count_if(is_delivered) as delivered_orders,
    count_if(is_delivered and not is_late) as on_time_orders,
    {{ safe_divide('count_if(is_delivered and not is_late)', 'count_if(is_delivered)') }}
        as on_time_rate,
    avg(case when is_delivered then delivery_days end) as avg_delivery_days,
    approx_percentile(case when is_delivered then delivery_days end, 0.9) as p90_delivery_days
from {{ ref('fct_orders') }}
group by date_trunc('month', purchase_date), customer_state
```

<!-- file: dbt/models/marts/mart_seller_performance.sql -->
```sql
-- Grain: seller_id, purchase_month. A seller's orders are those with any item of the seller,
-- deleted items included, so an order canceled before shipping still counts against the seller.
with

orders as (
    select
        order_id,
        order_status,
        is_delivered,
        is_late,
        date_trunc('month', purchase_date) as purchase_month
    from {{ ref('fct_orders') }}
),

items as (
    select
        order_id,
        seller_id,
        price,
        is_deleted
    from {{ ref('fct_order_items') }}
),

live_reviews as (
    select
        order_id,
        review_score
    from {{ ref('stg_reviews') }}
    where not is_deleted
),

seller_orders as (
    select distinct
        i.seller_id,
        o.order_id,
        o.purchase_month,
        o.order_status,
        o.is_delivered,
        o.is_late
    from items as i
    inner join orders as o on i.order_id = o.order_id
),

seller_gmv as (
    select
        i.seller_id,
        o.purchase_month,
        sum(
            case
                when not i.is_deleted and o.order_status not in ('canceled', 'unavailable')
                    then i.price
            end
        ) as gmv
    from items as i
    inner join orders as o on i.order_id = o.order_id
    group by i.seller_id, o.purchase_month
),

seller_reviews as (
    select
        so.seller_id,
        so.purchase_month,
        avg(r.review_score) as avg_review_score
    from seller_orders as so
    inner join live_reviews as r on so.order_id = r.order_id
    group by so.seller_id, so.purchase_month
),

seller_order_stats as (
    select
        seller_id,
        purchase_month,
        count(*) as orders_count,
        count_if(is_delivered) as delivered_orders,
        count_if(is_delivered and is_late) as late_orders,
        count_if(order_status = 'canceled') as canceled_orders
    from seller_orders
    group by seller_id, purchase_month
)

select
    s.seller_id,
    s.purchase_month,
    s.orders_count,
    r.avg_review_score,
    coalesce(g.gmv, 0) as gmv,
    {{ safe_divide('s.late_orders', 's.delivered_orders') }} as late_rate,
    {{ safe_divide('s.canceled_orders', 's.orders_count') }} as cancellation_rate
from seller_order_stats as s
left join seller_gmv as g
    on s.seller_id = g.seller_id and s.purchase_month = g.purchase_month
left join seller_reviews as r
    on s.seller_id = r.seller_id and s.purchase_month = r.purchase_month
```

### A4. Тесты

Тест полного пересчёта проверяет корректность, а не только идемпотентность: повторный прогон без изменений доказывает лишь второе.

<!-- file: dbt/tests/assert_mart_daily_sales_matches_full_recompute.sql -->
```sql
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
```

<!-- file: dbt/tests/_tests.yml -->
```yaml
data_tests:
  - name: assert_mart_daily_sales_matches_full_recompute
    description: >
      The incremental mart_daily_sales equals int_daily_sales, its full recompute (D7). Error on
      any row.
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
        data_tests: [not_null]
      - name: seller_state
        data_tests: [not_null]
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
```

Проверка:

```bash
make dbt-parse >/dev/null && echo parse ok
cd dbt && uv run sqlfluff lint models macros tests; cd ..
cd dbt && uv run dbt ls --profiles-dir . --target ci --resource-type model | grep -c marketplace; cd ..   # 17
```

### A5. Документация

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
```

<!-- edit: ARCHITECTURE.md -->
Найти:
```markdown
   `dim_*`, `mart_daily_sales` incremental merge, `mart_seller_performance`, `mart_delivery_sla`)
   hourly, triggered by the silver asset. Tests and docs run with it.
```
Заменить на:
```markdown
   `dim_*`, `mart_daily_sales` incremental by purchase date, `mart_seller_performance`,
   `mart_delivery_sla`) hourly, triggered by the silver asset. Tests and docs run with it.
```

### A6. Статические проверки

```bash
make lint && make test 2>&1 | tail -1 && make dbt-parse
```

## Часть B. Живая проверка

Предусловия: W3-T01 B прошла; стек поднят `make start`; реплеер не играет; Airflow не запущен. Функции `q` и `soft_deleted` как в W3-T01 B.

### B1. Первый прогон строит витрины целиком

```bash
make dbt-build 2>&1 | tail -1
soft_deleted
```
Ожидается: `Done. PASS=66 WARN=0 ERROR=0 SKIP=0 NO-OP=0 TOTAL=66` (17 моделей, 1 seed, 48 тестов); `soft_deleted` пуст (витрина создана впервые, временной таблицы не было).

### B2. GMV равен определению D8 прямо по silver

```bash
q "select sum(gmv) from gold.mart_daily_sales"
q "select sum(i.price) from silver.order_items i join silver.orders o on i.order_id = o.order_id where not i._is_deleted and not o._is_deleted and o.order_status not in ('canceled', 'unavailable')"
```
Ожидается: два одинаковых числа (09.10: 12845420.13). Если число сменилось, обнови его и дату в описании `mart_daily_sales` в `dbt/models/marts/_marts.yml`.

### B3. Порция реплея, затем silver

Бюджет задачи: 60 с на 720x, около 12 виртуальных часов. `make verify` ждёт bronze, делает merge silver и сверяет с Postgres.

```bash
make replay-burst SECONDS=60
make verify
```
Ожидается: `virtual_now` после позже, чем до, примерно на 12 часов; `verify ok`.

### B4. Инкрементальный прогон после изменений

```bash
q 'select count(*) from gold."mart_daily_sales$snapshots"'
make dbt-build 2>&1 | grep -E 'mart_daily_sales|full_recompute|Done'
soft_deleted
```
Ожидается: `mart_daily_sales` OK (incremental), `assert_mart_daily_sales_matches_full_recompute` PASS, `Done.` без ERROR; в `soft_deleted` ровно одна запись `gold mart_daily_sales__dbt_tmp` (цена D13 как она есть); снапшотов витрины стало больше.

### B5. Повтор без новых данных

```bash
q "select count(*), sum(gmv) from gold.mart_daily_sales"
make dbt-build 2>&1 | tail -1
q "select count(*), sum(gmv) from gold.mart_daily_sales"
soft_deleted
```
Ожидается: пары чисел до и после равны; `Done.` без ERROR; в `soft_deleted` вторая запись `gold mart_daily_sales__dbt_tmp` (временная таблица создаётся и дропается на каждом инкрементальном прогоне, D13) и ничего другого.

### B6. Финальные проверки

```bash
make lint && make test 2>&1 | tail -1 && make dbt-parse
```

## Готово, когда

- `make dbt-build` код 0, первый прогон строит витрины целиком (B1).
- После порции реплея и merge silver `make dbt-build` код 0, тест полного пересчёта PASS, в soft-deleted ровно одна новая запись `mart_daily_sales__dbt_tmp` (B4).
- Повтор без новых данных: `count(*)` и `sum(gmv)` витрины до и после равны (B5).
- `sum(gmv)` витрины равен GMV по D8 из `lake.silver`, запрос и число в описании модели (B2).
- `make lint`, `make test`, `make dbt-parse` зелёные.

## Если не так

| Симптом | Причина | Что делать |
|---|---|---|
| B4: тест полного пересчёта FAIL | инкремент разошёлся с полным расчётом | стоп; не чини, не делай `--full-refresh`. В отчёт: скомпилированный SQL теста из `dbt/target/compiled/marketplace/tests/` и его результат в Trino |
| B4: Trino отказал в `delete ... where (purchase_date) in (select ...)` | DELETE с подзапросом не прошёл на Iceberg | стоп, текст ошибки в отчёт |
| B4: в `soft_deleted` что-то кроме `mart_daily_sales__dbt_tmp` | лишний DROP | стоп, имя в отчёт |
| B2: суммы расходятся | витрина считает GMV не по D8 | стоп; сравни с блоком плана |
| B3: `verify failed` | см. таблицу W3-T00 | стоп |
| B3: `a replayer already answers on :8000` | играет другой реплеер | стоп, выясни какой, не убивай чужой процесс |

## Ловушки

- Пустая витрина с `max(...)` равным null без `coalesce` никогда не найдёт изменённых дат: инкремент молча ничего не делает.
- Повторный прогон без изменений проверяет идемпотентность, не корректность. Корректность ловит только тест полного пересчёта.
- Заказ с продавцами из разных штатов попадает в каждый штат: `orders_count` по штатам не складывается в число заказов дня. Это написано в описании модели.
- `purchase_date` бизнесовая; время обработки в даты витрин не подмешивается.

## Blast radius и пайплайн

Каждый инкрементальный прогон `mart_daily_sales` создаёт и дропает временную таблицу `mart_daily_sales__dbt_tmp` и делает DELETE затронутых дат (D13): так устроен `delete+insert` в dbt-trino 1.10.4 (проверено по `materializations/incremental.sql`). `--full-refresh` пересобирает витрину через `CREATE OR REPLACE` (D6), без DROP. Silver только читается. Порция реплея тратит около 12 виртуальных часов из бюджета D2.

## Отчёт: что собрать

Хвост B1, два числа B2, `virtual_now` до и после B3, вывод B4 и B5, `soft_deleted` после B4 и B5, `git diff --stat`.

## Коммит

```bash
git add dbt ARCHITECTURE.md
git commit -m "dbt: marts and incremental daily sales"
```
