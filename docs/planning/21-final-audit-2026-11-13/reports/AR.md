# AR. Архитектура и ADR

Дерево: HEAD `a8c1d49` плюс незакоммиченные правки владельца (`git status --short`: `M .github/workflows/ci.yml`,
`M OPERATIONS.md`, `M docs/HANDOFF.md`, `M docs/NEXT_SESSION.md`, `M tests/unit/test_workflows.py`,
`?? docs/planning/21-final-audit-2026-11-13/`). Агент ничего не менял в репозитории и на стенде.
Рабочие файлы: `<scratchpad>/audit/AR-work/adr-sizes.txt`.

## Оценки

- Архитектор: 4 из 5. Решения обоснованы, у большинства есть альтернативы и измеренная цена
  (`DECISIONS.md:339-349`, таблица MoR против CoW); минус: 8 ADR только строкой, ADR-014 и ADR-017
  устарели, нет ADR на Superset/MCP, `lake_ro`, gold и модель безопасности; формулировка
  exactly-once местами завышена (AR-03).
- Руководитель: 3 из 5. Цена владения и риски названы по частям (OPERATIONS «Backup»,
  `OPERATIONS.md:1768-1797`; ADR-026 о MinIO), но сводного «Production gap» нет, а три главных
  риска (архивный MinIO, pre-1.0 Lakekeeper без отката образа, нет бэкапа) разбросаны по 60 KB
  DECISIONS.
- Тимлид, нанимающий (часть AR): 3 из 5. DECISIONS 62.9 KB (`wc -c DECISIONS.md` = 62890) за
  30 минут не читается; ADR-005 один 14.8 KB журнала. После сжатия и Production gap будет 4.

## Сильные стороны

- Гарантии доставки разложены по стыкам и доказаны числами, а не заявлены: «No single component
  is exactly-once» (`ARCHITECTURE.md:124`); bronze offsets без дыр и повторов
  (`scripts/chaos/lib.sh:211-227`), MERGE с LSN-guard (`streaming/spark_jobs/silver_upsert.py:153-167`),
  сверка с источником по отпечатку всех колонок (README «Data quality», `README.md:201-209`).
- Решения с измеренным компромиссом: MoR против CoW для `silver.orders` (`DECISIONS.md:339-349`:
  5.7 MB против 78 KB на батч), выбор Spark-джоба для обслуживания вместо Trino по возможностям
  процедур (`DECISIONS.md:717-719`).
- Правила политики данных в коде, а не только в документе: `expire_snapshots` на bronze
  отказывает до старта Spark (`streaming/spark_jobs/maintenance.py:67-76`), сироты bronze только в
  `metadata` (`maintenance.py:80-84`).
- Понимание blast radius каталога: Lakekeeper трактует REST `DELETE` без `purgeRequested` как purge,
  поэтому защита таблиц и soft delete (`DECISIONS.md:116-127,139-145`).
- Честная работа с исчезающей зависимостью: MinIO собирается из исходников тега с проверкой SHA
  коммита (`docker/minio/Dockerfile:14-18`), `pull_policy: never` против чужого namespace
  (`docker/compose.yaml:7-10,162`).
- Свой экспортер и listener там, где стандартный инструмент слеп: lag Spark (ADR-013,
  `streaming/spark_jobs/metrics.py:23-41`), cAdvisor на containerd (ADR-023, 226 строк Python).
- Честный список недоказанного: `docs/evidence.md:271-285`, таблица бэкапов
  `OPERATIONS.md:1779-1797` («Restore tested: no»).

## Таблица ADR

Размер: байты раздела `## ADR-NNN` до следующего (скрипт в `AR-work/adr-sizes.txt`). «Только
строка»: есть строка в индексе `DECISIONS.md:6-33`, раздела нет. К/А/П: контекст, альтернативы,
последствия (да, нет, неявно). Сверка: два утверждения ADR против кода.

