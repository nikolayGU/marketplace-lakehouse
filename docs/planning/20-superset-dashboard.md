# 20. Дашборд Superset Marketplace v2 и стиль Harbor

Статус: действует, раздел 2 принят владельцем 12.11.2026 («ок подтверждаю рекомендации»). Вход: раздел 6 файла 19
(вариант A), макет и три палитры на холсте (артефакт «Marketplace dashboard mockup»,
https://claude.ai/artifact/FofqJJrQhGtVc5DCyffxYo, Page 1: `Main`, `Palette-harbor`).

## 1. Цель и границы

Результат: дашборд `marketplace` в Superset повторяет утверждённый макет (шапка, фильтры, 6 KPI,
разделы Sales, Delivery, Orders) на gold через `lake_ro`, и все дашборды проекта по умолчанию
берут одну палитру и тему Harbor. Скриншот дашборда стоит в README.

Состояние на входе (12.11, проверено):
- бандл `docker/superset/dashboards/`: 4 графика (`daily_sales`, `gmv_by_category`,
  `delivery_sla`, `cancellations`), 4 физических датасета, `color_scheme: supersetColors`
  (`Marketplace.yaml:105`), фильтров нет (`native_filter_configuration: []`, `:113`);
- `docker/superset/superset_config.py` не задаёт ни темы, ни схем цветов, ни якоря времени;
- данные кончаются 18.07.2026 по часам реплея, сегодня 12.11.2026; Superset считает «Last N»
  от `DEFAULT_RELATIVE_START_TIME` и `DEFAULT_RELATIVE_END_TIME`, по умолчанию `today`
  (`/app/superset/config.py:2048-2049` в контейнере), поэтому «последние 90 дней» сейчас пусты;
- GMV по правилу D8 (позиции без `is_deleted`, заказы не `canceled` и не `unavailable`) из
  `fct_orders` равен `mart_daily_sales.gmv` в 23 месяцах из 23, итог 13 113 797,93 (MCP Superset,
  `execute_sql`, 12.11).

Входит: колонка `customer_state` в `fct_order_items`; тема, схемы цветов и якорь времени в
`superset_config.py` и `compose.yaml`; датасеты, графики, фильтры и раскладка бандла; тесты;
живой импорт по «ок»; README, OPERATIONS, evidence.

За владельцем: «ок» на раздел 2; «ок» на `make up PROFILE=bi` (Д2.5); визуальная приёмка.

Не входит: вариант B (вкладки, продавцы), палитра Grafana, ADR-027 и ADR-028 (R-61, этап 2
документов: туда войдут решения С-Д7, С-Д8 этой спеки), MCP Playwright.

## 2. Решения

| ID | Вопрос | Решение | Альтернатива | Цена ошибки | Статус |
|---|---|---|---|---|---|
| С-Д1 | Раскладка | как макет `Main`: шапка, фильтры, 6 KPI, Sales (GMV по месяцам 8 колонок, топ-10 категорий 4), Delivery (доля в срок по месяцам 6, худшие штаты 6), Orders (доля отмен по месяцам 6, статусы 6) | вариант B | переделка раскладки | принято 12.11 |
| С-Д2 | Фильтры | период и штат клиента; фильтра категории нет | фильтр категории только для одного графика | путаница: фильтр сужает один график | принято 12.11 |
| С-Д3 | Цель доставки в срок | 95% | без цели | линия цели и подсветка ячеек вводят в заблуждение | принято 12.11 |
| С-Д4 | Палитра и линии | Harbor (раздел 3.2); линии 3px, ряд «год назад» серый, сглаживание без выхода за точки (монотонное по x), маркер только у последней точки | Sandstone, Dusk | — | принято 12.11 |
| С-Д5 | Язык | подписи на английском, как README | русский | расхождение с публичными документами | принято 12.11 |
| С-Д6 | Как фильтр штата клиента дойдёт до категорий | колонка `customer_state` в `fct_order_items` (dbt, `o.customer_state` из уже существующего join с `fct_orders`) | виртуальный датасет с join | виртуальные датасеты запрещены тестом `test_every_dataset_is_a_gold_mart_of_lake_ro_in_this_database` | принято 12.11 (список решений к макету) |
| С-Д7 | Якорь относительного времени | `DEFAULT_RELATIVE_START_TIME` и `DEFAULT_RELATIVE_END_TIME` из переменной `SUPERSET_DATA_ANCHOR`, значение: первый день месяца, в котором лежит последний заказ (сейчас `2026-07-01`). Тогда «Last quarter» = 01.04–30.06.2026, «Last year» = 12 полных месяцев 07.2025–06.2026, неполный июль нигде не смешивается с полными месяцами | день после последнего заказа (`2026-07-19`): KPI как в макете (20.04–18.07), но трендам нужны явные даты в четырёх графиках, их надо подставлять при импорте; правка после каждой порции реплея | KPI или тренды на неполном месяце; лишние правки после реплея | принято 12.11 |
| С-Д8 | Где тема | `THEME_DEFAULT` и `THEME_DARK` в `superset_config.py` | тема в бандле (`themes/`, `theme_uuid`) | импорт темы жёстко `overwrite=False` (`commands/dashboard/importers/v1/__init__.py:108-111` в контейнере): правка темы молча не применится | принято 12.11 |
| С-Д9 | Если переопределение ECharts в теме не даст монотонное сглаживание и 3px | прямые линии 3px, если ширина применилась; иначе прямые 2px по умолчанию | встроенный «Smooth line» (сплайн без монотонности) | сплайн уводит ряд «год назад» ниже нуля между нулевыми месяцами 10.2024 и 11.2024 | принято 12.11 |
| С-Д10 | Старые 4 графика | новые графики берут их uuid: `daily_sales` -> GMV по месяцам, `gmv_by_category` -> топ-10 категорий, `delivery_sla` -> худшие штаты, `cancellations` -> доля отмен по месяцам; работает только вместе с С-Д12 | новые uuid | импорт не удаляет графики вне бандла: в Superset остались бы 4 сироты, удаление это класс C | принято 12.11 |
| С-Д11 | Источник GMV | метрика на `fct_orders` по D8 (см. раздел 1) | `mart_daily_sales.gmv` | у витрины штат продавца, фильтр штата клиента на неё не действует | принято 12.11 |
| С-Д12 | Как правки бандла доходят до живого Superset | бандл главный: `init.sh` импортирует датасеты с `overwrite=True` (колонки и метрики сверяются с YAML, лишние удаляются), графики с `overwrite=True`, затем дашборд, как сейчас. Правки из UI теряются при каждом `superset-init` | как сейчас: `superset import-dashboards` перезаписывает только дашборд, датасеты и графики импортируются с `overwrite=False` (контейнер: `commands/dashboard/importers/v1/__init__.py:128,147`; `OPERATIONS.md:490-494`); новые метрики, колонки и 4 графика с прежними uuid в Superset не попадут, `check.py` упадёт | правки бандла не доходят до стенда, или правки из UI теряются | принято 12.11 |

Ожидаемые числа KPI при С-Д7 по рекомендации (период 01.04–30.06.2026 против предыдущих 91 дня,
31.12.2025–31.03.2026, как считает `inherit`: `models/helpers.py:1692-1695` в контейнере), запрос
в разделе 6:

| KPI | Период | Прошлый | Изменение |
|---|---|---|---|
| GMV | 2 687 103,87 | 2 863 849,49 | −6.2% |
| Orders | 18 991 | 21 355 | −11.1% |
| On-time | 17 919 из 18 545 = 96.6% | 18 204 из 20 814 = 87.5% | +9.2 pp |

## 3. Ограничения блока

### 3.1 Общие

- Классы действий по `13-harness.md`, раздел 2. Файлы `docker/` и бандл это класс B (ревью,
  полные проверки). `make up PROFILE=bi` пересоздаёт `superset`, `superset-mcp`, `superset-init`:
  класс C, «ок» на точный текст.
- `dbt/` смонтирован в живой Airflow: правка Д2.1 при паузе DAG `dbt_build`; `make dbt-build`
  класс A только при паузе и без запуска в полёте.
- Виртуальных датасетов нет (тест). Объекты Superset (графики, датасеты, дашборды) не
  удаляются; колонки и метрики датасетов сверяются с YAML при импорте (С-Д12). Палитра Grafana
  не меняется.
- Цвета рядов одни и те же в светлой и тёмной теме: схема Superset хранит один hex на ряд.
  Тёмные значения раздела 3.2 идут только в токены `THEME_DARK`. Визуальная приёмка в светлой
  теме.
- В бандле нигде нет `supersetColors`; цвета только из раздела 3.2.
- Версия Superset 6.1.0 (`docker/superset/Dockerfile:7`). Поведение сверять в контейнере
  `lakehouse-superset-1` (`/app/superset`) только чтением.

### 3.2 Harbor (светлая тема; тёмная в скобках)

| Роль | Значение |
|---|---|
| Фон страницы, карточка | `#f4f7fa`, `#ffffff` (`#0d1115`, `#181c21`) |
| Текст основной, вторичный, приглушённый | `#131a24`, `#48505d`, `#626a75` (`#edf0f4`, `#bac2ca`, `#979fa8`) |
| Сетка, ось | `#e4e8ec`, `#c3cad1` (`#272c31`, `#3f464d`) |
| Основной ряд | `#2c71b7` (`#3f83cb`) |
| Ряд сравнения «год назад» | `#8c959f` (`#606870`) |
| Линия цели | `#48505d`, 1.5px, пунктир |
| Primary (кнопки, ссылки), hover | `#175fa4`, `#064883` (`#2f74bb`, ссылка `#76afee`) |
| Хорошо: заливка, текст, фон | `#3a9742`, `#256c2c`, `#e8f9e7` |
| Внимание: заливка, текст, фон | `#f4af2d`, `#794d0b`, `#fff4db` |
| Плохо: заливка, текст, фон | `#d03c3c`, `#aa2a2c`, `#ffebe9` |
| Категории 1-8, порядок фиксирован | `#2c71b7`, `#d6781c`, `#0f9b89`, `#795dba`, `#9e6128`, `#3498bf`, `#bb8d1c`, `#c55b96` |
| Последовательная шкала | `#ecf1f7`, `#cadbee`, `#a7c4e5`, `#82abda`, `#5c93cf`, `#337ac3`, `#1762a9`, `#024b89`, `#003768` |
| Расходящаяся шкала | `#024884`, `#3377be`, `#80afe3`, `#e8eaec`, `#da9b6b`, `#ad5d00`, `#6c3803` |

Проверено 12.11 (`dataviz/scripts/validate_palette.py`): категории в светлом режиме на `#ffffff`
ALL CHECKS PASS, худшая соседняя пара CVD 12.3, нормальное зрение 21.5; тёмные значения тоже PASS
(дизайнер, команды в отчёте сессии). Текст не ниже 4.5:1 на карточке и странице.

## 4. Карточки

### Д2.1 `customer_state` в `fct_order_items` и описания колонок

**Зачем.** Фильтр штата клиента должен сужать и график категорий (С-Д6). Тест PF-41 (Д2.3)
сверяет колонки датасетов Superset с описаниями dbt, а 24 колонки датасетов сегодня в
`_core.yml` и `_marts.yml` не описаны (сверка 12.11: 10 у `fct_orders`, 7 у `fct_order_items`,
4 у `mart_daily_sales`, 3 у `mart_delivery_sla`).
**Оценка** 2 ч. **Зависит от:** «ок» на раздел 2. **Область коммита:** `dbt`.

**Вход.** `dbt/models/marts/fct_order_items.sql:4-20` (join `o` с `fct_orders` уже есть),
`dbt/models/marts/_core.yml:31-` (описание модели), материализация marts `table`
(`dbt/dbt_project.yml:26`), тесты `tests/unit/test_dbt_soft_delete.py`.

**Сделать.**
1. Тесты на отказ: в `tests/unit/` проверка, что `fct_order_items.sql` выбирает
   `o.customer_state` и `_core.yml` описывает колонку `customer_state` у `fct_order_items`;
   в `test_superset_bundle.py` проверка PF-41: колонки каждого датасета есть в описании модели
   dbt (`dbt/models/**/_*.yml`), вычисляемые колонки с `expression` не в счёт (перенесена сюда
   из Д2.3: она и задаёт шаг 3).
2. Пауза DAG `dbt_build`; строка `o.customer_state` после `o.purchase_date`; колонка в
   `_core.yml` с описанием «state of the customer of the order, for BI filters» (без `not_null`:
   join левый, у позиции без заказа штата нет).
3. Описания (`description`, без новых тестов данных) всех колонок, которые выставляют датасеты
   бандла и которых нет в YAML моделей; список даёт сверка `docker/superset/dashboards/datasets/**`
   против `dbt/models/marts/_core.yml` и `_marts.yml`.
4. `make dbt-parse`, `make dbt-build`, снять паузу последним шагом после коммита.

**Готово, когда.**
- новый тест красный до правки, зелёный после; `make check` зелёный;
- `make dbt-build` без ошибок;
- Trino: `select count(*) from lake.gold.fct_order_items where customer_state is null and not
  is_deleted` -> 0.

**Ловушки.** Правка без паузы `dbt_build`: живой Airflow возьмёт непроверенный SQL.

**Blast radius и пайплайн.** Пересоздаётся таблица `gold.fct_order_items` служебным DROP dbt
(D13, D14). Silver, bronze, Kafka, реплей не затронуты.

**Не входит.** Метрики и датасеты Superset (Д2.3).

### Д2.2 Тема Harbor, схемы цветов и якорь времени

**Зачем.** Один стиль на все дашборды проекта (С-Д4, С-Д8) и «последний период» по часам
данных (С-Д7).
**Оценка** 2.5 ч. **Зависит от:** раздел 2. **Область коммита:** `infra` (вместе с Д2.3, Д2.4).

**Вход.** `docker/superset/superset_config.py` (32 строки), сервисы `superset`, `superset-mcp`
в `docker/compose.yaml`; в контейнере `config.py:884-896` (формат категориальной схемы),
`:996-1009` (последовательной), `:921-973` (`THEME_DEFAULT`, `THEME_DARK`), `:980`
(`ENABLE_UI_THEME_ADMINISTRATION = True`).

**Проверено первым 12.11** (scout, только чтение):
1. Системных тем в базе нет: `select id, theme_name, is_system_default, is_system_dark from
   themes` в базе `superset` -> `1|THEME_DEFAULT|f|f`, `2|THEME_DARK|f|f`. Действует тема из
   конфига.
2. Ключ переопределения это `viz_type` графика: `echarts_timeseries_line`
   (`05addb45f9966def4730.chunk.js`: `h.echartsOptionsOverridesByChartType?.[f]`, `f` = пропс
   `vizType`). Слияние `lodash.mergeWith`: массив в переопределении заменяет массив графика
   целиком, объект под ключом `series` сливается в каждый элемент массива серий. Значит
   `series` задаётся объектом, не списком. На живом графике не проверено: Д2.5, шаг 3.
3. `pop_kpi` красит стрелку токенами `colorSuccess` и `colorError`, плашки изменения токенами
   `colorSuccessText`, `colorErrorText`, `colorSuccessBg`, `colorErrorBg`
   (`a2b6982f9575d54d7364.chunk.js`); своих цветов нет.

**Сделать.**
1. Тест на отказ `tests/unit/test_superset_style.py`: загрузка `superset_config.py` с
   подставленными env (`SUPERSET_DATABASE_URI`, `SUPERSET_SECRET_KEY`, `SUPERSET_DATA_ANCHOR`);
   проверки: схема `harbor` единственная с `isDefault: True` и цвета равны разделу 3.2;
   последовательная `harbor_blue` с `isDefault: True`; расходящаяся `harbor_diverging`;
   `THEME_DEFAULT` и `THEME_DARK` содержат токены раздела 3.2; `DEFAULT_RELATIVE_START_TIME`
   и `DEFAULT_RELATIVE_END_TIME` равны `SUPERSET_DATA_ANCHOR`; без переменной оба `today`;
   в `compose.yaml` у `superset` и `superset-mcp` есть `SUPERSET_DATA_ANCHOR` со значением по
   умолчанию `2026-07-01` (формат `YYYY-MM-01`).
2. `superset_config.py`: схемы (`EXTRA_CATEGORICAL_COLOR_SCHEMES`,
   `EXTRA_SEQUENTIAL_COLOR_SCHEMES`), темы (`colorPrimary`, `colorLink`, `colorLinkHover`,
   `colorSuccess`, `colorWarning`, `colorError`, `colorInfo`, `colorBgLayout`,
   `colorBgContainer`, `colorTextBase`, `colorText`, `colorTextSecondary`, `colorTextTertiary`,
   `colorBorder`, `colorBorderSecondary`, `borderRadius: 8`, шрифт по умолчанию Inter), у
   `THEME_DARK` `algorithm: dark`. Для плашек `pop_kpi` явно `colorSuccessText` `#256c2c`,
   `colorErrorText` `#aa2a2c`, `colorSuccessBg` `#e8f9e7`, `colorErrorBg` `#ffebe9` (контраст
   4.5:1); иначе их выведет алгоритм AntD.
3. Переопределение ECharts для линий под ключом `echarts_timeseries_line`: `series` объектом
   с шириной 3px, `smooth`, `smoothMonotone: "x"`, без маркеров.
4. `compose.yaml`: `SUPERSET_DATA_ANCHOR: ${SUPERSET_DATA_ANCHOR:-2026-07-01}` у `superset` и
   `superset-mcp`; строка в `.env.example` с комментарием «first day of the month of the latest
   order».

**Готово, когда.**
- тест красный до правки, зелёный после; `make check` зелёный;
- `docker compose --env-file .env.example -f docker/compose.yaml --profile bi config -q` rc 0.

**Ловушки.** `DATETIME("today")` и календарные фразы («previous calendar month», «Current
month») якорь не видят, только «Last N …» (проба `get_since_until` 12.11): в графиках только
такие фразы. Верхняя граница диапазона исключающая.

**Blast radius и пайплайн.** Только Superset и его MCP после пересоздания (Д2.5). Данные не
затронуты.

### Д2.3 Датасеты, метрики и фильтры бандла

**Зачем.** Метрики KPI по D8 в одном месте и два фильтра на весь дашборд (С-Д2, С-Д11).
**Оценка** 4 ч. **Зависит от:** Д2.1. **Область коммита:** `infra`.

**Вход.** `docker/superset/dashboards/datasets/Lakehouse_Trino_lake_ro/*.yaml`,
`tests/unit/test_superset_bundle.py`, бэклог PF-41 и PF-42 (файл 18).

**Проверено первым 12.11** (scout, только чтение). Фильтр уходит во все графики своей области;
сервер применяет его там, где у датасета есть колонка с тем же именем, и молча отклоняет у
остальных (`models/helpers.py:3484-3498`, `common/query_actions.py:182-190`). Значит в области
фильтра штата только графики на датасетах с `customer_state`. В бандле цель фильтра пишется
через `datasetUuid`, импорт подставляет числовой `datasetId`
(`commands/dashboard/importers/v1/utils.py:127-135`). Форма записи: эталон
`migrations/shared/native_filters.py:94-221` в контейнере.

**Сделать.**
1. Тесты на отказ в `test_superset_bundle.py`:
   график категорий фильтрует `not is_deleted` и статусы `canceled`, `unavailable` (PF-42);
   фильтр «Period» типа `filter_time` с умолчанием `Last quarter`; фильтр «Customer state»;
   графики трендов вне области фильтра «Period».
2. `fct_orders.yaml`: `main_dttm_col: purchase_date`; метрики `gmv`, `orders`, `paid_orders`,
   `aov`, `freight_share`, `on_time_rate`, `cancellation_rate`, `delivered_orders`,
   `late_orders`, `avg_delivery_days`, `in_transit_orders`. Формулы: GMV
   `SUM(CASE WHEN order_status NOT IN ('canceled','unavailable') THEN items_value END)`; AOV =
   GMV / paid orders; freight share = фрахт тех же заказов / GMV; on-time =
   `COUNT_IF(is_delivered AND NOT is_late) / COUNT_IF(is_delivered)`; cancellation rate =
   `COUNT_IF(order_status = 'canceled') / COUNT(*)`.
3. `fct_order_items.yaml`: колонка `customer_state`; вычисляемая `category_label` =
   `replace(product_category, '_', ' ')`; метрика `gmv` по D8.
4. `mart_delivery_sla.yaml`: метрика `on_time_rate`.
5. `Marketplace.yaml`: `native_filter_configuration` с двумя фильтрами (раздел 2, С-Д2, С-Д7).
6. Импорт по С-Д12: скрипт `docker/superset/import_bundle.py` заменяет в `init.sh` сборку
   архива и `superset import-dashboards`. В контексте приложения от имени `admin` он по порядку
   вызывает `ImportDatasetsCommand`, `ImportChartsCommand`, `ImportDashboardsCommand`, все с
   `overwrite=True`. Каждой команде свой `metadata.yaml` с типом `SqlaTable`, `Slice`,
   `Dashboard`: импорт проверяет тип (`commands/importers/v1/utils.py:90-102`), а файл бандла
   объявляет `Dashboard`. У CLI нет импорта графиков с перезаписью, поэтому скрипт. Монтируется
   в `superset-init` рядом с `init.sh` (`compose.yaml:868`). Комментарий в
   `docker/compose.yaml:881-883` под новое поведение.

**Готово, когда.** Тесты красные до правки, зелёные после; `make check` зелёный.

**Ловушки.** Колонка в YAML, которой ещё нет в Trino, импортируется без ошибки и ломает запросы:
Д2.1 живьём до Д2.5. `chartsInScope` в 6.1.0 при импорте не пересчитывается: не писать
(файл 19, раздел 6).

### Д2.4 Графики и раскладка

**Зачем.** Сам дашборд по макету.
**Оценка** 5 ч. **Зависит от:** Д2.2, Д2.3. **Область коммита:** `infra`.

**Вход.** Графики бандла (`charts/*.yaml`, у каждого `params` и `query_context` в одном виде:
`check.py` читает данные через `/api/v1/chart/{id}/data/`, ему нужен `query_context`), макет
`Main` на холсте.

**Проверено первым 12.11** (scout, только чтение). `handlebars` зарегистрирован в 6.1.0
(`8115.b1f8cee824d849099ff3.entry.js`), шаблон в ключе `handlebarsTemplate`, данные в шаблоне
`data`, хелпер `dateFormat`. Ряд сравнения называется `<label метрики>__1 year ago`
(`models/helpers.py:1583-1586`); как имя выглядит в `label_colors`, проверяется в Д2.5, шаг 3.

**Сделать.**
1. Тесты на отказ: у дашборда и каждого графика `color_scheme: harbor`, `supersetColors` в
   бандле нет; у KPI доли фрахта и доли отмен `comparison_color_scheme` «рост красный»;
   у графика доли в срок слой `FORMULA` 0.95; у таблицы штатов `HAVING` доставок от 50, порядок
   по доле в срок по возрастанию, 8 строк, условное форматирование ниже 0.95.
2. Шапка: Markdown (заголовок, подзаголовок макета) и «Data through»: `handlebars` с
   `max(purchase_date)`, вне области обоих фильтров.
3. 6 KPI `pop_kpi` на `fct_orders` (`time_compare: inherit`, R$ через `currency_format`,
   подпись `subtitle` как в макете).
4. Тренды на `time_range: Last year`, сетка месяц: GMV с `time_compare: ["1 year ago"]` и серым
   рядом сравнения через `label_colors` (uuid `daily_sales`); доля в срок на `mart_delivery_sla`
   со слоем цели (новый uuid); доля отмен (uuid `cancellations`).
5. Топ-10 категорий, горизонтальные столбцы по `category_label` (uuid `gmv_by_category`);
   статусы заказов, горизонтальные столбцы (новый uuid); таблица худших штатов на `fct_orders`
   (uuid `delivery_sla`).
6. Раскладка `Marketplace.yaml` как С-Д1, заголовки разделов компонентом `HEADER`.

**Готово, когда.** Тесты красные до правки, зелёные после; `make check` зелёный;
`test_charts_and_dashboard_refer_to_objects_of_the_bundle` зелёный; `reviewer` «принять» или
«принять с замечаниями» по Д2.2-Д2.4 одним кругом на дерево.

**Ловушки.** Подпись «R$ 322K · 12.3%» у столбцов Superset не соберёт: значение на столбце,
доля в подсказке, это допустимое отличие от макета. `inherit` сдвигает на число дней периода,
не на календарный квартал (раздел 2).

### Д2.5 Живой импорт, проверка, документы

**Зачем.** Доказать, что дашборд работает на стенде, и показать его в README.
**Оценка** 2 ч. **Зависит от:** коммиты Д2.1 и Д2.2-Д2.4, CI зелёный. **Область коммита:** `docs`.

**Сделать.**
1. По «ок» на точный текст: `make up PROFILE=bi` (пересоздаёт `superset`, `superset-mcp`,
   `superset-init`; `superset-init` заодно применит `healthcheck: disable` из R-01).
2. `docker compose exec superset python /app/check.py`: у каждого графика дашборда строки.
3. Числа KPI через MCP `get_chart_data` равны таблице раздела 2; линии: если переопределение
   ECharts не дало 3px и монотонное сглаживание, применить С-Д9 и повторить Д2.4 малым diff.
4. Визуальная приёмка: скриншот владельца (или MCP Playwright, если подключён к этому шагу):
   цвета Harbor, серый ряд «год назад», линия цели, подсветка ячеек.
5. README: скриншот `docs/img/superset-marketplace.png` и строка; OPERATIONS, раздел Superset:
   `SUPERSET_DATA_ANCHOR` (что это, как сдвинуть после реплея, пересоздание `superset` класс C),
   где палитра, новый порядок импорта вместо `OPERATIONS.md:490-494` (С-Д12); evidence: числа
   KPI с датой.

**Готово, когда.** `check.py` rc 0; числа KPI равны разделу 2; скриншот в README; `links`
без битых ссылок.

**Blast radius и пайплайн.** Метаданные Superset: 4 датасета и 4 графика перезаписаны по uuid
(колонки и метрики датасетов сверены с YAML), новые графики созданы, объекты не удаляются.
Данные не затронуты.

## 5. Порядок и коммиты

| Карточка | Коммит | Зависит от |
|---|---|---|
| Д2.1 | `dbt: customer state on order items for the dashboard filter` | раздел 2 |
| Д2.2, Д2.3, Д2.4 | `infra: superset harbor theme, data anchor and marketplace dashboard v2` | Д2.1 |
| Д2.5 | `docs: superset dashboard v2 live, screenshot, anchor runbook` | оба коммита, CI |

Каждый коммит кода: `make check`, `reviewer`, цикл verify (`13-harness.md`, раздел 5)
последним шагом. Push без force по «ок» сессии.

## 6. Проверки

Запрос чисел KPI (MCP Superset `execute_sql`, база 1, только чтение):

```sql
with w as (select 'cur' p, date '2026-04-01' s, date '2026-07-01' e
           union all select 'prev', date '2025-12-31', date '2026-04-01')
select w.p, count(*) orders,
       sum(case when o.order_status not in ('canceled','unavailable') then o.items_value end) gmv,
       count_if(o.is_delivered) delivered, count_if(o.is_delivered and not o.is_late) on_time
from w join gold.fct_orders o on o.purchase_date >= w.s and o.purchase_date < w.e
group by 1
```

Ожидание 12.11: `cur` 18 991, 2 687 103,87, 18 545, 17 919; `prev` 21 355, 2 863 849,49,
20 814, 18 204.

## 7. Замечено и не входит

Отличия от макета, принятые при ревью Д2.2-Д2.4 (12.11, оркестратор):
- линия цели 95% получает 3px из переопределения линий темы: объект `series` сливается в каждую
  серию, и серия аннотации не исключение (`05addb45f9966def4730.chunk.js`); пунктир остаётся;
- подписи под KPI статичные («Of delivered orders» вместо «Of 15,593 delivered; 2,821 on the
  way»): `pop_kpi` не собирает текст из данных;
- кросс-фильтры выключены (`cross_filters_enabled: false`): клик по категории или статусу сузил
  бы только графики на датасетах с этой колонкой, та же частичная фильтрация, от которой ушли в
  С-Д2;
- при «No filter» в Period плитки KPI показывают ошибку: сравнению периодов нужен замкнутый
  диапазон (`models/helpers.py:1387-1393` в контейнере); записать в OPERATIONS (Д2.5).

Линия цели 3px расходится с разделом 3.2 (1.5px), который принял владелец: подтвердить на
визуальной приёмке Д2.5.

Перенесено в Д2.5 из ревью Д2.2-Д2.4 (круг 2, «принять с замечаниями»):
- `test_query_follows_from_params` не сверяет колонки запроса и шаг pivot (`index`,
  `aggregates`) с `params`; бандл сейчас согласован (ревьюер сверил все 13 графиков);
- ключ ряда сравнения в `label_colors` по коду фронтенда `gmv__1 year ago` (колонка сдвига не
  попадает в verbose map), тест закрепляет `GMV__1 year ago`: сверить вживую и закрепить
  верный;
- тест линии цели требует 1.5px, на экране будет 3px: поправить тест или docstring после
  решения владельца.

Исправления после первой визуальной приёмки Д2.5 (13.11, ревью два круга, «принять с
замечаниями»; причины сверены по фронтенду 6.1.0 в контейнере):
- плитки `pop_kpi` регистрируются только при `FEATURE_FLAGS["CHART_PLUGINS_EXPERIMENTAL"]`
  (по умолчанию выключен): флаг в `superset_config.py`;
- «Data through» вместо `handlebars` (раздел 5, п. 2 выше устарел): шаблон компилируется через
  eval, CSP Superset без `unsafe-eval` его блокирует; теперь `big_number_total`, метрика
  `to_unixtime(with_timezone(CAST(MAX(purchase_date) AS TIMESTAMP), 'UTC')) * 1000` и
  `force_timestamp_formatting` с `%d %b %Y`;
- горизонтальный бар рисует первую строку внизу: отображение по возрастанию, выбор top-10 в SQL
  по убыванию;
- ряд сравнения: фронтенд вставляет шаг `rename` `gmv__1 year ago` -> `1 year ago` между pivot и
  flatten; шаг добавлен в сохранённый `query_context` `daily_sales`, `label_colors` ровно
  `GMV` и `1 year ago` (п. про ключ выше закрыт); тест сверяет состав и порядок
  `post_processing` с `params` (п. про pivot выше закрыт);
- низкое замечание круга 2: тест ждёт `rename` только при одной метрике без groupby, фронтенд
  строит его при любом сравнении периодов; на бандле без последствий (сравнение только у
  `daily_sales`), расширить при первом графике со сравнением и groupby.

Прочее:
- Палитра Harbor для Grafana: дашборды Grafana остаются в своих цветах; кандидат после Д2.
- MCP Playwright для скриншотов: Node в WSL нет, есть Windows `npx` и Chrome; решение на шаге
  Д2.5.4.
- Вариант B (вкладки Обзор, Доставка, Продавцы) после датасетов `mart_seller_performance`,
  `dim_sellers`, `dim_customers`.
