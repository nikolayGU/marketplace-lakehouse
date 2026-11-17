# GB. Gold, dbt, Superset, бизнес-смысл

Дерево: HEAD `a8c1d49` плюс незакоммиченные правки владельца (CI). Только чтение: файлы, `select` в
Trino через `docker compose ... exec -T trino trino` (запросы в
`scratchpad/audit/GB-work/q1.sql`..`q5.sql`), MCP `superset` (`get_instance_info`, `list_charts`,
`get_dashboard_info`, `get_chart_data`), `dbt/target/manifest.json` и `run_results.json` (сборка
12.11), одна мутация в копии бандла (`GB-work/mut`). dbt не запускался.

## Оценки

- Analytics engineer, BI: 4 из 5. Модели с тестами ключей, D8 одинаков в dbt и Superset, четыре
  пути к GMV равны живьём; минус: метрики KPI в Superset не защищены тестом, глоссарий расходится
  с дашбордом, нет exposures и контрактов.
- Заказчик аналитики: 4 из 5. Дашборд отвечает на продажи, заказы, доставку и отмены с
  сравнением периодов, числа KPI равны Trino; минус: продавцы, оплаты и отзывы только в gold без
  дашборда, свежесть видна только как дата последней покупки.
- Аналитик-потребитель: 3 из 5. Определения есть, но разнесены по `docs.md`, YAML моделей и
  метрикам бандла и местами не совпадают; одно имя (`orders_count`, `freight_value`,
  `items_count`, `cancellation_rate`) значит разное в разных моделях; у датасетов Superset
  описаний колонок нет.

## Сильные стороны

- GMV сходится четырьмя путями живьём 13.11: silver по правилу D8, `fct_orders`,
  `fct_order_items`, `mart_daily_sales` = 13 113 797,93 (`q1.sql`); `dq_checks` сверяет GMV по дням
  витрины с Postgres (`airflow/dags/lakehouse/reconcile.py:344-375`), а значения колонок
  `fct_orders` и `fct_order_items` с silver (`reconcile.py:142-158`).
- Инкрементальная витрина с доказательством: delete+insert по дате покупки и водяному знаку
  (`dbt/models/marts/mart_daily_sales.sql:23-35`), тест равенства полному пересчёту
  (`dbt/tests/assert_mart_daily_sales_matches_full_recompute.sql`), известный предел D18 назван в
  описании (`dbt/models/marts/_marts.yml:7-11`).
- Мягкие удаления: staging хранит, каждый потребитель фильтрует; статический тест на мутации
  (`tests/unit/test_dbt_soft_delete.py`) и тест на данных
  (`dbt/tests/assert_gold_has_no_deleted_entities.sql`).
- Минимальные права BI: каталог `lake_ro` с `iceberg.security=read_only`
  (`docker/trino/etc/catalog/lake_ro.properties:9`) и правила `grafana|superset` только на
  `(fct|dim|mart)_.*` в `lake_ro.gold` (`docker/trino/etc/rules.json:3-14`), 30+ тестов в
  `tests/unit/test_trino_access.py`, включая совпадение по префиксу имени.
- Бандл Superset как код: импорт с перезаписью по uuid (`docker/superset/import_bundle.py:41-58`),
  колонки датасетов сверяются с описаниями dbt и с SQL моделей
  (`tests/unit/test_superset_bundle.py:99-165`), только якорные периоды
  (`test_time_ranges_use_only_anchored_phrases`). Живьём KPI через MCP равны Trino: GMV
  2 687 103,87 против 2 863 849,49, AOV 142,28 против 135,30, доля отмен 0,39% против 0,62%.
- Аномалии источника как warn-тесты с порогом ошибки из var (`dbt/tests/_tests.yml:6-22`):
  отличие от «нет тестов» и от «красная сборка на известных данных».
- `on_table_exists: replace` и макрос сида через truncate (`dbt/dbt_project.yml:18-20`,
  `dbt/macros/trino__reset_csv_table.sql`): сборка не копит мягко удалённые таблицы Lakekeeper.

## Что слой даёт бизнесу

### Вопросы, на которые есть ответ

