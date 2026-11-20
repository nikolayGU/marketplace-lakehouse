# P08. Gold и BI: формулы KPI под тестом, глоссарий метрик, числа описаний, exposures

Статус: исполнен 20.11.2026, `580e608`. Сессия на Opus: `/task docs/planning/21-final-audit-2026-11-13/P08-gold-bi.md`.

## Цель

Формулы метрик Superset под тестом и сверены с константой `dq_checks`; AOV по решению В-24; у каждой
метрики графиков есть подключённый блок глоссария dbt; описания dbt без устаревших чисел;
exposures для Superset и Grafana; колонки-ловушки и заголовок таблицы штатов честные; комментарии
Trino называют `superset`. На стенд бандл доходит одним импортом (В-05).

## Находки пакета

| ID | Серьёзность | Суть | Где подробности |
|---|---|---|---|
| GB-01, QA-03 | средняя | метрики `fct_orders` без теста: мутации B2, B3, B4 и GMV без фильтра проходят набор | `reports/GB.md` GB-01; `reports/QA.md` QA-03, «Мутации» |
| GB-03, PF-44 | средняя | глоссарий `dbt/models/docs.md` расходится с дашбордом и не покрывает его метрики; `late_rate`, `orders_count` у `mart_seller_performance` без описания | `reports/GB.md` GB-03 |
| GB-04, PF-45 | низкая | устаревшие числа 287, 765/735/30, 12 894 209.50 в описаниях dbt | `reports/GB.md` GB-04 |
| GB-05 | низкая | колонки-ловушки датасетов; заголовок «most late» при сортировке по доле в срок | `reports/GB.md` GB-05 |
| GB-06 | низкая | нет exposures, lineage кончается на витринах | `reports/GB.md` GB-06 |
| 20-6 | низкая | имя `test_kpi_tiles_fit_the_row_...` обещает больше, чем проверяет | `registry.md`, 2.6; спека 20, раздел 7 |
| GB-02 (часть) | низкая | комментарии `lake_ro.properties` без `superset`, `W6-D17` в двух файлах Trino | `reports/GB.md` GB-02, последний пункт |

## Решения владельца и действия класса C

- В-05 (README, раздел 3): один повторный импорт бандла после правок. По «ок» владельца на точный
  текст (класс C, пересоздаёт one-shot `superset-init`; команда из `OPERATIONS.md`, раздел
  «Superset (profile `bi`)», абзац «Import order»):

  ```bash
  docker compose --env-file .env -f docker/compose.yaml --profile bi \
    up -d --force-recreate --no-deps superset-init
  ```

  «Нет»: правки остаются в репозитории, в «Итог» строка «на стенде не применено».
- Пауза и снятие паузы DAG `dbt_build` входят в порядок класса B (`13-harness.md`, раздел 2);
  `make dbt-build` класс A только при паузе и без запуска в полёте.
- В-24 (README, раздел 3): AOV на дашборде привести к D8, делить на заказы с хотя бы одной
  неудалённой позицией; рекомендация «да». Обе ветки в шаге 3. Сам вопрос не класс C; при «да»
  правка доходит до стенда только через импорт В-05.

## Зависимости

- После P05: он переносит `output_columns` из `tests/unit/test_superset_bundle.py` в
  `tests/unit/dbt_sql.py`; файл теста брать после его коммита.
- После P02 `.md` под `dbt/` считается кодом для гейта: `docs.md` требует
  `make check` и ревью (пакет и так с кодом).
- P10 после правит те же файлы (`(Dn)`, даты в `dbt/`, `PF-42` в тесте): новые тексты без ID
  карточек, `Dn` и дат в скобках (шаблон `work/DC/r66_pattern.txt`).
- P11 (OPERATIONS) и P13 (README, ARCHITECTURE, evidence) ведут документную часть GB-02.

## Вход

Сверить первым шагом, по цитате (номера строк после других пакетов сдвигаются):

1. `fct_orders.yaml` (`docker/superset/dashboards/datasets/Lakehouse_Trino_lake_ro/`): `:29`
   `SUM(CASE WHEN order_status NOT IN ('canceled', 'unavailable') THEN items_value END)`;
   `:53-55` `aov` делит на `NULLIF(COUNT_IF(order_status NOT IN ('canceled', 'unavailable')), 0)`;
   `:81` `1.0 * COUNT_IF(order_status = 'canceled') / NULLIF(COUNT(*), 0)`.
   `mart_delivery_sla.yaml:29` `1.0 * SUM(on_time_orders) / NULLIF(SUM(delivered_orders), 0)`.