| ADR | Название | Статус в индексе | KB | К/А/П | Утверждение 1 | Утверждение 2 | Вердикт |
|---|---|---|---|---|---|---|---|
| 001 | Olist replay | accepted | 0.8 | да/неявно/да | 80% bulk: `oltp/replayer/settings.py:30` `replay_initial_share = 0.8`, совпало | `REPLAY_DATA` по умолчанию `raw`: `settings.py:44`, совпало | исправить: `DECISIONS.md:41-42` «license must be checked before shipping a sample» устарело, лицензия названа в `README.md:229-234` |
| 002 | Two PostgreSQL | accepted | только строка | нет | `postgres-oltp` `docker/compose.yaml:38`, `postgres-meta` `:541`, совпало | в `postgres-meta` базы `airflow, iceberg_catalog, lakekeeper, meta, superset` (живой `psql`), строка ADR этого не говорит | оставить строку; дописать «postgres-meta holds Lakekeeper, Airflow, Superset» |
| 003 | Kafka KRaft 1 broker | accepted | только строка | нет | RF 1, 3 партиции: `connect/register.sh:40`, `.env.example:29`, совпало | retention 24 h `.env.example:28`, совпало; но есть ещё `KAFKA_LOG_RETENTION_BYTES: 2147483648` `docker/compose.yaml:85`, ADR молчит | исправить: короткий раздел (3-4 строки) с retention.bytes |
| 004 | Object storage | accepted, источник образа superseded ADR-026 | 1.2 | да/да/да | «removed the web console», «there is no console» `DECISIONS.md:51,58`: не совпало, консоль `--console-address :9001` `docker/compose.yaml:164,172` | «last community release 2025-09-07» `DECISIONS.md:54`: не совпало, есть тег `RELEASE.2025-10-15T17-29-55Z` (`git ls-remote`, AR-01) | исправить и сжать до 0.6 KB (образ ушёл в ADR-026) |
| 005 | Catalog JDBC then REST | accepted | 14.8 | да/да/да | `CATALOG_TYPE` по умолчанию `rest`: `streaming/spark_jobs/settings.py:18`, совпало | Trino без vended credentials: `docker/trino/etc/catalog/lake.properties:8`, совпало | сжать до 2-2.5 KB: `:81-93`, `:162-192`, `:204-223` в evidence; `:187-192` удалить (устарело) |
| 006 | Spark 3.5 + Iceberg 1.11, local[2] | accepted | только строка | нет | `apache/spark:3.5.9` и `iceberg-spark-runtime-3.5_2.12/1.11.0`: `streaming/Dockerfile:1,15`, совпало | `SPARK_MASTER=local[2]` `.env.example:46`, `streaming/run-job.sh:9`, совпало | исправить: раздел 4-5 строк (запечённый образ, статус версии) |
| 007 | Bronze append, silver MERGE | accepted | 3.3 | да/неявно/да | триггер 20 s: `settings.py:32`, `bronze_cdc_ingest.py:144`, совпало | метрика `lakehouse_dq_lsn_repeats_last_hour`: `airflow/dags/dq_checks.py:402`, совпало | сжать до 1.8 KB: `:285-308` в evidence; `:285` «Verified» согласовать с `ARCHITECTURE.md:128-131` (AR-03) |
| 008 | Bronze JSON text | accepted | 1.0 | да/нет/да | `partitioned by (source_table, days(ingest_ts))`: `bronze_cdc_ingest.py:65`, совпало | format v2: `bronze_cdc_ingest.py:66`, совпало | оставить |
| 009 | Soft deletes `_is_deleted` | accepted | только строка | нет | staging отдаёт `_is_deleted as is_deleted`: `dbt/models/staging/stg_orders.sql:10`, совпало | фильтр у потребителя: `dbt/models/marts/dim_customers.sql:11`, совпало | оставить строку |
| 010 | silver.orders MoR | accepted, measured | 2.3 | да/да/неявно | свойства MoR и `file` granularity: `silver_upsert.py:35-39`, совпало | `months(order_purchase_timestamp)`: `silver_upsert.py:41`, совпало | сжать до 1.5 KB: таблица `:341-347` и числа `:352-354` в evidence |
| 011 | Airflow 3 LocalExecutor | accepted | 2.6 | да/да/да | `parallelism` 2: `docker/airflow/airflow.env:6`; лимит 900M `docker/compose.yaml:626`, совпало | `dq_checks` каждые 15 мин: `airflow/dags/dq_checks.py:85`, совпало | сжать до 2.0 KB: `:391-394` (неделя 3) удалить, `:390` «owner's Modify gate» убрать; добавить строку про Asset и паузу |
| 012 | No Schema Registry | accepted | только строка | нет | `JsonConverter`, `schemas.enable=false`: `connect/shop-connector.json:23-26`, совпало | «until week 6» `DECISIONS.md:19`: устарело, неделя 6 прошла, реестра нет | исправить: раздел 4 строки (почему JSON, альтернатива Avro/Protobuf + Apicurio/Karapace) |
| 013 | Spark metrics listener | accepted | 1.8 | да/да/да | `spark_streaming_kafka_lag` и др.: `streaming/spark_jobs/metrics.py:23-41`, совпало | kafka-exporter отвергнут для lag: в compose он есть только для брокера (`docker/compose.yaml:710-733`), совпало | сжать до 1.2 KB (`:410-421`) |
| 014 | Superset optional, Grafana | accepted | только строка | нет | «marts are shown through Grafana»: не совпало, Superset в `bi` с дашбордом из 13 графиков (`docker/superset/dashboards/charts/`, 13 файлов; `Marketplace.yaml` 13 `chartId`) и MCP (`docker/compose.yaml:891-925`) | «optional»: совпало (профиль `bi`, `docker/compose.yaml:814`) | пометить superseded by ADR-027 |
| 015 | Removed: ClickHouse, k8s ... | accepted | только строка | нет | нет сервиса Alertmanager (`config --services` по всем профилям), совпало | нет Cosmos: dbt через BashOperator `airflow/dags/dbt_build.py:9,24`, совпало | оставить; дописать «no DQ framework» (см. список решений) |
| 016 | Compose profiles | accepted | 1.3 | да/да/да | `make start` = `spark-bronze kafka-connect trino`: `Makefile:36-37`, совпало | `make up` отказывает с `core`: `Makefile:39-41`, совпало | исправить: список профилей `DECISIONS.md:425-426` без `stateful` и `jobs` (`docker/compose.yaml:356,414`) |
| 017 | Stateful job mandatory | accepted | только строка | нет | дубль ADR-024 | дубль ADR-024 | пометить superseded by ADR-024 |
| 018 | REPLICA IDENTITY FULL | accepted | 1.4 | да/да/да | все 7 таблиц: `oltp/migrations/001_schema.sql:98-104`, совпало | алерт `SlotWalRetainedHigh`: `observability/prometheus/alerts.yml:19`, совпало | оставить (сжать до 1.0 KB по желанию) |
| 019 | Incremental snapshots | accepted | 2.6 | да/неявно/да | `signal.data.collection = cdc.debezium_signal`: `connect/shop-connector.json:19`, совпало | таблица в своей схеме и в публикации: `oltp/migrations/002_debezium_signal.sql:8,15`, совпало | сжать до 2.0 KB |
| 020 | Silver contracts, timestamps | accepted | 2.0 | да/нет/да | `smallint` в `int`: `tests/unit/test_contracts.py:39`, совпало | `decimal.handling.mode=double`: `connect/shop-connector.json:21`, совпало | исправить: строка альтернатив (`precise`, `string`) |
| 021 | Silver upsert | accepted | 2.6 | да/нет/да | guard `t._last_lsn is null or s._last_lsn > t._last_lsn`: `silver_upsert.py:158`, совпало | shuffle 4: `settings.py:43`, совпало | оставить (2.2 KB) |
| 022 | `source.sequence` в bronze | accepted | 1.5 | да/неявно/да | колонка после `lsn`: `bronze_cdc_ingest.py:55`, совпало | silver упорядочивает по `lsn`: `silver_upsert.py:140-144`, совпало | оставить (1.0 KB) |
| 023 | Observability sources | accepted | 4.4 | да/да/да | container-exporter «about 200 lines»: 226 строк (`wc -l`), лимит 128M `docker/compose.yaml:803`, совпало | JMX agent 1.6.0 с sha256: `docker/connect/Dockerfile:6-8`, совпало | сжать до 2.3 KB: `:629-643` в evidence |
| 024 | orders_per_minute | accepted | 3.4 | да/да/да | профиль `stateful`, 1792M: `docker/compose.yaml:356,403`, совпало | shuffle 2: `settings.py:55`, `orders_per_minute.py:132`, совпало | сжать до 2.2 KB: `:676-692` в OPERATIONS «Stateful job» ссылкой |
| 025 | Maintenance policy | accepted | 5.2 | да/да/да | отказ expire bronze: `maintenance.py:67-71`, совпало | ежедневно 03:30: `airflow/dags/iceberg_maintenance.py:36`, совпало | сжать до 2.5 KB: `:749-761` уже есть в `docs/evidence.md:87`, заменить ссылкой; `:733,737-739` без «ladder», «ok» |
| 026 | MinIO from source | accepted (единственный со `Status:`) | 5.2 | да/да/да | проверка SHA коммита: `docker/minio/Dockerfile:14-18`, совпало | `golang:1.24.6-bookworm@sha256`, `alpine:3.22@sha256`: `Dockerfile:8,58`, совпало | сжать до 2.5 KB: `:765-767` (ревью, вердикт) убрать, `:792-807` до 3 строк, `:820-828` откат в OPERATIONS; дописать тег 2025-10-15 и CVE |

