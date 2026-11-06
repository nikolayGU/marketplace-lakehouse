# Локальные интерфейсы: как самому пройти стенд от Postgres до дашборда

Часть аудита 06.11.2026 (`AUDIT_REPORT.md`). Все адреса взяты из `docker/compose.yaml` и
`docker ps`, а не из стандартных портов; HTTP-статусы сняты 06.11 13:19-13:40 UTC на HEAD
`f7eede8`. «200» значит только, что сервис ответил; что работает функция, подтверждает столбец
«Проверка функции». Визуально в браузере страницы не открывались: подтверждена HTTP- и
API-доступность и результат запросов.

Все порты опубликованы только на `127.0.0.1` (`${BIND_IP:?}` в compose, `.env.example:4`).
Пароли лежат в `.env` (его генерирует `make secrets`); здесь только имена переменных.

## 1. Сводная таблица

| Сервис | Адрес | Тип | Статус 06.11 | Вход | Конфигурация | Проверка функции |
|---|---|---|---|---|---|---|
| Airflow 3.3.2 | http://127.0.0.1:8090 | Web UI + REST `/api/v2` | 200; `/api/v2/monitor/health` 200 | без логина, все админы (`AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_ALL_ADMINS=True`) | `docker/airflow/airflow.env`, `airflow/dags/` | 5 DAG, 0 import errors; `silver_upsert` success каждые 5 мин; run 12:10 06.11: `merge` try 2 success |
| Grafana 13.2.2 | http://127.0.0.1:3000 | Web UI | `/api/health` 200, `/api/search` 401 без входа | `admin`, пароль `GRAFANA_ADMIN_PASSWORD` из `.env` (`OPERATIONS.md:594-595`) | `observability/grafana/` | плагин `trino-datasource@1.4.1` зарегистрирован (лог 11:52); SQL всех панелей от пользователя `grafana`: `queries ok: 39`; рендер панелей в браузере не проверен |
| Prometheus 3.14 | http://127.0.0.1:9090 | Web UI + API | `/-/healthy` 200 | без входа | `observability/prometheus/` | 8 из 8 targets `up`, 15 правил (12 имён), активных алертов 0 |
| Trino 483 | http://127.0.0.1:8080/ui/ | Web UI + HTTP API + CLI | 200, title `Trino` | в форме любое имя пользователя, пароля нет; права по имени (`docker/trino/etc/rules.json`) | `docker/trino/etc/` | SELECT по bronze, silver, gold выполняются; `make trino` открывает CLI |
| Spark UI, `bronze_cdc_ingest` | http://127.0.0.1:4040 | Web UI | 302 на `/jobs/`; `/StreamingQuery/` 200 | без входа | `streaming/` | приложение `bronze_cdc_ingest` с 11:52:31, `spark_streaming_kafka_lag` 0 по всем партициям |
| Метрики bronze | http://127.0.0.1:4041/metrics | Prometheus text | 200 | без входа | `streaming/spark_jobs/metrics.py` | `spark_streaming_last_batch_timestamp` моложе 120 с |
| Spark UI, `orders_per_minute` | http://127.0.0.1:4043 | Web UI | 302 на `/jobs/` | без входа | профиль `stateful` | приложение запущено с 11:52:31 |
| Spark UI, `silver_upsert` | http://127.0.0.1:4042 | Web UI | нет соединения | без входа | только пока идёт `make silver`; merge из Airflow порт не публикует | не проверено (запуск `make silver` запрещён без «ок») |
| Kafka Connect (Debezium 3.5.2) | http://127.0.0.1:8083/connectors?expand=status | REST | 200 | без входа | `connect/shop-connector.json` | коннектор и задача `RUNNING`; offset в `connect-offsets` равен `confirmed_flush_lsn` слота |
| Lakekeeper 0.13.6 | http://127.0.0.1:8181/ui/ | Web UI + REST | `/health` 200, `/ui/` 200 (title `Lakekeeper`) | без аутентификации | `docker/compose.yaml` (сервис `lakekeeper`) | warehouse `lake` active; namespaces bronze, silver, gold, demo; 1 + 9 + 9 + 3 таблиц. UI в документации проекта не описан |
| MinIO (S3 API) | http://127.0.0.1:9000 | S3 API | `/minio/health/live` 200; `/` 403 | ключи `S3_ACCESS_KEY` / `S3_SECRET_KEY` из `.env` | `docker/minio/` | 169 файлов данных пяти таблиц из метаданных Iceberg все на диске MinIO |
| MinIO Console | недоступна | Web UI | браузер на `:9000` получает 307 на `127.0.0.1:46311`, порт не опубликован | нет | консоль убрана по ADR-004 (`DECISIONS.md:51,58`), управлять через `mc` | см. FINDING F-07 |
| PostgreSQL источник | 127.0.0.1:5432, БД `shop` | SQL | healthy | `OLTP_USER` / `OLTP_PASSWORD`; проще `make psql` | `oltp/`, команда в compose | `wal_level=logical`, слот `shop_slot` active, публикация `shop_publication` |
| PostgreSQL meta | 127.0.0.1:5433 | SQL | healthy | `META_USER` / `META_PASSWORD` | `docker/postgres-meta/init` | базы Lakekeeper, Airflow, JDBC-каталога отката |
| Kafka 4.3.1 | 127.0.0.1:9092 (host listener) | протокол Kafka, CLI | healthy | без аутентификации | compose, сервис `kafka` | `make kafka-topics` (внутри контейнера); 7 топиков `oltp.shop.*` по 3 партиции. Клиент с хоста не подключится: брокер объявляет `localhost:29092`, который не опубликован (F-20) |
| kafka-ui | http://127.0.0.1:8085 | Web UI | не запущен (профиль `tools`) | без входа | compose, сервис `kafka-ui` | не проверено: запуск контейнера требует «ок» владельца |
| Superset 6.1.0 | http://127.0.0.1:8088 | Web UI | не запущен (профиль `bi`) | `SUPERSET_SECRET_KEY` в `.env` | монтирует `docker/superset/superset_config.py`, файла нет | не запускается, см. FINDING F-02 |
| Реплеер | http://127.0.0.1:8000 | `/health`, `/metrics`, `/status` | не запущен | без входа | `oltp/replayer/server.py` | только при `make replay-live` (тратит бюджет реплея) |
| dbt | нет UI | CLI | `dbt debug`: All checks passed | профиль `dbt/profiles.yml`, пользователь Trino `dbt` | `dbt/` | `dbt test` 06.11: PASS=61 WARN=4 ERROR=0 |

