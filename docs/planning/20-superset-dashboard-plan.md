# План: дашборд Superset v2 и стиль Harbor

> Для исполнителей: план к спеке `20-superset-dashboard.md` (читать вместе). Исполнение по циклу
> `AGENTS.md`: оркестратор даёт `implementer` бриф одной задачи, тест на отказ первым, затем
> `make check`, `reviewer`, цикл verify; коммиты по разделу 5 спеки, не после каждого шага.
> Шаги с флажками (`- [ ]`) для отметок.

**Цель.** Дашборд `marketplace` по утверждённому макету и тема Harbor по умолчанию для всех
дашбордов проекта.

**Архитектура.** dbt даёт `customer_state` в `fct_order_items`; `superset_config.py` задаёт
тему, схемы цветов и якорь относительного времени из `SUPERSET_DATA_ANCHOR`; бандл YAML
(датасеты с сохранёнными метриками, 13 графиков, 2 нативных фильтра) импортируется скриптом
`import_bundle.py` с перезаписью по порядку датасеты, графики, дашборд.

**Стек.** Superset 6.1.0 (ECharts, AntD v5 токены), dbt-trino, pytest, PyYAML.

**Спека.** `docs/planning/20-superset-dashboard.md`, решения С-Д1..С-Д12 приняты 12.11.

## Общие ограничения

- Цвета только из раздела 3.2 спеки; строки `supersetColors` в бандле нет.
- Имена схем: категориальная `harbor`, последовательная `harbor_blue`, расходящаяся
  `harbor_diverging`.
- Переменная якоря `SUPERSET_DATA_ANCHOR`, значение по умолчанию в compose `2026-07-01`.
- Время в графиках и фильтрах только фразами `Last <unit>`, `Last <n> <units>` или `No filter`:
  `DATETIME("today")` и календарные фразы якорь не видят.
- Подписи на английском. Виртуальных датасетов нет. Объекты Superset не удаляются.
- Тесты Python на хосте не импортируют `superset` (его нет в окружении `uv`).

## Фокус ревью

1. Фильтр штата в области графика, у датасета которого нет `customer_state`: сервер молча
   отклоняет фильтр, цифры не меняются. Ожидание: в области фильтра только графики на датасетах
   с этой колонкой. Тест в задаче 3.
2. `series` в переопределении ECharts списком заменяет все серии графика и ломает его.
   Ожидание: объект. Тест в задаче 2.
3. Диапазон времени фразой, которая не видит якорь: KPI и тренды пусты. Тест в задаче 4.
4. Деление на ноль в долях, когда фильтр оставил штат без доставленных заказов. Ожидание:
   пустое значение, не ошибка. Тест в задаче 3 (`NULLIF` в каждой метрике с делением).
5. `query_context` графика расходится с `params`: дашборд верен, а `check.py`, MCP и API отдают
   другое. Тест в задаче 4.

---

### Задача 1 (Д2.1): `customer_state` в `fct_order_items`, описания колонок, PF-41

**Файлы.**
- Изменить: `dbt/models/marts/fct_order_items.sql` (строка `o.customer_state,` после
  `o.purchase_date,`), `dbt/models/marts/_core.yml`, `dbt/models/marts/_marts.yml`.
- Тесты: `tests/unit/test_dbt_bi_columns.py` (новый), `tests/unit/test_superset_bundle.py`.

**Интерфейсы.** Производит: колонку `gold.fct_order_items.customer_state` (varchar, штат
клиента заказа, null только у позиции без заказа); описания 24 колонок (раздел «Состояние»
ниже) и `customer_state`.

