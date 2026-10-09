# 07. Спека: неделя 3, gold и оркестрация

Версия 1.1, 09.10.2026. Решения раздела 2 приняты владельцем 09.10.2026 вместе с D14 и D15 плана `08-w3-plan/` (README, раздел 3); там, где решения и уточнения плана расходятся с текстом спеки, главнее они. Формат по `06-spec-standard.md`. Архитектура и исходные задачи в `00-mini-architecture-review.md` и `01-roadmap.md`; здесь то, что нужно исполнителю: решения, проверенные факты, карточки, проверки. Факты из аудитов 07.10 (`.superpowers/`, git-ignored) перенесены сюда с датой. Сверено 09.10: dbt-trino, Trino и Airflow 3 по документации (context7), данные Olist по `data/raw`, реплей по `make replay-status`.

## 1. Цель и границы

Цель недели: gold строится dbt из silver по событию «silver обновился», тесты отличают поломку пайплайна от известных аномалий источника, Airflow оркестрирует только batch (silver, dbt, DQ, optimize), путь с чистого клона воспроизводится одной командой.

Состояние на входе:

- Silver: 7 таблиц равны Postgres (`reconcile` ok, 08.10) плюс `silver.quarantine`. Каталог Lakekeeper, protection на 9 таблицах bronze и silver.
- `dbt/` пуст: README и пустые каталоги, `make dbt-parse` падает. В `airflow/` нет Dockerfile и DAG, `docker/airflow/airflow.env` заглушка. Compose уже описывает три сервиса профиля `orchestrate` и монтирует им `airflow/dags`, `dbt` (read-only) и `docker.sock`.
- Реплей (09.10): виртуальное время 2026-07-11 09:58, горизонт 2026-09-21 17:36, осталось около 72 виртуальных дней, 31 395 событий. На скорости 2880 это 36 минут реального времени.

Входит: W3-T00..T06. За владельцем: решения раздела 2 и W3-T07 (гейты dbt и Airflow).

Не входит: метрики и алерты (W4), `expire_snapshots` и `remove_orphan_files` (W5-T05), smoke в CI (W5-T03), README-витрина и Grafana по gold (W6 или порядок B из HANDOFF), история статусов заказа (раздел 7).

## 2. Решения до старта

Блок стартует после «ок» владельца на эту таблицу. Карточки ссылаются на решения по ID.