2. Тест метрик только у `fct_order_items` (`test_superset_bundle.py:173-186`). Константа
   `airflow/dags/lakehouse/reconcile.py:343` `GMV_EXCLUDED_STATUSES = ("canceled", "unavailable")`;
   модуль без airflow, в тестах `from lakehouse import reconcile` (`pythonpath`).
3. MCP «Average order value» (id 6, 13.11): `aov__inherit` 135.304237, по D8 135.3106.
4. D8, `docs/planning/07-w3-spec.md:45`: «AOV: GMV, делённый на число таких заказов с хотя бы
   одной неудалённой позицией»; `:48` доля отмен «среди всех заказов той же даты покупки».
   Спека 20: С-Д11 «метрика на `fct_orders` по D8»; раздел 4, Д2.3, п. 2 «AOV = GMV / paid
   orders» (формула принята владельцем вживую 13.11). `dbt/models/docs.md:11-14` повторяет D8.
5. Метрики графиков (`params.metrics`, `params.metric`, `timeseries_limit_metric`): `aov`,
   `avg_delivery_days`, `cancellation_rate`, `delivered_orders`, `freight_share`, `gmv`,
   `late_orders`, `on_time_rate`, `orders`. Блоков нет у `avg_delivery_days`, `delivered_orders`,
   `freight_share`, `late_orders`, `orders`; блок `aov` есть, но `doc('aov')` нигде нет.
6. `dbt/tests/_tests.yml:8-9` и `assert_payments_match_order_value.sql:1-2` «287 orders»;
   `dbt/models/marts/_core.yml:4-5` «765 orders have no live item ... 735 never had one, 30»;
   `_marts.yml:16` «(12 894 209.50 on 2026-10-18)»; `_marts.yml` у `mart_seller_performance`
   нет `orders_count` и `late_rate`.
7. `mart_daily_sales.yaml:47-66` `orders_count`, `canceled_orders` с `description: null`;
   `mart_delivery_sla.yaml:75` колонка `on_time_rate`; заголовок «States with the most late
   deliveries» в `charts/delivery_sla.yaml:1` и `dashboards/Marketplace.yaml:276`.
8. Exposures в manifest (команда `EXPOSURES` ниже) -> `0`. Grafana `marketplace.json` (uid
   `marketplace`) читает `fct_orders`, `fct_order_items`, `mart_daily_sales`.
9. `docker/trino/etc/catalog/lake_ro.properties:1-2` «# W6-D17: ... the only catalog the Grafana
   user `grafana` may read»; `access-control.properties:1` «(W6-D17)».

## Границы

- Менять можно: `tests/unit/test_superset_bundle.py`, новый `tests/unit/test_dbt_exposures.py`;
  `dbt/models/docs.md`, `marts/_core.yml`, `_marts.yml`, новый `marts/_exposures.yml`,
  `dbt/tests/_tests.yml`, комментарий `assert_payments_match_order_value.sql`; бандл:
  `fct_orders.yaml`, `mart_daily_sales.yaml`, `mart_delivery_sla.yaml`, `charts/delivery_sla.yaml`,
  `Marketplace.yaml`; комментарии двух файлов `docker/trino/etc/`; при В-24 «нет» строка в
  `docs/planning/07-w3-spec.md`.
- Нельзя: SQL моделей dbt, имена колонок, `rules.json`, ключи `.properties`, прочие метрики и
  графики, документы GB-02 (P11, P13), `airflow/dags/`.
- Живой стек: `dbt/` смонтирован в Airflow, правка только при паузе `dbt_build`; Trino не
  перезапускать (меняются только комментарии); импорт бандла только по В-05.

## Шаги

0. Пауза (класс B): `$COMPOSE exec -T airflow-scheduler airflow dags pause dbt_build`; затем
   `... airflow dags list-runs dbt_build --state running` пусто. До снятия паузы правки `dbt/`.