Состояние 12.11, колонок датасетов нет в YAML моделей: `fct_orders`: `customer_id`,
`customer_city`, `customer_state`, `order_status`, `order_purchase_timestamp`, `items_count`,
`freight_value`, `payment_value`, `is_delivered`, `is_canceled`; `fct_order_items`: `price`,
`freight_value`, `is_deleted`, `order_status`, `purchase_date`, `product_category`,
`seller_state`; `mart_daily_sales`: `orders_count`, `canceled_orders`, `items_count`,
`freight_value`; `mart_delivery_sla`: `delivered_orders`, `on_time_orders`,
`avg_delivery_days`. Описания по смыслу SQL моделей (например `is_canceled`: «order_status is
canceled»; `is_delivered`: «order_status is delivered»), по-английски, одна строка.

- [ ] **Шаг 1. Тесты на отказ.**
  `test_dbt_bi_columns.py::test_fct_order_items_selects_the_customer_state`: в тексте
  `fct_order_items.sql` есть `\bo\.customer_state\b`;
  `::test_core_yml_describes_the_customer_state_of_order_items`: у модели `fct_order_items` в
  `_core.yml` колонка `customer_state` с непустым `description`.
  `test_superset_bundle.py::test_every_dataset_column_is_described_in_dbt` (PF-41): для каждого
  датасета бандла каждая колонка без `expression` есть в `columns` модели с тем же
  `table_name` в `dbt/models/**/_*.yml`; сообщение называет датасет и колонку.
- [ ] **Шаг 2.** `uv run pytest tests/unit/test_dbt_bi_columns.py tests/unit/test_superset_bundle.py -q`
  -> 3 failed (PF-41 перечисляет 24 колонки).
- [ ] **Шаг 3 (оркестратор).** Пауза DAG `dbt_build` (REST `PATCH /api/v2/dags/dbt_build`
  `{"is_paused": true}` или `airflow dags pause dbt_build` в контейнере scheduler), проверка, что
  запуска в полёте нет.
- [ ] **Шаг 4.** Правка SQL и двух YAML; у `customer_state` без `not_null`.
- [ ] **Шаг 5.** Тесты шага 2 -> passed; `make check` зелёный; `make dbt-parse` rc 0.
- [ ] **Шаг 6 (оркестратор).** `make dbt-build` без ошибок; Trino: `select count(*) from
  lake.gold.fct_order_items where customer_state is null and not is_deleted` -> `0`.
- [ ] **Шаг 7.** `reviewer`, цикл verify, коммит `dbt: customer state on order items for the
  dashboard filter`, снятие паузы `dbt_build` последним шагом.

### Задача 2 (Д2.2): тема Harbor, схемы цветов, якорь времени

**Файлы.**
- Изменить: `docker/superset/superset_config.py`, `docker/compose.yaml` (сервисы `superset`
  со строки 807 и `superset-mcp` со строки 887: `environment`), `.env.example`.
- Тест: `tests/unit/test_superset_style.py` (новый).

**Интерфейсы.** Производит для задач 3 и 4: id схем `harbor`, `harbor_blue`,
`harbor_diverging`; ключ переопределения `echarts_timeseries_line`; переменную
`SUPERSET_DATA_ANCHOR`.

Значения (все из раздела 3.2 спеки):

| Ключ | Светлая `THEME_DEFAULT.token` | Тёмная `THEME_DARK.token` |
|---|---|---|
| `colorPrimary`, `colorLink` | `#175fa4` | `#2f74bb`, ссылка `#76afee` |
| `colorLinkHover` | `#064883` | `#76afee` |
| `colorSuccess`, `colorSuccessText`, `colorSuccessBg` | `#3a9742`, `#256c2c`, `#e8f9e7` | `#54b05a`, `#71c575`, `#1c2e1c` |
| `colorWarning`, `colorWarningText`, `colorWarningBg` | `#f4af2d`, `#794d0b`, `#fff4db` | `#f4af2d`, `#f1bf5b`, `#37290f` |
| `colorError`, `colorErrorText`, `colorErrorBg` | `#d03c3c`, `#aa2a2c`, `#ffebe9` | `#e55551`, `#f3827a`, `#401f1f` |
| `colorInfo` | `#2c71b7` | `#3f83cb` |
| `colorBgLayout`, `colorBgContainer` | `#f4f7fa`, `#ffffff` | `#0d1115`, `#181c21` |
| `colorTextBase`, `colorText` | `#131a24` | `#edf0f4` |
| `colorTextSecondary`, `colorTextTertiary` | `#48505d`, `#626a75` | `#bac2ca`, `#979fa8` |
| `colorBorder`, `colorBorderSecondary`, `colorSplit` | `#c3cad1`, `#e4e8ec`, `#e4e8ec` | `#3f464d`, `#272c31`, `#272c31` |
| `borderRadius` | `8` | `8` |