| Вопрос | Где | Колонка или метрика |
|---|---|---|
| Сколько продали за период и против прошлого периода | дашборд, KPI «GMV»; `gold.fct_orders` | метрика `gmv` (`fct_orders.yaml:26-33`) = сумма `items_value` заказов не `canceled` и не `unavailable` |
| Динамика продаж по месяцам против прошлого года | график «GMV by month, R$» | `gmv` по `purchase_date`, сетка месяц, ряд `1 year ago` |
| Продажи по дням и штату продавца, отменённый GMV | `gold.mart_daily_sales` | `gmv`, `canceled_gmv`, `items_count`, `freight_value` |
| Сколько заказов размещено, в каком они статусе | KPI «Orders», «Orders by current status» | `orders` = `COUNT(*)` по `fct_orders`, `order_status` |
| Средний чек | KPI «Average order value» | `aov` = GMV / заказы не `canceled` и не `unavailable` |
| Какая доля выручки уходит на доставку | KPI «Freight share» | `freight_share` = фрахт тех же заказов / GMV |
| Топ категорий по выручке | «Top 10 categories by GMV»; `gold.fct_order_items` | `gmv` по `category_label` (`product_category`) |
| Доставляем ли в срок, где хуже всего | KPI «On-time delivery», «On-time delivery by month» с целью 95%, таблица штатов | `on_time_rate`, `late_orders`, `avg_delivery_days`; `gold.mart_delivery_sla` (`on_time_orders`, `p90_delivery_days`) |
| Сколько заказов отменяют | KPI и график доли отмен | `cancellation_rate` = `canceled` / все заказы |
| Как работает каждый продавец по месяцам | `gold.mart_seller_performance` (нет на дашборде) | `orders_count`, `gmv`, `avg_review_score`, `late_rate`, `cancellation_rate` |
| Сколько покупателей и сколько вернулись | `gold.dim_customers` (нет на дашборде) | 93 152 человека, `is_repeat` у 2 883 (3,1%), `first_order_ts`, `last_order_ts` |
| Где данные расходятся с бухгалтерией заказа | тест `assert_payments_match_order_value` | 297 заказов: оплаты не равны позициям плюс фрахт (источник) |

### Каким числам верить и почему

- GMV: равен в silver и трёх моделях gold (выше); по дням сверяется с Postgres каждые 15 минут
  (`dq_checks`), витрина равна полному пересчёту (тест dbt). Дашборд считает GMV из
  `fct_orders.items_value`; его формула в Superset тестом не защищена (GB-01).
- Число заказов: `fct_orders` 96 358 = живые заказы silver 96 358 (`q1.sql`); silver сверяется с
  Postgres по 7 таблицам (`make reconcile`). Сумма `mart_daily_sales.orders_count` 96 849 больше:
  заказ считается в каждом штате своих продавцов (описано, `_marts.yml:5-7`).
- Доля в срок: по месяцам `fct_orders` и `mart_delivery_sla` дают одинаковые доставленные и в срок
  (0 расходящихся месяцев, `q2.sql`). Оговорка: знаменатель только доставленные; заказы, которые
  так и не доставлены после обещанной даты, в доле не участвуют (за 01.04-30.06.2026 их 237 при
  18 545 доставленных: 96,6% против 95,4%, если считать их опоздавшими, `q4.sql`).
- Доля отмен: `fct_orders` и silver по месяцам совпадают (0 расхождений, `q2.sql`).
- Чего не проверяет никто автоматически: формулы метрик Superset (GB-01), числа на графиках после
  импорта (`check.py` проверяет только, что строки есть, `docker/superset/check.py:44-72`).

### Свежесть

Silver merge каждые 5 минут (`airflow/dags/silver_upsert.py:32`), `dbt_build` после каждого merge
по Asset (`airflow/dags/dbt_build.py:15`, сборка 22 с, `run_results.json` 12.11), кэш графиков
Superset 300 с (`docker/superset/superset_config.py:19-20`). Сейчас реплей стоит: последний merge
silver 2026-11-06 16:20 UTC, последняя покупка 2026-07-18 («Data through»). Даты синтетические:
история Olist сдвинута на календарь первой загрузки (`oltp/replayer/load.py:1`), диапазон
2024-08-09..2026-07-18. Потребитель видит только дату последней покупки, а не время сборки gold.

### Очевидные вопросы маркетплейса без ответа (граница проекта)