1. GB-01, QA-03 (`implementer`). Тесты в `test_superset_bundle.py`:
   `test_saved_metrics_have_the_expected_expressions`: словарь «датасет -> {метрика: выражение}»
   для `fct_orders`, `fct_order_items`, `mart_delivery_sla`; выражения как в YAML после
   `" ".join(expr.split())`, множество имён равно ключам словаря (новая метрика без строки
   красная). `test_paid_metrics_exclude_the_statuses_of_reconcile`: для `gmv`, `paid_orders`,
   `aov`, `freight_share`, `in_transit_orders` (`fct_orders`) и `gmv` (`fct_order_items`) каждое
   вхождение `order_status NOT IN (...)` (regex без учёта регистра, разбор как
   `tests/unit/test_reconcile.py:48-52`) равно `frozenset(reconcile.GMV_EXCLUDED_STATUSES)`, а
   число вхождений не меньше 1 и равно числу агрегатов `SUM(`, `COUNT_IF(`. Сейчас тесты зелёные;
   отказ доказывают мутации («Готово, когда»). 20-6, тест `:306`
   `test_kpi_tiles_fit_the_row_with_one_big_number_and_a_short_comparison` сверяет только
   значения (`KPI_TILE`, высота 32): имя `test_kpi_tiles_pin_font_sizes_height_and_columns`.
2. GB-06 (`implementer`). Тест первым: `tests/unit/test_dbt_exposures.py`, красный (файла нет):
   у exposure `marketplace_superset` `depends_on` равно множеству `table_name` датасетов бандла;
   у `marketplace_grafana` равно таблицам `lake_ro.gold.(\w+)` из `rawSQL` панелей
   `marketplace.json`. Затем `marts/_exposures.yml`: два `type: dashboard`, `owner: {name: Data
   platform}`, `http://127.0.0.1:8088/superset/dashboard/marketplace/` и `:3000/d/marketplace`,
   `depends_on` через `ref()`. `doc()` в `description` exposure работает в dbt 1.10.23
   (проверено `dbt parse` в копии); в описание Superset войдут блоки шага 3.
3. GB-03, PF-44 (`implementer`; тексты на английском). Что верно, решено:
   - AOV по В-24. «Да»: в `fct_orders.yaml` делитель `aov` становится
     `NULLIF(COUNT_IF(order_status NOT IN ('canceled', 'unavailable') AND items_count > 0), 0)`
     (`items_count` = «Number of live items of the order», `_core.yml`), описание «GMV per paid
     order with at least one live item». Тест первым: строка `aov` в словаре шага 1, красный;
     потом YAML. Сдвигается только плитка AOV, прошлый квартал 135.304237 -> 135.3106; в тестах
     только выражение шага 1, в evidence и спеке 20 AOV нет. На стенд через В-05. Блок `aov` в
     `docs.md` остаётся по D8. «Нет»: метрика бандла не меняется; блок `aov` описывает формулу
     дашборда («GMV divided by the orders that are neither canceled nor unavailable, orders
     without a live item included»); оркестратор дописывает в `07-w3-spec.md` под строкой AOV
     глоссария D8 оговорку «дашборд Superset делит на все заказы не `canceled` и не
     `unavailable` (решение В-24, 13.11)».
   - Доля отмен: формула одна, узка формулировка блока: «among all orders whose purchase date
     falls in the row: a day, a month, a period, or a seller and month».
   - Доля в срок: дашборд и D8 совпадают; дописать: знаменатель только `delivered`, заказ без
     даты доставки в знаменателе и не в срок, недоставленные после обещанной даты не входят.
   - `purchase_date`: «shifted by one constant so that the last purchase of the full Olist
     history fell on the day of the initial load (`oltp/replayer/load.py`); the replay has not
     played all of it, so the data ends earlier».
   Тест первым: `test_every_dashboard_metric_has_a_glossary_block_used_by_dbt`: метрики графиков
   (как во «Входе», п. 5, только строки) есть в `{% docs <имя> %}` файла `docs.md` и в
   `doc('<имя>')` какого-либо `dbt/models/**/*.yml`. Красный на 5 блоках и `aov`. Затем блоки
   `orders`, `freight_share`, `delivered_orders`, `late_orders`, `avg_delivery_days` по
   выражениям датасета (знаменатель словами), блок `name_scopes` («Same name, different scope»:
   `orders_count` в `mart_daily_sales` по штату продавца, в `mart_seller_performance` по
   продавцу, сумма больше числа заказов; `freight_value`, `items_count` в `fct_orders` по всем
   статусам, в `mart_daily_sales` только заказы GMV); подключить через описание
   `marketplace_superset`, колонки `delivered_orders`, `avg_delivery_days` у
   `mart_delivery_sla` через `doc()`. `_marts.yml`, `mart_seller_performance`: `orders_count`
   (заказы с любой позицией продавца, удалённые включены; по продавцам не суммировать),
   `late_rate` (`late / delivered`; доставленный без даты ни поздний, ни в срок).