Остальные токены (`brand*`, `font*`, `transitionTiming`, `colorEditorSelection` и т. д.)
копируются литералом из `THEME_DEFAULT` 6.1.0 (`/app/superset/config.py:921-961` в контейнере):
своя тема заменяет словарь целиком, а импортировать `superset.config` из `superset_config.py`
нельзя (циклический импорт). `THEME_DEFAULT["algorithm"] = "default"`,
`THEME_DARK["algorithm"] = "dark"`.

Переопределение линий в обеих темах:
`"echartsOptionsOverridesByChartType": {"echarts_timeseries_line": {"series": {"lineStyle":
{"width": 3}, "smooth": True, "smoothMonotone": "x", "showSymbol": False}}}`.

Схемы: `EXTRA_CATEGORICAL_COLOR_SCHEMES = [{"id": "harbor", "label": "Harbor", "description":
"Marketplace Lakehouse palette", "isDefault": True, "colors": [<8 цветов раздела 3.2 по
порядку>]}]`; `EXTRA_SEQUENTIAL_COLOR_SCHEMES = [{"id": "harbor_blue", "label": "Harbor blue",
"isDefault": True, "isDiverging": False, "colors": [<9 шагов>]}, {"id": "harbor_diverging",
"label": "Harbor diverging", "isDefault": False, "isDiverging": True, "colors": [<7 шагов>]}]`.

Якорь: `DEFAULT_RELATIVE_START_TIME = DEFAULT_RELATIVE_END_TIME =
os.environ.get("SUPERSET_DATA_ANCHOR", "today")`.

- [ ] **Шаг 1. Тест на отказ** `test_superset_style.py`. Фикстура грузит `superset_config.py`
  через `importlib.util.spec_from_file_location` с `monkeypatch.setenv` для
  `SUPERSET_DATABASE_URI`, `SUPERSET_SECRET_KEY` и (кроме одного теста) `SUPERSET_DATA_ANCHOR`.
  Тесты: `test_harbor_is_the_only_default_categorical_scheme` (список равен ожидаемому
  целиком); `test_sequential_and_diverging_harbor_schemes`;
  `test_theme_tokens_follow_harbor` (по таблице выше, обе темы, `algorithm`);
  `test_line_override_is_an_object_for_every_series` (`series` это `dict`, ширина 3,
  `smoothMonotone == "x"`, обе темы; фокус ревью 2);
  `test_relative_time_anchor_comes_from_the_environment` (`2026-07-01` -> обе переменные);
  `test_relative_time_defaults_to_today_without_the_anchor`;
  `test_compose_passes_the_anchor_to_superset_and_its_mcp` (`yaml.safe_load` compose: у
  `superset` и `superset-mcp` `SUPERSET_DATA_ANCHOR: ${SUPERSET_DATA_ANCHOR:-2026-07-01}`).
- [ ] **Шаг 2.** `uv run pytest tests/unit/test_superset_style.py -q` -> все failed.
- [ ] **Шаг 3.** Правка `superset_config.py`, compose, `.env.example` (строка
  `SUPERSET_DATA_ANCHOR=2026-07-01` с комментарием «first day of the month of the latest order;
  Superset counts Last N days/months from it»).
- [ ] **Шаг 4.** Тест -> passed; `make check` зелёный; `docker compose --env-file .env.example
  -f docker/compose.yaml --profile bi config -q` rc 0.

### Задача 3 (Д2.3): датасеты, метрики, фильтры, импорт с перезаписью