Противоречия между ADR:
- ADR-014 против фактического Superset (`docker/compose.yaml:807-925`) и `ARCHITECTURE.md:116-120`.
- ADR-017 и ADR-024 описывают одно решение.
- ADR-004 («no console», «mc as the console» в ADR-026 `DECISIONS.md:768`) против
  `docker/compose.yaml:164,172`.
- ADR-007 `DECISIONS.md:285-293` («Verified ... So bronze is exactly once across Spark restarts»)
  против `ARCHITECTURE.md:128-131` («the skip ... is reproduced by test, not by a live run»).
- ADR-005 `DECISIONS.md:257-264` (точка отката отпущена 29.10) против комментариев compose
  `docker/compose.yaml:204-205,509,539-540` («kept as the rollback point», «JDBC rollback catalog»).
- ADR-016 `DECISIONS.md:425-426` и `ARCHITECTURE.md:140-143` перечисляют 6 профилей; в compose их 8
  (`core, query, orchestrate, obs, bi, tools, stateful, jobs`).

## Целевой вид DECISIONS (не больше 35 KB)

Сейчас 62 890 байт. Правило: ADR не больше 2.5 KB; «Context / Decision / Alternatives /
Consequences», дата решения одной строкой; замеры и журналы проверок ссылкой на
`docs/evidence.md#decision-measurements` (новый раздел) или на существующий раздел OPERATIONS; без
ID карточек кроме даты, без «owner's ok», «gate», «ladder», «verdict».

| Блок | Сейчас | Цель | Что вынести (строки `DECISIONS.md`) | Куда |
|---|---|---|---|---|
| шапка и индекс | `:1-33`, 3.9 KB | 2.6 KB | строки индекса до одной фразы (`:11-32` до 100 символов); `:4` ссылка на `00-mini-architecture-review.md` (ru) заменить на ARCHITECTURE | нет |
| ADR-004 | 1.2 | 0.6 | `:51-56` проверка quay 21.09 | удалить (история в ADR-026) |
| ADR-005 | 14.8 | 2.2 | `:81-93` JDBC и Trino 483; `:162-185` side by side; `:204-223` cutover; `:187-192` удалить | evidence «Catalog cutover» (новый подраздел) |
| ADR-007 | 3.3 | 1.8 | `:285-308` числа chaos 1 и 2b | evidence «Failure scenarios» (там уже есть сценарии, `docs/evidence.md:63`) |
| ADR-010 | 2.3 | 1.5 | `:339-354` таблица и числа optimize | evidence «Decision measurements» |
| ADR-011 | 2.6 | 2.0 | `:391-394` удалить (заменено ADR-025), `:371-372` пик 579 MiB в evidence | evidence |
| ADR-013 | 1.8 | 1.2 | `:410-421` до 3 строк | нет |
| ADR-019 | 2.6 | 2.0 | `:480-488` сжать | нет |
| ADR-023 | 4.4 | 2.3 | `:629-631` WAL burst, `:633-643` инцидент chaos 6 | evidence «Failure scenarios», сценарий 6 |
| ADR-024 | 3.4 | 2.2 | `:676-692` факты 23.10 | ссылка `OPERATIONS.md#stateful-job` |
| ADR-025 | 5.2 | 2.5 | `:749-761` первый запуск | ссылка `docs/evidence.md#maintenance-before-and-after` |
| ADR-026 | 5.2 | 2.5 | `:765-767` ревью; `:792-807` до 3 строк; `:820-828` откат | откат в `OPERATIONS.md` раздел MinIO |
| ADR-018, 020, 022, 016 | 6.2 | 4.6 | сжать по 0.3-0.5 | нет |
| новые ADR-027..030 и разделы 003, 006, 012 | 0 | 4.5 | черновики ниже | нет |

Итог по плану около 34-35 KB. Проверка: `wc -c DECISIONS.md` не больше 35840 и скрипт из
`AR-work/adr-sizes.txt` (ни один раздел больше 2.5 KiB).

## Решения без ADR

| Решение (код) | Нужен ADR или строка | Где |
|---|---|---|
| Superset 6.1 + MCP, admin без входа на loopback (R-61) | ADR-027, заменяет ADR-014 | `docker/compose.yaml:807-925`, `docker/superset/superset_config.py:33-37` |
| `lake_ro` и file ACL Trino (R-61) | ADR-028 | `docker/trino/etc/rules.json`, `catalog/lake_ro.properties:9` |
| Модель безопасности ноутбука: loopback, без аутентификации, общие root-ключи S3, docker.sock | ADR-029 (сводит куски ADR-005 (c), «No authentication» `:245-247`, ADR-011 `:378-383`, ADR-023 `:611-612`, которые потом удалить) | `docker/compose.yaml:1-2`, `airflow.env:11`, `compose.yaml:616,793` |
| Gold: dbt на Trino, таблицы `CREATE OR REPLACE`, один incremental `delete+insert` | ADR-030 | `dbt/dbt_project.yml:18-26`, `dbt/models/marts/mart_daily_sales.sql:4-9` |
| Airflow 3, LocalExecutor | строка не нужна, ADR-011 | `airflow.env:3` |
| Asset-расписание и потеря события при паузе DAG | строка в ADR-011 | `airflow/dags/dbt_build.py:15`, `ARCHITECTURE.md:92-96` |
| StatsD, statsd-exporter | есть в ADR-023 `:623-627` | |
| container-exporter | есть в ADR-023 `:596-603` | |
| Сборка MinIO | есть в ADR-026; дописать строку про тег 2025-10-15 (AR-01) | |
| Запечённый образ Spark (код джобов в образе, один образ на 5 ролей, `pull_policy: never`) | строка в разделе ADR-006 | `streaming/Dockerfile:33-37`, `docker/compose.yaml:261,295,354,411` |
| Политика пинов: реестровые образы по digest, свои без digest и не тянутся | строка в ADR-026 | `docker/compose.yaml:7-10` |
| Нет DQ-фреймворка (Great Expectations, Soda): dbt tests плюс `dq_checks` против источника | строка в ADR-015 | `airflow/dags/dq_checks.py` |
| Деньги на проводе `double` | строка альтернатив в ADR-020 | `connect/shop-connector.json:21` |
| Kafka `retention.bytes` 2 GiB на партицию, внутренние топики Connect RF 1 | раздел ADR-003 | `docker/compose.yaml:85,123-125` |

Черновики (английский, для вставки в DECISIONS; номер и дата при вставке):