| ID | Вопрос | Рекомендация | Альтернатива | Цена ошибки |
|---|---|---|---|---|
| D1 | Как не поднять контейнер реплеера случайно (дополнение к ADR-016 о профилях; у ADR-016 есть только строка индекса, раздел пишет W3-T00) | Без правки compose: `make start` поднимает `core` без `oltp-replayer`, `make up` с профилем `core` отказывается, контейнер реплеера стартует только `make replay-live` | Профиль `replay` для `oltp-replayer`: одна строка compose, но это изменение инфраструктуры | Контейнер играет на 2880x: остаток реплея уходит за 36 минут |
| D2 | Бюджет реплея | W3 до 10 виртуальных дней, W4 до 15, W5 до 15, W6 до 10, около 22 в резерве на Operate-гейты | Неразрушающий второй круг реплея с новыми ключами (отдельная задача реплеера) | W4-W6 без живого трафика: алерты, stateful job и демо нечем проверить |
| D3 | Грейн и состав клиентов | `dim_customers` по `customer_unique_id`: `customer_id` в Olist выдаётся на каждый заказ (09.10: 94 406 заказов, 94 406 `customer_id`, 91 259 `customer_unique_id`). В измерении только клиенты с хотя бы одним заказом в silver: загрузчик кладёт в `shop.customers` сразу всех 99 441, и строки клиентов будущих заказов это артефакт предзагрузки реплея, а не зарегистрированные клиенты | По `customer_id`; все строки `shop.customers` | Repeat rate 0, когорты бессмысленны; клиенты из будущего с пустыми датами заказов |
| D4 | Где фильтровать soft delete | Staging не фильтрует и отдаёт `is_deleted`, фильтр в модели-потребителе; `fct_order_items` хранит удалённые позиции с флагом | Один фильтр `not _is_deleted` в staging | Реплеер удаляет позиции отменённых заказов: отменённый GMV не посчитать |
| D5 | Geolocation | Не моделировать в W3: витрины на уровне штата (`customer_state`, `seller_state`); seed только перевод категорий, 71 строка | Агрегат по zip prefix скриптом в seed | Seed на 1 000 163 строки (61 MB) раздувает публичный репо и грузится через Trino минутами |
| D6 | `on_table_exists` в dbt-trino | `replace` на весь проект: Trino Iceberg делает `CREATE OR REPLACE TABLE` атомарно и сохраняет историю снапшотов | `rename`, умолчание dbt-trino | `rename` делает DROP бэкапа на каждом прогоне: blast radius, а под soft delete Lakekeeper каждая копия живёт 7 дней |
| D7 | Инкремент `mart_daily_sales` | `delete+insert` по `purchase_date`: целиком пересчитываются даты покупки заказов, изменившихся после водяного знака витрины; singular-тест «инкремент равен полному пересчёту» | `merge` по `(sales_date, seller_state)` из роадмапа | Merge не удаляет исчезнувшую группу (у штата в эту дату отменили все позиции), строка остаётся с прежними числами |
| D8 | Определения метрик | Глоссарий ниже, он же в dbt docs | Без глоссария | README, Grafana и аналитик считают GMV по-разному |
| D9 | Как Airflow запускает Spark | `DockerOperator` с образом `lakehouse/spark:dev` через уже смонтированный `docker.sock`; ADR: сокет равен root на хосте, это приемлемо для однопользовательского ноутбука с портами на 127.0.0.1; unit-тест сверяет переменные окружения DAG с блоком `spark-silver` в compose | BashOperator и `docker compose run`: в образ Airflow нужны compose CLI и репо с `.env` | Без теста env DAG разойдётся с `make silver`, и silver из Airflow упадёт или пойдёт не в тот каталог |
| D10 | Каденция DAG | `silver_upsert` каждые 5 минут, первый таск пропускает запуск, если в bronze нет нового снапшота; `dbt_build` по Asset `lake.silver`; `dq_checks` каждые 15 минут по времени (перевод на Asset это Modify-гейт владельца) | `dbt_build` раз в час по времени, без Asset | Без пропуска JVM Spark стартует каждые 5 минут впустую, а Asset будит dbt каждые 5 минут |
| D11 | Maintenance в W3 | Только `optimize` таблиц silver через Trino, в одном pool с `silver_upsert`; expire и orphan files в W5 после ADR о политике | Всё из W5-T05 сразу | `expire_snapshots` на bronze ломает чтение silver (ADR-021, apache/iceberg#18000); expire и orphan files в blast radius |
| D12 | Вход в UI Airflow | SimpleAuthManager без логина (`simple_auth_manager_all_admins`), порт только на 127.0.0.1; `AIRFLOW_ADMIN_PASSWORD` убрать из `.env.example` с записью в DECISIONS | Пользователь `admin` с паролем из `.env` через файл паролей SimpleAuthManager: больше кода в образе | Без логина DAG управляет любой процесс ноутбука; для однопользовательского ноутбука приемлемо |
| D13 | Служебные DROP, DELETE и TRUNCATE самого dbt в `lake.gold` | Разрешить заранее как штатную работу инструмента: инкремент `delete+insert` на каждом прогоне создаёт и дропает временную таблицу `<model>__dbt_tmp` и делает DELETE по ключу, повтор `dbt seed` делает TRUNCATE, смена view на table дропает view. Ручные DROP, DELETE, TRUNCATE где угодно по-прежнему только с «ок». Раз в неделю смотреть число soft-deleted в `gold` (OPERATIONS, раздел Lakekeeper) | Спрашивать на каждый прогон: dbt по Asset тогда не работает вообще. Или `mart_daily_sales` как `table` с полной пересборкой: без DROP, но без инкремента, нужного гейту dbt | Каждая временная таблица под soft delete Lakekeeper живёт 7 дней вместе с файлами; при прогонах только после порций реплея это десятки небольших таблиц в неделю |

Глоссарий метрик (D8):

- `purchase_date`: дата `order_purchase_timestamp`. Это бизнес-время после сдвига дат на «сегодня», а не время обработки. Все даты витрин считаются от неё.
- GMV: сумма `price` неудалённых позиций заказов со статусом не `canceled` и не `unavailable`. Доставка (`freight_value`) отдельной метрикой.
- AOV: GMV, делённый на число таких заказов с хотя бы одной неудалённой позицией.
- Отменённый GMV: сумма `price` всех позиций заказов `canceled`, включая удалённые.
- On-time rate: доля заказов `delivered` с `date(order_delivered_customer_date) <= date(order_estimated_delivery_date)`.
- Cancellation rate: доля заказов `canceled` среди всех заказов той же даты покупки.
- Review score: среднее `review_score` неудалённых отзывов.

## 3. Ограничения блока

- Версии: dbt-core и dbt-trino 1.10 (уже в `pyproject.toml` и `uv.lock`), Trino 483, каталог `lake` на Lakekeeper, Airflow 3.3.2. Поведение инструментов сверяется с документацией этих версий (context7), не по памяти.
- `$COMPOSE` ниже означает `docker compose --env-file .env -f docker/compose.yaml` из корня репо, как в `Makefile`: compose-файла в корне нет, и без `--env-file` compose остановится на `LAKEKEEPER_ENCRYPTION_KEY`. В одноразовом проекте те же команды выполняются из его каталога.
- Утверждённые решения D1-D13 главнее старого текста `00-mini-architecture-review.md`, `ARCHITECTURE.md` и README каталогов. Карточка, которая реализует решение, правит эти тексты в своём коммите (шаг «Документация»), чтобы `00` снова был источником правды.
- Реплей только порциями: `make replay-burst` из W3-T00, до него `replay_burst` из `scripts/chaos/lib.sh`. В пределах бюджета D2; сколько потрачено, пишется в HANDOFF.
- Профили: `core` без реплеера плюс `query`; с W3-T04 ещё `orchestrate`, и тогда `TRINO_XMX=2g`. Все профили сразу не поднимаются.
- Один писатель silver. Когда `silver_upsert` в Airflow включён, ручной `make silver` запрещён: два процесса на один checkpoint. Нужен ручной прогон: сначала DAG на паузу.
- Gold не защищён и пересобирается из silver, но DROP в `lake.gold` на Lakekeeper всё равно удаляет файлы (soft delete 7 дней). Служебные операции самого dbt разрешены только по D13. Ручной DROP таблицы или схемы, удаление модели вместе с таблицей и переименование модели (старая таблица остаётся сиротой, её удаление это DROP) только с «ок» владельца.
- JDBC-строки в `iceberg_catalog` остаются точкой отката переключения до конца W3: не трогать, Spark с `CATALOG_TYPE=jdbc` не запускать.
- dbt без пакетов: встроенные тесты и свои generic-тесты в `dbt/tests/generic/`. В Airflow проект смонтирован read-only, а `dbt deps` на рантайме это сеть и запись в каталог проекта.
- SQL: lowercase, CTE, только `ref()` и `source()`. Корневой `.sqlfluff` (`templater = raw`) не разберёт Jinja, а dbt-templater требует живой Trino, которого нет в CI. Поэтому у `dbt/` свой `.sqlfluff`: `dialect = trino`, `templater = jinja` с dbt builtins.
- Порты только на 127.0.0.1, секреты только из `.env` через `${VAR}`, хосты и порты в коде и профилях через env с дефолтом.
- Один коммит на карточку, после проверок раздела 6 и «ок» владельца на дифф.

## 4. Карточки

### W3-T00 Путь с чистого клона: `make start`, `bootstrap`, `verify`, `replay-burst`

**Зачем.** README «Run» не доводит до данных: в нём нет `make migrate` и `make replay-load`, `make replay` запускает второй реплеер внутри контейнера, где первый уже держит порт 8000, а `make up PROFILE=core` поднимает контейнер реплеера, который сразу играет на 2880x. Пока пути нет, проект нельзя проверить с нуля, smoke в CI (W5-T03) не на чем строить, а «запускается одной командой» в README будет неправдой.

**Оценка** 4 ч. **Зависит от:** D1, D2. **Область коммита:** `infra`.

**Вход.**
- В `Makefile` есть `secrets`, `data`, `migrate`, `replay-load`, `replay-start`, `replay-status`, `silver`, `up`, `down`.
- `connect/register.sh` идемпотентен: топики `--create --if-not-exists`, конфиг коннектора через `PUT`.
- В `scripts/chaos/lib.sh` есть всё для проверок: `replay_burst`, `no_other_replayer`, `bronze_caught_up`, `bronze_offsets_report`, `reconcile`, `run_silver`. Их вызывать, не переписывать. `bronze_offsets_report` только печатает таблицу и ничего не утверждает.
- `replay-load` отказывается работать на непустых таблицах; `python -m replayer status` возвращает 1, если состояния реплея нет.
- Загрузчик читает только `$DATA_DIR/raw`, причём `raw_dir()` в `oltp/replayer/load.py` берёт `DATA_DIR` из окружения процесса. `.env` читает только `Settings` (`oltp/replayer/settings.py`), а `make replay-load` `.env` в окружение не экспортирует. Сэмпл лежит в `data/sample`.
- `up -d spark-bronze kafka-connect trino` с профилями `core` и `query` поднимает по `depends_on` весь `core`, кроме `oltp-replayer` (проверено по `docker compose config` 09.10).

**Сделать.**
1. `make start`: `$(COMPOSE) --profile core --profile query up -d --build spark-bronze kafka-connect trino`.
2. В `make up`: если `PROFILE` содержит `core`, цель отказывается и печатает подсказку `make start` (D1). `make down` без изменений.
3. `make replay-burst SECONDS=<n> [SPEED=720]`: `no_other_replayer`, затем `replay_burst` из `lib.sh`; печатает `virtual_now` до и после.
4. `make verify`: отказ, если запущен `airflow-scheduler` (`$COMPOSE --profile '*' ps -q airflow-scheduler` не пуст): `run_silver` при включённом Airflow даст второго писателя silver. Затем `no_other_replayer`; ожидание `bronze_caught_up` до `VERIFY_WAIT` секунд (по умолчанию 900: initial snapshot полного датасета это около полумиллиона событий, а bronze берёт 20 000 offsets за триггер 20 с, около 8 минут); `run_silver`; новая функция `bronze_offsets_ok` в `lib.sh` рядом с `bronze_offsets_report`: тот же запрос в TSV, код 1, если сумма дублей и дыр больше 0; `reconcile`; в bronze есть строки по всем 7 `source_table`. Итог одной строкой `verify ok` или причина, код выхода не 0 при любом провале.
5. `make bootstrap`, идемпотентно и без blast radius: `start`; ожидание, пока `spark-bronze`, `kafka-connect` и `trino` станут healthy (`docker inspect` по id из `$COMPOSE --profile '*' ps -q <service>`, до 5 минут); `migrate`; `bash connect/register.sh`; `replay-load`, только если `replayer status` вернул 1, иначе строка `replay state exists, load skipped`; `verify`; `scripts/lakekeeper/protect.sh` (идемпотентен; на чистом стеке таблиц silver нет до первого `run_silver`, поэтому он идёт последним).
6. `REPLAY_DATA=raw|sample`, по умолчанию `raw`: каталог данных становится полями `Settings` (`data_dir`, `replay_data`), которые читаются и из окружения, и из `.env`; `raw_dir()` берёт путь оттуда, а не из `os.environ`. Нужен для проверки этой карточки и для smoke W5-T03. Новая переменная в `.env.example` со значением `raw` и строкой в DECISIONS (это контракт `.env`); живой `.env` без неё работает по умолчанию. Тест в `tests/unit/test_load.py` через временный `.env` с `REPLAY_DATA=sample` и без переменной в окружении: читается каталог `sample`; без переменной вовсе `raw`.
7. Удалить цель `make replay`: она запускает второй реплеер. Для непрерывного демо `make replay-live` (`up -d oltp-replayer`), в `help` предупреждение, что он тратит бюджет D2.
8. Документация: README «Run» (новый путь и время с нуля), OPERATIONS «Profiles», «Daily commands», «Backup» (`make nuke && make bootstrap`); в DECISIONS раздел ADR-016 (сейчас там только строка индекса) с D1; строка в HANDOFF.

**Готово, когда.**
- Чистый клон в соседнем каталоге: `git clone` текущего коммита плюс незакоммиченный дифф задачи (`git add -N` для новых файлов, затем `git diff HEAD --binary | git -C <клон> apply`). Живой стек перед этим остановлен `make down PROFILE=core,query` (тома целы, bronze догнал Kafka). В клоне `make secrets`, в его `.env` `COMPOSE_PROJECT_NAME=lakehouse-fresh` и `REPLAY_DATA=sample` (копировать данные не нужно), затем `make bootstrap`: код 0 и `verify ok`; время с нуля записано в README и OPERATIONS.
- Повторный `make bootstrap` там же: код 0, `load skipped`, `verify ok`.
- `$COMPOSE --profile '*' ps -q oltp-replayer` пуст в обоих проектах (в клоне команда из его каталога).
- Живой стек: `make start && make verify` печатает `verify ok`, `make replay-status` до и после показывает одно и то же `virtual_now`.
- При запущенном `airflow-scheduler` `make verify` отказывается с подсказкой.
- `make up PROFILE=core` отказывается и подсказывает `make start`.
- `make lint`, `make test` зелёные.

**Ловушки.**
- Скрипты, которые ищут контейнер по имени `lakehouse-<service>-1` (`spark-kill.sh`, `connect-restart.sh`, `late.sh`), в проекте `lakehouse-fresh` не найдут его. В `start`, `verify` и `bootstrap` только `$COMPOSE ps` и `exec`.
- Образы `lakehouse/spark:dev` и `lakehouse/replayer:dev` общие для обоих проектов: сборка в клоне перетегирует их. Поэтому в клоне тот же код, что в рабочем дереве.
- Порт 8000 один на хост: пока играет `make replay-start` или контейнер реплеера, `replay-burst` и `verify` отказываются с кодом 2. Это ожидаемо.
- `reconcile` при идущем реплее даёт ложный DIFF, поэтому первым шагом `no_other_replayer`, а перед сверкой догон bronze.
- Первая сборка образа Spark скачивает около 400 MB jar-ов; честное «время с нуля» её включает.

**Blast radius и пайплайн.** В самих целях нет. Живой стек только `down` без `-v`; bronze перед остановкой догнал Kafka (`bronze_caught_up`), иначе при простое дольше 24 ч непрочитанное уйдёт по retention. Тома одноразового проекта после проверки удаляются только с «ок» владельца (`docker compose -p lakehouse-fresh down -v` в blast radius), иначе остаются.

**Не входит.** Smoke в CI (W5-T03), запись демо (W6), digest образов и прочая гигиена compose.

### W3-T01 dbt: проект, sources, staging, ядро моделей

**Зачем.** Gold это потребитель всего конвейера: без него нет lineage, тестов на данные и бизнес-ответа. Ядро (`fct_*`, `dim_*`) задаёт грейны, на которых стоят все витрины.

**Оценка** 4 ч. **Зависит от:** D3, D4, D5, D6, D13; живой silver. **Область коммита:** `dbt`.

**Вход.**
- `lake.silver.{customers, sellers, products, orders, order_items, payments, reviews}`: колонки как в `contracts/silver/*.json` плюс `_is_deleted boolean`, `_last_lsn bigint`, `_updated_at` (время MERGE в silver, `timestamp(6) with time zone` в Trino, не время источника).
- Удаления бывают только у `order_items` (отмена до отгрузки) и `reviews` (отзыв снят); 09.10 их 40 и 16.
- Типы в Trino: `timestamp_ntz` из контракта это `timestamp(6)`, деньги `decimal(10,2)`, `smallint` стал `integer`.
- `make dbt-parse` уже вызывает `dbt parse --profiles-dir . --target ci`.
- Данные Olist (`data/raw`, 09.10): 8 статусов заказа; 610 товаров без категории; у категорий `pc_gamer` и `portateis_cozinha_e_preparadores_de_alimentos` нет перевода.

**Сделать.**
1. `dbt/dbt_project.yml`: проект `marketplace`, профиль `lakehouse`, все модели в схеме `gold` без кастомных схем (в Trino `lake.gold.<model>`), `+on_table_exists: replace` (D6), staging и intermediate `view`, marts `table`.
2. `dbt/profiles.yml` в git (секретов нет, Trino без аутентификации): target `dev` с `host: "{{ env_var('TRINO_HOST', '127.0.0.1') }}"`, `port: "{{ env_var('TRINO_PORT', '8080') | as_number }}"`, `database: lake`, `schema: gold`, `threads: 2`; target `ci` с теми же полями только для `parse`.
3. `dbt/.sqlfluff` по разделу 3.
4. Первым делом проверка views: `dbt run --select stg_customers` создаёт view в `lake.gold`. Документация Trino обещает views в REST-каталоге по Iceberg View spec, но связку с Lakekeeper 0.13.6 никто не запускал. Не создаётся: стоп и вопрос владельцу, обходной путь staging как `ephemeral`.
5. `models/staging/_sources.yml`: source `silver` (`database: lake`, `schema: silver`), 7 таблиц, `loaded_at_field: _updated_at`. Freshness (`warn_after` 30 минут, `error_after` 2 часа) только у `orders`, `order_items`, `payments`, `reviews`: реплеер меняет только их, а `customers`, `sellers`, `products` загружены один раз, и их `_updated_at` стоит с первой загрузки. Проверяет `dbt source freshness` в `dq_checks`, не `dbt build`.
6. `stg_<table>`, 7 views: выбор колонок, `_is_deleted` как `is_deleted`, `_updated_at` как `updated_at`, опечатки Olist `product_name_lenght` и `product_description_lenght` как `..._length`. Фильтра по удалению нет (D4).
7. Seed `dbt/seeds/category_translation.csv`: копия `data/sample/product_category_name_translation.csv`, который уже в репо (71 строка, D5). Из `data/raw` в git ничего не идёт (`CLAUDE.md`).
8. `int_orders_enriched` (view, грейн `order_id`): заказ, клиент (`customer_unique_id`, штат, город), агрегаты неудалённых позиций (`items_count`, `items_value`, `freight_value`), агрегаты платежей (`payment_value`, `payment_installments_max`). Только `left join` от заказа, агрегаты через `coalesce(..., 0)`: у заказа без позиций `left join` к агрегату даёт null, а не 0.
9. `fct_orders` (грейн `order_id`): поля `int_orders_enriched` плюс `purchase_date`, `is_delivered`, `is_canceled`, `delivery_days`, `is_late` по глоссарию D8 и `updated_at` как наибольший `updated_at` заказа, всех его позиций (включая удалённые) и платежей. Этот `updated_at` водяной знак инкремента W3-T02.
10. `fct_order_items` (грейн `order_id, order_item_id`): все позиции, включая удалённые, с `is_deleted`; `purchase_date` заказа, категория товара, штат продавца, `updated_at`.
11. `dim_customers` (грейн `customer_unique_id`, D3): только клиенты с хотя бы одним живым заказом в silver; адрес из строки `customers` самого позднего заказа (при равном времени покупки наибольший `customer_id`), `orders_count`, `first_order_ts`, `last_order_ts`, `is_repeat`. `dim_products` (грейн `product_id`): категория `coalesce(перевод, исходное имя, 'unknown')`. `dim_sellers` (грейн `seller_id`).
12. Тесты в том же коммите: `unique` и `not_null` на ключ каждой модели; для составных ключей свой generic-тест `unique_combination` в `dbt/tests/generic/`; `relationships` от `fct_order_items` к `fct_orders`, `dim_products`, `dim_sellers` и от `fct_orders.customer_unique_id` к `dim_customers`.
13. `Makefile`: `dbt-build` (`cd dbt && uv run dbt build --profiles-dir . --target dev`). В `ci.yml` шаг `make dbt-parse` (комментарий там это и планирует).
14. Документация: `dbt/README.md` по факту (сейчас он обещает фильтр `_deleted` в staging и seed geolocation); `_deleted` как `_is_deleted` в `ARCHITECTURE.md`; в `00-mini-architecture-review.md` §3 фраза «Geolocation и перевод категорий грузятся как справочники в dbt seeds» по D5.

**Готово, когда.**
- `make dbt-parse`: код 0, локально и в CI.
- `make dbt-build`: код 0, все тесты pass.
- Числа в Trino равны: `select count(*) from lake.gold.fct_orders` и `select count(*) from lake.silver.orders where not _is_deleted`; `select count(*) from lake.gold.dim_customers` и `select count(distinct c.customer_unique_id) from lake.silver.orders o join lake.silver.customers c on c.customer_id = o.customer_id where not o._is_deleted and not c._is_deleted` (09.10: 91 259).
- `select count(*) from lake.gold.fct_orders where items_count = 0` около 765 (09.10: 735 заказов без единой позиции и 30 со всеми позициями удалёнными); число на дату прогона записано в описание модели.
- Повторный `make dbt-build`: `select count(*) from lake.gold."fct_orders$snapshots"` вырос на 1 (`CREATE OR REPLACE` в той же таблице, без DROP), в списке soft-deleted таблиц Lakekeeper (OPERATIONS, раздел Lakekeeper) нет ничего из `gold`.
- `make lint` зелёный, `sqlfluff` разбирает `dbt/models` без ошибок парсинга.

**Ловушки.**
- `customer_id` в Olist свой у каждого заказа: по нему repeat rate ноль (D3).
- `inner join` от позиций к заказам теряет около 765 заказов без позиций (отменённые и недоступные). Все соединения от заказа `left join`.
- Фильтр `not is_deleted` в staging выбросит позиции отменённых заказов, а из них считается отменённый GMV (D4).
- `_updated_at` это время обработки в silver. Даты витрин только от `order_purchase_timestamp`.
- `on_table_exists` задаётся в `dbt_project.yml` до первого `dbt run`: умолчание `rename` уже на втором прогоне делает DROP.
- Проект в Airflow смонтирован read-only, а dbt пишет `target/` и `logs/` в каталог проекта. На хосте это не мешает, в Airflow нужны `--target-path` и `--log-path` во временный каталог (W3-T05).

**Blast radius и пайплайн.** Создаёт namespace `gold` в Lakekeeper и таблицы в нём. Модели без DROP: таблицы через `CREATE OR REPLACE`, views через `create or replace view`. Повтор `dbt seed` делает TRUNCATE таблицы перевода категорий, это D13. Bronze и silver только читаются, checkpoint и offsets не затронуты.

**Не входит.** Витрины (W3-T02), тесты на аномалии источника и docs (W3-T03), история статусов заказа (раздел 7).

### W3-T02 Витрины: `mart_daily_sales`, `mart_delivery_sla`, `mart_seller_performance`

**Зачем.** Бизнес-ответы проекта (продажи по дням и штатам, SLA доставки, продавцы) и главный учебный объект dbt: инкрементальная модель, которая остаётся верной, когда изменения приходят задним числом. Отмена или доставка приходит через дни после покупки и меняет прошлые даты.

**Оценка** 3 ч. **Зависит от:** W3-T01, D7, D8, D13. **Область коммита:** `dbt`.

**Сделать.**
1. Макрос `safe_divide(a, b)`: null при нулевом делителе. Все доли в витринах через него.
2. `mart_daily_sales`: `materialized='incremental'`, `incremental_strategy='delete+insert'`, `unique_key='purchase_date'`. Грейн `(purchase_date, seller_state)`, поля `orders_count`, `items_count`, `gmv`, `freight_value`, `canceled_orders`, `canceled_gmv` (D8) и `source_updated_at`, наибольший `fct_orders.updated_at` среди заказов строки. Штат продавца приходит только через позиции, поэтому заказы без позиций (09.10: 765, почти все `unavailable` и `canceled`) идут в строку `seller_state = 'unknown'`: иначе они выпадут из `orders_count` и `canceled_orders`.
3. Инкремент (D7): водяной знак `coalesce(max(source_updated_at), timestamp '1970-01-01 00:00:00 UTC')` из `{{ this }}`; затронутые даты `select distinct purchase_date from {{ ref('fct_orders') }} where updated_at > <водяной знак>`; модель считает только эти даты, целиком по всем штатам. `delete+insert` удаляет все строки этих дат и вставляет пересчитанные, поэтому исчезнувшая группа тоже уходит.
4. `mart_delivery_sla` (table), грейн `(purchase_month, customer_state)`: `delivered_orders`, `on_time_orders`, `on_time_rate`, `avg_delivery_days`, `p90_delivery_days` (`approx_percentile`).
5. `mart_seller_performance` (table), грейн `(seller_id, purchase_month)`: `orders_count`, `gmv`, `avg_review_score`, `late_rate`, `cancellation_rate`.
6. Singular-тест `dbt/tests/assert_mart_daily_sales_matches_full_recompute.sql`: тот же расчёт по всем датам без инкремента, `except` в обе стороны, ожидается 0 строк. Это проверка корректности, а не только идемпотентности.
7. Тесты ключей на всех витринах (`unique_combination`, `not_null`). Описания моделей, ссылки на глоссарий добавит W3-T03.
8. Документация: в `ARCHITECTURE.md` «`mart_daily_sales` incremental merge» по D7.

**Готово, когда.**
- `make dbt-build`: код 0, первый прогон строит витрины целиком.
- Порция `make replay-burst SECONDS=60` (около 12 виртуальных часов на 720x), `make silver`, `make dbt-build`: код 0, тест полного пересчёта pass; в списке soft-deleted Lakekeeper ровно одна новая запись `mart_daily_sales__dbt_tmp` (цена D13 как она есть).
- Ещё один `make dbt-build` без новых данных: `select count(*), sum(gmv) from lake.gold.mart_daily_sales` до и после равны.
- `select sum(gmv) from lake.gold.mart_daily_sales` равно GMV, посчитанному по определению D8 прямо из `lake.silver` (запрос в описании модели).

**Ловушки.**
- Пустая витрина с `max(...)` равным null без `coalesce` никогда не найдёт затронутых дат: инкремент молча ничего не делает.
- Повторный прогон без изменений проверяет идемпотентность, не корректность. Корректность ловит только тест полного пересчёта.
- Заказ с позициями продавцов из разных штатов попадает в каждый штат: `orders_count` по штатам не складывается в число заказов дня. Это пишется в описании модели.
- `purchase_date` бизнесовая, время обработки сюда не подмешивается.

**Blast radius и пайплайн.** Каждый инкрементальный прогон `mart_daily_sales` создаёт и дропает временную таблицу `mart_daily_sales__dbt_tmp` и делает DELETE затронутых дат (D13): так устроен `delete+insert` в dbt-trino 1.10. `--full-refresh` пересобирает витрину через `CREATE OR REPLACE` (D6), без DROP. Silver только читается.

**Не входит.** Grafana-панели (W6-T01), бизнес-SQL в README (W6 или порядок B).

### W3-T03 DQ-тесты на источник, freshness, docs и глоссарий

**Зачем.** В Olist есть известные аномалии. Тест должен отличать «сломался пайплайн» (error) от «так в источнике» (warn с порогом и причиной), иначе либо `dbt build` вечно красный, либо реальные поломки прячутся среди «нормальных» предупреждений. Docs и глоссарий нужны потребителю.

**Оценка** 2 ч. **Зависит от:** W3-T01, W3-T02. **Область коммита:** `dbt`.

**Сделать.**
1. Сначала измерить на живом gold и записать числа с датой в описания тестов: заказы, где `payment_value` расходится с `items_value + freight_value` больше чем на 0.01 (09.10: 279, 0.3%); доставка клиенту раньше передачи перевозчику; товары без категории; категории без перевода.
2. Singular-тесты на эти аномалии с severity по умолчанию (`error`), `warn_if: '>0'` и `error_if` выше измеренного. Порог берётся из переменной dbt с дефолтом, например в тесте платежей `{{ config(warn_if='>0', error_if='>' ~ var('payments_mismatch_error_if', 1000)) }}` (1000 это около 1% заказов). Рост за порог означает поломку у нас, а не в источнике. `severity: warn` не ставить: с ним dbt 1.10 игнорирует `error_if` и тест не упадёт никогда (`dbt/task/test.py`, тест валится только при `severity == ERROR`).
3. `accepted_values` на `order_status`, severity error: `created, approved, invoiced, processing, shipped, delivered, canceled, unavailable` (все 8 значений датасета).
4. Описания всех моделей и ключевых колонок, глоссарий D8 в `dbt/models/docs.md` блоками `{% docs %}`, ссылки на него из колонок витрин.
5. `make dbt-docs`: `dbt docs generate`.
6. В `dbt/README.md`: freshness стоит на 4 таблицах, которые меняет реплеер; при остановленном реплее через 30 минут это warn, через 2 часа error и код 1, это сигнал «трафика нет», а не поломка пайплайна.

**Готово, когда.**
- `make dbt-build`: код 0; warn только у тестов на известные аномалии, у каждого в описании число, дата и причина.
- Сразу после порции реплея и `make silver`: `cd dbt && uv run dbt source freshness --profiles-dir .` даёт pass по `orders`, `order_items`, `payments`, `reviews` и код 0; у `customers`, `sellers`, `products` freshness не проверяется.
- Тест умеет падать: `cd dbt && uv run dbt test --profiles-dir . --select <тест платежей> --vars '{payments_mismatch_error_if: 0}'` завершается с кодом 1, без `--vars` с кодом 0 и warn.
- `make dbt-docs`: есть `dbt/target/index.html`, в `dbt/target/catalog.json` все модели gold.

**Ловушки.**
- Порог, выставленный на глаз, либо вечно красный, либо ничего не ловит. Сначала замер, потом порог.
- `accepted_values` с severity warn пропустит новый статус от реплеера; это контракт источника, поэтому error.

**Blast radius и пайплайн.** Нет, только тесты и описания.

**Не входит.** Сверка source, silver и gold с причинами расхождений (W5-T04).

### W3-T04 Образ Airflow и профиль `orchestrate`

**Зачем.** Airflow оркестрирует batch-шаги с ретраями и зависимостями. Сейчас `make up PROFILE=orchestrate` падает на сборке: нет `airflow/Dockerfile`, `docker/airflow/airflow.env` пустой, а `AIRFLOW_FERNET_KEY` из `make secrets` Airflow не примет.

**Оценка** 3 ч. **Зависит от:** D9, D12. Можно делать параллельно с W3-T01..T03. **Область коммита:** `orchestrate`.

**Вход.**
- Compose: `airflow-api-server` (127.0.0.1:8090), `airflow-scheduler`, `airflow-dag-processor`, все в сети `lake`, `env_file: ./airflow/airflow.env`. API-server и scheduler монтируют `airflow/dags`, `dbt` (read-only) и `/var/run/docker.sock`.
- БД `airflow` в `postgres-meta` создаёт init-скрипт (имя захардкожено, совпадает с `AIRFLOW_DB`).
- В `.env` есть `AIRFLOW_FERNET_KEY`, `AIRFLOW_JWT_SECRET`, `AIRFLOW_ADMIN_PASSWORD`. `make_env.py` генерирует их как `secrets.token_urlsafe(24)`, это 32 символа.
- Compose подставляет `${VAR}` из `.env` и в значения `env_file` (отключается только `format: raw`).
- Heap Trino задаётся при создании контейнера: `command` получает `-J-Xmx${TRINO_XMX}`. `make up PROFILE=orchestrate` контейнер Trino не пересоздаёт, а переменная окружения оболочки при подстановке главнее `.env`.
- У ADR-011 в `DECISIONS.md` есть только строка индекса, раздела нет.

**Сделать.**
1. Образец конфигурации: официальный compose той же версии, `curl -LfO 'https://airflow.apache.org/docs/apache-airflow/3.3.2/docker-compose.yaml'`. Из его общего блока переносятся переменные, не сервисы.
2. `airflow/Dockerfile`: `FROM apache/airflow:3.3.2`; `apache-airflow-providers-docker` с constraints-файлом этой версии Airflow и Python образа; dbt-core и dbt-trino тех же версий, что в `uv.lock`, в отдельном venv `/opt/dbt-venv`; клиенты `trino` и `psycopg` для `dq_checks`.
3. `docker/airflow/airflow.env` через `${VAR}`: `LocalExecutor`; строка БД на `postgres-meta`, БД `airflow`; Fernet-ключ; `AIRFLOW__API_AUTH__JWT_SECRET`, один на все три сервиса; `AIRFLOW__CORE__EXECUTION_API_SERVER_URL=http://airflow-api-server:8080/execution/`; `LOAD_EXAMPLES=False`; миграция БД при старте (в официальном образе `_AIRFLOW_DB_MIGRATE=true`, сверить); `COMPOSE_PROJECT_NAME` и переменные блока `spark-silver` для DockerOperator; `TRINO_HOST=trino`; `OLTP_*` для `dq_checks`.
4. Fernet: `scripts/make_env.py` генерирует `AIRFLOW_FERNET_KEY` в формате Fernet (urlsafe base64 от 32 случайных байт, 44 символа). Тест в `tests/unit/test_make_env.py`: ключ декодируется ровно в 32 байта. `make secrets` существующий `.env` не перезаписывает, поэтому в OPERATIONS одна команда, которая заменяет только эту строку живого `.env`.
5. Доступ к сокету: первым шагом `$COMPOSE exec airflow-scheduler python -c "import docker; print(docker.from_env().ping())"`. Ответ `True`: ничего не делать. Permission denied: `group_add` с GID сокета у двух сервисов в compose. Риск сокета записать в ADR (D9).
6. Аутентификация по D12: SimpleAuthManager (умолчание Airflow 3) без логина, `AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_ALL_ADMINS=True`; `AIRFLOW_ADMIN_PASSWORD` убрать из `.env.example` с записью в DECISIONS.
7. `make airflow-init`: pool `lake_writers` на 1 слот (`airflow pools set`), идемпотентно.
8. RAM: `orchestrate` только при Trino на 2g. Порядок: `TRINO_XMX=2g make start` (пересоздаёт Trino с новым heap), затем `make up PROFILE=orchestrate`. `.env` хранит обычные 2500m, чтобы `core,query` без Airflow работали как раньше. `docker stats` в таблицу `00-mini-architecture-review.md` §6.
9. Документация: раздел ADR-011 в DECISIONS (сейчас только строка индекса): LocalExecutor, BashOperator для dbt, D9 и D12; OPERATIONS, раздел «Airflow»: как поднять, где UI, порядок с `TRINO_XMX=2g`, команда замены Fernet-ключа.

**Готово, когда.**
- `TRINO_XMX=2g make start && make up PROFILE=orchestrate`: три сервиса healthy за 3 минуты, `http://127.0.0.1:8090` открывается; `docker inspect -f '{{json .Config.Cmd}}' $($COMPOSE --profile '*' ps -q trino)` содержит `-J-Xmx2g`.
- `$COMPOSE exec airflow-scheduler airflow pools list`: `lake_writers`, 1 слот.
- `$COMPOSE exec airflow-scheduler airflow dags list-import-errors`: пусто.
- Пробный DAG с BashOperator `echo ok` (в git не идёт) успешен: execution API и JWT работают.
- `$COMPOSE exec airflow-scheduler /opt/dbt-venv/bin/dbt --version`: dbt-trino 1.10.
- `make test` (тест Fernet), `make lint` зелёные; `docker stats` записан.

**Ловушки.**
- Ключ в 32 символа Airflow не примет. Менять его безопасно только до первого запуска: потом им зашифрованы connections и variables.
- Разные JWT-секреты у api-server и scheduler: задачи падают на авторизации в execution API.
- `EXECUTION_API_SERVER_URL` по умолчанию смотрит в localhost контейнера scheduler: задачи не стартуют.
- dbt в одном окружении с Airflow ломает зависимости Airflow, поэтому отдельный venv.
- Сокет в контейнере принадлежит root или группе docker: uid 50000 без группы получает permission denied.

**Blast radius и пайплайн.** Нет. В том же `postgres-meta` живут БД `lakekeeper` и `iceberg_catalog`: их не трогать.

**Не входит.** DAG (W3-T05), StatsD-метрики Airflow (W4-T01).

### W3-T05 DAG: `silver_upsert`, `dbt_build`, `dq_checks`, `iceberg_maintenance`

**Зачем.** Расписание, зависимости и ретраи вместо ручных `make silver` и `make dbt-build`. Asset-зависимость gold от silver это учебная цель гейта Airflow.

**Оценка** 6 ч, два коммита: `silver_upsert` с `dbt_build`, затем `dq_checks` с `iceberg_maintenance`. **Зависит от:** W3-T01..T04, D9, D10, D11, D13. **Область коммита:** `orchestrate`.

**Сделать.**
1. Пакет `airflow/dags/lakehouse/`: настройки из env (`pydantic-settings`), сборка env для Spark, SQL-запросы, функции решений. Модули пакета не импортируют `airflow`, поэтому тестируются на хосте; DAG-файлы только собирают операторы. `airflow/dags` добавить в `pythonpath` pytest и в `files` mypy.
2. `silver_upsert`: каждые 5 минут, `max_active_runs=1`, `catchup=False` явно, 1 ретрай через 1 минуту.
   - `bronze_has_new_snapshot` (`@task.short_circuit`): id последнего снапшота `lake.bronze."cdc_events$snapshots"` через Trino против Variable `silver_upsert_last_bronze_snapshot`. Равны: возвращает `False`, остальное skipped, Asset не публикуется. Иначе возвращает id, он уходит в XCom.
   - `merge` (`DockerOperator`, pool `lake_writers`): образ `lakehouse/spark:dev`, команда `silver_upsert`, `network_mode` `<COMPOSE_PROJECT_NAME>_lake`, `mem_limit` 2 GB, `mount_tmp_dir=False`, `auto_remove="success"`, env как у сервиса `spark-silver` в compose; `outlets=[Asset("lake.silver")]`.
   - `remember_snapshot`: пишет в Variable id, прочитанный первым таском, а не текущий. Пришедшее после чтения подберёт следующий запуск.
3. `dbt_build`: `schedule=[Asset("lake.silver")]`, `max_active_runs=1`, без ретраев (упавший тест ретрай не починит). BashOperator: `/opt/dbt-venv/bin/dbt build --project-dir /opt/dbt --profiles-dir /opt/dbt --target dev --target-path /tmp/dbt/target --log-path /tmp/dbt/logs --vars '<dbt_vars>'`, где `<dbt_vars>` берётся шаблоном из `dag_run.conf["dbt_vars"]`, по умолчанию `{}`. Запуск по Asset идёт с пустым conf; переменные нужны ручному запуску, на этом стоит chaos 9 (W3-T06).
4. `dq_checks`: каждые 15 минут, Python-таски, SQL по образцу `reconcile` и `lsn_duplicates_since` из `lib.sh`.
   - Валят DAG: дубли ключей в любой таблице silver; расхождение `count(*)` Postgres и живых строк silver, но только в покое: последний снапшот bronze старше 5 минут и равен Variable `silver_upsert_last_bronze_snapshot`. Вне покоя расхождение пишется в лог как «в пути».
   - Пишутся в лог (экспорт в Prometheus это W4-T03): повторы доставки за час (одинаковые `source_table, key, lsn`, транспорт); no-op источника за час (`op = 'u' and before = after`); новые строки карантина за час; freshness `now() - max(_updated_at)` по таблицам silver; `dbt source freshness`.
5. `iceberg_maintenance`: ежедневно, pool `lake_writers`, для каждой таблицы silver `alter table lake.silver.<t> execute optimize` через Trino. Bronze не трогается (D11).
6. Тесты на хосте: env для DockerOperator совпадает по ключам с `spark-silver.environment` из `docker/compose.yaml` (YAML читается в тесте); решение «покой или в пути» для таблицы входов; пропуск при равных id снапшота.
7. Документация: OPERATIONS, раздел «Airflow» из W3-T04 дополняется DAG: как поставить `silver_upsert` на паузу перед ручным `make silver`, что значит красный `dq_checks`. Раздел ADR-011 дополняется D10 и D11. Старый текст по D10 и D11: в `00-mini-architecture-review.md` §4 «dbt_build (hourly)» на схеме и «Batch раз в час» в таблице; в `ARCHITECTURE.md` п. 6 и 7 (hourly; `iceberg_maintenance` с expire и orphan files); таблица DAG в `airflow/README.md`.

**Готово, когда.**
- `$COMPOSE exec airflow-scheduler airflow dags list-import-errors` пусто, `airflow dags list` там же показывает четыре DAG.
- Порция `make replay-burst SECONDS=60`; в течение 10 минут `silver_upsert` success с выполненным `merge`, затем `dbt_build` success по Asset. Следующий `silver_upsert` без новых данных: `merge` skipped, `dbt_build` не запускался.
- `dq_checks` в покое success, в логе обе метрики дублей, `now() - max(_updated_at)` по 7 таблицам silver и результат `dbt source freshness` по 4 таблицам реплея.
- Во время той же порции ручной запуск `iceberg_maintenance`: пока идёт `merge`, его задачи стоят в очереди pool, интервалы выполнения `merge` и `optimize` в UI не пересекаются; DAG success.
- Сразу после `iceberg_maintenance` `select content, count(*) from lake.silver."orders$files" group by 1` не показывает строк с `content = 1` (delete files свёрнуты).
- Сутки при остановленном реплее: все DAG зелёные, `docker stats` записан.
- `make test`, `make lint` зелёные.

**Ловушки.**
- Ручной `make silver` при включённом DAG даёт два писателя на один checkpoint.
- Сеть compose называется `<COMPOSE_PROJECT_NAME>_lake`: имя из env, иначе в проекте `lakehouse-fresh` DAG пойдёт в чужую сеть.
- DockerOperator по умолчанию монтирует временный каталог хоста, которого нет у Airflow в контейнере: `mount_tmp_dir=False`.
- Контейнер DockerOperator не подчиняется лимитам compose: `mem_limit` задаётся в операторе.
- Asset публикуется при любом успехе таска: без пропуска dbt перестраивает gold каждые 5 минут впустую.
- `optimize` и MoR MERGE на `silver.orders` одновременно: проигравший коммит падает (ADR-010). Поэтому оба в pool на 1 слот.
- Сверка во время реплея всегда «расходится»: падать на ней можно только в покое.
- Одна метрика дублей по LSN не видит дубли источника: chaos 3 дал 95 no-op UPDATE и 0 повторов LSN (07.10). Поэтому две метрики.

**Blast radius и пайплайн.** `optimize` создаёт replace-снапшоты silver без удаления данных; старые файлы остаются до expire в W5, streaming-чтение silver их не читает. Checkpoint silver тот же, что у `make silver`: первый прогон из Airflow продолжает с места ручного. Expire, orphan files и DROP не делаются.

**Не входит.** Экспорт метрик (W4-T03), алерты (W4-T05), expire и orphan files (W5-T05), перевод `dq_checks` на Asset (Modify-гейт владельца).

### W3-T06 Chaos 9 (нужен Operate-гейту dbt) и optional chaos 10

**Зачем.** Показать, что поломка в batch-слое видна и не портит данные: DAG красный, витрины остаются прошлой версией, повтор доделывает. Chaos 9 обязателен: на `make chaos-break-dbt-test` стоит Operate-гейт dbt (`02-learning-gates.md`). Chaos 10 только если останется время.

**Оценка** 1 ч. **Зависит от:** W3-T05. **Область коммита:** `dbt`.

**Сделать.**
1. Chaos 9, `make chaos-break-dbt-test`: `$COMPOSE exec airflow-scheduler airflow dags trigger dbt_build --conf '{"dbt_vars": "{chaos_break_test: true}"}'`; singular-тест на `fct_orders` падает только при этой переменной. Модели после `fct_orders` skipped, витрины остаются прошлой версией. Повтор без conf зелёный.
2. Chaos 10 (optional): отдельный target dbt с пониженным лимитом памяти запроса через `session_properties` (`query_max_memory`, имя свойства сверить для Trino 483); модель падает, инкрементальная витрина не повреждена, повтор на обычном target доделывает. Конфиг Trino не меняется.
3. OPERATIONS: сценарии 9 и 10 по шаблону из пяти ответов; у сценария 9 в таблице OPERATIONS и в `00-mini-architecture-review.md` §8 снять пометку optional (на нём гейт).

**Готово, когда.** Chaos 9 воспроизводится командой: `dbt_build` красный, `select count(*) from lake.gold."mart_daily_sales$snapshots"` до и после равен, повтор без conf зелёный. Если делался chaos 10: после повтора тест полного пересчёта pass.

**Blast radius и пайплайн.** Нет.

### W3-T07 Гейты dbt и Airflow (владелец)

По `02-learning-gates.md`, ответы в `LEARNING.md`. Исполнитель не делает их за владельца: на просьбу даёт файл, функцию и подсказку.

## 5. Порядок и коммиты

| # | Задача | Область | Зависит от |
|---|---|---|---|
| 1 | W3-T00 путь с чистого клона | `infra` | D1, D2 |
| 2 | W3-T01 dbt: проект, staging, ядро | `dbt` | D3-D6, D13 |
| 3 | W3-T02 витрины | `dbt` | 2, D7, D8, D13 |
| 4 | W3-T03 DQ-тесты, docs | `dbt` | 3 |
| 5 | W3-T04 Airflow: образ и профиль | `orchestrate` | D9, D12; параллельно 2-4 |
| 6 | W3-T05 `silver_upsert` и `dbt_build` | `orchestrate` | 1-5, D10, D13 |
| 7 | W3-T05 `dq_checks` и `iceberg_maintenance` | `orchestrate` | 6, D11 |
| 8 | W3-T06 chaos 9, optional chaos 10 | `dbt` | 7 |
| 9 | HANDOFF, итоги W3, потраченный бюджет реплея | `docs` | все |

## 6. Проверки для каждой задачи

- `make lint`, `make test`; для dbt ещё `make dbt-parse` и `dbt build --select <model>+`; для compose `docker compose config`.
- Первый тест на отказ: дубль ключа, исчезнувшая группа в инкременте, расхождение env DAG и compose, повтор без новых данных.
- Живая проверка DoD на стеке; числа в OPERATIONS, ADR или описания моделей, с датой.
- Влияние на checkpoint, таблицы, offsets, реплей и DAG пишется явно; если нужно что-то удалить, стоп и вопрос.
- Ревью диффа по разделу «Плагины агента» в `CLAUDE.md`, коммит после «ок» владельца.

## 7. Замечено и не входит в W3

Кандидаты на решение владельца:

- История статусов заказа. Вопросы «сколько заказов висело в shipped на дату X» и «когда отменили» требуют истории, а silver хранит текущее состояние. Времени отмены в источнике нет: реплеер ставит `canceled` без timestamp, а `source_ts_ms` в bronze это часы реплея, не бизнес-время. Варианты: (a) реплеер пишет бизнес-время в колонку источника, это изменение схемы `shop` и контракта; (b) `fct_order_status_history` из bronze с оговоркой «время обработки»; (c) не моделировать. Решить до W6.
- SCD2 на измерениях не нужен: реплей не меняет клиентов, продавцов и товары, SCD1 записать решением.
- Сверка по значениям, а не только по `count(*)`: равные количества прячут устаревшие строки. W5-T04.
- Если бюджета D2 не хватит, нужен неразрушающий второй круг реплея: `make replay-reset` это TRUNCATE, который Debezium не передаёт (`skipped.operations=t` по умолчанию), silver сохранит старые строки, а новый `replay-load` пересчитает сдвиг дат и задвоит даты в gold.