**Файлы.**
- Изменить: `docker/superset/dashboards/datasets/Lakehouse_Trino_lake_ro/fct_orders.yaml`,
  `fct_order_items.yaml`, `mart_delivery_sla.yaml`; `docker/superset/dashboards/dashboards/Marketplace.yaml`
  (`metadata.native_filter_configuration`); `docker/superset/init.sh`; `docker/compose.yaml`
  (`superset-init`: том `./superset/import_bundle.py:/init/import_bundle.py:ro`, комментарий
  `:881-883`).
- Создать: `docker/superset/import_bundle.py`.
- Тесты: `tests/unit/test_superset_bundle.py`, `tests/unit/test_superset_import.py` (новый).

**Интерфейсы.** Производит для задачи 4 сохранённые метрики (имя -> выражение):

| Датасет | Метрика | Выражение |
|---|---|---|
| `fct_orders` | `gmv` | `SUM(CASE WHEN order_status NOT IN ('canceled', 'unavailable') THEN items_value END)` |
| | `orders` | `COUNT(*)` |
| | `paid_orders` | `COUNT_IF(order_status NOT IN ('canceled', 'unavailable'))` |
| | `aov` | выражение `gmv` / `NULLIF(` выражение `paid_orders` `, 0)` |
| | `freight_share` | `SUM(CASE WHEN order_status NOT IN ('canceled', 'unavailable') THEN freight_value END)` / `NULLIF(` выражение `gmv` `, 0)` |
| | `on_time_rate` | `1.0 * COUNT_IF(is_delivered AND NOT is_late) / NULLIF(COUNT_IF(is_delivered), 0)` |
| | `cancellation_rate` | `1.0 * COUNT_IF(order_status = 'canceled') / NULLIF(COUNT(*), 0)` |
| | `delivered_orders` | `COUNT_IF(is_delivered)` |
| | `late_orders` | `COUNT_IF(is_late)` |
| | `avg_delivery_days` | `AVG(CASE WHEN is_delivered THEN delivery_days END)` |
| | `in_transit_orders` | `COUNT_IF(NOT is_delivered AND order_status NOT IN ('canceled', 'unavailable'))` |
| `fct_order_items` | `gmv` | `SUM(CASE WHEN NOT is_deleted AND order_status NOT IN ('canceled', 'unavailable') THEN price END)` |
| `mart_delivery_sla` | `on_time_rate` | `1.0 * SUM(on_time_orders) / NULLIF(SUM(delivered_orders), 0)` |

`verbose_name` метрик по-английски, как подписи макета (`GMV`, `Orders`, `Average order
value`, `Freight share`, `On-time delivery`, `Cancellation rate` и т. д.). Существующую метрику
`count` не трогать. В `fct_order_items.yaml` колонка `customer_state` и вычисляемая
`category_label` (`expression: replace(product_category, '_', ' ')`, `verbose_name:
Category`).

Нативные фильтры (форма по `migrations/shared/native_filters.py:94-221` в контейнере):
- `NATIVE_FILTER-period001`, `name: Period`, `filterType: filter_time`, `targets: [{}]`,
  `defaultDataMask: {extraFormData: {time_range: Last quarter}, filterState: {value: Last
  quarter}}`, `scope: {rootPath: [ROOT_ID], excluded: [<chartId трендов и Data through>]}`;
- `NATIVE_FILTER-cstate001`, `name: Customer state`, `filterType: filter_select`, `targets:
  [{column: {name: customer_state}, datasetUuid: ab73c7d5-dce3-5791-a95e-6fbb48d0a084}]`,
  `controlValues: {multiSelect: true, enableEmptyFilter: false, defaultToFirstItem: false,
  inverseSelection: false, searchAllOptions: false}`, `defaultDataMask: {extraFormData: {},
  filterState: {value: null}}`, `scope: {rootPath: [ROOT_ID], excluded: [<chartId Data
  through>]}`. `chartsInScope` не писать.