- Способы оплаты и рассрочка: `payment_type` есть только в `stg_payments`, в витринах нет.
- Отзывы по товару и категории, тексты отзывов, NPS: только средняя оценка продавца за месяц.
- Когорты, удержание, LTV, повторные покупки во времени: только флаг `is_repeat`.
- География глубже штата и расстояние доставки: геолокация не моделируется (D5).
- Комиссия, маржа, возвраты и их суммы, себестоимость: таких данных в Olist нет.
- Воронка (визиты, конверсия), маркетинг, привлечение продавцов: данных нет.
- История атрибутов: измерения только текущие (без SCD2), смена штата продавца не видна.
- Время по этапам (одобрение, передача перевозчику) по продавцу: поля есть в `fct_orders`, витрины нет.
- Прогноз и сезонность: нет.

## Старый бэклог

| ID | статус сейчас | делать / не делать | причина |
|---|---|---|---|
| R-23 | открыт: `mart_seller_performance.sql:32-57` читает `items` и `orders` трижды, `dim_customers.sql:25-62` дважды | не делать | вся сборка 22 с, самая долгая модель 3,9 с (`run_results.json`); переписывание даёт риск расхождения без видимой выгоды |
| R-24 | открыт: `int_daily_sales` считается в тесте полного пересчёта и в unique на view | не делать | 2,2 с и 2,1 с; дубли витрины ловит `unique_combination` (`_marts.yml:17-20`), EXCEPT их видеть не обязан |
| R-46 | открыт: инкремент `mart_daily_sales` | не делать | это показанная компетенция (D7) с доказательством равенства; снятие трогает `dq_checks`, `reconcile.py:167-170`, D18; неверного числа нет |
| R-66 (часть dbt) | открыт: даты и числа в описаниях dbt, ссылки `(Dn)` на русскую спеку видны в dbt docs | делать: числа в GB-04; `(Dn)` в пакете DC по R-66 | числа устарели (GB-04); `D8` в описании ничего не говорит читателю dbt docs |
| PF-40, F-06 | открыт: smoke кончается на `make verify` (silver), в evidence «CI and smoke» (`docs/evidence.md:165-171`) нет фразы, что gold и дашборд доказаны ручными прогонами | делать: одна фраза (GB-02); шаг dbt в smoke не делать | честность утверждения дёшево; smoke с dbt это минуты CI и новый путь отказа |
| PF-41 | закрыт частично: колонки бандла против dbt (`test_superset_bundle.py:99-165`); job сборки образа Superset в CI нет (`.github/workflows/ci.yml:74-93` только hadolint) | не делать (передать IN) | образ по digest и `constraints.txt`, живой `check.py` 13 из 13 |
| PF-42 | закрыт: `test_superset_bundle.py:173-186` | закрыт | та же дыра у метрик `fct_orders`: GB-01 |
| PF-43 | открыт: контрактов нет (`manifest.json`: `contract.enforced` false у всех) | не делать | проект заморожен, новых моделей не будет; живьём все деньги `decimal(38,2)` (`q1.sql`: `typeof`) |
| PF-44, F-15 | открыт: `late_rate` и `orders_count` в `mart_seller_performance` без описания (`_marts.yml:69-87`) | делать (GB-03) | доставленный без даты: в `late_rate` не опоздал, в `on_time_rate` не в срок; читателю надо сказать |
| PF-45 | открыт: 287 в `dbt/tests/_tests.yml:8`, живьём 297 (`run_results.json`, `q1.sql`) | делать (GB-04) | ложное число в описании |
| PF-53 | открыт: кэш 300 с не описан в OPERATIONS, раздел Superset | делать (GB-02) | одна строка, объясняет «нового заказа ещё нет» |
| Д2.5: `annotation_layers` в `queries[0]` не сверяются с `params` | открыт: `test_superset_bundle.py:384-390`; сейчас равны (`width` 3 в обоих) | не делать | FORMULA рисует фронтенд из `form_data`; вреда нет |
| Д2.5: `rename` в тесте только для одной метрики без groupby | открыт: `test_superset_bundle.py:532-540` | не делать | сравнение периодов только у `daily_sales`; бандл заморожен |
| Д2.5: README «4 charts» | открыт: `README.md:87` | делать (GB-02) | ложное утверждение на первой странице |
| Д2.5: скриншот Superset в README | открыт: `docs/img/superset-marketplace.png` нет, `docs/evidence.md:269` «planned» | решение владельца | картинку даёт владелец |
| R-61 | открыт: ADR на Superset и `lake_ro` | передать AR | не область GB |
| 14, разд. 7: dbt 1.10.23 | открыт: `airflow/Dockerfile:15`, `pyproject.toml:16-17` | не делать | обновление без выгоды для читателя; назвать в разрыве с продом |
| F-02 | закрыт: Superset работает, 13 графиков (MCP `get_instance_info`) | закрыт | |

