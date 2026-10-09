# 01. Roadmap: 6 недель, до 120 часов

Версия 1.1, 09.10.2026 (1.0 от 19.09.2026). Приоритет: working pipeline → понимание → failure/recovery → observability → tests → docs → advanced. Если неделя не закрыта, сжимаются недели 5-6, а не наоборот.

Формат задачи: `W<n>-T<nn>`, оценка в часах, DoD. Владелец делает Read/Explain/Operate/Modify гейты (`02-learning-gates.md`), всё остальное пишет AI.

С недели 3 этот файл оглавление: суть задачи, оценка, DoD в одну строку. Исполняется спека блока, написанная по `06-spec-standard.md`: решения владельца, карточки с командами DoD, ловушки, blast radius. Неделя 3: `07-w3-spec.md`. Для недель 4-6 ниже перечислено, что их спека обязана закрыть.

---

## Неделя 1. Vertical slice (~20 ч)

Закрыта, кроме гейта владельца W1-T08.

Цель: `make up PROFILE=core && make replay` с нуля за 10 минут, в Trino видны CDC-события.

| Задача | Часы | DoD |
|---|---|---|
| W1-T01 Скелет репо, `uv`, `ruff`, `pre-commit`, `Makefile`, `.env.example`, `make secrets` | 2 | `make lint` зелёный на пустом репо |
| W1-T02 `compose.yaml` профиль `core`: postgres-oltp, postgres-meta (JDBC catalog), kafka, kafka-connect, minio. Лимиты памяти, healthchecks, порты на 127.0.0.1. `docker compose pull` фиксирует реальные теги | 3 | `make up PROFILE=core` все healthy; `docker stats` записан в `00-mini-architecture-review.md` §6 |
| W1-T03 OLTP-схема `shop` (SQL-миграции, `sqitch`-подобный простой runner или `alembic`), `make data` (загрузка Olist), сэмпл 2 000 заказов в `data/sample/` | 3 | `select count(*) from shop.orders` = 100k на полном датасете |
| W1-T04 `oltp_replayer`: initial load 80% со сдвигом дат, replay 20% по виртуальным часам, `replay_state`, флаги LATE/DUPLICATE/SPEED | 4 | Реплеер перезапускается без повторной загрузки; `/metrics` отдаёт `replayer_events_total` |
| W1-T05 Debezium коннектор `shop-connector` (`snapshot.mode=initial`, topic prefix `oltp`, heartbeat), скрипт регистрации, топики 3 партиции, retention 24 ч | 2 | `kafka-console-consumer` показывает envelope INSERT/UPDATE/DELETE |
| W1-T06 Образ Spark с Iceberg runtime, Kafka connector, S3A, postgres driver; JDBC catalog в `postgres-meta`; `bronze_cdc_ingest` job: subscribePattern `oltp\.shop\..*`, append в `bronze.cdc_events`, trigger 20 с, checkpoint в MinIO | 4 | После `docker kill spark-bronze` и restart job продолжает с checkpoint, `count(*)` растёт; поведение по дублям записывается как наблюдение (chaos 1 в W2 делает это экспериментом) |
| W1-T07 Trino профиль `query`, catalog `lake` через JDBC (драйвер в `plugin/iceberg`, проверить) | 1 | `select source_table, count(*) from lake.bronze.cdc_events group by 1` |
| W1-T08 Гейт Kafka (Read/Explain/Operate/Modify) | 1 | Заметки в `LEARNING.md` |

## Неделя 2. Silver + Iceberg (~22 ч)

Закрыта 08.10.2026, кроме гейтов владельца W2-T08 и Modify-гейта W2-T07. Спека и план: `04-w2-spec.md`, `05-w2-plan.md`.

Цель: silver отражает текущее состояние Postgres без дублей, late и DELETE обработаны, schema evolution пройдена.