4. GB-04, PF-45 (оркестратор, правка до 20 строк). Числа снять в момент исполнения:

   ```sql
   select
    (select count(*) from lake.gold.fct_orders where order_status not in ('canceled','unavailable')
       and abs(payment_value - (items_value + freight_value)) > 0.01) payments_mismatch,
    (select count_if(items_count = 0) from lake.gold.fct_orders) no_live_item,
    (select count_if(items_count = 0 and not exists (select 1 from lake.gold.fct_order_items i
       where i.order_id = o.order_id)) from lake.gold.fct_orders o) never_had,
    (select sum(gmv) from lake.gold.mart_daily_sales) mart_gmv
   ```

   Через `$COMPOSE exec -T trino trino --execute "<запрос>"`; GMV по silver: запрос из описания
   `mart_daily_sales` (`_marts.yml:13-15`); статус потерявших позиции: `work/GB/q5.sql.txt` плюс
   `group by order_status`. 13.11: 297; 793 = 751 + 42 (все 42 `canceled`); 13113797.93 = silver.
   Заменить три числа, дату при них убрать. Сверку silver-GMV в описании оставить; 610, 23, 2,
   0,85 не трогать.
5. GB-05 (`implementer`). Тест первым `test_trap_columns_say_how_to_aggregate`: `description`
   непуст у `mart_daily_sales.orders_count`, `canceled_orders` («do not sum across states: an
   order counts once per seller state; count orders on fct_orders») и у колонки
   `mart_delivery_sla.on_time_rate` («rate of one row; do not average it, use the metric
   on_time_rate»). И `test_dashboard_slice_names_match_the_charts`: `sliceName` в `position`
   равен `slice_name` графика того же uuid; заголовок `delivery_sla` равен «States with the
   lowest on-time share». Затем описания и заголовок в двух файлах.
6. GB-02, комментарии Trino (оркестратор): `lake_ro.properties:1-2` «the only catalog the BI
   users `grafana` and `superset` may read», `W6-D17` убрать в обоих файлах, ключи не трогать.
7. `make check`, `make dbt-parse`, `make dbt-build` при паузе, ревью `reviewer` (предмет код).
   Затем В-05: импорт по «ок», проверка `check.py` и MCP. Затем цикл verify и коммит по
   `13-harness.md`, раздел 5; снятие паузы `dbt_build` последним.
   Коммит: `bi: kpi formulas under test, metric glossary, exposures, honest dataset labels`.

## Готово, когда

Команда `EXPOSURES`:

```bash
uv run python -c "import json;print(len(json.load(open('dbt/target/manifest.json'))['exposures']))"
```

- [ ] `uv run pytest tests/unit/test_superset_bundle.py tests/unit/test_dbt_exposures.py
      tests/unit/test_trino_access.py -q` (одной строкой) -> `passed`, без failed.
- [ ] Мутации в копии дерева в scratchpad (`rsync` `tests/unit`, `docker/superset`, `dbt/models`,
      `airflow/dags`, `pyproject.toml`; прогон `.venv/bin/python -m pytest
      tests/unit/test_superset_bundle.py -q -p no:cacheprovider` из копии; образец
      `work/QA/mutate.py.txt`) -> failed с именем метрики: B2, B3, B4 из
      `work/QA/mutations.json.txt` (B2 совпадает с мутацией GMV из `reports/GB.md`); M1 (при
      В-24 «да») `aov`: `AND items_count > 0), 0)` -> `), 0)`; M2 `mart_delivery_sla.yaml`:
      `"1.0 * SUM(on_time_orders) / NULLIF(SUM(delivered_orders), 0)"` -> `"AVG(on_time_rate)"`;
      M3 `fct_orders.yaml`: `SUM(CASE WHEN order_status NOT IN ('canceled', 'unavailable') THEN
      freight_value END)` -> `SUM(freight_value)`. До правки B2 давала `34 passed` (проверено).