`import_bundle.py`: `main(bundle: Path) -> None`. Читает все файлы бандла в словарь
`{относительный путь: текст}`; для каждой команды подменяет `metadata.yaml` на
`{version: 1.0.0, type: <SqlaTable|Slice|Dashboard>, timestamp: ...}`; в контексте приложения
(`superset.app.create_app()`, `app.app_context()`, `override_user(security_manager.find_user(
username="admin"))`) по порядку `ImportDatasetsCommand(contents, overwrite=True).run()`,
`ImportChartsCommand(...)`, `ImportDashboardsCommand(...)`. Ошибка любой команды: выход с кодом
1 (сейчас CLI логирует исключение и выходит с 0). `init.sh`: вместо блока сборки архива и
`superset import-dashboards` строка `python /init/import_bundle.py "$BUNDLE_DIR"`; проверка
Trino перед импортом остаётся.

Перенесено из ревью задачи 1 (круг 2, 12.11, «принять с замечаниями»), делается в этой задаче:
- среднее: `test_every_dataset_column_is_selected_by_its_model` ищет слово в любом месте SQL и
  ловит только `col as alias` у колонки, которая встречается один раз; 6 колонок датасетов не
  защищены (`fct_order_items.order_id`, `product_id`, `seller_id`; `fct_orders.order_status`;
  `mart_daily_sales.purchase_date`; `mart_delivery_sla.customer_state`). Сравнивать множества
  имён на выходе финального `select` (элемент верхнего уровня: алиас после последнего `as`,
  иначе последний идентификатор после `.`); мутации `order_status as status`, удаление
  `i.seller_id,`, `upper(p.product_category) as category` должны краснеть; docstring не обещает
  больше, чем проверяется;
- низкое: `COMMENT` и `without_comments` вынести из `test_dbt_soft_delete.py` в общий модуль
  тестов (сейчас два теста импортируют его из тестового модуля); `re.escape` для имени колонки;
- низкое (dbt, при паузе `dbt_build`): `_marts.yml` `mart_daily_sales.seller_state`: «State of a
  seller among the items of the orders of the row»; `_core.yml` `fct_order_items.customer_state`:
  «Null if the order or its customer is missing».

- [ ] **Шаг 1. Тесты на отказ.**
  `test_superset_bundle.py`: `test_category_chart_counts_live_items_of_paid_orders` (PF-42:
  метрика графика категорий это `gmv` датасета `fct_order_items`, в её выражении есть
  `NOT is_deleted` и оба статуса); `test_every_ratio_metric_guards_division` (фокус ревью 4:
  каждое выражение метрики с `/` содержит `NULLIF`);
  `test_period_filter_defaults_to_last_quarter_and_skips_trends`;
  `test_state_filter_reaches_only_charts_with_the_column` (фокус ревью 1: каждый график в
  области `Customer state` стоит на датасете с колонкой `customer_state`).
  `test_superset_import.py` (разбор `import_bundle.py` через `ast`, без импорта superset):
  `test_bundle_import_overwrites_datasets_charts_dashboard_in_order`;
  `test_each_import_gets_its_own_metadata_type`; `test_init_runs_the_bundle_import`
  (`init.sh` вызывает `/init/import_bundle.py`, `superset import-dashboards` в нём нет);
  `test_superset_init_mounts_the_import_script` (compose).
- [ ] **Шаг 2.** Новые тесты -> failed.
- [ ] **Шаг 3.** Правка датасетов, фильтров, скрипта, `init.sh`, compose. `chartId` трендов в
  `excluded` берутся из `position` задачи 4: здесь фильтры пишутся с `excluded` по номерам,
  которые задача 4 назначит (таблица задачи 4, колонка `chartId`).
- [ ] **Шаг 4.** Тесты -> passed; `make check` зелёный.

### Задача 4 (Д2.4): графики и раскладка

**Файлы.** `docker/superset/dashboards/charts/*.yaml` (4 перезаписать, 9 создать),
`dashboards/Marketplace.yaml` (`position`, `metadata`); тесты в `test_superset_bundle.py`.