| Задача | Часы | DoD |
|---|---|---|
| W2-T01 Контракты `contracts/silver/<table>.json`, тесты парсера envelope | 2 | `pytest tests/unit` зелёный |
| W2-T02 `silver_upsert` job: Iceberg streaming read из bronze, `AvailableNow`, `foreachBatch`, dedup `(source_table, key, lsn)`, `MERGE INTO` с условием `source.lsn > target._last_lsn`, soft delete | 5 | `count(*)` silver.orders = count в Postgres после догона |
| W2-T03 Свойства таблиц: MoR для `silver.orders`, CoW для остальных, partition `orders` по `month(purchase_ts)` | 1 | `DESCRIBE EXTENDED`, ADR-007 |
| W2-T04 `silver.quarantine` для невалидных событий (не парсится JSON, нет PK) | 2 | Poison event не роняет job |
| W2-T05 Chaos 1-4 (`spark-kill`, `connect-restart`, duplicates, late) как `make chaos-*` с проверочными SQL. Chaos 1 это эксперимент: есть ли дубли в bronze после kill, что в `snapshots.summary` (`spark.sql.streaming.epochId`) | 4 | Каждый сценарий воспроизводится и описан в `OPERATIONS.md`; результат chaos 1 записан в ADR-007 |
| W2-T06 Iceberg demo-скрипты: snapshots, time travel, `rollback_to_snapshot`, `expire_snapshots`, small files (`files` metadata table до/после `rewrite_data_files`) | 3 | `make iceberg-demo` печатает результаты |
| W2-T07 Schema evolution: `REPLAY_SCHEMA_EVOLUTION_AT`, миграция `ADD COLUMN sales_channel`, bronze не ломается, silver обновляется по контракту | 2 | Modify-гейт владельца: добавить колонку самому |
| W2-T08 Гейты Spark и Iceberg | 3 | `LEARNING.md` |
| W2-T09 Should-have: Lakekeeper (профиль `rest`), перенос таблиц JDBC → REST через `register_table`, Spark и Trino на REST. Лимит 3 часа: не завёлся, остаёмся на JDBC, ADR-005 фиксирует почему | 3 | Обе стороны видят одни таблицы, или ADR с причиной отказа |

## Неделя 3. dbt + Airflow (~25 ч)

Цель: gold строится dbt по событию «silver обновился», тесты отличают поломку пайплайна от аномалий источника, Airflow оркестрирует только batch, путь с чистого клона воспроизводится одной командой. Спека `07-w3-spec.md`, решения D1-D13 ждут «ок» владельца.

| Задача | Часы | DoD |
|---|---|---|
| W3-T00 Путь с чистого клона: `make start` (core без реплеера), `bootstrap`, `verify`, `replay-burst`, данные `raw` или `sample` | 4 | `make bootstrap` в одноразовом проекте на сэмпле печатает `verify ok`, повтор идемпотентен, контейнер реплеера не стартует |
| W3-T01 dbt-проект: sources на silver, `stg_*` views без фильтра удалений, seed перевода категорий, `int_orders_enriched`, `fct_orders`, `fct_order_items`, `dim_customers` (грейн `customer_unique_id`), `dim_products`, `dim_sellers`; `on_table_exists=replace` | 4 | `make dbt-build` зелёный, `fct_orders` равен живым строкам `silver.orders`, повторный прогон без DROP |
| W3-T02 Витрины: инкрементальная `mart_daily_sales` (`delete+insert` по дате покупки изменившихся заказов), `mart_delivery_sla`, `mart_seller_performance`, макрос `safe_divide`. Geolocation не моделируется (D5) | 3 | После порции реплея тест «инкремент равен полному пересчёту» проходит |
| W3-T03 Тесты на аномалии источника (warn с измеренным порогом), `accepted_values` статусов, freshness sources, docs и глоссарий метрик | 2 | `make dbt-build` зелёный, warn только у известных аномалий с числом и причиной, docs собираются |
| W3-T04 Образ Airflow (dbt в отдельном venv, docker provider), `airflow.env`, валидный Fernet-ключ, pool `lake_writers` | 3 | Профиль `orchestrate` healthy, пробная задача проходит execution API |
| W3-T05 DAG `silver_upsert` (5 мин, DockerOperator, пропуск без нового снапшота bronze), `dbt_build` (Asset от silver), `dq_checks` (15 мин: сверка в покое, две метрики дублей, freshness), `iceberg_maintenance` (daily, только optimize silver) | 6 | После порции реплея silver и dbt проходят по Asset, без новых данных `merge` skipped, `merge` и `optimize` не пересекаются, сутки зелёные |
| W3-T06 Chaos 9 (сломать dbt test, на нём Operate-гейт dbt) и optional chaos 10 (память Trino через session property) | 1 | В `OPERATIONS.md` |
| W3-T07 Гейты dbt и Airflow | 2 | `LEARNING.md` |

