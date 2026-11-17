# DP. Путь данных (data engineer)

Основание: только чтение, HEAD `a8c1d49` плюс незакоммиченная починка CI владельца (не трогалась).
Прочитаны целиком: `streaming/spark_jobs/*.py`, `streaming/Dockerfile`, `run-job.sh`, README;
`oltp/replayer/*.py`, `oltp/migrations/**`, `oltp/init/01-debezium.sh`, `oltp/Dockerfile`, README;
`connect/*`; `contracts/**`; `scripts/reconcile_sql.py`, `replay-burst.sh`, `fetch_data.py`,
`make_sample.py`; `data/README.md`; раздел exactly-once и поток данных `ARCHITECTURE.md`; списки
тестов DP в `tests/unit`. Spark-тесты не запускались (на хосте нет JVM, `make test-spark` запрещён
брифом): поведение Spark доказано чтением кода и тестов.

Живые пробы (только `select`, файлы запросов в `DP-work/q1.sql`, `q2.sql`, `q3.sql`):

| Что | Результат |
|---|---|
| bronze | 559 742 строки; повторов `(topic, partition, offset)` 0; групп логических повторов `(table, key, lsn, op)` 966 (повторы Debezium, поглощены silver); `op`: r 511 936, c 28 353, u 19 374, d 75, NULL 4 |
| silver, дубли ключа | 0 по всем 7 таблицам |
| silver против Postgres, живые строки | 7 из 7 равны: orders 96 358, order_items 109 191, payments 100 727, reviews 93 494, customers 99 441, products 32 951, sellers 3 095 |
| silver, `_last_lsn is null` | 506 143 из 535 332 строк (94.5%): строки из инкрементального снапшота (ADR-019) |
| silver, `_is_deleted` | order_items 53, reviews 22 (= 75 событий `d` в bronze) |
| quarantine | 4 строки `orders:unparsed_envelope` (яд chaos 7), повторов координат 0 |
| слот | `shop_slot` active, удержано 316 kB |
| реплей | `virtual_now` 2026-07-18, pending 21 701, delayed 9; миграции 001, 002; `sales_channel` в `shop.orders` нет (003 живьём не применялась) |
| bronze, снапшоты | 184 |
| Prometheus | `max_over_time(spark_streaming_batch_duration_seconds[7d])`: bronze 4.18 с, orders_per_minute 0.55 с |

## Оценки

- Data engineer: 4 из 5. Exactly-once держится на каждом стыке и доказан тестами и chaos с числами;
  минусы: мёртвый слой отката с паролем суперпользователя в Spark и Trino, 94.5% строк silver без
  LSN, эволюция схемы не проверена живьём.
- QA (часть DP): 4 из 5. Spark-тесты ловят поведение (повтор эпохи, LSN, карантин, потеря
  checkpoint); не покрыты исполнением SQL дыр offsets bronze и ядро реплеера на настоящем Postgres.
- Безопасность (часть DP): 3 из 5. `META_PASSWORD` суперпользователя `postgres-meta` получают три
  Spark-сервиса, Trino и env DAG без нужды (R-40); пароль Debezium открытым текстом в REST Connect.
- Архитектор (часть DP): 4 из 5. Компромиссы названы в ADR-007, 019, 021, 022; неточны две фразы
  раздела exactly-once в `ARCHITECTURE.md`.
- Новый инженер (README DP): 4 из 5. README компонентов точны, кроме `connect/README.md:6` и слоя
  отката в `streaming/README.md:5-7,31-34`.

## Сильные стороны

- Пропуск уже записанной эпохи в Iceberg-синке воспроизведён тестом, а не только ссылкой на доку:
  удаление записи commit-лога checkpoint, отрицательный контроль новым query id, две очереди в
  одной таблице: `tests/unit/test_iceberg_sink.py:129-200`.
- MERGE silver с охраной LSN и явной семантикой строк без LSN (снапшот проигрывает любому
  потоковому событию): `streaming/spark_jobs/silver_upsert.py:132-167`; тесты
  `tests/unit/test_silver_upsert.py:140-183,321-384`; живьём chaos 4 (старое событие после нового,
  `_last_lsn` не сдвинулся), `docs/evidence.md:76`.
- Карантин с причиной, ровно один раз на запись Kafka (merge по координатам):
  `silver_upsert.py:104-122,234-243`; тесты `test_silver_upsert.py:679-724`; chaos 7.
- Повторы и сбои измерены числами: 2b 253 повтора поглощены, 10b kill между таблицами и retry
  Airflow, 7 из 7 после (`docs/evidence.md:73-81`); сегодня 0 дублей ключа и 7 из 7 по счёту.
- Контракт один на таблицу и сверен с DDL источника тестом (колонки, типы, NOT NULL, PK):
  `tests/unit/test_contracts.py:89-100`; копии ключей и колонок в `reconcile.py` и `settings.py`
  тоже под тестами (`test_reconcile.py:25-36`, `test_dags.py` про `SILVER_KEYS`).
- Реплеер детерминирован и возобновляем: батч в одной транзакции, часы из `replay.state`, выбор
  повторов и опозданий по md5: `oltp/replayer/replay.py:186-221,101-108`.

## Exactly-once: стыки