**Интерфейсы.** Потребляет метрики и фильтры задачи 3, схему `harbor` задачи 2.

Графики (uuid новых: `uuid.uuid5(uuid.NAMESPACE_URL, "lakehouse/superset/chart/<файл без
.yaml>")`):

| `chartId` | Файл | uuid | `viz_type` | Датасет | Главное в `params` | Фильтры |
|---|---|---|---|---|---|---|
| 1 | `data_through.yaml` | новый | `handlebars` | `fct_orders` | метрика `MAX(purchase_date)` с label `data_through`; `handlebarsTemplate`: «Data through {{dateFormat …}}» в формате `D MMM YYYY` | вне обоих |
| 2-7 | `kpi_gmv`, `kpi_orders`, `kpi_aov`, `kpi_freight_share`, `kpi_on_time`, `kpi_cancellation_rate` | новые | `pop_kpi` | `fct_orders` | метрика по имени; `time_compare: [inherit]`; `comparison_color_enabled: true`; `comparison_color_scheme`: `Red` у доли фрахта и доли отмен, `Green` у остальных; R$ через `currency_format` у GMV и AOV; доли `.1%` (отмены `.2%`); `subtitle` как подписи макета | Period, штат |
| 8 | `daily_sales.yaml` (GMV by month) | `fedd884c-a753-54d2-8d42-7f11d9bc5540` | `echarts_timeseries_line` | `fct_orders` | `gmv`, сетка `P1M`, `time_range: Last year`, `time_compare: [1 year ago]`, `comparison_type: values`, `color_scheme: harbor` | штат |
| 9 | `gmv_by_category.yaml` (Top 10 categories) | `38fb522a-dbb6-534c-9c83-5345c61a1240` | `echarts_timeseries_bar`, горизонтальный | `fct_order_items` | `x_axis: category_label`, `gmv`, 10 строк по убыванию, значения на столбцах | Period, штат |
| 10 | `on_time_by_month.yaml` | новый | `echarts_timeseries_line` | `mart_delivery_sla` | `on_time_rate`, `P1M`, `Last year`, ось 0.75-1.0, `.0%`, слой `FORMULA` `Target 95%`, `value` `0.95`, пунктир, ширина 1.5, `#48505d` | штат |
| 11 | `delivery_sla.yaml` (States with the most late deliveries) | `203f021c-39d0-5703-baa6-abd82d61b845` | `table` | `fct_orders` | группа `customer_state`; `delivered_orders`, `late_orders`, `on_time_rate`, `avg_delivery_days`; `HAVING COUNT_IF(is_delivered) >= 50`; порядок по `on_time_rate` по возрастанию; 8 строк; `conditional_formatting` `<` `0.95` цвет `#d03c3c` | Period, штат |
| 12 | `cancellations.yaml` (Cancellation rate by month) | `664e832f-1b2d-578a-b059-ac81f90ac19c` | `echarts_timeseries_line` | `fct_orders` | `cancellation_rate`, `P1M`, `Last year`, `.2%` | штат |
| 13 | `orders_by_status.yaml` | новый | `echarts_timeseries_bar`, горизонтальный | `fct_orders` | `x_axis: order_status`, `orders`, по убыванию, значения на столбцах | Period, штат |

У каждого графика `query_context` повторяет `params` (как у нынешних графиков: `form_data`
равен `params`, метрики запроса равны метрикам `params`).

`Marketplace.yaml`: `MARKDOWN` с заголовком «Marketplace overview» и подзаголовком макета
плюс строка «Figures by complete months; the month in progress is left out.»; ряд KPI из 6
графиков по ширине 2; заголовки разделов `HEADER` «Sales», «Delivery», «Orders»; ряды 8+4, 6+6,
6+6. `metadata`: `color_scheme: harbor`, `color_scheme_domain` = 8 цветов `harbor`,
`label_colors` для ряда «год назад» (`GMV__1 year ago`: `#8c959f`, `GMV`: `#2c71b7`; точное
имя ряда сверить в задаче 5).