```text
## ADR-027 Superset as the BI layer, with an MCP endpoint (supersedes ADR-014)
Context: ADR-014 left Superset optional and showed the marts in Grafana. A business reader expects
cross-filters, period comparison and named metrics; an agent needs a programmatic way to query and
build charts.
Decision: Superset 6.1.0 in profile `bi` (base image by digest plus pinned drivers), metadata in
`postgres-meta`, the `Marketplace` dashboard as code in `docker/superset/dashboards/`, imported by
`superset-init` with overwrite (the bundle wins over UI edits). It reads only the `lake_ro.gold`
marts as Trino user `superset` (ADR-028), `allow_dml: false`. `superset-mcp` serves Superset's MCP
service on 127.0.0.1:5008; every tool runs as `admin` (`MCP_DEV_USERNAME`), Host and Origin are
checked against DNS rebinding. The UI has a login, MCP has none.
Alternatives: Grafana only (no metric layer, no cross-filters); Metabase or Evidence (another
stack, no MCP); MCP with JWT auth (`MCP_AUTH_ENABLED`, an identity provider for one user).
Consequences: two long-running services (1280M + 512M); any local process can change Superset
metadata through MCP, not data; UI edits are lost on re-import; the Grafana `Marketplace`
dashboard stays as a light view of the same marts.
```

```text
## ADR-028 Read-only BI access: catalog `lake_ro` and Trino file-based access control
Context: Trino has no authentication here. Dashboards must not write, must not read silver, and
file-based access control has no privilege for table procedures such as `expire_snapshots`.
Decision: `lake_ro` is a twin of `lake` (same Lakekeeper, warehouse and S3 keys) with
`iceberg.security=read_only`. `rules.json` gives the users `grafana` and `superset` SELECT on
`lake_ro.gold.(fct|dim|mart)_*` only, no other catalog, no procedures, no system information;
every other user keeps full rights. Rules load on restart only.
Alternatives: Trino authentication (password file, OAuth2) with the same rules; Lakekeeper
authorization (OpenFGA) with vended credentials; separate read-only MinIO keys for `lake_ro`.
Consequences: protects against mistakes, not against a local attacker: the user name is a label.
`lake_ro` still holds the root S3 keys. dbt views over silver (`stg_*`) are hidden from BI.
```

```text
## ADR-029 Local security model
Context: one user on one laptop, no data worth protecting; each auth system costs memory and setup.
Decision: every published port is bound to `BIND_IP` (127.0.0.1; compose refuses an empty value).
No authentication in Kafka, Connect, Lakekeeper (`allow-all`), Trino, Airflow (every user is
admin) and Superset MCP; Superset UI and Grafana use generated passwords. Secrets live only in
`.env`, generated by `make secrets` and never committed. One MinIO root key pair is shared by
Spark, Trino and Lakekeeper. The Airflow scheduler and container-exporter hold the Docker socket.
Alternatives: Docker secrets; a socket proxy; per-service MinIO users and policies; OIDC
(Keycloak) for Trino, Lakekeeper, Airflow and Superset.
Consequences: any local process, or an escape from any container with the socket, owns the stack.
Nothing may be exposed beyond loopback without the items of "Production gap".
```

```text
## ADR-030 Gold: dbt on Trino, tables per run, one incremental mart
Context: gold is derived from silver and can always be rebuilt. dbt-trino's default `rename`
drops a backup table on every run, and on Lakekeeper a drop is a soft delete that keeps files.
Decision: staging and intermediate models are views, marts are tables written with
`CREATE OR REPLACE` (`on_table_exists: replace`). `mart_daily_sales` is incremental
`delete+insert` by `purchase_date` and re-selects every date with an order changed since the
mart's watermark. dbt runs after each silver merge (Asset `lake.silver`), in pool `gold_writers`
with gold maintenance. Gold is not protected and keeps 7 days of snapshots (ADR-025).
Alternatives: `merge` increments everywhere; a full rebuild of `mart_daily_sales` as well.
Consequences: `delete+insert` is two commits, so a reader can see a date missing between them;
marts agree with each other per dbt run, not per query; recovery is a rebuild from silver.
```

Строки в существующие ADR (английский):
- ADR-003: `Retention is 24 h or 2 GiB per partition, whichever comes first (compose
  KAFKA_LOG_RETENTION_BYTES); Connect's internal topics have RF 1.`
- ADR-006: `Job code is baked into lakehouse/spark:dev, one local image for bronze, silver, the
  stateful job, Lakekeeper bootstrap and maintenance; a code change needs a rebuild. Spark 3.5 is
  the last 3.x line and gets security fixes only; Spark 4 is a separate migration.`
- ADR-011: `Airflow 3.3 queues no Asset event for a paused DAG; GoldStaleAtRest covers it.`
- ADR-012 (раздел): `JSON envelopes keep every tool (kcat, Trino, Python) able to read a record;
  contracts live in contracts/ as JSON Schema. Alternative: Avro or Protobuf with a registry
  (Apicurio, Karapace): typed evolution, one more service.`
- ADR-015: `No data quality framework (Great Expectations, Soda): dbt tests plus dq_checks, which
  reconcile against the source.`
- ADR-020: `Alternatives for decimals on the wire: precise (base64 bytes, unreadable in tools) or
  string; double was kept because the fingerprints match at two decimals.`
- ADR-026: `Registry images are pinned by digest; lakehouse/* images are built here and never
  pulled. A later tag, RELEASE.2025-10-15T17-29-55Z, fixes CVE-2025-62506 (service account and STS
  session policies, not used here); staying on 2025-09-07 is an accepted risk.`

## Старый бэклог