## Находки «делать»

### GB-01 [средняя] Формулы KPI на `fct_orders` не защищены тестом: потеря фильтра статусов не краснеет

Где: `docker/superset/dashboards/datasets/Lakehouse_Trino_lake_ro/fct_orders.yaml:26-117`
(метрики `gmv`, `paid_orders`, `aov`, `freight_share`, `on_time_rate`, `cancellation_rate`,
`in_transit_orders`); `mart_delivery_sla.yaml` метрика `on_time_rate`; тест есть только для
`fct_order_items` (`tests/unit/test_superset_bundle.py:173-186`).
Факт: в копии бандла `gmv` заменён на `SUM(items_value)` (`GB-work/mut`), `uv run pytest
.../test_superset_bundle.py` -> `34 passed`. Живьём у 374 отменённых заказов есть живые позиции
(`q3.sql`), значит такая правка меняет GMV, AOV и долю фрахта на дашборде.
Чем плохо: правка метрики в UI или в YAML (например, при следующем импорте) даёт неверный KPI, а
`make check` и `check.py` зелёные; `dq_checks` сверяет с Postgres витрину, а не метрику Superset.
Правка: тест на отказ первым в `test_superset_bundle.py`: словарь ожидаемых выражений метрик
`fct_orders` и `mart_delivery_sla` (точный текст после схлопывания пробелов, как сейчас в YAML),
сравнение на равенство; отдельно утверждение, что каждая метрика `fct_orders`, читающая
`items_value` или `freight_value`, содержит `order_status NOT IN ('canceled', 'unavailable')`, а
`on_time_rate` датасета `mart_delivery_sla` это отношение сумм, а не `AVG`. Проверить мутацией в
копии: красный.
Проверка: `uv run pytest tests/unit/test_superset_bundle.py -q` -> passed; мутация
`SUM(items_value)` в копии -> failed с именем метрики.
Размер: S; класс A (только тест); «ок» не нужно.
Старый ID: нет (аналог PF-42).

### GB-02 [высокая] Публичные описания дашборда и BI не совпадают с фактом

Где и факт:
- `README.md:87`: «dashboard "Marketplace" (4 charts over `lake_ro.gold`)»; факт 13 графиков
  (MCP `get_instance_info`: `total_charts: 13`; `docker/superset/dashboards/charts/` 13 файлов).
- `README.md:163`: доказательство Superset это прогон v1 06.11 с графиками `Cancellations`,
  `Daily sales`, которых больше нет; есть проверка 13.11 (`docs/evidence.md:268`).
- `README.md:8-11`: «four business questions» и только скриншот Grafana; дашборд Superset
  отвечает ещё на заказы, AOV, долю фрахта с сравнением периодов.
- `ARCHITECTURE.md:116-117`: Superset «shows the same four questions»; это уже не так.
- `OPERATIONS.md:533-535`: замер `check.py` только v1 (4 графика).
- `OPERATIONS.md:548`, `:557`: ссылки `superset_config.py:32` и `:28-31`; сейчас
  `MCP_DEV_USERNAME` на `docker/superset/superset_config.py:37`, комментарий на `:33-36`.
- `docs/evidence.md:259-261`: «against the previous quarter»; `inherit` сравнивает с прошлыми
  91 днями (31.12.2025-31.03.2026, `docs/planning/20-superset-dashboard.md:51-53`).
- PF-53: в разделе Superset OPERATIONS нет кэша 300 с и цепочки свежести.
- PF-40: `docs/evidence.md:165-171` не говорит, что smoke кончается на silver.
- Комментарии кода: `docker/trino/etc/catalog/lake_ro.properties:1-2` «the only catalog the
  Grafana user `grafana` may read» без `superset`; `access-control.properties:1` с `W6-D17`.