- [ ] **Шаг 1. Тесты на отказ** в `test_superset_bundle.py`:
  `test_harbor_is_the_scheme_everywhere` (в текстах бандла нет `supersetColors`; у дашборда и
  у каждого графика с `color_scheme` значение `harbor`);
  `test_kpis_treat_growth_of_freight_and_cancellations_as_bad`;
  `test_on_time_chart_draws_the_95_percent_target`;
  `test_states_table_hides_small_states_and_flags_misses` (`>= 50`, 8 строк, порядок по
  возрастанию, правило `<` 0.95);
  `test_time_ranges_use_only_anchored_phrases` (фокус ревью 3: каждое `time_range` в
  `params` и в фильтрах соответствует `^(Last \w+|Last \d+ \w+|No filter)$`);
  `test_query_context_repeats_params` (фокус ревью 5);
  `test_the_four_old_charts_keep_their_uuids` (С-Д10).
- [ ] **Шаг 2.** Новые тесты -> failed.
- [ ] **Шаг 3.** 13 графиков и раскладка.
- [ ] **Шаг 4.** Весь `test_superset_bundle.py` -> passed; `make check` зелёный.
- [ ] **Шаг 5 (оркестратор).** `reviewer` по задачам 2-4 одним кругом на дерево; исправления
  не больше двух кругов; цикл verify; коммит `infra: superset harbor theme, data anchor and
  marketplace dashboard v2`; push; CI зелёный.

### Задача 5 (Д2.5): живой импорт, проверка, документы

Выполняет оркестратор; документы пишет `docs-writer`.

- [ ] **Шаг 1.** По «ок» на точный текст `make up PROFILE=bi`: пересоздаются `superset`,
  `superset-mcp`, `superset-init`. Лог `superset-init` без ошибок импорта, rc 0.
- [ ] **Шаг 2.** `docker compose exec superset python /app/check.py` -> 13 строк
  `<график>: <n> rows`, rc 0.
- [ ] **Шаг 3.** Проверки в контейнере `superset` через REST (вход админом, как `check.py`):
  `POST /api/v1/chart/data` по `query_context` `kpi_gmv`, `kpi_orders`, `kpi_on_time` с
  `time_range: Last quarter` и `time_offsets: [inherit]` -> значения раздела 2 спеки
  (2 687 103,87 и 2 863 849,49; 18 991 и 21 355; 0.966 и 0.875); `gmv_by_category` с фильтром
  `customer_state IN ('SP')` -> фильтр в `applied_filters`, не в `rejected_filters`;
  `daily_sales` -> имена колонок ответа для `label_colors`. Если имя ряда сравнения другое,
  правка `label_colors` малым diff (цикл: тест, ревью, verify, коммит).
- [ ] **Шаг 4.** Визуальная приёмка в светлой теме (скриншот владельца или MCP Playwright):
  цвета Harbor, серый ряд «год назад», линии 3px без горбов ниже нуля в 10-11.2024 ряда
  сравнения, линия цели, подсветка ячеек, KPI. Если линии не те, С-Д9: из переопределения
  убрать `smooth` и `smoothMonotone` (или всё переопределение, если не дошла и ширина), малый
  diff по циклу.
- [ ] **Шаг 5.** `docs-writer`: README (скриншот `docs/img/superset-marketplace.png`, строка),
  OPERATIONS (раздел Superset: `SUPERSET_DATA_ANCHOR` и как его сдвинуть после реплея,
  пересоздание `superset` класс C; порядок импорта вместо `OPERATIONS.md:490-494`; где
  палитра), evidence (числа KPI с датой). Ссылки без битых.
- [ ] **Шаг 6.** Коммит `docs: superset dashboard v2 live, screenshot, anchor runbook`; push;
  HANDOFF, NEXT_SESSION, индекс `docs/planning/README.md`.