| ID | статус сейчас | делать / не делать | причина |
|---|---|---|---|
| R-60 (DECISIONS) | закрыт `3e00084` по пунктам `:278-279`, `:256-258`, `:302`, `:385-388`, `:133-134` (сверено: `:282` `lsn_repeats`, `:257-264` откат отпущен); остаток: длинные строки `DECISIONS.md:544,582,633-643,655,687,733,759,803` и `ARCHITECTURE.md:50,100,135` | делать в составе AR-04 | правится при сжатии |
| R-61 | открыт: ADR-027 и ADR-028 нет (`grep -n 'ADR-02[789]' DECISIONS.md` пуст) | делать (AR-02) | ложное ADR-014 видно читателю |
| R-64 | открыт: 62 890 байт, ADR-005 14.8 KB | делать (AR-04) | 30-минутное чтение |
| PF-04 | открыт: `README.md:51`, `DECISIONS.md:11,51,54,58,768`, `docker/compose.yaml:154`, `docker/minio/Dockerfile:1` | делать (AR-01) | ложное утверждение на первой странице |
| PF-52 | открыт: нет `postgres-meta` в `ARCHITECTURE.md:16-53` и SVG | делать (AR-06) | SPOF стенда не показан |
| PF-15 (фраза ADR-011) | ADR-011 `:378-380` и ADR-023 `:611-612` верны («root on the host in effect»); `:ro` у сокета `docker/compose.yaml:793` вводит в заблуждение, это область IN | не делать в AR | ADR точен |
| F-04 | открыт, область DP: эпоха пропускается по номеру без сверки checkpoint и таблицы | AR: назвать в предусловиях гарантий (AR-03) | влияет на формулировку exactly-once при восстановлении |
| F-07 | закрыт `bd8ad43` (консоль на 9001) | не делать | |
| ARCH-01 | закрыт: исключения названы `ARCHITECTURE.md:144-147` и `docker/compose.yaml:1-6`, сверено (у `minio-init` нет `deploy`) | не делать | |
| ARCH-02 | закрыт: Superset поднят (`docker ps`: `lakehouse-superset-1 Up 9 hours (healthy)`) | не делать | |
| ARCH-04 | закрыт `8fafdbb` | не делать | |
| 14 §7 `:680` dbt 1.10.23, S3FileIO, vended credentials, expire bronze | открыт | не делать; назвать в Production gap и статусе версий (AR-10) | апгрейд и новая зависимость |
| 14 §7 `:678-679` строки JDBC в `iceberg_catalog` | открыт, данные | не делать (решение владельца, blast radius) | строки не трогать и при R-40 |
| R-40 | открыт: `settings.py:16-21`, `catalog.py:34-39`, `docker/airflow/airflow.env` `CATALOG_JDBC_*`, `scripts/lakekeeper/register.sh`, `docker/compose.yaml:204-205,509,539-540` | делать (код: DP/IN; ADR-005 и комментарии: AR-07) | мёртвый слой, пароль суперпользователя в 5 местах |

## Находки «делать»

### AR-01 [высокая] «Last community release» и «no console» ложны
Где: `README.md:51`; `DECISIONS.md:11,51,54,58,768`; `docker/compose.yaml:154`; `docker/minio/Dockerfile:1`.
Факт: `git ls-remote --tags https://github.com/minio/minio 'RELEASE.2025-1*'` выводит
`9e49d5e7... refs/tags/RELEASE.2025-10-15T17-29-55Z`; проект пинит `RELEASE.2025-09-07T16-13-09Z`
(`docker/compose.yaml:159`). Тег 2025-10-15 исправляет CVE-2025-62506 (CVSS 8.1, обход session и
inline policy у service accounts и STS). Консоль есть: `command: server /data --console-address :9001`
(`docker/compose.yaml:164`), порт `:172` «web console». Для `mc` 2025-08-13 действительно последний.
Чем плохо: интервьюер проверит один `git ls-remote` и усомнится в остальных утверждениях; CVE не
названа.
Правка: «pinned community releases (MinIO 2025-09-07, mc 2025-08-13)» во всех местах; ADR-004 «the
community edition stripped the console to an object browser»; ADR-026 строка про тег 2025-10-15 и
CVE как принятый риск (текст выше, «Строки в существующие ADR»), `:768` «`mc` as the admin tool».
Смена тега не входит (решение владельца, B, пересоздание `minio` C).
Проверка: `grep -rn 'last community\|no console\|removed the web console\|as the console' README.md DECISIONS.md docker` пусто;
`grep -n 'CVE-2025-62506' DECISIONS.md` одна строка.
Размер: S; класс A.
Старый ID: PF-04.

### AR-02 [средняя] Нет ADR на Superset и MCP, на `lake_ro` и ACL; ADR-014 устарел
Где: `DECISIONS.md:21`; `ARCHITECTURE.md:116-120`.
Факт: ADR-014 «Superset optional; marts are shown through Grafana + Trino datasource»; в compose
`superset`, `superset-init`, `superset-mcp` (`docker/compose.yaml:807-925`), дашборд из 13 графиков
(`ls docker/superset/dashboards/charts | wc -l` = 13). `ARCHITECTURE.md:116-117`: «it shows the
same four questions as a dashboard». `grep -n 'ADR-027' DECISIONS.md` пусто.
Чем плохо: решение с самым большим поверхностным риском (MCP с правами admin) не записано как
решение; ADR-014 вводит в заблуждение.
Правка: ADR-027 и ADR-028 по черновикам; строка ADR-014 «superseded by ADR-027»; в
`ARCHITECTURE.md:116-117` «a dashboard `Marketplace` with six KPI tiles and trends of sales,
delivery and orders (ADR-027)»; ссылки ADR-028 в `ARCHITECTURE.md:110-115`.
Проверка: `grep -c '^## ADR-02[78]' DECISIONS.md` = 2; `grep -n 'four questions' ARCHITECTURE.md` пусто;
`grep -n 'ADR-014' DECISIONS.md | grep superseded` одна строка.
Размер: S; класс A; текст ADR на «ок» владельца.
Старый ID: R-61.

### AR-03 [средняя] Формулировка exactly-once завышает в трёх местах и не называет предусловия
Где: `ARCHITECTURE.md:80-82,122,126-127`; `docs/interview-notes.md:253-254`; `DECISIONS.md:285,293`.
Факт:
- `ARCHITECTURE.md:127` и `docs/interview-notes.md:253-254`: «dbt incremental models merge on a
  unique key». Код: одна incremental модель, `incremental_strategy='delete+insert'`,
  `unique_key='purchase_date'` (`dbt/models/marts/mart_daily_sales.sql:5-7`); остальные marts это
  таблицы `CREATE OR REPLACE` (`dbt/dbt_project.yml:18-26`). Ложно.
- `ARCHITECTURE.md:80-82`: «deduplicates by `(table, key, lsn)`», «`WHEN MATCHED AND source.lsn >
  target._last_lsn`», «Late events never overwrite newer state». Код: одна строка на ключ по
  `lsn desc nulls last, ts_ms, kafka_offset` (`silver_upsert.py:140-144`), guard с
  `t._last_lsn is null or` (`:158`); «never» верно только при одном писателе источника
  (`DECISIONS.md:560-565`) и не для снапшота после стримленной версии (`DECISIONS.md:492-496`).
- Заголовок `ARCHITECTURE.md:122` «Where exactly-once comes from» подаёт итог как exactly-once.
- Не названы предусловия: потеря возможна при простое потребителя дольше retention (24 h или
  2 GiB на партицию, `docker/compose.yaml:84-85`), при потере слота, при восстановлении checkpoint
  из копии, несогласованной с таблицей (F-04); silver коммитит таблицы по одной
  (`silver_upsert.py:280-289`), согласованного снимка между таблицами нет.
- `DECISIONS.md:285` «Verified on 2026-09-26 ...» и `:293` «So bronze is exactly once» при том,
  что обе живые остановки пришлись до записи (`DECISIONS.md:289-291`), а пропуск эпохи доказан
  тестом (`ARCHITECTURE.md:128-131`).
