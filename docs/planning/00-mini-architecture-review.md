# 00. Mini Architecture Review

Версия 1.0, 19.09.2026. Ревью стека для mini-версии проекта: ноутбук 16 GB, WSL2 + Docker Desktop, 6 недель / до 120 часов, 95-99% кода пишет AI. Цель: понять и уметь объяснить, а не построить много.

Формат вердикта: **KEEP**, **SIMPLIFY**, **POSTPONE**, **REMOVE**, **ADD**. Всё, что помечено «проверить», проверяется в первой неделе запуском, а не верой в документацию.

---

## 1. Резюме

Предложенный стек в целом правильный: это ровно та цепочка, которую спрашивают на собеседованиях Senior DE в 2026. Ревью нашло семь точек, где нужно изменить подход, чтобы уложиться в 16 GB и 120 часов и не потерять карьерный сигнал.

| # | Находка | Решение |
|---|---|---|
| 1 | Все 12 сервисов одновременно не влезают в 16 GB (Windows съедает 4-5 GB) | Compose-профили и правило «core + один из orchestrate / obs / bi». RAM-бюджет в разделе 6 |
| 2 | Синтетические данные дают бессмысленные дашборды и не дают интервью-историй | Replay реального публичного датасета Olist (100k заказов бразильского маркетплейса, 2016-2018) через Postgres со сдвигом дат «в сегодня». Раздел 3 |
| 3 | `MERGE INTO` в Iceberg прямо из streaming-запроса ненадёжен (issues #9730, #10805, #13431) | Bronze: append-only streaming sink. Silver: отдельный Spark job с `Trigger.AvailableNow` и `foreachBatch` → `MERGE INTO`, запускается Airflow. Это и есть правильный production-паттерн |
| 4 | MinIO: community-образы не публикуются с октября 2025, консоль вырезана | Пин последнего community-тега (проверить pull в W1), fallback RustFS или Garage. ADR-004 |
| 5 | Superset стоит ~1.2 GB и почти не даёт сигнала DE (BI у тебя уже сильная сторона) | POSTPONE в неделю 6, профиль `bi`, один дашборд. Если не хватает времени, дашборд делается в Grafana через Trino datasource |
| 6 | Kafka lag для Spark не виден в kafka-exporter: Spark не коммитит offsets в consumer group | ADD: `StreamingQueryListener` в Spark-драйвере публикует `processed offset`, `input rows`, `batch duration` в Prometheus. Одна из лучших интервью-историй проекта |
| 7 | Девять агентов, ADR-001..030, 90 задач из большого плана для mini избыточны | Один `CLAUDE.md`, `DECISIONS.md` с короткими ADR, роадмап на 6 недель, гейты Read/Explain/Operate/Modify |
| 8 | Внешнее ревью 19.09: REST catalog не должен блокировать неделю 1, stateful job не может быть optional, Superset не в core | JDBC catalog в `postgres-meta` для vertical slice, Lakekeeper как should-have после него (ADR-005); `orders_per_minute` обязателен (неделя 5, W5-T01); Superset в OPTIONAL, графики через Grafana + Trino datasource |

Ничего из ключевой цепочки Postgres → Debezium → Kafka → Spark → Iceberg → Trino → dbt не удалено.

---

## 2. Ответы на восемь вопросов

### 2.1 Какие компоненты оставить

| Компонент | Вердикт | Какую проблему решает и почему именно он |
|---|---|---|
| PostgreSQL (OLTP-источник) | **KEEP** | Реалистичный OLTP с WAL. Отдельный инстанс `postgres-oltp`: replication slot и `wal_level=logical` живут только здесь, чтобы мёртвый коннектор растил WAL песочницы, а не метабазы Airflow |
| Debezium (Kafka Connect, 1 worker) | **KEEP** | Единственный способ показать CDC по-настоящему: snapshot, LSN, slot, envelope before/after, at-least-once |
| Kafka 4.x KRaft, 1 брокер | **KEEP** | Пробел №1 по вакансиям. Один брокер, `replication.factor=1`, 3 партиции на топик: партиции, ordering по ключу, consumer groups, retention, replay видны и так |
| Spark Structured Streaming | **KEEP, `local[2]`** | Единственный движок, который закрывает Spark-пробел. Standalone-кластер на ноутбуке это три JVM ради нуля понимания. Executors, tasks, shuffle, checkpoint, Spark UI видны в `local[2]` |
| Iceberg + S3-хранилище | **KEEP** | Пробел lakehouse: snapshots, time travel, schema evolution, hidden partitioning, MERGE, compaction |
| Iceberg catalog | **SIMPLIFY → JDBC catalog сначала, REST (Lakekeeper) как should-have** | Spark и Trino должны видеть один каталог. JDBC catalog в `postgres-meta` это ноль новых сервисов (в Trino нужно положить postgres JDBC-драйвер в plugin-директорию, проверить в W1). REST это индустриальный стандарт 2026 и лучший сигнал, Lakekeeper это Rust, ~150 MB, но ещё один bootstrap. Переход JDBC → REST после vertical slice через `register_table`, сам переход это учебная задача. ADR-005 |
| Trino single node | **KEEP** | SQL-движок над lake, dbt-адаптер, интервью-вопросы про federated query и MPP. `Xmx` 2-2.5 GB |
| dbt Core + dbt-trino | **KEEP** | Аналитический слой: staging → intermediate → marts, incremental merge, tests, docs, lineage |
| Airflow 3 (LocalExecutor) | **KEEP, SIMPLIFY** | Три процесса: api-server, scheduler, dag-processor (в 3.x он обязателен и отдельный). Без triggerer, без Celery. Оркестрирует только batch: silver merge, dbt, DQ, maintenance |
| Prometheus + Grafana | **KEEP** | Минимум наблюдаемости. Экспортеры: kafka-exporter, postgres-exporter, Spark listener, Connect JMX, Airflow StatsD |
| GitHub Actions | **KEEP** | lint, unit tests, `dbt parse`, compose config, build образов, smoke |
| Docker Compose | **KEEP** | Один `compose.yaml`, профили `core`, `query`, `orchestrate`, `obs`, `bi`, `tools` |

### 2.2 Какие компоненты убрать или отложить

| Компонент | Вердикт | Почему |
|---|---|---|
| ClickHouse | **REMOVE** | Твоё решение, согласен: уже сильная сторона, не закрывает пробел, +1 GB |
| Kubernetes / k3s / Helm | **REMOVE** | Отдельный пробел, не про данные, на 16 GB не поместится рядом с платформой |
| Terraform / Ansible | **REMOVE** | Нет сервера, нечего описывать. Вернутся, если появится Hetzner |
| Superset | **OPTIONAL → только если недели 5-6 закрыты досрочно** | Сигнал для DE слабый, BI уже сильная сторона, стоимость 1.2 GB и 4-6 часов. Витрины показываются через Grafana + Trino datasource (2-3 панели по gold), `dbt docs` и SQL в README. Профиль `bi` в compose остаётся на случай свободного времени |
| Schema Registry + Avro | **POSTPONE (stretch)** | JSON envelope Debezium с `schemas.enable=false` и JSON Schema контрактов в `contracts/` достаточно, чтобы объяснить, зачем нужен реестр. Avro добавляется в неделе 6, если всё закрыто |
| Kafka UI (Kafbat) | **SIMPLIFY → профиль `tools`, по требованию** | Сначала CLI (`kafka-topics.sh`, `kafka-consumer-groups.sh`, `kafka-console-consumer.sh`): это то, что спрашивают. UI поднимается на 15 минут для картинки |
| Alertmanager + Telegram | **POSTPONE** | Алерты пишутся как Prometheus rules и видны в Grafana. Доставка в Telegram это 30 минут в неделе 4, если есть время |
| Loki / логи | **REMOVE** | Docker `json-file` + `make logs` |
| Stateful job `orders_per_minute` (окно 1 мин, watermark 5 мин, `outputMode=update`) | **KEEP, обязателен** | Без него watermark, state и поведение late event остаются теорией, а это обязательный минимум Spark-вопросов на собеседовании. Неделя 5, первая задача, можно вытянуть раньше, если неделя 2 закрыта в срок |
| Cosmos для dbt в Airflow | **REMOVE** | `BashOperator` + `dbt build`. Task-per-model не стоит ещё одной версионно-чувствительной зависимости |

### 2.3 Какие компоненты добавить

| Компонент | Вердикт | Почему без него нельзя |
|---|---|---|
| `oltp_replayer` (Python) | **ADD** | Единственный самописный сервис-источник. Загружает Olist в Postgres, потом воспроизводит жизненный цикл заказов во времени с ускорением. Управляет: скоростью, долей late/duplicate событий, schema evolution. Раздел 3 |
| `postgres-meta` | **ADD** | Один инстанс, три БД: `airflow`, `lakekeeper`, `superset`. Отдельно от OLTP-источника |
| Spark `StreamingQueryListener` → Prometheus | **ADD** | Без него нет метрик «lag», «rows/batch», «batch duration» для Spark. Kafka-exporter показывает lag только для consumer groups, а Spark хранит offsets в checkpoint |
| `dq_checks` DAG с reconciliation | **ADD** | Сверка `count(*)` по таблицам Postgres vs silver, freshness `max(ts)` vs now, доля дубликатов в bronze. Это то, что отличает «пайплайн работает» от «данные верны» |
| `scripts/chaos/` | **ADD** | Восемь обязательных сценариев отказа как воспроизводимые команды `make chaos-<name>`, два optional. Раздел 8 |
| `Makefile` | **ADD** | Единая точка входа оператора: `make up PROFILE=core`, `make replay`, `make chaos-spark-kill`, `make gate-kafka` |
| `contracts/` (JSON Schema) | **ADD** | Контракт на CDC envelope и на схемы таблиц silver. Проверяется в тестах парсера |

### 2.4 Что будет слишком тяжёлым для ноутбука

Лимиты памяти контейнеров, которые нужно поставить сразу, и что не запускать одновременно: раздел 6. Коротко:

- Три JVM (Kafka, Kafka Connect, Trino) плюс Spark-драйвер это уже ~7 GB лимитов. Это ядро, оно живёт всегда, когда идёт работа.
- Airflow (три процесса, ~1.8 GB) и Superset (~1.2 GB) не запускаются вместе с Trino на полном `Xmx`. При включении `orchestrate` Trino получает `Xmx=2g` вместо `2.5g`.
- Второй Spark-контейнер (silver, `AvailableNow`) живёт 1-3 минуты и запускается Airflow. Пока он работает, свободной памяти должно быть ~2 GB: поэтому Superset и Kafka UI в этот момент выключены.
- WSL2 нужно ограничить явно: `.wslconfig` с `memory=12GB`, `swap=8GB`, `processors=8`. Без этого WSL2 съест всё и Windows начнёт свопить.
- Chrome с Spark UI, Grafana и Airflow UI это ещё 1-2 GB на стороне Windows. Держать открытыми только нужные вкладки.
- Если станет тесно: Trino выключается, пока идёт работа со Spark, и наоборот. Это нормальный режим для недель 1-2.

### 2.5 Что даёт максимальный карьерный сигнал

По убыванию, с привязкой к тому, что реально спрашивают:

1. Kafka + CDC: ordering по ключу, at-least-once, replay, что происходит со slot при мёртвом коннекторе. Спрашивают почти всегда.
2. Spark Structured Streaming: micro-batch, checkpoint, restart, `AvailableNow` vs continuous, watermark и state, почему `foreachBatch` + MERGE, а не streaming MERGE.
3. Iceberg: snapshots, time travel, schema evolution без переписывания, small files и compaction, CoW vs MoR, идемпотентность записи.
4. Идемпотентность и exactly-once end-to-end: где at-least-once, где dedup, почему итог корректен. Это архитектурный вопрос уровня senior.
5. Data Quality и reconciliation source vs lake: редко в pet-проектах, часто в вопросах.
6. Observability стрима: lag, freshness, «файл свежий» vs «данные свежие».
7. Failure scenarios с runbook: показывает, что ты оператор, а не только строитель.
8. dbt: incremental, tests, docs. Нужен, но это уже частично закрыто в твоём рабочем опыте.
9. CI/CD и Airflow: гигиена, ожидается, отдельного сигнала не даёт.
10. Superset: минимальный сигнал.

### 2.6 Минимальный vertical slice (неделя 1)

Postgres (Olist загружен) → Debezium snapshot + streaming → Kafka `oltp.shop.orders` → Spark `bronze_cdc_ingest` (append в `bronze.cdc_events`, JDBC catalog) → Trino `select count(*) from bronze.cdc_events`.

Критерий: `make up PROFILE=core && make replay` за 10 минут с нуля, после чего в Trino видны строки, а `make down && make up` не теряет их. Про дубли в bronze см. раздел 7: гарантия отсутствия дублей даётся на silver, а поведение bronze при рестарте проверяется экспериментом, а не обещается.

Без Airflow, без Grafana, без dbt, без silver. Всё это добавляется поверх работающего потока.

### 2.7 Порядок реализации на 6 недель

Подробно в `01-roadmap.md`. Коротко:

| Неделя | Фокус | Результат |
|---|---|---|
| 1 | Vertical slice | Поток Postgres → Trino работает, `make up` с нуля, гейт Kafka |
| 2 | Silver + Iceberg | `AvailableNow` MERGE, dedup, late events, DELETE, schema evolution, time travel; сценарии Spark restart, Connect restart, duplicates; гейты Spark, Iceberg |
| 3 | dbt + Airflow | staging/intermediate/marts, tests, docs; DAG `silver_upsert`, `dbt_build`, `dq_checks`, `iceberg_maintenance`; гейты dbt, Airflow |
| 4 | Observability + failure | Prometheus, Grafana, экспортеры, listener, 6 алертов; оставшиеся сценарии отказа; OPERATIONS.md; гейт observability |
| 5 | Stateful job + CI/CD + DQ + compaction | `orders_per_minute` (watermark, state), GitHub Actions, reconciliation, compaction, small-files демо |
| 6 | Документация + interview prep + буфер | Grafana-панели по gold, README-карта, DECISIONS, LEARNING, interview notes, мок-собес; Superset только если всё закрыто |

Правило: если неделя 2 не закрыта к концу недели 3, недели 5-6 сжимаются, а не наоборот. Pipeline и понимание важнее CI и Superset.

### 2.8 Что запускать последовательно, а не одновременно

| Профиль | Сервисы | Когда включён |
|---|---|---|
| `core` | postgres-oltp, postgres-meta (JDBC catalog), kafka, kafka-connect, minio, spark-bronze, oltp-replayer | Всегда во время работы |
| `rest` | lakekeeper | Should-have: после vertical slice, если заводится быстро |
| `query` | trino | Почти всегда; выключается, если идёт тяжёлая отладка Spark |
| `orchestrate` | airflow-api-server, airflow-scheduler, airflow-dag-processor | С недели 3; запускает spark-silver и dbt |
| `obs` | prometheus, grafana, kafka-exporter, postgres-exporter, statsd-exporter, cadvisor | С недели 4; лёгкий, обычно живёт вместе с core |
| `bi` | superset | Optional, только для демо, вместо `orchestrate` |
| `tools` | kafka-ui | По требованию, на 15 минут |

Рабочие комбинации: `core+query` (недели 1-2), `core+query+orchestrate` (неделя 3), `core+query+orchestrate+obs` (недели 4-5, Trino на `Xmx=2g`), `core+query+obs+bi` (демо). Всё сразу не запускается никогда, и это правило записано в `OPERATIONS.md`.

---

## 3. Данные: Olist replay вместо синтетики

Синтетика даёт равномерные распределения, и любой дашборд на ней выглядит фальшиво. Реальных данных e-commerce у тебя нет, а рабочие использовать нельзя. Решение: публичный датасет Olist (бразильский маркетплейс, ~100k заказов за 2016-2018, 9 CSV: orders, order_items, customers, sellers, products, payments, reviews, geolocation, category translation). Реальная сезонность, реальные категории, реальные статусы доставки и задержки.

Как из статического датасета сделать живой OLTP:

1. `make data` скачивает архив (Kaggle CLI или ручная загрузка в `data/raw/`, ~45 MB, в git не коммитится). Лицензия Kaggle-датасета: проверить на странице датасета перед публикацией сэмпла в репо. Для тестов и CI в репо лежит сэмпл ~2 000 заказов.
2. Все временные метки сдвигаются на константу так, чтобы последний день датасета стал «сегодня». Относительный порядок событий сохранён, дашборды показывают «последние 2 года», freshness-метрики осмысленны.
3. Initial load: справочники (customers, sellers, products) и первые 80% истории заказов грузятся батчем. Debezium в режиме `snapshot.mode=initial` делает snapshot. Bronze сразу получает объём для Trino и dbt.
4. Replay: оставшиеся 20% истории воспроизводятся по виртуальным часам с ускорением (`REPLAY_SPEED`, например 1 день за 30 секунд). Каждый заказ проходит жизненный цикл, и это настоящие INSERT/UPDATE/DELETE:
   - INSERT `orders`, `order_items`, `payments` в момент `order_purchase_timestamp`;
   - UPDATE `orders.status` в моменты approved → shipped → delivered (реальные timestamps из датасета);
   - INSERT `reviews` в момент `review_creation_date`;
   - UPDATE `orders.status = 'canceled'` для отменённых;
   - DELETE `order_items` при отмене до отгрузки и DELETE `reviews` по «запросу пользователя» (небольшая доля, чтобы silver обрабатывал tombstone).
5. Chaos-ручки реплеера: `LATE_RATIO` (часть UPDATE delivered задерживается на N минут), `DUPLICATE_RATIO` (повторный идентичный UPDATE), `SCHEMA_EVOLUTION_AT` (в заданный момент реплеер применяет миграцию `ALTER TABLE orders ADD COLUMN sales_channel`, и новые события идут с новым полем).
6. Реплеер идемпотентен по перезапуску: хранит позицию в таблице `replay_state`, повторный запуск продолжает, а не начинает заново.

Схема OLTP (`shop` schema в Postgres): `customers`, `sellers`, `products`, `orders`, `order_items`, `payments`, `reviews`. Geolocation и перевод категорий грузятся как справочники в dbt seeds.

Что это даёт для интервью: «я воспроизвёл два года реальных транзакций маркетплейса через CDC с ускорением в 3000 раз, с управляемой долей поздних и дублирующихся событий» звучит сильнее, чем «генератор случайных заказов».

---

## 4. Финальная архитектура MINI

```
                     ┌────────────────────────────── orchestrate (Airflow 3) ──────────────────────────────┐
                     │  silver_upsert (5 min)   dbt_build (hourly)   dq_checks (15 min)   iceberg_maintenance │
                     └───────────┬──────────────────────┬──────────────────┬──────────────────────┬──────────┘
                                 │                      │                  │                      │
oltp_replayer ──▶ postgres-oltp ──▶ kafka-connect ──▶ kafka ──▶ spark-bronze ──▶ Iceberg bronze ──▶ spark-silver ──▶ Iceberg silver ──▶ trino ◀── dbt ──▶ Iceberg gold ──▶ superset
 (Olist replay)   (wal_level=      (Debezium PG)    (KRaft,     (streaming,       (MinIO +          (AvailableNow,     (typed,            (SQL over lake, dbt-trino)          (bi, week 6)
                   logical)                          3 parts)    append-only)      Lakekeeper)        foreachBatch       deduped,
                                                                                                     MERGE INTO)        no duplicates)
                     ┌───────────────────────────────────── obs (Prometheus + Grafana) ─────────────────────────────────────┐
                     │ postgres-exporter (slot lag, WAL)  kafka-exporter  connect JMX  spark listener  statsd (Airflow)  cadvisor │
                     └──────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Роль каждого звена в цепочке:

| Звено | Проблема, которую решает | Почему не проще | Границы | Главный failure mode | Как восстанавливается |
|---|---|---|---|---|---|
| PostgreSQL OLTP | Источник правды, транзакции | Без OLTP нет CDC | Один инстанс, без реплик | Рестарт: slot сохраняется, WAL растёт, если коннектор мёртв | Коннектор переподключается, читает с сохранённого LSN |
| Debezium | Читает WAL, превращает транзакции в события без нагрузки на таблицы | Polling по `updated_at` не видит DELETE и промежуточные UPDATE | At-least-once; один slot на коннектор | Рестарт после commit в Kafka, но до commit offset → дубли событий | Offset в `connect-offsets`, дубли снимает silver |
| Kafka | Буфер и лог: развязывает producer и consumer, даёт replay | Прямой Spark → Postgres JDBC не масштабируется и не буферизует | 1 брокер, RF=1 | Брокер упал → Connect и Spark ждут, ничего не теряется в пределах retention | Restart, consumers продолжают с offsets |
| Spark bronze | Kafka → Iceberg append, микробатчи 20 с | Kafka Connect Iceberg sink существует, но не даёт Spark-навыка | `local[2]`, один job | Kill посреди микробатча | Checkpoint + атомарный Iceberg commit. Iceberg пишет `queryId`/`epochId` в summary снапшота и пропускает уже закоммиченный epoch при повторе: это делает append идемпотентным в рамках одного checkpoint. Утверждение проверяется экспериментом в W2 (chaos 1), а не принимается на веру; гарантия «без дублей» для потребителей даётся на silver |
| Iceberg bronze | Сырой журнал CDC, все события, схема гибкая (`after` как JSON string) | Parquet без табличного формата не даёт ACID и snapshots | Partition `(source_table, day(ingest_ts))` | Small files при частых батчах | `rewrite_data_files` в maintenance DAG |
| Spark silver | Инкрементально читает bronze (Iceberg streaming read), dedup по `(pk, lsn)`, `MERGE INTO` типизированные таблицы, применяет DELETE | Streaming MERGE напрямую ненадёжен; dbt на Trino не умеет читать инкрементально по snapshot | `AvailableNow` каждые 5 минут | Падение посреди MERGE | Iceberg атомарен; checkpoint не сдвинулся; повтор даёт тот же результат (MERGE идемпотентен) |
| Iceberg silver | Текущее состояние таблиц источника + история snapshots | Overwrite всей таблицы каждые 5 минут это small files и нет истории | MoR для `orders` (частые UPDATE), CoW для остальных; решение ADR-007 | Delete files накапливаются | Compaction |
| Trino | SQL над lake для dbt, DQ и людей | Spark SQL медленный на старте и тяжёлый для интерактива | 1 нода, `Xmx` 2-2.5g | OOM на большом join | `query.max-memory-per-node`, лимит на dbt-модель |
| dbt | staging → intermediate → marts, tests, lineage | Ручной SQL не тестируется и не документируется | Batch раз в час | Тест упал → DAG красный, marts не обновлены | Исправить, перезапустить; incremental не ломает историю |
| Airflow | Расписание и зависимости batch-шагов, ретраи, видимость | cron не даёт ретраев, логов, lineage между DAG | Только batch; стрим не оборачивает | Scheduler упал | Restart, недостающие запуски catchup=False |
| Prometheus + Grafana | Lag, freshness, ошибки, ресурсы | Логи не отвечают «сколько отстаём» | Без долгого хранения | Сам мониторинг упал | Не влияет на данные |

---

## 5. Компоненты, версии, образы

Версии проверены 19.09.2026 по официальным источникам. Всё равно первая задача недели 1: `docker compose pull` и фиксация того, что реально скачалось, в `DECISIONS.md`.

| Сервис | Образ / версия | Заметка |
|---|---|---|
| postgres-oltp, postgres-meta | `postgres:17` | 18 вышел в сентябре 2025; 17 безопаснее для Debezium и экспортеров. Проверить поддержку 18 в Debezium 3.5 и при желании поднять |
| kafka | `apache/kafka:4.3.1` | KRaft, single node, `KAFKA_HEAP_OPTS=-Xmx768m` |
| kafka-connect | `quay.io/debezium/connect:3.5` | Docker Hub `debezium/connect` заморожен на 2.7, образы только на quay.io |
| minio | последний community-тег `minio/minio:RELEASE.2025-xx` | Проверить pull; консоли нет, admin через `mc`. Fallback: RustFS или Garage. ADR-004 |
| iceberg catalog | JDBC catalog в `postgres-meta` (W1); `quay.io/lakekeeper/catalog:v0.13.1` (should-have) | Spark: `org.apache.iceberg.jdbc.JdbcCatalog` + postgres driver jar. Trino: `iceberg.catalog.type=jdbc`, драйвер в `plugin/iceberg` (проверить, бандлится ли). Переход на REST через `register_table` |
| spark | `apache/spark:3.5.9` + `iceberg-spark-runtime-3.5_2.12:1.11.0` + `spark-sql-kafka-0-10` | Spark 4.x runtime появился только с Iceberg 1.10, моложе; 3.5 безопаснее. ADR-006 |
| trino | `trinodb/trino:483` | Iceberg connector, `iceberg.catalog.type=rest` |
| dbt | `dbt-core 1.10.x` + `dbt-trino 1.10.3` | Стратегии `append`, `merge`, `delete+insert` |
| airflow | `apache/airflow:3.3.2` | LocalExecutor; api-server + scheduler + dag-processor |
| prometheus, grafana | `prom/prometheus:v3.14.0`, `grafana/grafana:13.2.2` | |
| экспортеры | `danielqsj/kafka-exporter:v1.10.0`, `prometheuscommunity/postgres-exporter`, `prom/statsd-exporter`, `gcr.io/cadvisor/cadvisor` | Версии закрепить при первом pull |
| superset | `apache/superset` (тег 6.1 по digest) | Теги на Docker Hub не semver, пиновать по digest |

Python: 3.12, `uv`, `ruff`, `mypy`, `pytest`, `pydantic-settings`, `psycopg`, `prometheus-client`. SQL: `sqlfluff`. YAML: `yamllint`. Dockerfile: `hadolint`.

---

## 6. RAM-бюджет

Лимиты в `compose.yaml` (`deploy.resources.limits.memory`), ожидаемое реальное потребление ниже. Замерить `docker stats` в неделе 1 и поправить таблицу.

| Сервис | Лимит | Профиль |
|---|---|---|
| postgres-oltp | 768 MB | core |
| postgres-meta | 512 MB | core (Lakekeeper), orchestrate, bi |
| kafka | 1.25 GB | core |
| kafka-connect (heap 1 GB) | 1.5 GB | core |
| minio | 512 MB | core |
| lakekeeper | 256 MB | rest (should-have) |
| spark-bronze (driver `Xmx` 1.5 GB) | 2.5 GB | core |
| oltp-replayer | 256 MB | core |
| **Итого core** | **~7.3 GB** (реально ~5) | |
| trino (`Xmx` 2.5 GB, при orchestrate 2 GB) | 3.5 GB | query |
| airflow: api-server, scheduler, dag-processor | 700 + 600 + 500 MB | orchestrate |
| spark-silver (короткоживущий, `Xmx` 1.5 GB) | 2 GB | запускается Airflow |
| prometheus, grafana, 4 экспортера | ~900 MB | obs |
| superset | 1.2 GB | bi (optional) |
| kafka-ui | 400 MB | tools |

Комбинации: `core+query` ≈ 11 GB лимитов (реально ~7), `core+query+orchestrate+obs` ≈ 14 GB лимитов (реально ~10), что укладывается в `memory=12GB` для WSL2 с учётом того, что лимиты редко достигаются одновременно. Superset и Airflow вместе не запускаются.

`.wslconfig` (в `%USERPROFILE%`):

```
[wsl2]
memory=12GB
swap=8GB
processors=8
```

Диск: Olist в Postgres ~300 MB, bronze за неделю replay ~1-2 GB, silver ~500 MB, Kafka retention 24 ч ~1 GB, образы ~8 GB. Итого ~15 GB на SSD.

---

## 7. Модель данных по слоям

| Слой | Таблицы | Формат | Ключ идемпотентности |
|---|---|---|---|
| OLTP `shop` | customers, sellers, products, orders, order_items, payments, reviews | Postgres | PK |
| Kafka | `oltp.shop.<table>`, 3 партиции, key = PK, retention 24 ч | JSON envelope Debezium | offset |
| bronze | `bronze.cdc_events` (topic, partition, offset, key, op, ts_ms, lsn, source_table, before, after как string, ingest_ts) | Iceberg append, partition `(source_table, day(ingest_ts))` | (topic, partition, offset) |
| silver | `silver.<table>` типизированные, текущее состояние, `_deleted`, `_last_lsn`, `_updated_at` | Iceberg MERGE, MoR для orders | PK + max(lsn) |
| gold (dbt) | `stg_*` views, `int_orders_enriched`, `fct_orders`, `fct_order_items`, `dim_customers`, `dim_products`, `dim_sellers`, `mart_daily_sales` (incremental), `mart_seller_performance`, `mart_delivery_sla` | Iceberg через Trino | dbt `unique_key` |

Bronze и дубли: источников дублей два. Debezium после рестарта (at-least-once) шлёт повторные события с теми же `lsn`, и они честно попадают в bronze как новые Kafka-записи с новыми offsets. Spark-рестарт посреди батча: Iceberg-sink пропускает уже закоммиченный epoch (проверить в chaos 1). Поэтому контракт такой: bronze это at-least-once журнал, дубли в нём допустимы и измеряются метрикой `bronze_duplicate_ratio` по `(source_table, key, lsn)`; silver гарантирует отсутствие дублей.

Late events: silver сравнивает `lsn` входящего события с `_last_lsn` строки и не откатывает более новое состояние. Дубли: `dropDuplicates(["source_table","key","lsn"])` внутри батча плюс сравнение с `_last_lsn` между батчами. DELETE: `op='d'` ставит `_deleted=true` (soft delete в silver, чтобы факты не исчезали из истории); dbt-слой фильтрует.

Schema evolution: bronze не ломается, потому что `after` это строка. Silver job читает схему из `contracts/silver/<table>.json`; новая колонка добавляется через `ALTER TABLE silver.orders ADD COLUMN sales_channel` и правку контракта. Это Modify-гейт недели 2.

---

## 8. Сценарии отказа

Каждый сценарий это `make chaos-<name>` плюс страница в `OPERATIONS.md` с пятью ответами: что произошло, что видит мониторинг, какие данные под угрозой, как восстанавливается, почему нет потерь/дублей или где они возможны.

| # | Сценарий | Команда | Ожидаемый ответ системы |
|---|---|---|---|
| 1 | Spark bronze kill посреди микробатча | `docker kill spark-bronze` | Restart с checkpoint; незакоммиченный батч повторяется. Гипотеза: Iceberg пропускает уже закоммиченный epoch и дублей по (topic, partition, offset) нет; проверить по `snapshots.summary`. Если дубли есть, это фиксируется в OPERATIONS как известное поведение at-least-once bronze; silver в любом случае без дублей |
| 2 | Kafka Connect restart | `docker restart kafka-connect` | Возможны дубли событий (at-least-once); bronze содержит дубли, silver нет |
| 3 | Duplicate events из источника | `REPLAY_DUPLICATE_RATIO=0.1` | Bronze растёт, silver `count(*)` не меняется, DQ-метрика `bronze_duplicate_ratio` растёт |
| 4 | Late events | `REPLAY_LATE_RATIO=0.1 LATE_DELAY=300` | Silver не откатывает `delivered` в `shipped`; watermark-демо в optional job |
| 5 | Postgres restart | `docker restart postgres-oltp` | Коннектор падает и поднимается по retry; slot сохранён; после восстановления LSN продолжается |
| 6 | Коннектор мёртв 30 минут | `make chaos-connect-pause` | `pg_replication_slots.wal_status` и retained WAL растут: алерт `PostgresSlotWalRetained`; после старта догоняет |
| 7 | Corrupted event | `make chaos-poison-event` (ручной produce мусора в топик) | Bronze принимает как есть (строка), silver отправляет в `silver.quarantine` и не падает; алерт по `quarantine_rows` |
| 8 | Kafka down | `docker stop kafka` | Connect и Spark в retry; после старта оба продолжают; проверка `count` до/после |
| 9 (optional) | Airflow task failure (dbt test) | `make chaos-break-dbt-test` | DAG красный, marts не обновлены, предыдущая версия видна; алерт `AirflowDagFailed` |
| 10 (optional) | Partial processing (Trino OOM в dbt) | Лимит памяти Trino вниз | dbt падает на модели, incremental не повреждён; повтор доделывает |

---

## 9. Что осознанно не делается

- Нет multi-node, репликации, ISR. Объясняется словами и в DECISIONS.
- Нет exactly-once producer в Debezium (Connect EOS не включается): показывается, как at-least-once + идемпотентный sink дают корректный итог.
- Нет Schema Registry до недели 6.
- Нет Superset в обязательной части: витрины смотрятся в Grafana через Trino datasource.
- Нет секретов в git; `.env` генерируется `make secrets`, порты только на `127.0.0.1`.
- Нет agent-зоопарка: один `CLAUDE.md`, при желании два субагента (`reviewer`, `mentor`) в `.claude/agents/`.
- Нет ClickHouse, k8s, Terraform, Ansible: возвращаются во «второй фазе» на сервере, когда/если он появится. Большой план в соседнем репозитории остаётся картой этой фазы.

---

## 10. Открытые вопросы для владельца

1. Лицензия Olist: проверить на Kaggle перед тем, как класть сэмпл в публичный репо. Если нельзя, сэмпл генерируется из полного датасета локально, а в git лежит только скрипт.
2. MinIO vs RustFS/Garage: решить после `docker pull` в W1. Ключевое слово в вакансиях «S3», а не «MinIO».
5. Trino JDBC catalog: бандлится ли postgres-драйвер в `plugin/iceberg` образа 483. Если нет, положить jar в образ (одна строка Dockerfile) или сразу идти в REST.
3. Название репозитория: `de-lakehouse-mini` или доменное, например `marketplace-lakehouse`. Доменное лучше читается в портфолио.
4. Язык docs: README и публичные документы на английском, planning-документы на русском. Подтвердить.