Пароли и ключи в этот документ не выписаны намеренно.

## 2. Порядок самостоятельного изучения

1. Docker запущен: `docker version`, затем `make status` (это `docker compose --profile '*' ps`).
   Ожидается 18 контейнеров `healthy` (core, query, orchestrate, obs, stateful). Короткая сводка:
   `make report` (git, отметки, контейнеры, часы реплея; только чтение).
2. Все сервисы разом: `make verify-fast` (только чтение: bronze догнал Kafka, offsets без дублей
   и дыр, сверка Postgres и silver по 7 таблицам). Если не хочется трогать отметку verify, то же
   по частям: `make reconcile` (сверка) и запросы из шагов 4-8.
3. С чего начать: Airflow http://127.0.0.1:8090. Там видно, что делает платформа сама:
   `silver_upsert` каждые 5 минут, `dq_checks` каждые 15, `dbt_build` по Asset `lake.silver`,
   `iceberg_maintenance` в 03:30. Затем Grafana http://127.0.0.1:3000, дашборды Pipeline health
   (лаг, свежесть, слот) и Marketplace (бизнес-витрины).
4. CDC: `make connector-status` или http://127.0.0.1:8083/connectors?expand=status (оба
   `RUNNING`); слот в Postgres:
   `make psql`, затем `select slot_name, active, confirmed_flush_lsn from pg_replication_slots;`.