Чем плохо: вопрос «exactly-once?» самый частый на собеседовании по CDC; одна ложная деталь (merge
в dbt) обесценивает аккуратный раздел.
Правка: заголовок «Delivery guarantees: effectively-once»; абзац: «End to end the pipeline is
effectively-once: at-least-once delivery plus idempotent sinks, not a transactional exactly-once.
Silver equals the source as long as Kafka retention (24 h or 2 GiB per partition) and the
replication slot outlive any consumer outage, the source has one writer per key (ADR-021), and a
restored Spark checkpoint matches its table. Silver commits table by table, so a reader can see
`orders` merged before `order_items`. Gold marts are rebuilt tables; `mart_daily_sales` is
`delete+insert` by date (ADR-030).» В `:80-82` формулировки по коду. Тот же текст в
interview-notes `:253-254`. В ADR-007 `:285` «Measured on ... ; the epoch skip itself is
reproduced by `test_iceberg_sink.py`, both live kills landed before the write stage».
Проверка: `grep -rn 'merge on a unique key' ARCHITECTURE.md docs/interview-notes.md` пусто;
`grep -n 'effectively-once' ARCHITECTURE.md` одна строка и выше; ссылка
`#where-exactly-once-comes-from` обновлена во всех файлах: `grep -rn 'where-exactly-once-comes-from' --include=*.md .`
пусто или указывает на новый якорь.
Размер: S; класс A.
Старый ID: нет (F-04 как предусловие).

