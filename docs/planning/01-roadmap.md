# 01. Roadmap: 6 недель, до 120 часов

Версия 1.0, 19.09.2026. Приоритет: working pipeline → понимание → failure/recovery → observability → tests → docs → advanced. Если неделя не закрыта, сжимаются недели 5-6, а не наоборот.

Формат задачи: `W<n>-T<nn>`, оценка в часах, DoD. Владелец делает Read/Explain/Operate/Modify гейты (`02-learning-gates.md`), всё остальное пишет AI.

---

## Неделя 1. Vertical slice (~20 ч)

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

## Неделя 3. dbt + Airflow (~20 ч)

Цель: gold-слой строится по расписанию, тесты и DQ работают, Airflow оркестрирует только batch.

| Задача | Часы | DoD |
|---|---|---|
| W3-T01 dbt-проект: `sources` на silver, `stg_*` views, `int_orders_enriched`, `fct_orders`, `fct_order_items`, `dim_customers`, `dim_products`, `dim_sellers` | 4 | `dbt build` зелёный |
| W3-T02 Incremental `mart_daily_sales` (merge, `unique_key=(sales_date, seller_state)`), `mart_seller_performance`, `mart_delivery_sla`; seeds geolocation и category translation | 3 | Повторный `dbt run` не меняет строки |
| W3-T03 Тесты: unique, not_null, relationships, accepted_values для статусов, freshness на sources, один макрос (`cents_to_brl` или `safe_divide`), `dbt docs generate` | 2 | `dbt test` зелёный, docs открываются |
| W3-T04 Профиль `orchestrate`: postgres-meta, airflow api-server/scheduler/dag-processor, образ Airflow с dbt-trino и docker provider | 3 | UI на 127.0.0.1:8090, healthy |
| W3-T05 DAG `silver_upsert` (каждые 5 мин, DockerOperator запускает spark-silver), `dbt_build` (hourly, Asset от silver_upsert), `dq_checks` (15 мин: freshness, reconciliation Postgres vs silver, duplicate ratio), `iceberg_maintenance` (daily) | 5 | Все DAG зелёные сутки |
| W3-T06 Optional chaos 9 (сломать dbt test) и 10 (Trino память) | 1 | В `OPERATIONS.md` |
| W3-T07 Гейты dbt и Airflow | 2 | `LEARNING.md` |

## Неделя 4. Observability + failure (~20 ч)

Цель: по дашборду видно lag, freshness, ошибки; шесть алертов; все 10 сценариев отказа описаны.

| Задача | Часы | DoD |
|---|---|---|
| W4-T01 Профиль `obs`: prometheus, grafana (provisioning из файлов), kafka-exporter, postgres-exporter (slot lag, retained WAL), statsd-exporter для Airflow, cadvisor, Connect JMX exporter | 4 | Все targets UP |
| W4-T02 `StreamingQueryListener` в Spark-драйвере: `spark_streaming_input_rows`, `spark_streaming_batch_duration_seconds`, `spark_streaming_kafka_lag` (endOffset минус processed) через `prometheus_client` | 3 | Метрики видны в Prometheus |
| W4-T03 `freshness` gauge: DQ DAG пишет `lakehouse_table_freshness_seconds{layer,table}` в Pushgateway или через statsd | 2 | На дашборде |
| W4-T04 Grafana: дашборд «Pipeline health» (lag, rows/batch, batch duration, freshness, connector status, slot WAL, DAG failures) и «Infra» (cadvisor) | 3 | Скриншоты в `docs/img/` |
| W4-T05 Алерты: `ConnectorNotRunning`, `SlotWalRetainedHigh`, `SparkNoBatch5m`, `FreshnessAbove15m`, `AirflowDagFailed`, `ContainerRestarting` | 2 | Каждый алерт срабатывает в соответствующем chaos |
| W4-T06 Chaos 5, 6, 7, 8; `OPERATIONS.md` дописан по всем сценариям | 4 | 8 обязательных сценариев по 5 ответов |
| W4-T07 Гейт observability | 2 | `LEARNING.md` |

## Неделя 5. Stateful job + CI/CD + DQ + compaction (~19 ч)

| Задача | Часы | DoD |
|---|---|---|
| W5-T01 Обязательный stateful job `orders_per_minute`: окно 1 мин по `purchase_ts`, watermark 5 мин, `outputMode=update`, `foreachBatch` upsert в `silver.orders_per_minute`; метрики state rows и watermark в listener; late event с `REPLAY_LATE_DELAY_SECONDS` < и > watermark | 5 | Событие внутри watermark обновляет окно, за пределами отбрасывается, оба случая показаны SQL и объяснены |
| W5-T02 `ci.yml`: ruff, mypy, yamllint, hadolint, sqlfluff, `pytest tests/unit`, `dbt parse`, `docker compose config`, gitleaks, сборка образов spark и airflow с кэшем | 4 | Зелёный на PR |
| W5-T03 `smoke.yml` (по кнопке или nightly): `core` на runner, replay 60 с, проверка `count(*) > 0` в bronze через Trino CLI | 3 | Проходит на ubuntu-latest |
| W5-T04 Reconciliation отчёт: таблица источник vs silver vs gold, расхождения с причиной (in-flight, quarantine) | 3 | В `dq_checks` и на дашборде |
| W5-T05 Compaction в `iceberg_maintenance`: `rewrite_data_files`, `rewrite_position_delete_files`, `expire_snapshots(7d)`, `remove_orphan_files`; демо small files до/после | 3 | Число файлов падает в 10 раз |

## Неделя 6. Документация + interview prep + буфер (~16 ч)

| Задача | Часы | DoD |
|---|---|---|
| W6-T01 Grafana + Trino datasource: дашборд «Marketplace» по gold (продажи по дням, топ категорий, SLA доставки по штатам, отмены) | 2 | Скриншот в README |
| W6-T02 README как карта, `ARCHITECTURE.md` с диаграммой, `DECISIONS.md` со всеми ADR, `LEARNING.md` с итогами гейтов | 4 | Прочитать глазами рекрутера за 3 минуты |
| W6-T03 `docs/interview-notes.md`: 30 вопросов-ответов по проекту (Kafka, Spark, Iceberg, CDC, idempotency, DQ) | 3 | Мок-собес с AI пройден |
| W6-T04 Буфер. Если всё закрыто: Superset (профиль `bi`, один дашборд) или Schema Registry + Avro | 7 | |

---

## Правила недели

- Понедельник: план недели из таблицы, максимум 5 задач в работе.
- Каждая задача: AI пишет, владелец читает diff, запускает, закрывает DoD, только потом коммит.
- Пятница: гейты недели, запись в `LEARNING.md`, `docker stats` в RAM-таблицу, что не закрыто переносится, а не накапливается.
- Если задача превысила оценку в 2 раза: остановиться, записать в `DECISIONS.md` вариант «упростить или вырезать».