Чем плохо: интервьюер видит «4 charts» на первой странице и 13 на дашборде; ссылки на строки
ведут не туда; «previous quarter» неверно называет сравнение.
Правка: README:87 «13 charts: 6 KPI with period comparison, trends, top categories, states»;
README:163 заменить на проверку 13.11 (`check.py`: 13 из 13, KPI из evidence) со ссылкой на
`docs/evidence.md#superset-dashboard-v2`; README:8-9 одна фраза про KPI Superset; ARCHITECTURE:116-117
«six KPI with period comparison, GMV, on-time and cancellation trends, top categories, worst
states»; OPERATIONS:533-535 замер 13.11; OPERATIONS:548, 557 без номеров строк (имя переменной);
evidence:259-261 «against the previous 91 days»; OPERATIONS, раздел Superset, абзац «Freshness»:
silver каждые 5 мин, `dbt_build` по Asset, кэш графиков 300 с, «Data through» это дата последней
покупки, не время сборки; evidence «CI and smoke»: «smoke ends at silver; gold, `dq_checks` and
the dashboards are proven by the manual runs below»; два комментария Trino назвать `superset`,
убрать `W6-D17`.
Проверка: `grep -n "4 charts\|same four questions\|superset_config.py:3\|previous quarter" README.md
ARCHITECTURE.md OPERATIONS.md docs/evidence.md` -> пусто; `grep -n superset
docker/trino/etc/catalog/lake_ro.properties` -> строка; `uv run pytest tests/unit/test_trino_access.py -q`
-> passed; проверка ссылок `links` пакета DC без битых.
Размер: S; класс A (документы, `docs-writer`), комментарии Trino класс B без рестарта; «ок» не нужно.
Старый ID: Д2.5 (README «4 charts»), PF-40, PF-53.

### GB-03 [средняя] Глоссарий метрик расходится с дашбордом и не покрывает его метрики

Где и факт:
- `dbt/models/docs.md:11-14` `aov`: «orders ... that have at least one live item»; метрика
  дашборда делит на все заказы не `canceled` и не `unavailable`
  (`fct_orders.yaml:50-59`). Живьём 8 таких заказов без позиций (`q1.sql`), в прошлом периоде
  21 166 против 21 165 (`q2.sql`). Блок `aov` не подключён ни к одной колонке (`grep -rn
  "doc('aov')" dbt` пусто).
- `docs.md:27-30` `cancellation_rate`: «among all orders of the same purchase date»; колонки с
  таким зерном нет, блок используется только в `mart_seller_performance` (`_marts.yml:86-87`);
  на дашборде это отмены среди всех заказов периода.
- `docs.md:1-4` `purchase_date`: «shifted so that the last day of the dataset is "today"»; данные
  кончаются 2026-07-18 (`q1.sql`), сдвиг на день первой загрузки (`oltp/replayer/load.py:1`).
- Нет блоков для `orders`, `freight_share`, `paid_orders`; `on_time_rate` не говорит, что
  недоставленные после срока не входят (237 за последний квартал, `q4.sql`).
- Одно имя, разный смысл: `orders_count` в `mart_daily_sales` (сумма 96 849), `dim_customers`,
  `mart_seller_performance` (сумма 96 894) против 96 358 заказов; `freight_value` и `items_count`
  в `fct_orders` (все статусы: 2 185 367,16 и 109 191) и в `mart_daily_sales` (только оплаченные:
  2 177 025,53 и 108 747) (`q3.sql`). В `mart_seller_performance` без описания `orders_count`,
  `late_rate` (`_marts.yml:69-87`; PF-44).