- [ ] `make dbt-parse` exit 0; `EXPOSURES` -> `2`.
- [ ] `grep -c "{% docs" dbt/models/docs.md` -> не меньше 12;
      `grep -rn "287 orders\|765 orders\|12 894" dbt/models dbt/tests` -> пусто.
- [ ] `make dbt-build` (пауза `dbt_build`, ничего в полёте) -> `ERROR=0`, `WARN=4` (четыре
      теста аномалий источника; 12.11 было 79 pass/success и 4 warn в `run_results.json`).
- [ ] `grep -rn "most late deliveries" docker/superset` -> пусто;
      `grep -rn "W6-D17" docker/trino` -> пусто;
      `grep -n superset docker/trino/etc/catalog/lake_ro.properties` -> строка.
- [ ] `make check` зелёный; вердикт `reviewer` «принять» или «принять с замечаниями».
- [ ] При В-05 «да»: `docker inspect -f '{{.State.ExitCode}}' lakehouse-superset-init-1` -> `0`;
      `docker exec lakehouse-superset-1 python /app/check.py` -> 13 строк `rows`, exit 0; MCP
      `get_chart_info` графика с uuid `203f021c-...` -> «States with the lowest on-time share»;
      `get_chart_data` «Average order value» -> `aov__inherit` 135.3106 при В-24 «да» (D8,
      `work/GB/q2.sql.txt`, делитель `paid_with_items`), 135.304237 при «нет»;
      `get_dataset_info` `mart_daily_sales` -> описания двух колонок.
- [ ] `make verify` -> `verify ok`; DAG `dbt_build` снят с паузы последним шагом.

## Не входит

- Документная часть GB-02 (README «4 charts», ARCHITECTURE, OPERATIONS, evidence, PF-40, PF-53):
  P11 и P13. Раздел «Что слой даёт бизнесу» из `reports/GB.md` это вход для README в P13.
- Замена `(D8)` и `PF-42` в существующих строках (P10); находки «не делать» GB-N1..GB-N7.

## Риски и откат

- `dbt_build` на паузе теряет событие Asset (`ARCHITECTURE.md`, п. 6): merge silver за паузу
  оставит gold позади; реплей стоит, `make dbt-build` шага 7 догоняет gold.
- Импорт перезаписывает объекты бандла, правки из UI и колонки вне YAML теряются (комментарий
  над `superset-mcp` в compose). Откат: `git revert` и тот же импорт по новому «ок».
- В-24 «да»: AOV прошлого квартала на плитке 135.30 -> 135.31; в evidence AOV не записан.

## Расхождения с отчётом аудита

- GB-03 предлагал подогнать блок `aov` под метрику, не спрашивая владельца; формула дашборда
  и D8 оба приняты владельцем, поэтому выбор вынесен в В-24.
- GB-05: таблица штатов строится на датасете `fct_orders`, не `mart_delivery_sla`; правке не мешает.
- GB-06: «подключён» значит `doc()` в YAML dbt; метрики без колонки идут в описание exposure.

## Итог

Исполнено 20.11.2026 (UTC) одной сессией на Opus (оркестратор), коммит `580e608` (15 файлов,
+296 -26). Решения из аргумента `/task`: рутина сессии «да», В-24 «да», В-05 «да»; импорт бандла
по «ок» на точный текст. Код и тесты: `implementer`, 3 брифа (А шаги 1, 3 AOV, 5 в бандле и
`test_superset_bundle.py`; Б шаги 2, 3 в `dbt/` и `test_dbt_exposures.py`; В исправления круга 1
ревью); шаги 4, 6, переносы длинных строк и живые шаги: оркестратор; ревью `reviewer`, два круга.