| Стык | Механизм | Где | Доказано | Остаточный риск |
|---|---|---|---|---|
| Postgres -> слот | логический слот `shop_slot` (pgoutput), публикация на схему `shop`, `REPLICA IDENTITY FULL` (полный `before`) | `oltp/init/01-debezium.sh:21`; `connect/shop-connector.json:12-14`; `oltp/migrations/001_schema.sql:98-104` | chaos 5 (рестарт Postgres), chaos 6 (коннектор стоит 30 мин, WAL удержан, потом 7 из 7) | удаление слота = потеря (guard запрещает); рост WAL до диска (алерты `SlotWalRetainedHigh`, `SlotWalHeldIdle`); TRUNCATE не публикуется (`OPERATIONS.md:131-136`) |
| Debezium -> Kafka | at-least-once, offsets в `connect-offsets`, ключ = PK, порядок по ключу внутри партиции, heartbeat 10 с | `connect/shop-connector.json:14,18,20` | chaos 2a, 2b: 253 повтора после kill, поглощены; сегодня 966 групп логических повторов в bronze | повторы по замыслу; потеря только при потере тома Kafka (RF=1) |
| Kafka -> bronze | offsets Kafka в checkpoint Spark; Iceberg-синк пропускает эпоху `(queryId, epoch)`, уже записанную; `failOnDataLoss=true` | `streaming/spark_jobs/bronze_cdc_ingest.py:127-148`, `:135` | `test_iceberg_sink.py:129,166,185`; chaos 1 и 8 (0 повторов и дыр offsets в 21 партиции); `make verify` (`scripts/chaos/lib.sh:196-226`); сегодня 0 повторов offset | новый checkpoint = новый query id, повторная дозапись в пределах 24 ч (silver поглощает); SQL дыр и повторов не исполняется тестом (DP-08); простой bronze дольше retention 24 ч = остановка с ошибкой и ручной инкрементальный снапшот без удалений |
| bronze -> чтение silver | Iceberg streaming source с checkpoint, `AvailableNow`; снапшоты `replace` компакции пропускаются; expire bronze запрещён | `silver_upsert.py:313-325`; `maintenance.py:67-72,99-104` | `test_silver_upsert.py:395` (только новое с прошлого запуска), `:432` (потеря checkpoint: перечитка без изменения значений) | expire bronze ломает чтение (apache/iceberg#18000, ADR-021); один писатель держит имя контейнера (OR) |
| MERGE silver | внутри батча новейшее событие на PK (LSN, затем `ts_ms`, затем offset); `MERGE` с `s._last_lsn > t._last_lsn`, строка без LSN заменяется любым событием; удаление мягкое; карантин по координатам Kafka | `silver_upsert.py:132-150,153-167,234-243` | тесты `test_silver_upsert.py:140-190,321-384,679-724`; chaos 3, 4, 7, 10b | 94.5% строк без LSN: повтор снапшот-события перезаписывает строку теми же значениями и новым `_updated_at`; после потерянных событий снапшот не исправит строку с LSN и не удалит удалённую (ADR-019, `DECISIONS.md:490-496`) |
| Kafka -> `orders_per_minute` | состояние в checkpoint, `collect_set(order_id)` против повторов, MERGE только вверх | `orders_per_minute.py:68-75,87-110` | `test_orders_per_minute.py:163,221,238,252` | позднее водяного знака отбрасывается по замыслу (счётчик `spark_streaming_late_rows_dropped_total`) |

Вывод: стыка, где возможна потеря или перестановка при штатных сбоях, нет. Повторы есть на двух
стыках по замыслу и поглощаются MERGE. Слабое место не в коде, а в доказательстве: проверка дыр
offsets bronze не исполняется тестом (DP-08).

## Q2. Late, удаления, снапшот, эволюция схемы, невалидные события

| Случай | Что происходит | Чем покрыто |
|---|---|---|
| Out-of-order (старое после нового) | LSN-охрана, строка не откатывается | `test_silver_upsert.py:334`; chaos 4 |
| Late по времени события | `REPLAY_LATE_RATIO` сдвигает `delivered`, коммит позже с большим LSN; окно `orders_per_minute` принимает до водяного знака, позже отбрасывает и считает | `OPERATIONS.md:1534-1539`; `test_orders_per_minute.py:124-160` |
| Удаление | `tombstones.on.delete=false`, `d` с полным `before`, `_is_deleted=true`; повторная вставка того же события не воскрешает, новая вставка воскрешает | `test_silver_upsert.py:343,356`; живьём 75 = 53 + 22 |
| Повтор снапшота Debezium | инкрементальный (LSN null) проигрывает потоковому, новее старого по `ts_ms` | `test_silver_upsert.py:161,172,366` |
| Новая колонка в источнике | bronze не меняется (JSON), silver игнорирует и пишет предупреждение `unknown_fields`; принять: контракт, затем `ALTER TABLE`, иначе `ensure_table` останавливает job | `contracts/README.md:37-39`; `test_silver_upsert.py:285,386`; `test_envelope.py:117`; `test_replay_evolution.py`. Живьём 003 не применялась (`has_sales_channel` 0) |
| Смена типа | число вне `decimal(10,2)` или `int` даёт null после `try_cast`, причина `type_mismatch`, карантин, сверка красная | `contracts.py:59-71`; `test_silver_upsert.py:255-283` |
| Переименование nullable-колонки | поле пропало, silver пишет null (PF-34); сверка падает на SQL Postgres со старым именем, громко | `contracts/README.md:34-36` |
| Невалидное событие | `unparsed_envelope`, `unknown_op`, `null_key`, `type_mismatch`, `null_required`, `no_contract`; рост карантина только в логе `dq_checks` | `test_silver_upsert.py:213-240,679-724`; алерта нет (OB) |

## Старый бэклог

| ID | статус сейчас | делать / не делать | причина |
|---|---|---|---|
| R-07 | открыт: лог считает и карантин `silver_upsert.py:268-275` (`count` всех событий); MERGE при 0 годных `:264-267`; `--option` без `=` `maintenance.py:241,300` | делать (DP-03) | неверная диагностика, дешёво |
| R-20 | открыт: нет `distribution-mode` `bronze_cdc_ingest.py:139-148` | не делать | батч bronze не дольше 4.18 с за 7 дней при триггере 20 с; нужен рестарт bronze (C) |
| R-28 | открыт: `silver_upsert.py:250,254,284`; `replay.py:214-217,267`; `orders_per_minute.py:53-55` | не делать | выигрыша не измерить на этом объёме |
| R-40 | открыт, полный список в DP-01 | делать (DP-01) | мёртвый код на виду и пароль суперпользователя в 5 местах |
| R-44 | открыт: `bronze_cdc_ingest.py:69-84`, `settings.py:52`, `maintenance.py:233`, ENVELOPE `source.table` `bronze_cdc_ingest.py:39`, `# noqa: UP017` `maintenance.py:111,116,327` | делать (DP-02), кроме тройного разбора JSON в `connect/register.sh:16-22,28-32,47-50` | мёртвый код; разбор JSON это вкус |
| R-60 (остаток) | `maintenance.py:9-10` ссылается на ADR-021: верно (`DECISIONS.md:554-556`, apache/iceberg#18000) | не делать | ложная находка |
| R-66 (пути DP) | `connect/README.md:6`, `oltp/README.md:31`, `oltp/migrations/evolution/003_orders_sales_channel.sql:1`, `oltp/replayer/settings.py:32`, `scripts/replay-burst.sh:4`, `streaming/spark_jobs/catalog.py:10`, `maintenance.py:1`, `metrics.py:2`, `offsets.py:1`, `orders_per_minute.py:1`, `progress.py:1`, `settings.py:45`, `silver_upsert.py:126`, `tests/unit/test_spark_settings.py:97` | делать, ведёт DC | ID карточек W*-T* в коде |
| PF-11 / F-09 | открыт: пароль подставляется литералом `connect/register.sh:58-65`; в OPERATIONS о нём ни строки (`grep -n -i "connect-configs\|debezium.*password" OPERATIONS.md README.md` пуст) | делать строку (DP-09), код не делать | только loopback; провайдер секретов и ротация это C |
| PF-30 / F-04 | эпоха по номеру: так устроен Iceberg; JDBC одним флагом закрывается DP-01 | не делать | процедуры восстановления нет, таблица Backup (`OPERATIONS.md:1779-1785`) уже говорит, что файлы без каталога не восстанавливают |
| PF-31 / F-05 | открыт: `Replayer.step` проверен только на подделке (`test_replay_evolution.py:62-160`) | не делать | ошибка реплеера не ломает инвариант: сверка идёт против того, что в источнике; smoke играет минуту на чистом клоне; цена M |
| PF-32 | открыт: SQL `bronze_offsets_ok` `scripts/chaos/lib.sh:219-226` не исполняется ни одним тестом (`grep -rln bronze_offsets_ok tests/` пуст) | делать (DP-08), пересекается с OR и QA | единственное доказательство «нет дыр и повторов offsets» в `verify` |
| PF-33 / F-16 | открыт: `orders_per_minute.py:97-98`, имя вида на каждый батч | делать (DP-04) | вид на каждый батч живёт в сессии долгого драйвера |
| PF-34 / F-17 | поведение не менялось `silver_upsert.py:108-122`; описано `contracts/README.md:34-36` | не делать | Debezium шлёт все колонки при `REPLICA IDENTITY FULL`; переименование ловит сверка |
| PF-35 / F-18 | `enum`, `minimum`, `maximum` в контрактах ничто не исполняет и не сверяет с CHECK (`grep -rn enum streaming/` пуст) | делать (DP-06) | вторая копия домена может разойтись молча |
| PF-35 / F-19 | `OPERATIONS.md:1534-1539` объясняет оба смысла «late»; перестановка итогового статуса меняет только источник | не делать | silver зеркалит источник, сверка не страдает |
| PF-36 / F-24 | открыт: `docker/compose.yaml:470,472-473`; `load` идёт на хосте (`Makefile:25-26`, `scripts/bootstrap.sh:18-21`), контейнер только `start` (`oltp/Dockerfile:18-19`) | делать (DP-05) | мёртвый mount данных |
| F-10 | образ контейнера `spark-orders-per-minute` (`9b41b55b`) `docker image inspect` не находит, тег указывает на `94bda0b9`; код streaming после сборки 10.11 не менялся (`git log 6ff434b..HEAD -- streaming` только docs `3e00084`) | ведёт IN (PF-26) | вне кода DP |
| Б8 | закрыт `f648243` (тесты двух запросов в синке) | | |
| Б10 | закрыт: kill silver живьём (`50659c5`, evidence 10b), REL-07 тестом `test_silver_upsert.py:432`; миграция 003 живьём не делалась | не делать (003 живьём) | бюджет реплея, решение владельца 04.11; покрыто unit-тестами |
| 14 §7: строки `iceberg_catalog` | не тронуты | не делать | данные, бриф запрещает; R-40 убирает только код |
| 14 §7: `lab.orders.20261023173825`, `lab.orders.20261023174112`, `lake.demo.meta_probe` | на стенде есть (`kafka-topics --list`, `show tables from demo`) | не делать | blast radius, читатель репозитория их не видит |
| 14 §7: S3FileIO, vended credentials | `catalog.py:21-23` HadoopFileIO, `docker/trino/etc/catalog/lake.properties:8` | не делать | нужен AWS SDK v2 в образе, выигрыша нет |
| Верх HANDOFF: CI красный | Spark-тесты на раннере с JDK новее 17 (`getSubject`) | ведёт IN | замечание: с JDK 17 на раннере те же 49 Spark-тестов идут дважды, на хосте и в `make test-spark` |

## Находки «делать»

### DP-01 [средняя] Убрать мёртвый слой отката на JDBC-каталог (R-40)

Где (полный список, сверен 13.11):

Код:
- `streaming/spark_jobs/catalog.py:34-47`: ветка `if settings.catalog_type == "jdbc"`; оставить
  только REST-блок. Комментарии `:21-22` («Both catalogs», «JdbcCatalog defaults») и `:25-26`
  («Kept for jdbc too...») переписать: `io-impl` HadoopFileIO нужен, потому что в образе нет AWS
  SDK v2; `fs.s3.impl` нужен, потому что Lakekeeper кладёт таблицы под `s3://`.
- `streaming/spark_jobs/settings.py:16-22`: `catalog_type`, `catalog_jdbc_url`,
  `catalog_jdbc_user`, `catalog_jdbc_password`, `catalog_warehouse` и комментарий.
- `streaming/Dockerfile:22`: `org/postgresql/postgresql/42.7.8/postgresql-42.7.8.jar` (драйвер
  нужен только JdbcCatalog; в `spark_jobs` других JDBC нет).
- `airflow/dags/lakehouse/settings.py:53-57` (`CATALOG_TYPE`, `CATALOG_JDBC_URL`,
  `CATALOG_JDBC_USER`, `CATALOG_JDBC_PASSWORD`, `CATALOG_WAREHOUSE` в `SPARK_SILVER_ENV`) и `:65`
  (`CATALOG_JDBC_PASSWORD` из `SPARK_SILVER_SECRETS`).

Compose и env:
- `docker/compose.yaml:206-207` (комментарий «kept as the rollback point»); `spark-bronze`
  `:301-302` (`depends_on: postgres-meta`), `:312-317`; `spark-orders-per-minute` `:372-376`;
  `spark-silver` `:416-418` (`depends_on`), `:429-433`; `trino` `:494-496` (`depends_on`),
  `:509-512` (`CATALOG_DB`, `META_USER`, `META_PASSWORD` и комментарий), `:518` (`S3_BUCKET`, его
  не читает ни один файл `docker/trino/etc`); комментарии `:539-540` («and the JDBC rollback
  catalog») и `:551` («creates iceberg_catalog»). Зависимость от `postgres-meta` у Spark и Trino
  не нужна: они ждут `lakekeeper-bootstrap`, а тот через `lakekeeper` ждёт `postgres-meta`
  (`:215`).
- `docker/airflow/airflow.env:31-35`.
- `.env.example:37-40` (`CATALOG_TYPE`, `CATALOG_DB` и два комментария).
- `docker/postgres-meta/init/01-databases.sql:1` (`create database iceberg_catalog;`): только для
  новых томов, живую базу и её строки не трогает. Решение владельца (см. ниже).

Скрипты и документы:
- `scripts/lakekeeper/register.sh` (124 строки): удалить; `scripts/lakekeeper/protect.sh:5`
  (ссылка на ранбук); `scripts/README.md:33-38`.
- `docs/runbooks/catalog-cutover.md` (287 строк): `git mv` в
  `docs/planning/archive/catalog-cutover-2026-10-08.md`.
- `OPERATIONS.md:355` (ссылка), `:395-410` (два абзаца «After the cutover» и «Registration...»),
  `:412-430` (колонка «JDBC catalog» таблицы «What deletes files» и фразы «the right column destroys
  the rollback point too», «the left one applies again only after a rollback»), `:567`
  (`iceberg_catalog`), `:1765` (строка ранбука). Структуру OPERATIONS ведёт OB.
- `DECISIONS.md:12` (статус ADR-005), `:197` (ссылка на ранбук -> архив), `:252-264` (абзац
  Rollback): одна строка о снятии слоя отката с датой и коммитом.
- `streaming/README.md:5-7` (PostgreSQL JDBC в образе), `:31-34` (`CATALOG_TYPE`, `jdbc`).

Тесты:
- `tests/unit/test_spark_settings.py:9-33` (четыре теста `catalog_type`) удалить; `:36-65`
  оставить без `CATALOG_TYPE`, `CATALOG_JDBC_PASSWORD` и комментария `:50`; `:68-101` (JDBC)
  удалить.
- `tests/unit/test_dags.py:62-90` правок не требуют: сверяют `SPARK_SILVER_ENV`, compose и
  `airflow.env` между собой, после согласованной правки зелёные.

Остаётся: база `iceberg_catalog` и её строки на живом `postgres-meta`; исторические абзацы
ADR-005 (`DECISIONS.md:69-190`), `docs/interview-notes.md:232`, `docs/evidence.md:331-333`;
`META_PASSWORD` у `postgres-meta`, `lakekeeper`, Airflow (`airflow.env:17`, строка подключения
метабазы) и трёх сервисов Superset.

Факт: `catalog.py:34` «`if settings.catalog_type == "jdbc":`»; `compose.yaml:316`
«`CATALOG_JDBC_PASSWORD: ${META_PASSWORD}`»; точка отката отпущена 29.10 (`DECISIONS.md:258-261`,
`OPERATIONS.md:397-402`).
Чем плохо: пароль суперпользователя `postgres-meta` (там же базы `lakekeeper`, `airflow`,
`superset`) лежит в env трёх Spark-контейнеров, контейнеров DockerOperator, Trino и Airflow без
единого читателя; внешний читатель видит «rollback path», которого нет; `CATALOG_TYPE=jdbc` в
shell всё ещё переключает каталог (ранбук сам предупреждает, `OPERATIONS.md:395-404`).
Правка: тест на отказ первым в `tests/unit/test_compose.py`: ни у одного сервиса с образом
`lakehouse/spark:dev` и у `trino` нет ключей env с префиксом `CATALOG_` и значений с `META_`;
`META_PASSWORD` встречается только у `postgres-meta`, `lakekeeper`, `superset*` и в
`airflow.env` только в `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN` (красный на HEAD: `spark-bronze`
`:316`). Плюс в `test_spark_settings.py`: `"catalog_type" not in Settings.model_fields`. Затем
правки по списку одним коммитом кода (код DAG смонтирован, лишние ключи старого env ему не мешают;
старый образ без `CATALOG_TYPE` берёт default `rest`, так что порядок «код, потом пересоздание»
безопасен).
Проверка:
- `git grep -n -E "CATALOG_TYPE|CATALOG_JDBC|catalog-cutover|lakekeeper/register" -- ':!docs/planning' ':!DECISIONS.md' ':!docs/HANDOFF.md'` пусто;
- `uv run pytest tests/unit/test_spark_settings.py tests/unit/test_dags.py tests/unit/test_compose.py -q` зелёный; `make check`;
- `docker compose --env-file .env.example -f docker/compose.yaml --profile '*' config -q` rc 0;
- после пересоздания (C): `docker exec lakehouse-spark-bronze-1 sh -c 'test -z "${CATALOG_JDBC_PASSWORD+x}"'` rc 0 (значение не печатать), то же для `lakehouse-trino-1` и `META_PASSWORD`; `make verify` -> `verify ok`.
Пересоздаются (`config --hash '*'` на копии compose до и после правки, `.env.example`, один каталог,
`DP-work/hash/`): `airflow-api-server`, `airflow-dag-processor`, `airflow-scheduler`,
`spark-bronze`, `spark-orders-per-minute`, `spark-silver` (one-shot), `trino`. Плюс сборка
`lakehouse/spark:dev` из-за `Dockerfile`; DockerOperator берёт новый образ со следующего запуска.
Размер: M; класс B (код), C (сборка образа, пересоздание 7 сервисов в цикле verify с паузой DAG);
«ок»: строка ADR-005, перенос ранбука, `01-databases.sql`, пересоздание.
Старый ID: R-40; закрывает часть PF-30.

### DP-02 [низкая] Мёртвый код и шимы апгрейда streaming (R-44)

Где: `streaming/spark_jobs/bronze_cdc_ingest.py:69-72` (`ADDED_COLUMNS`), `:76-77,80-84` (цикл в
`ensure_table`); `:39` (`source.table` в `ENVELOPE`, не читается: `source_table` берётся из
топика `:87-90`); `settings.py:52` (`opm_starting_offsets`, нигде не задаётся:
`git grep -n OPM_STARTING_OFFSETS` пусто, `scripts/demo/watermark.sh:104-106` задаёт другие
`OPM_*`) и `orders_per_minute.py:143`; `maintenance.py:233` (`days=None`, не читается: `validate`
`:259-269`, `execute` `:287-304`); `# noqa: UP017` `maintenance.py:111,116,327` и проза о Python
3.10 `settings.py:3`, `orders_per_minute.py:17`, `maintenance.py:14`.
Факт: живой bronze уже с `source_sequence` (вставка ADR-022 в октябре), свежий DDL `:46-67` её
содержит.
Чем плохо: внешний читатель видит код апгрейда, который больше не исполнится, и настройку без
пользователей.
Правка:
1. `pyproject.toml` `[tool.ruff]`: `per-file-target-version = {"streaming/**" = "py310"}`; снять
   три `# noqa: UP017` (иначе RUF100). Проверено на копии в `DP-work/ruff/`: ruff 0.16.8 без
   `noqa` «All checks passed!», а `except*` в `streaming/` даёт ошибку синтаксиса для py310.
   Прозу заменить одной строкой «ruff checks streaming/ as py310 (pyproject)».
2. Удалить `ADDED_COLUMNS` и цикл; `tests/unit/test_bronze_cdc_ingest.py:20` (импорт) и
   `:221-225` удалить. `test_silver_upsert.py:468-498` не удалять, а переписать без шима: колонку
   добавить `alter table ... add column source_sequence string after lsn` (свойство «чтение silver
   переживает колонку, добавленную в bronze между запусками» остаётся).
3. `startingOffsets` литералом `"earliest"` с комментарием как у bronze `:131`; поле
   `opm_starting_offsets` удалить. `days=None` и `source.table` удалить.
Проверка: `uv run ruff check streaming` rc 0; `git grep -n -E "ADDED_COLUMNS|opm_starting_offsets|noqa: UP017"` пусто; `make check`; `make test-spark SPARK_TESTS="test_bronze_cdc_ingest.py test_silver_upsert.py test_orders_per_minute.py test_maintenance.py"` зелёный.
Размер: S; класс B; живое действие не нужно до следующей сборки образа (её даёт DP-01).
Старый ID: R-44.

### DP-03 [низкая] Лог silver считает карантин как merged; `--option` без `=` падает после старта Spark (R-07)

Где: `streaming/spark_jobs/silver_upsert.py:264-275`; `maintenance.py:241,300`.
Факт: `:268-275` логирует `count` (все события таблицы, с карантином); MERGE `:267` идёт и при 0
годных; `maintenance.py:300` `dict(item.split("=", 1) ...)` даёт `ValueError` на каждую таблицу
уже после `open_session()` `:325`.
Чем плохо: строка «batch N: M events merged» завышает число при карантине, а это строка, по которой
читают chaos-скрипты и человек; ошибка ввода `--option` видна как сбой каждой таблицы.
Правка: `valid = count - sum(why.values())`; при `valid == 0` строка «nothing to merge» без MERGE;
в строке merged число `valid`. Префикс `batch N: M events merged into lake.silver.<t> in X s`
сохранить: его читают `scripts/chaos/silver-kill.sh:43,154,171`, `scripts/chaos/late.sh:92`,
`tests/unit/test_chaos_silver_kill.py:69-72`. `--option`: `type=` с `ArgumentTypeError`, если нет
`=` или ключ пуст. Тесты первыми: `test_maintenance.py` `parse_args(["rewrite-data", "--option",
"nokey", "silver.orders"])` -> `SystemExit` 2 (красный на HEAD); Spark-тест с `caplog`: батч из
одного годного и одного битого события пишет «1 events merged» (красный на HEAD: 2). Проверить в
том же тесте, коммитит ли Iceberg снапшот на MERGE с пустым источником (число строк
`lake.silver.orders.snapshots` до и после батча только из битых); если снапшота нет, этот пункт
только про лог.
Проверка: `uv run pytest tests/unit/test_maintenance.py -q`; `make test-spark SPARK_TESTS=test_silver_upsert.py`.
Размер: S; класс B; новый образ при следующей сборке.
Старый ID: R-07.

### DP-04 [низкая] Временные виды `opm_batch_<id>` копятся в долгоживущем драйвере

Где: `streaming/spark_jobs/orders_per_minute.py:97-98`.
Факт: `view = f"opm_batch_{batch_id}"`, вид не удаляется; `silver_upsert` использует постоянные
имена (`silver_upsert.py:236,263`).
Чем плохо: каждый непустой батч оставляет в каталоге сессии вид с планом микробатча; сервис живёт
неделями (`restart: unless-stopped`).
Правка: постоянное имя `opm_batch` или `spark.catalog.dropTempView(view)` в `finally`. Тест первым
(`test_orders_per_minute.py`): после двух `upsert` нет временного вида с префиксом `opm_batch_`
(`spark.catalog.listTables()`, `isTemporary`).
Проверка: `make test-spark SPARK_TESTS=test_orders_per_minute.py`.
Размер: S; класс B; на стенде после сборки образа и `make up PROFILE=stateful` (C).
Старый ID: PF-33, F-16.

### DP-05 [низкая] Мёртвый mount данных у `oltp-replayer`

Где: `docker/compose.yaml:470` (`DATA_DIR: /data`), `:472-473` (`${DATA_DIR}:/data:ro`).
Факт: контейнер запускает только `start` (`oltp/Dockerfile:18-19`, `Makefile:77-78`); `load`
читает CSV на хосте (`Makefile:25-26`, `scripts/bootstrap.sh:18-21`).
Чем плохо: читатель compose ищет, кто читает `/data`; лишний доступ контейнера к каталогу хоста.
Правка: тест первым в `tests/unit/test_compose.py`: у `oltp-replayer` нет `volumes` и `DATA_DIR`;
затем удалить три строки.
Проверка: `uv run pytest tests/unit/test_compose.py -q`; `config -q` rc 0.
Размер: S; класс B; контейнер сейчас не запущен (`docker ps`), пересоздастся при следующем
`make replay-live`.
Старый ID: PF-36, F-24.

### DP-06 [низкая] Домены в контрактах (`enum`, диапазон) не исполняются и не сверены с CHECK; список таблиц коннектора не сверен с контрактами

Где: `contracts/silver/orders.json:12`, `payments.json:12`, `reviews.json:13` против
`oltp/migrations/001_schema.sql:43-48,69-71,85`; `connect/shop-connector.json:16` против
`contracts/silver/*.json`.
Факт: `grep -rn enum streaming/` пусто; `test_contracts.py:89-100` сверяет колонки, типы, NOT NULL
и PK, но не домены; `test_envelope.py:103` («unknown-status») проверяет JSON Schema фикстуры, что
читается как «silver отвергает неизвестный статус», а silver его пропустит; теста «список
коннектора = контракты» нет (`grep -rln table.include.list tests/unit` даёт только
`test_dags.py:227`, про слот).
Чем плохо: вторая копия домена расходится молча при новой миграции; новая таблица с контрактом без
строки в коннекторе видна только по красной сверке.
Правка: строка в `contracts/README.md` после `:36`: «`enum`, `minimum`, `maximum` mirror the
source CHECK constraints; silver does not check them, the source does, and dbt `accepted_values`
in `dbt/models/staging/_staging.yml` tests gold's input». Два теста в `test_contracts.py`: домены
контрактов равны спискам CHECK из `001_schema.sql` (разбор как `source_tables()` `:46-68`);
множество `x-source-table` равно `table.include.list`.
Проверка: `uv run pytest tests/unit/test_contracts.py -q`; мутация: убрать `"unavailable"` из
`orders.json` -> красный.
Размер: S; класс A (тест и README).
Старый ID: PF-35, F-18.

### DP-07 [низкая] Раздел exactly-once в ARCHITECTURE: две неточные фразы

Где: `ARCHITECTURE.md:80`, `:126-127`.
Факт: `:80` «deduplicates by `(table, key, lsn)`», а код оставляет одну строку на PK, новейшую по
LSN, затем `ts_ms`, затем offset (`silver_upsert.py:140-150`). `:126-127` «a replayed or duplicated
event is a no-op; dbt incremental models merge on a unique key»: строка без LSN заменяется любым
событием (`silver_upsert.py:158`), а таких 506 143 из 535 332 (живой `select`); повтор
снапшот-события перезаписывает её теми же значениями и новым `_updated_at` (это фиксирует
`test_silver_upsert.py:432`); `mart_daily_sales` это `delete+insert` по `purchase_date`
(`dbt/models/marts/mart_daily_sales.sql:5-7`), не merge.
Чем плохо: интервьюер читает именно этот раздел; формулировка шире кода.
Правка: `:80` «keeps the newest event per primary key (highest LSN; a snapshot read without LSN
loses to any streamed change)»; `:126-127` «a replayed or duplicated streamed event is a no-op; a
replayed snapshot read rewrites its row with the same values; the one incremental dbt model
replaces whole days (`delete+insert` on `purchase_date`)». По желанию ссылка на таблицу стыков
выше в `docs/evidence.md`.
Проверка: `grep -n "deduplicates by\|merge on a unique key" ARCHITECTURE.md` пусто.
Размер: S; класс A, `docs-writer`.
Старый ID: нет.

### DP-08 [средняя] SQL дыр и повторов offsets bronze не исполняется тестом

Где: `scripts/chaos/lib.sh:219-226` (`bronze_offsets_ok`), `:211-215` (`bronze_offsets_report`).
Факт: `grep -rln "bronze_offsets_ok\|bronze_offsets_report" tests/` пусто; это единственная
проверка «нет повтора и дыры offset» в `make verify` и chaos 1, 8.
Чем плохо: ослабление условия (`>` на `>=`, потерянная ветка `or`) даёт ложный зелёный стыка
Kafka -> bronze, и набор это пропустит.
Правка: тест первым: вынести текст запроса в переменную или файл, исполнить его в тесте на
`sqlite3` (стандартный `group by` и `having`) или на Postgres-сервисе CI, как
`test_reconcile_postgres.py`, против фикстуры с одним повтором, одной дырой и чистой партицией;
ждать 2 плохие партиции; мутации `>=` и без `or` красные.
Проверка: `uv run pytest tests/unit/<новый файл> -q`; мутанты красные.
Размер: S-M; класс B. Пересекается с OR и QA: свести в один пакет.
Старый ID: PF-32.

### DP-09 [низкая] Пароль роли Debezium открытым текстом в REST Connect не назван в документах

Где: `connect/register.sh:58-65` (`envsubst` подставляет пароль в конфиг); `README.md:93`
(Connect без аутентификации); `OPERATIONS.md:289-345` (Access control).
Факт: `GET 127.0.0.1:8083/connectors/shop-connector/config` отдаёт `database.password` литералом,
он же в топике `connect-configs`; в OPERATIONS и README ни строки
(`grep -n -i "connect-configs\|debezium.*password" OPERATIONS.md README.md` пусто).
Чем плохо: при не-loopback `BIND_IP` пароль роли с REPLICATION читается без входа.
Правка: строка в «Access control» или в модели безопасности (PF-03): что видно, почему принято
(loopback), что делать в проде (`EnvVarConfigProvider` с `allowlist.pattern`, ротация пароля,
старые записи остаются в компактируемом топике).
Проверка: `grep -n "connect-configs" OPERATIONS.md` одна строка.
Размер: S; класс A, `docs-writer`; ведёт IN вместе с PF-03.
Старый ID: PF-11, F-09.

### DP-10 [низкая] `connect/README.md`: неверный вызов REST и история в тексте

Где: `connect/README.md:6`.
Факт: «by `register.sh` (week 1, W1-T05) before POSTing to `http://127.0.0.1:8083/connectors`»;
скрипт делает `PUT .../connectors/shop-connector/config` (`connect/register.sh:62-65`), повторный
запуск применяет правку конфига (`:62`).
Правка: «`register.sh` creates the topics, then PUTs the config to
`/connectors/shop-connector/config` (an upsert: re-run it to apply a change)»; без «week 1, W1-T05».
Проверка: `grep -n "POSTing\|W1-T05" connect/README.md` пусто.
Размер: S; класс A.
Старый ID: часть R-66.

## Находки «не делать»

| ID | что | почему не делать |
|---|---|---|
| R-20 | `distribution-mode=none` у bronze | батч bronze 4.18 с максимум за 7 дней при триггере 20 с; рестарт bronze (C) ради невидимого выигрыша |
| R-28 | два action на таблицу в батче silver, `count(*)` и UPDATE state реплеера на каждом шаге, двойной разбор в opm | выигрыш не измерить на этом объёме |
| R-44 часть | один разбор JSON вместо трёх в `connect/register.sh:16-32,47-50` | вкус, около 10 строк |
| PF-30 | сверка checkpoint и таблицы на старте bronze | так устроен Iceberg; бэкапа и процедуры восстановления нет; JDBC-флаг уходит в DP-01 |
| PF-31 | интеграционный тест `Replayer.step` на Postgres | ошибка реплеера не ломает инвариант (сверка против источника); smoke играет минуту; цена M |
| PF-34 | причина `missing_field` для пропавшего nullable-поля | при `REPLICA IDENTITY FULL` Debezium шлёт все колонки; описано `contracts/README.md:34-36`; переименование ловит сверка |
| PF-35 (F-19) | честная строка о `REPLAY_LATE_RATIO` | уже есть `OPERATIONS.md:1534-1539`; затрагивает только источник |
| нет | позиция для снапшот-строк через `source_sequence` (ADR-019, ADR-022) | смена контракта bronze; предел честно описан `DECISIONS.md:490-496` |
| нет | `postpone` может унести `delivered` за `horizon_ts` (`replay.py:149-153` и кап `:143`), событие не выстрелит | только с `REPLAY_LATE_RATIO > 0` в последние 300 виртуальных секунд двухмесячного расписания |
| нет | `decimal.handling.mode=string` вместо `double` | `numeric(10,2)` это не больше 10 значащих цифр, double точен; смена меняет контракт и сверку; выбор описан `contracts/README.md:29` |
| нет | миграция 003 живьём | бюджет реплея, решение владельца по Б10; путь покрыт unit-тестами |
| 14 §7 | лаб-топики, `lake.demo.meta_probe`, строки `iceberg_catalog` | blast radius; читатель репозитория их не видит |
| нет | `fetch_data.py:53-54` выдаёт подсказку про вход в Kaggle на любой сбой | косметика |
| R-60 | `maintenance.py:9-10` ADR-021 | ссылка верна (`DECISIONS.md:554-556`) |

## Разрыв с продом

- Debezium at-least-once без EOS-источника и без Schema Registry: дрейф схемы виден только в silver
  (карантин, предупреждение `unknown_fields`) и в сверке.
- Один брокер, RF=1, retention 24 ч: потеря тома Kafka или простой bronze дольше суток лечится только
  инкрементальным снапшотом, который не переносит удаления.
- 94.5% строк silver без LSN (наследство инцидента ADR-019): порядок между снапшот-чтениями только
  по времени Debezium.
- Бэкапа checkpoint, каталога и `warehouse/` нет, восстановление не проверялось
  (`OPERATIONS.md:1768-1785`).
- Эволюция схемы ручная (контракт, потом `ALTER TABLE`) и живьём не доказана; изменение домена (новый
  статус) в silver не ловится, только dbt `accepted_values`.
- Карантин без алерта и без инструмента повторной обработки.
- Spark `local[2]`, по процессу на job; свежесть silver ограничена расписанием 5 мин.
- Общие учётки и секреты в env: суперпользователь `postgres-meta` у многих сервисов (часть уходит с
  DP-01), пароль Debezium открытым текстом в REST Connect; менеджера секретов нет.

## Не проверено

- Spark-тесты не запускались (бриф): все утверждения о поведении Spark по коду и тестам. Проверит
  `make test-spark` (владельцем или в CI).
- Коммитит ли Iceberg снапшот на MERGE с пустым источником (DP-03): `make test-spark
  SPARK_TESTS=test_silver_upsert.py` с новой проверкой числа снапшотов.
- `make verify` и `make reconcile` не запускались: сверены только количества живых строк 7 из 7 и
  дубли ключей; отпечатки значений не сравнивались (последний `verify ok` 13.11 по HANDOFF).
- Число задач shuffle у bronze (R-20) не измерено (Spark UI на 4040 не открывался).
- `spark-orders-per-minute`: `RestartCount` 1, перезапуск 18:22:55 UTC 13.11 после
  `no recent heartbeats: 2066229 ms` в 18:12:47 (похоже на сон хоста); причина выхода не
  разбиралась: `docker logs --since 2026-11-13T18:12:00Z --until 2026-11-13T18:23:00Z
  lakehouse-spark-orders-per-minute-1 2>&1 | grep -v py4j | tail -60`.
- Образ контейнера opm `9b41b55b` не находится `docker image inspect` (вероятно, digest индекса в
  хранилище containerd, как в записи HANDOFF 10.11), сверка с тегом не сделана (IN, PF-26).
- `per-file-target-version` проверен только на копии в scratchpad с ruff 0.16.8, не в репозитории.
- Хэши compose для DP-01 считались на копии с `.env.example`; с живым `.env` набор сервисов тот же
  по построению (меняются только строки env этих сервисов), но не проверялся.
- Значение `skipped.operations` по умолчанию в Debezium 3.5 взято из `OPERATIONS.md:133-134`, не
  перепроверено по документации.