- README dbt обещает «the metric glossary of `models/docs.md`» (`dbt/README.md:40-41`).
Чем плохо: аналитик, сверяющий AOV или долю отмен по глоссарию, получает другое число и не знает,
какое верно; при суммировании `orders_count` завышает заказы.
Правка: тест на отказ первым в `test_superset_bundle.py`: для каждой метрики, на которую ссылается
график бандла, в `dbt/models/docs.md` есть блок `{% docs <metric_name> %}` (красный: нет
`orders`, `freight_share`, `late_orders`, `delivered_orders`, `avg_delivery_days`). Затем
`docs.md`: блоки по формулам датасета (знаменатель словами, ссылка на датасет Superset); `aov`
по метрике (заказы не `canceled` и не `unavailable`); `cancellation_rate` «canceled orders among
the orders of the row or period»; `purchase_date` «shifted by one constant onto the calendar of
the initial load»; `on_time_rate` с оговоркой про недоставленные; абзац «Same name, different
scope» про `orders_count`, `freight_value`, `items_count`. `_marts.yml`: описания `orders_count`
и `late_rate` у `mart_seller_performance` (доставленный без даты не опоздал и не в срок).
Метрики Superset не менять (повторный импорт это класс C).
Проверка: `uv run pytest tests/unit/test_superset_bundle.py -q` passed; `make dbt-parse` exit 0;
`grep -c "{% docs" dbt/models/docs.md` больше 7.
Размер: M; класс A (YAML, Markdown dbt без смены SQL; `dbt/` смонтирован в живой Airflow, но
описания не меняют сборку); «ок» не нужно.
Старый ID: PF-44, F-15.

### GB-04 [низкая] Устаревшие числа в описаниях dbt

Где и факт: `dbt/tests/_tests.yml:8-10` и `dbt/tests/assert_payments_match_order_value.sql:1-2`
«287 orders (2026-10-09)», живьём 297 (`run_results.json` 12.11: `warn 297`; `q1.sql`);
`dbt/models/marts/_core.yml:4-5` «765 orders have no live item (2026-10-09): 735 never had one,
30 lost», живьём 793, 751, 42 (`q5.sql`); `dbt/models/marts/_marts.yml:12-16` «12 894 209.50 on
2026-10-18», живьём 13 113 797,93 (`q1.sql`).
Чем плохо: описание в dbt docs даёт неверное число; проверяющий решит, что сверка не сходится.
Правка: числа и дату обновить на текущие (`q1.sql`, `q5.sql` в отчёте как источник) или убрать
число и оставить запрос сверки; 610, 23, 2, 0,85 верны (`q5.sql`), их не трогать.
Проверка: `make dbt-parse` exit 0; `grep -rn "287\|765 orders\|12 894" dbt/models dbt/tests` пусто.
Размер: S; класс A; «ок» не нужно.
Старый ID: PF-45, часть R-66.

### GB-05 [низкая] Колонки-ловушки в датасетах Superset и название таблицы штатов

Где и факт:
- `mart_daily_sales.yaml:47-66`: `orders_count`, `canceled_orders` с `description: null`; датасет
  не используется ни одним графиком (все `dataset_uuid` в `charts/*.yaml`), но открыт в Explore и
  SQL Lab. `SUM(orders_count)` даёт 96 849 вместо 96 358 (`q1.sql`).
- `mart_delivery_sla.yaml:75`: колонка `on_time_rate` рядом с метрикой того же имени; среднее
  колонки 92,2% против 93,3% по метрике (`q3.sql`).
- `charts/delivery_sla.yaml:1` и `dashboards/Marketplace.yaml:276`: «States with the most late
  deliveries», а сортировка по наименьшей доле в срок (`delivery_sla.yaml` описание, живьём PI с 17
  опозданиями первым, BA с 63 третьим: MCP `get_chart_data` 3).
Чем плохо: аналитик в Superset суммирует `orders_count` или усредняет `on_time_rate` и получает
неверное число; заголовок обещает не то, что показывает таблица.
Правка: тест на отказ (у этих трёх колонок непустой `description` со словами «do not sum across
states» и «use the metric on_time_rate»); описания в YAML; заголовок «States with the lowest
on-time share» в обоих файлах. Доходит до стенда только повторным импортом `superset-init`.
Проверка: `uv run pytest tests/unit/test_superset_bundle.py -q` passed; после импорта
`docker exec lakehouse-superset-1 python /app/check.py` 13 из 13.
Размер: S; класс B; повторный импорт `--force-recreate --no-deps superset-init` класс C, «ок» на
точный текст.
Старый ID: нет.

### GB-06 [низкая] Нет exposures: lineage dbt кончается на витринах