## Неделя 4. Observability + failure (~20 ч)

Цель: по дашборду видно lag, freshness, ошибки; шесть алертов; все 10 сценариев отказа описаны.

| Задача | Часы | DoD |
|---|---|---|
| W4-T01 Профиль `obs`: prometheus, grafana (provisioning из файлов), kafka-exporter, postgres-exporter (slot lag, retained WAL), statsd-exporter для Airflow, cadvisor, Connect JMX exporter | 4 | Все targets UP |
| W4-T02 `StreamingQueryListener`: `spark_streaming_input_rows_total`, `spark_streaming_batch_duration_seconds` и `spark_streaming_last_batch_timestamp` уже есть с W1, добавить `spark_streaming_kafka_lag` (endOffset минус processed, ADR-013) | 3 | Метрики видны в Prometheus |
| W4-T03 `freshness` gauge: `dq_checks` шлёт `lakehouse_table_freshness_seconds{layer,table}` через statsd-exporter, который уже есть в профиле `obs`. Pushgateway это новый сервис, только через ADR | 2 | На дашборде |
| W4-T04 Grafana: дашборд «Pipeline health» (lag, rows/batch, batch duration, freshness, connector status, slot WAL, DAG failures) и «Infra» (cadvisor) | 3 | Скриншоты в `docs/img/` |
| W4-T05 Алерты: `ConnectorNotRunning`, `SlotWalRetainedHigh`, `SparkNoBatch5m`, `FreshnessAbove15m`, `AirflowDagFailed`, `ContainerRestarting` | 2 | Каждый алерт срабатывает в соответствующем chaos |
| W4-T06 Chaos 5, 6, 7, 8; `OPERATIONS.md` дописан по всем сценариям | 4 | 8 обязательных сценариев по 5 ответов |
| W4-T07 Гейт observability | 2 | `LEARNING.md` |

Спека недели 4 обязана закрыть:

- Каталоги `observability/*` пусты. Bind-маунт отсутствующего файла создаёт на хосте каталог от root, и контейнер не стартует, а `docker compose config` этого не ловит: DoD каждой задачи проверяет живой старт, не только config.
- Экспортеры в compose без healthcheck и `depends_on`, у трёх тег не проверен: правило compose из `CLAUDE.md` выполняется в W4-T01.
- Для Connect JMX exporter в образе Connect нет jar: свой слой образа или bind-маунт jar, решение владельца в спеке.
- Chaos 6 и `SlotWalRetainedHigh`: слот не двигается, пока в `shop` нет изменений (pgoutput пропускает пустые транзакции, heartbeat не сдвигает LSN), поэтому на простое WAL растёт без всякого отказа. Сценарий и порог алерта проверяются во время порции реплея; лечение через `heartbeat.action.query` это новая таблица и топик, значит ADR.
- Silver живёт минуту и сам метрик не отдаёт: длительность и исход `merge` для алертов берутся из Airflow (StatsD). Метрика `quarantine_rows_total` это Modify-гейт владельца, её не делать.
- Cadvisor на Docker Desktop с WSL2: первым шагом проверить, что `container_memory_usage_bytes{name=~"lakehouse.*"}` отдаёт ряды по всем контейнерам.
- Имена алертов как в W4-T05; в `00-mini-architecture-review.md` §8 они те же.
- В `02-learning-gates.md` Operate-гейт observability называет dbt test сценарием 8; по таблице сценариев это 9, а 8 это Kafka down.

## Неделя 5. Stateful job + CI/CD + DQ + compaction (~19 ч)