| Критерий | Проверка | Результат |
|---|---|---|
| Вход | чтение и grep цитат, MCP, Trino | все 9 пунктов подтверждены; номера сдвинуты: тест метрик `:132`, а не `:173`; `reconcile.py:337`, а не `:343`; тест плиток `:265`; файлы `work/` лежат в папке аудита |
| Тесты пакета | `uv run pytest tests/unit/test_superset_bundle.py tests/unit/test_dbt_exposures.py tests/unit/test_trino_access.py -q` | `165 passed` |
| Мутации | копия в scratchpad, `.venv/bin/python -m pytest tests/unit/test_superset_bundle.py -q -p no:cacheprovider` | база `47 passed`; B2, B3, M3 по 2 failed (`test_saved_metrics_have_the_expected_expressions[fct_orders]` и `test_paid_metrics_exclude_the_statuses_of_reconcile[fct_orders-gmv\|paid_orders\|freight_share]`); B4, M1 `[fct_orders]`, M2 `[mart_delivery_sla]` по 1 failed; имя метрики в diff словаря (`{'cancellation_rate': ...}`); ревьюер добавил красные T1-T7 (описания ловушек, ref exposures, `doc()`, `sliceName`, статусы `in_transit_orders`) |
| Тесты на отказ | до правки | бандл: `5 failed, 42 passed` (`aov`, 3 ловушки, заголовок); exposures и глоссарий `3 failed` (нет файла, 5 блоков); ловушки после ревью `1 failed` на описании «Orders.» |
| dbt | `make dbt-parse`; `EXPOSURES` | exit 0; `2` |
| Глоссарий и числа | `grep -c "{% docs" dbt/models/docs.md`; grep `287 orders\|765 orders\|12 894` | `13`; пусто |
| Числа описаний | запрос шага 4 в Trino | `297`, `793` = `751` + 42 (все `canceled`), mart = silver = `13113797.93` |
| `make dbt-build` | пауза `dbt_build`, ничего в полёте | `PASS=79 WARN=4 ERROR=0 SKIP=0 NO-OP=2 TOTAL=85` |
| grep бандла и Trino | `most late deliveries`; `W6-D17`; `superset` в `lake_ro.properties` | пусто; пусто; строка 2 |
| `make check` | после круга 1 | `2144 passed, 149 skipped` |
| Ревью | `reviewer` | круг 1 «принять с замечаниями» (1 среднее: тест ловушек проверял только непустое описание; 3 низких); круг 2 «принять с замечаниями» (1 низкое, ниже) |
| В-05 | `--profile bi up -d --force-recreate --no-deps superset-init` 20:25Z | `ExitCode 0`; `check.py` 13 строк `rows`, exit 0; MCP: график id 3 «States with the lowest on-time share»; «Average order value» `aov__inherit` 135.304237 -> `135.310630`; `mart_daily_sales` описания `orders_count`, `canceled_orders` |
| Verify | цикл §5 перед коммитом | `verify ok`, full-отметка дерева `63ea9f6b` |
| CI | `gh run watch 44811320997 --exit-status` | exit 0, `success` на `580e608`, 13 job `success` |
| Пауза | `dbt_build` с начала сессии | снята последней; `airflow dags trigger dbt_build` один раз, run `success` |

Отклонения от пакета:
- Тест глоссария лежит в `tests/unit/test_dbt_exposures.py` (пакет файл не называл): он читает
  и бандл, и dbt.
- Тест ловушек по ревью требует фраз (`do not sum`, `fct_orders`; `do not average`,
  `on_time_rate`), а не только непустого описания.
- В exposure `maturity: medium`; подписи перед `doc()` убраны (блоки начинаются своей
  подписью), заголовок «Dashboard metrics defined on the datasets».
- `cancellation_rate` дополнен знаменателем продавца («orders with any item of the seller,
  deleted items included»); в `name_scopes` «can exceed», а не «exceeds».
- Описания колонок `mart_daily_sales` начинаются с сути колонки; строки > 100 перенесены, в том
  числе комментарий `lake_ro.properties`.

Не проверено: страница lineage в `dbt docs` (`dbt docs generate` не запускался; exposures есть в
manifest); вид дашборда глазами после импорта (проверены `check.py` и MCP).

Замечено вне пакета: `tests/unit/test_marketplace_dashboard.py:3` пишет `(W6-D17)` (P10);
`lake_ro.properties:5` 104 символа, было до пакета.

Риски: числа 297, 793/751/42 и 13 113 797.93 по шагу 4 стоят без даты замера и устареют после
следующего реплея молча (низкое замечание ревью); AOV прошлого квартала на плитке 135.30 ->
135.31.