Где: `manifest.json`: `exposures 0`; в `dbt/models/` нет файла с `exposures:`.
Чем плохо: dbt docs не показывают, какие модели питают дашборды; при правке `fct_orders` не видно,
что ломается Superset и Grafana.
Правка: `dbt/models/marts/_exposures.yml`: `marketplace_superset` (`depends_on`: `fct_orders`,
`fct_order_items`, `mart_delivery_sla`, `mart_daily_sales`; `url` `http://127.0.0.1:8088/superset/dashboard/marketplace/`)
и `marketplace_grafana` (модели панелей из `observability/grafana/dashboards/marketplace.json`);
`owner` без имени владельца (роль). Тест на отказ: модели `depends_on` равны таблицам датасетов
бандла (`test_superset_bundle.py`).
Проверка: `make dbt-parse` exit 0; `python3 -c "import json;print(len(json.load(open('dbt/target/manifest.json'))['exposures']))"` -> 2.
Размер: S; класс A; «ок» не нужно.
Старый ID: нет.

## Находки «не делать»

| ID | что | почему не делать |
|---|---|---|
| GB-N1 | dbt-тест «GMV `fct_orders` по дням равен `mart_daily_sales`» | равенство по построению из одних staging; потерю фильтра удалений ловит `test_dbt_soft_delete.py` (`AGGREGATES_ONLY`), формулу Superset dbt не видит (это GB-01) |
| GB-N2 | синхронизировать описания всех колонок датасетов Superset с dbt | M работы и импорт класса C ради подсказок; опасные три колонки в GB-05 |
| GB-N3 | убрать датасет `mart_daily_sales` из бандла | импорт не удаляет объекты, на стенде останется сирота; удаление класс C; описания GB-05 дешевле |
| GB-N4 | переименовать `freight_value`, `items_count`, `orders_count` по смыслу | ломает датасеты, `dq_checks`, Grafana; хватит глоссария GB-03 |
| GB-N5 | «Data through» заменить или дополнить временем сборки gold | новая метрика из `$snapshots`, импорт класс C; назвать в разрыве с продом |
| GB-N6 | считать недоставленные после срока опоздавшими в `on_time_rate` | смена принятого определения D8 и чисел evidence; оговорка в глоссарии GB-03 |
| GB-N7 | тест `value_in_range` для `payment_value`, долей в [0, 1] | данных вне диапазона нет, доли через `safe_divide` и NULLIF; польза мала |

## Разрыв с продом

- Нет слоя семантики: правило D8 записано в `int_daily_sales.sql`, `mart_seller_performance.sql`,
  пяти метриках `fct_orders.yaml` и метрике `fct_order_items.yaml`; согласованность держат тесты и
  ручные сверки, а не одно определение.
- Нет контрактов и версий моделей, которые читает BI; нет exposures (GB-06).
- Нет аутентификации и RLS: пользователь Trino это метка, Superset с одним `admin`, MCP от имени
  `admin`.
- Свежесть для потребителя только «Data through» (дата покупки); нет «обновлено в», SLA по
  витрине и алерта свежести под нагрузкой (`GoldStaleAtRest` только в покое).
- Измерения только текущие (без SCD2): смена штата продавца оставляет старые даты витрины
  устаревшими (D18).
- Нет E2E в CI до gold и дашборда (PF-40); образ Superset не собирается в CI.
- Якорь времени `SUPERSET_DATA_ANCHOR` двигается руками после реплея.
- dbt 1.10 без процесса обновлений.

## Не проверено

- Визуально дашборд (скриншота нет); фильтр «Customer state» живьём не применялся. Проверка:
  открыть `http://127.0.0.1:8088/superset/dashboard/marketplace/`, выбрать штат SP.
- Числа `mart_seller_performance` кроме суммы GMV (13 113 797,93 = D8, `q2.sql`) и `dim_customers`
  кроме суммы заказов (96 358).
- Статус поддержки dbt-core 1.10 (EOL): `context7` или страница релизов dbt.
- `make dbt-docs` и вид глоссария в dbt docs: требует Trino и пишет только в `dbt/target`.
- Grafana «Marketplace» (область OB, DC): её числа против gold не сверялись в этом аудите.
- Почему в `fct_orders` даты доставки позже конца данных (до 2026-09-15 при последней покупке
  2026-07-18, `q4.sql`): семантика реплея, область DP.