5. Kafka: `make kafka-topics` (топики и партиции). Последние события таблицы:
   `docker exec lakehouse-kafka-1 /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic oltp.shop.orders --partition 0 --offset <N> --max-messages 5 --formatter-property print.key=true`
   (с `--partition` и `--offset` консьюмер не создаёт группу; с `--from-beginning` без партиции
   создаёт пустую группу `console-consumer-*`). Отставание Spark смотреть не в `make kafka-groups`
   (Spark не коммитит offsets в группы, а группа Connect `connect-lakehouse` имеет тип `connect`
   и видна только в `kafka-groups.sh --list`; см. F-28), а в
   http://127.0.0.1:4041/metrics (`spark_streaming_kafka_lag`) или на дашборде Pipeline health.
6. Spark: http://127.0.0.1:4040, вкладка Structured Streaming (`/StreamingQuery/`): батчи раз в
   20 с, input rows. Silver-merge идёт в коротком контейнере `lakehouse-silver-merge` из Airflow:
   его лог в Airflow, задача `merge` DAG `silver_upsert`.
7. Iceberg и MinIO: каталог http://127.0.0.1:8181/ui/ (Lakekeeper) или REST
   `curl -s http://127.0.0.1:8181/management/v1/warehouse`. Файлы таблиц через Trino:
   `select file_path, record_count from silver."orders$files"`; снапшоты:
   `select * from bronze."cdc_events$snapshots" order by committed_at desc limit 5`. Сами объекты
   на диске MinIO (консоли нет): `docker exec lakehouse-minio-1 ls /data/lakehouse/warehouse/silver/orders/data`.
8. SQL в Trino: `make trino` (каталог `lake`), затем `show schemas; select count(*) from silver.orders;`
   UI http://127.0.0.1:8080/ui/ показывает кластер и историю запросов; сам SQL удобнее в CLI.
9. dbt: `cd dbt && uv run dbt debug --profiles-dir . --target dev`, `dbt ls`, `dbt test` (только
   SELECT). `make dbt-build` пишет в `lake.gold`: при DAG `dbt_build` не на паузе его гоняет
   Airflow. Документация моделей: `make dbt-docs` собирает в `dbt/target`; `dbt docs serve` по
   умолчанию берёт порт 8080, который занят Trino, поэтому `--port 8081`.
10. Airflow DAG: http://127.0.0.1:8090, DAG `silver_upsert` (граф: `bronze_has_new_snapshot`,
    `merge`, `remember_snapshot`), `dq_checks` (лог задачи `reconcile_values`: строки
    `reconcile_values_differing{...}=0`), `dbt_build`.
11. Дашборд: Grafana http://127.0.0.1:3000, вход `admin`, дашборд Marketplace (uid
    `marketplace`, 4 панели: продажи по дням, GMV по категориям, SLA доставки по штатам, отмены).
    Источник: Trino, каталог `lake_ro`, пользователь `grafana`, только витрины `fct_*`, `dim_*`,
    `mart_*`. Superset в этом стенде нет: профиль `bi` не стартует (F-02).

## 3. Что посмотреть, чтобы самому повторить сквозную трассу аудита

Аудит прошёл один заказ и одно удаление отзыва через все слои (раздел 4 `AUDIT_REPORT.md`).
Повторить на тех же ключах можно только чтением:

```bash
# Postgres
docker exec lakehouse-postgres-oltp-1 psql -U shop -d shop -X -c \
  "select order_id, order_status from shop.orders where order_id='1723f84b8a70b486955d59dad4bed0f2'"
# bronze, silver, gold
docker exec lakehouse-trino-1 trino --catalog lake --execute \
  "select kafka_offset, op, lsn, ingest_ts from bronze.cdc_events where topic='oltp.shop.orders' and kafka_partition=0 and kafka_offset in (77464, 77465)"
docker exec lakehouse-trino-1 trino --catalog lake --execute \
  "select order_status, _last_lsn, _updated_at from silver.orders where order_id='1723f84b8a70b486955d59dad4bed0f2'"
docker exec lakehouse-trino-1 trino --catalog lake --execute \
  "select order_status, purchase_date, payment_value from gold.fct_orders where order_id='1723f84b8a70b486955d59dad4bed0f2'"
```

Kafka держит события 24 часа (`KAFKA_RETENTION_HOURS=24`): после 07.11 ~12:06 UTC эти три
сообщения (два по заказу, одно удаление отзыва) из топиков уйдут, bronze, silver и gold их сохранят.