### AR-04 [средняя] DECISIONS 62.9 KB: сжать до 35 KB
Где: `DECISIONS.md` целиком, план по строкам в разделе «Целевой вид DECISIONS».
Факт: `wc -c DECISIONS.md` = 62890; ADR-005 14.8 KB (`:69-265`), ADR-025 и ADR-026 по 5.2 KB.
Журнальные абзацы и процессный жаргон для публичного документа: `:144` («then in `CLAUDE.md`, now
in `AGENTS.md`»), `:390` («owner's Modify gate»), `:733`, `:737-739` («ladder», «its own "ok"»),
`:765-767` («independent review of the diff, verdict "accept"»), `:643`.
Чем плохо: ADR не читается за 30 минут; журнал проверок прячет решение; жаргон агентного процесса
вне раздела «How it was built» нарушает правило публичных документов (`AGENTS.md`, «Язык и стиль»).
Правка: по таблице; в `docs/evidence.md` новый раздел `## Decision measurements` с подразделами
по ADR (якоря), куда переезжают диапазоны строк; ничего не терять: каждое число либо в evidence,
либо в OPERATIONS со ссылкой из ADR.
Проверка: `wc -c DECISIONS.md` не больше 35840; скрипт размеров разделов: ни один больше 2560
байт; `grep -n -i 'ladder\|modify gate\|verdict\|CLAUDE.md\|"ok"' DECISIONS.md` пусто;
проверка ссылок DC (скрипт по `*.md`) без битых якорей.
Размер: M; класс A; формулировки решений не меняются (только сжатие), это проверяет ревью.
Старый ID: R-64, остаток R-60.

### AR-05 [средняя] Восемь ADR только строкой, два устарели, профили неполны
Где: `DECISIONS.md:9,10,13,16,19,21,22,24`; `:41-42`; `:425-426`; `ARCHITECTURE.md:135,140-143`.
Факт: разделов нет у ADR-002, 003, 006, 009, 012, 014, 015, 017 (`grep -c '^## ADR-' DECISIONS.md` = 18
при 26 в индексе). ADR-017 повторяет ADR-024. ADR-012 «until week 6» и `ARCHITECTURE.md:135`
«Schema Registry (stretch)» устарели. ADR-001 `:41-42` «license must be checked» решено
(`README.md:229-234`). Профили `stateful` и `jobs` (`docker/compose.yaml:356,414`) не названы в
ADR-016 `:425-426` и `ARCHITECTURE.md:140-143`.
Чем плохо: клик по ADR-012 или ADR-006 из индекса никуда не ведёт; это вопросы, которые задают
(«почему не Avro», «почему local[2]»).
Правка: ADR-014 и ADR-017 «superseded by ADR-027 / ADR-024» в индексе, без раздела; короткие
разделы ADR-003, ADR-006, ADR-012 (строки выше); ADR-002, 009, 015 остаются строкой, к 015
добавить «no DQ framework»; в ADR-001 убрать «must be checked»; профили дописать.
Проверка: `grep -c '^## ADR-' DECISIONS.md` не меньше 21 (18 + 003, 006, 012 + новые);
`grep -n 'until week 6\|(stretch)\|must be checked' DECISIONS.md ARCHITECTURE.md` пусто;
`grep -n 'stateful' ARCHITECTURE.md | grep -i profile` есть строка в «Resource model».
Размер: S; класс A.
Старый ID: нет.

### AR-06 [средняя] Диаграмма без `postgres-meta`, главной общей точки отказа
Где: `ARCHITECTURE.md:16-53`; `docs/img/architecture.svg`.
Факт: `grep -n 'postgres-meta\|meta' ARCHITECTURE.md` в блоке Mermaid пусто; тексты SVG (извлечены
скриптом) совпадают с Mermaid и тоже без неё. Живой `postgres-meta` держит базы `airflow,
iceberg_catalog, lakekeeper, meta, superset` (`psql` по `pg_database`). Также: узел
`iceberg_maintenance ... optimize on silver` (`:42`) не показывает expire и компакцию bronze по
параметру и DAG `iceberg_orphans` (`airflow/dags/iceberg_orphans.py:30`).
Чем плохо: без неё не видно, что отказ одной базы останавливает каталог всех таблиц, Airflow и
Superset; это первый вопрос архитектора о SPOF.
Правка: узел `PM[("postgres-meta<br/>Lakekeeper, Airflow, Superset metadata")]`, рёбра `LK -.- PM`,
`SU -.- PM` (Airflow) и `SS -.- PM`; узел обслуживания «iceberg_maintenance 03:30, iceberg_orphans
weekly (ADR-025)»; переэкспорт SVG командой `ARCHITECTURE.md:59-62`.
Проверка: `grep -c 'postgres-meta' ARCHITECTURE.md` не меньше 1 в блоке; `grep -c 'postgres-meta' docs/img/architecture.svg` не меньше 1.
Размер: S; класс A.
Старый ID: PF-52.

### AR-07 [средняя] Комментарии compose обещают точку отката JDBC, которой нет
Где: `docker/compose.yaml:204-205,509,539-540`; `streaming/spark_jobs/settings.py:16-17`; ADR-005 `DECISIONS.md:257-264`.
Факт: compose `:204-205` «The JDBC catalog in postgres-meta is kept as the rollback point
(docs/runbooks/catalog-cutover.md)»; `:509` «serve only the JDBC lake.properties of the rollback»;
`:539-540` «and the JDBC rollback catalog»; ADR-005 `:259-261`: точка отката перестала быть
годной после обслуживания 29.10.
Чем плохо: читатель compose верит, что откат на JDBC работает; ради этого `META_PASSWORD`
суперпользователя раздаётся Spark, Trino и Airflow.
Правка: если владелец принимает R-40, удалить слой (код ведёт DP/IN) и закрыть ADR-005 строкой
«The JDBC catalog code and its credentials were removed on <date>; the rows in `iceberg_catalog`
stay as data.» Если нет: комментарии `:204-205,509,539-540`, `settings.py:16-17` переписать «the
pre-cutover JDBC catalog, no longer a valid rollback (ADR-025 deleted files its snapshots read)».
Проверка: `grep -n 'rollback point\|rollback catalog\|of the rollback' docker/compose.yaml streaming/spark_jobs/settings.py` пусто.
Размер: S (комментарии) или M (R-40); класс B; R-40 требует «ок».
Старый ID: R-40, R-60.

### AR-08 [низкая] DECISIONS ссылается на устаревший русский документ как на «longer reasoning»
Где: `DECISIONS.md:4`; `docs/planning/00-mini-architecture-review.md:3,205-216`.
Факт: `:4` «Longer reasoning lives in `docs/planning/00-mini-architecture-review.md` (ru)»; документ
от 19.09 говорит «Консоли нет», «JDBC-строки ... точкой отката до конца W3» (`:212-213`), без
баннера «история».
Чем плохо: англоязычный читатель уходит в русский документ с устаревшими фактами.
Правка: `:4` «Measurements behind the decisions: docs/evidence.md#decision-measurements»; в начало
`00-mini-architecture-review.md` строку «Статус: история (19.09.2026); действующее:
`ARCHITECTURE.md`, `DECISIONS.md`».
Проверка: `grep -n '00-mini' DECISIONS.md` пусто; `sed -n 3,4p docs/planning/00-mini-architecture-review.md` содержит «история».
Размер: S; класс A.
Старый ID: нет.

### AR-09 [низкая] Нет раздела «Production gap»; «deliberately absent» устарел
Где: `ARCHITECTURE.md:133-136`.
Факт: «Multi-broker Kafka, Spark cluster, Schema Registry (stretch), ... Each is either already
known to the author or does not close a skill gap». Разрыва с продом по измерениям нет нигде в
публичных документах (`grep -rn -i 'production gap' --include=*.md . | grep -v planning` пусто).
Чем плохо: самый сильный ответ на «что бы вы сделали в проде» не записан; фраза про автора читается
как оправдание.
Правка: заменить раздел матрицей «Production gap» ниже (английский), плюс строка «Version status,
checked 2026-11-13» из раздела «Стек глазами 2026 года».
Проверка: `grep -n '^## Production gap' ARCHITECTURE.md` одна строка; `grep -n 'stretch' ARCHITECTURE.md` пусто.
Размер: S; класс A.
Старый ID: нет (раздел 7 спеки 14, `:680`, как содержимое).

### AR-10 [низкая] Мелкие расхождения ARCHITECTURE и кода
Где: `ARCHITECTURE.md:110-111` («four panels» Grafana, верно: `marketplace.json` 4 панели);
`streaming/spark_jobs/maintenance.py:84` «(ADR-021, ADR-005)» для правила «bronze data files are never
deleted», которое записано в ADR-025 (`DECISIONS.md:722-724`).
Факт: см. Где. Grafana верна, ссылка ADR в сообщении об ошибке неточна.
Правка: `maintenance.py:84` «(ADR-025)».
Проверка: `grep -n 'ADR-021, ADR-005' streaming/spark_jobs/maintenance.py` пусто; `uv run pytest tests/unit/test_maintenance.py -q` зелёный.
Размер: S; класс B (код).
Старый ID: нет.

## Находки «не делать»

| ID | что | почему не делать |
|---|---|---|
| AR-N1 | Смена тега MinIO на 2025-10-15 | CVE про service accounts и STS, которых нет; пересоздание `minio` класс C; назвать риск (AR-01) достаточно |
| AR-N2 | Апгрейд Lakekeeper 0.13.6 до 0.15.0 | нет отката образа после migrate (`DECISIONS.md:158-160`), нужен бэкап базы; выигрыш читатель не увидит |
| AR-N3 | Spark 4.x, Iceberg 1.12, dbt 1.11/1.12 | апгрейд ради апгрейда; назвать статус версий в документе |
| AR-N4 | S3FileIO и vended credentials, снятие запрета expire bronze | новая зависимость (AWS SDK v2), риск для bronze без копии |
| AR-N5 | Аутентификация Trino, Lakekeeper, MCP | новый сервис (IdP); назвать в Production gap |
| AR-N6 | Разделы для ADR-002, 009, 015 | строка индекса полна, раздел только раздует DECISIONS |
| AR-N7 | Перевод `00-mini-architecture-review.md` и `01-roadmap.md` | планы на русском по правилу; хватит баннера (AR-08) |

## Оценка для руководителя

Проект: CDC-платформа «Postgres, Debezium, Kafka, Spark, Iceberg (Lakekeeper, MinIO), Trino, dbt,
Airflow, Superset» на одном ноутбуке 16 GB, 27 сервисов в 8 профилях compose, 20 запущены сейчас
(`docker ps`).

| Измерение | Балл | Доказательство |
|---|---|---|
| Корректность данных | 4 | `reconcile` по 7 таблицам: количество, PK, суммы decimal, отпечаток всех колонок (`README.md:203-205`); минус: гарантия зависит от одного писателя и окна retention (AR-03) |
| Надёжность | 3 | 9 сценариев отказа с числами (`docs/evidence.md:63`); всё в одном экземпляре, восстановление из копии не проверено (`OPERATIONS.md:1779-1797`) |
| Наблюдаемость | 4 | 16 правил с тестами promtool (`grep -c 'alert:' observability/prometheus/alerts.yml` = 16), свой lag Spark и retained WAL; нет доставки алертов (ADR-015) |
| Безопасность | 2 | только loopback и сгенерированные секреты; нет аутентификации в Trino, Lakekeeper, Airflow, MCP; общие root-ключи S3; docker.sock (ADR-029) |
| Воспроизводимость | 4 | образы по digest, MinIO из исходников с проверкой SHA, `uv.lock`, еженедельный smoke с чистого клона; минус: CI красный на HEAD (`gh run list`: `43423260590 failure`), сумма sha1 джарок берётся с того же Maven Central (`streaming/Dockerfile:25-26`) |
| Сопровождаемость | 3 | 787 тестовых функций в `tests/unit`; минус: мёртвый слой JDBC (R-40), 7 своих образов, pre-1.0 Lakekeeper без отката образа |
| Документация | 3 | ADR с альтернативами и замерами; минус: DECISIONS 62.9 KB, OPERATIONS 134 KB, устаревшие места (AR-01, AR-02, AR-05) |
| Стоимость владения | 3 | один ноутбук, профили вместо кластера (ADR-016); всё вместе около 8.3 GiB пика (`docs/planning/18-postfix-audit-2026-11-06.md:109`, PF-50); свои компоненты (container-exporter, сборка MinIO) требуют владельца |

Три главных риска:
1. Зависимости на исходе: MinIO community архивирован (репозиторий только для чтения с 2026,
   образов нет, сборка из исходников), закреплённый тег до исправления CVE-2025-62506; Lakekeeper
   0.13.6 при вышедшем 0.15.0 и без отката образа; Spark 3.5 только с исправлениями безопасности.
2. Bronze единственная копия истории дольше 24 ч Kafka, бэкапа нет, восстановление не проверено;
   ключ `LAKEKEEPER_ENCRYPTION_KEY` только в `.env`: потеря `.env` делает каталог нечитаемым
   (`OPERATIONS.md:1787-1789`).
3. Модель безопасности годится только для одного пользователя на loopback: любой локальный процесс
   управляет стеком, MCP работает как `admin`, имя пользователя Trino это метка.

Что сделано лучше, чем обычно в учебных проектах:
- Гарантии доказаны сбоями с числами и сверкой с источником, а не заявлены.
- Решения записаны с альтернативами и измеренной ценой (MoR против CoW, cAdvisor против своего
  экспортера).
- Разрушительные операции ограничены кодом (политика обслуживания, защита таблиц Lakekeeper).
- Честный список недоказанного и таблица бэкапов с «Restore tested: no».

## Разрыв с продом

Матрица для публичного раздела «Production gap» (английский, для `ARCHITECTURE.md`):

| Dimension | In the project | Missing | Laptop stand-in | In production |
|---|---|---|---|---|
| High availability | one instance of every service, restart policies, healthchecks | broker, catalog, metadata DB and object store replicas | `restart: unless-stopped`, chaos drills with measured recovery | 3+ Kafka brokers with RF 3 and `min.insync.replicas` 2; Postgres primary with a standby (Patroni or a managed service); several Lakekeeper replicas; erasure-coded or cloud object storage |
| Scale | `local[2]` Spark, 3 partitions, ~100k orders | cluster execution, autoscaling | profiles that never all run at once (ADR-016) | Spark on Kubernetes or a managed runtime (EMR, Dataproc, Databricks); partitions sized by throughput; Trino cluster with workers |
| Security | loopback only, generated secrets in `.env`, Trino ACL for BI users, read-only catalog | authentication, TLS, per-service credentials, secret store | `BIND_IP=127.0.0.1`, user name as a label | OIDC (Keycloak or the cloud IdP) for Trino, Lakekeeper, Airflow, Superset; TLS everywhere; Vault or a cloud secret manager; per-service S3 roles; Lakekeeper authorization (OpenFGA); no Docker socket in workloads |
| Data governance | JSON Schema contracts, quarantine, dbt tests and descriptions, soft deletes | schema registry, lineage, catalog of owners, PII handling | contracts in git, reconcile against the source | Avro or Protobuf with a schema registry and compatibility rules; OpenLineage into DataHub or OpenMetadata; PII tags and masking; data contracts with owners |
| Environments and deploy | one compose stack, CI with lint, tests, Spark tests and a weekly smoke from a clean clone | dev, staging, prod; deploy pipeline; IaC | `make start`, `make bootstrap` | Terraform for the platform, Helm or a managed service per component, promotion through environments, dbt runs per environment |
| Observability and on-call | Prometheus rules with tests, Grafana, runbooks | alert delivery, log aggregation, SLOs with error budgets | alerts read in the UI (ADR-015) | Alertmanager to PagerDuty or Opsgenie; Loki or a log service; tracing; SLOs on freshness and lag |
| Disaster recovery | Iceberg snapshots 7 days, one manual copy of `warehouse/`, documented restore gaps | regular backups, tested restore, RPO and RTO | rebuild from the repo and the dataset (`make nuke && make bootstrap`) | scheduled `pg_dump` or PITR of the catalog DB, object store versioning and cross-region replication, Kafka mirroring (MirrorMaker 2), quarterly restore drills |
| Cost | free, one 16 GB laptop | cost tracking | memory limits per service | right-sized clusters, spot workers for batch, storage lifecycle rules, per-team cost tags |

## Стек глазами 2026 года

Проверено 13.11.2026 веб-поиском (источники вторичные, кроме релиз-нот Lakekeeper и Iceberg).

| Компонент | В проекте | Текущее состояние | Назвать в документе |
|---|---|---|---|
| MinIO | `RELEASE.2025-09-07T16-13-09Z` из исходников | репозиторий архивирован (2026), community только исходниками; есть тег 2025-10-15 с исправлением CVE-2025-62506 | да: AR-01, ADR-026 |
| Lakekeeper | 0.13.6 по digest | вышли 0.14.0 (2026-10-08) и 0.15.0 (2026-11-06); pre-1.0 | да: «two minors behind, no image rollback» |
| Spark | 3.5.9, Java 17 | 4.0, 4.1 текущие; 3.5 последняя 3.x, по агрегаторам расширенная поддержка (только безопасность) до 11.2027; официальная страница не проверена | да, строка в ADR-006 |
| Iceberg | 1.11.0 | вышел 1.12.0; Spark 3.5 в 1.11 поддерживается, в 1.12 удалён 3.4 | да, кратко |
| dbt | core 1.10.23, dbt-trino 1.10.4 | core 1.11 (GA 12.2025), 1.12 (07.2026); Fusion для Trino не найден | да, кратко; срок поддержки 1.10 не проверен |
| Kafka, Debezium, Trino, Airflow, Superset, Postgres | 4.3.1, 3.5, 483, 3.3.2, 6.1.0, 17 | не проверено (`context7` или веб по каждому) | нет, если не устарели |

## Не проверено

- Официальная страница жизненного цикла Spark (дата конца поддержки 3.5): проверить
  `https://spark.apache.org/versioning-policy.html`.
- Текущие версии Kafka, Debezium, Trino, Airflow, Superset, Postgres: не искались.
- Что `delete+insert` в dbt-trino это два коммита Iceberg (вывод из устройства адаптера): проверить
  `select snapshot_id, operation from lake.gold."mart_daily_sales$snapshots" order by committed_at desc limit 4`
  после `dbt_build`.
- Рендер Mermaid и SVG сверен только по текстам узлов, не по рёбрам.
- `make secrets` генерирует значения `token_urlsafe` (по аудиту 18, PF-04), не перечитано.
- Superset MCP живьём не вызывался (только чтение compose и конфига).