| Задача | Часы | DoD |
|---|---|---|
| W5-T01 Обязательный stateful job `orders_per_minute`: окно 1 мин по `purchase_ts`, watermark 5 мин, `outputMode=update`, `foreachBatch` upsert в `silver.orders_per_minute`; метрики state rows и watermark в listener; позднее событие внутри и за пределами watermark | 5 | Событие внутри watermark обновляет окно, за пределами отбрасывается, оба случая показаны SQL и объяснены |
| W5-T02 `ci.yml`: hadolint, `uv sync --locked`, Spark-тесты с Iceberg через `make test-spark` в собранном `lakehouse/spark:ci`, сборка образа Airflow, кэш слоёв (ruff, mypy, yamllint, sqlfluff, `pytest`, `dbt parse`, `docker compose config`, gitleaks уже есть) | 4 | Зелёный на PR, тесты MERGE, карантина и пропуска эпохи не skipped |
| W5-T03 `smoke.yml` (по кнопке или nightly): `make bootstrap` на `REPLAY_DATA=sample` (W3-T00), короткая порция реплея, `make verify` | 3 | Проходит на ubuntu-latest |
| W5-T04 Reconciliation отчёт: источник vs silver vs gold, по количеству и по значениям (хэш строки по ключу), расхождения с причиной (в пути, карантин); сверка только в покое, как `dq_checks` W3-T05 | 3 | В `dq_checks` и на дашборде |
| W5-T05 Maintenance по ADR о политике: silver и gold `expire_snapshots(7d)`, `remove_orphan_files`, `rewrite_position_delete_files`; bronze только `rewrite_data_files` и очистка `metadata.json` (`write.metadata.delete-after-commit.enabled`), `expire_snapshots` на bronze запрещён до решения по apache/iceberg#18000 (ADR-021); демо small files до и после | 3 | Число файлов падает в 10 раз; expire и orphan files запущены впервые после «ок» владельца |

Спека недели 5 обязана закрыть:

- W5-T01: позднего события по `purchase_ts` сейчас взять неоткуда. `REPLAY_LATE_RATIO` сдвигает только UPDATE `delivered`, а INSERT заказа поздно не приходит. На 2880x 5 минут watermark это 0.1 с реального времени, а один батч bronze в 20 с покрывает 16 виртуальных часов. Нужен механизм (публикация старого события в Kafka по образцу `chaos-late` или другое окно) и решение, что читает stateful job: Kafka или bronze.
- W5-T02: на runner CI нет `/opt/spark/jars`, поэтому тесты с `needs_iceberg` там сейчас skipped, а это самые ценные тесты W2.
- W5-T03: Kaggle в CI недоступен, отсюда сэмпл; smoke без него не построить.
- W5-T05: `expire_snapshots` и `remove_orphan_files` в blast radius; MERGE без изменений тоже коммитит снапшот `silver.orders`, это учесть в retention; `metadata.json` bronze копятся (около 4 300 в сутки при непрерывном потоке).

## Неделя 6. Документация + interview prep + буфер (~16 ч)

| Задача | Часы | DoD |
|---|---|---|
| W6-T01 Grafana + Trino datasource: дашборд «Marketplace» по gold (продажи по дням, топ категорий, SLA доставки по штатам, отмены) | 2 | Скриншот в README |
| W6-T02 README как карта, `ARCHITECTURE.md` с диаграммой, `DECISIONS.md` со всеми ADR, `LEARNING.md` с итогами гейтов | 4 | Прочитать глазами рекрутера за 3 минуты |
| W6-T03 `docs/interview-notes.md`: 30 вопросов-ответов по проекту (Kafka, Spark, Iceberg, CDC, idempotency, DQ) | 3 | Мок-собес с AI пройден |
| W6-T04 Буфер. Если всё закрыто: Superset (профиль `bi`, один дашборд) или Schema Registry + Avro | 7 | |

Дешёвую часть W6-T02 (README со статусом done, measured, planned и ссылками на доказательства, диаграмма) можно сделать раньше: это порядок B в HANDOFF, выбор за владельцем.

---

## Правила недели

- Перед стартом недели: спека блока по `06-spec-standard.md` и «ок» владельца на её таблицу решений.
- Реплей только порциями, в пределах бюджета недели (D2 в `07-w3-spec.md`); сколько потрачено, пишется в HANDOFF.
- До W3-T00 `make up` с профилем `core` не запускать: он поднимает контейнер реплеера, который играет на полной скорости. Сервисы поднимаются по имени (`OPERATIONS.md`, «Profiles»).
- Понедельник: план недели из таблицы, максимум 5 задач в работе.
- Каждая задача: AI пишет, владелец читает diff, запускает, закрывает DoD, только потом коммит.
- Пятница: гейты недели, запись в `LEARNING.md`, `docker stats` в RAM-таблицу, что не закрыто переносится, а не накапливается.
- Если задача превысила оценку в 2 раза: остановиться, записать в `DECISIONS.md` вариант «упростить или вырезать».
