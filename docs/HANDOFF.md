# HANDOFF

Обновляется в конце каждой недели или смыслового блока. Читать первым в каждой сессии.

## Состояние на 17.10.2026, конец сессии

Аудит проекта, путь с чистого клона (W3-T00) и ядро dbt (W3-T01) сделаны. Следующая задача W3-T02, витрины: стартовый промпт в `docs/NEXT_SESSION.md`, правила агентов в `AGENTS.md` и `docs/agent-rules.md`.

### Что сделано

| Коммит | Что |
|---|---|
| `846429b docs: idle stack checks of 2026-10-17, adr-020 reconcile wording` | проверки на простое (раздел ниже), формулировка ADR-020 |
| `afa0584 infra: make start, bootstrap, verify and replay-burst` | W3-T00; healthcheck реплеера без curl (D16); `reconcile` по количеству, набору PK и суммам decimal во всех 7 таблицах (D17, `scripts/reconcile_sql.py`); README и OPERATIONS описывают реальный путь запуска; ADR-016 |
| `59dec70 dbt: project, staging and core models` | W3-T01: `lake.gold`, 7 staging views, `int_orders_enriched`, `fct_orders`, `fct_order_items`, `dim_customers`, `dim_products`, `dim_sellers`, seed `category_translation` |

### Стек на конец сессии

- Запущены `make start`: postgres-oltp, postgres-meta, kafka, kafka-connect, minio, lakekeeper, spark-bronze, trino; рестартов и OOM нет. Контейнера реплея нет.
- Реплей не тратился: `virtual_now` 2026-07-11 09:58:25, как 08.10. Бюджет W3 по D2 (10 виртуальных дней) не начат.
- Bronze и silver без новых коммитов с 2026-10-08 04:36 UTC; `make verify` в этой сессии ничего в silver не записал (снапшоты silver до и после те же).
- Gold: namespace `lake.gold` создан W3-T01; soft-deleted таблиц в Lakekeeper нет.
- Одноразовый проект `lakehouse-fresh` (проверка W3-T00) удалён вместе с томами, с «ок» владельца.

### Проверки 17.10.2026, после `make dbt-build`

| Что | Результат |
|---|---|
| `make dbt-build`, первый и второй прогон | `PASS=51 WARN=0 ERROR=0 SKIP=0 TOTAL=51` оба раза |
| `fct_orders` против `silver.orders` | 94 406 = 94 406 живых строк |
| `dim_customers` против `customer_unique_id` живых заказов | 91 259 = 91 259 |
| Заказы без живых позиций | 765: 735 без позиций вообще, 30 потеряли все при отмене |
| Второй прогон без DROP | снапшотов `fct_orders` 1 → 2 (CREATE OR REPLACE, D6), `category_translation` 2 → 4 (TRUNCATE и INSERT, D14), в seed 71 строка, soft-deleted пуст |
| `make verify` после dbt | 7 из 7 таблиц `rows ok`, `keys ok`, суммы ok (`order_items` 12 917 340.13 и 2 137 203.35, `payments` 15 218 867.61), `verify ok` |
| `make lint`, `make test`, `make dbt-parse` | зелёные; 135 passed, 62 skipped |

Проверки на простое, до реплея и до dbt, в разделе «Проверки 17.10.2026, на простое, до реплея» ниже.

### Открытые вопросы

- **Сдвигает ли heartbeat Debezium слот без изменений в `shop`: не определено.** На простое WAL не пишется вообще, сравнивать нечего. Проверять во время порции реплея: `confirmed_flush_lsn` против `pg_current_wal_lsn()` дважды с паузой.
- **Retention Kafka 24 ч против простоя Spark.** Если bronze стоит дольше 24 ч, а источник пишет, непрочитанное удаляется, `failOnDataLoss=true` (`bronze_cdc_ingest.py:134`) роняет запрос, Docker перезапускает его по кругу (OPERATIONS.md, Bronze ingest; `docs/runbooks/spark-stalled.md`). Выход только удаление checkpoint (blast radius) или правка кода; `make cdc-snapshot` не чинит ключи с LSN в silver и не возвращает удаления (ADR-019). Если источник молчит, потерь нет: retention удаляет только прочитанное, это видно сейчас. Простой реплеера безопасен: часы продолжают с `replay.state.virtual_now`. Выбор `failOnDataLoss=true` и цикл рестартов не записаны ни в одном ADR, ADR-003 есть только строкой индекса, Consequences ADR-019 («no blast radius») обещают больше, чем путь даёт. Решение за владельцем.
- **dbt-core 1.10.23 печатает «This version of dbt is deprecated».** Версии закреплены решениями W3 (`uv.lock`); обновлять или нет, решает владелец.
- **765 заказов без живых позиций** (735 без позиций вообще, 30 потеряли все при отмене): в `mart_daily_sales` по D15 735 идут в штат `unknown`; порог и формулировка теста аномалии в W3-T03.

## Состояние на 08.10.2026, после переключения каталога

Неделя 2 закрыта, включая переключение на Lakekeeper. Отставание от роадмапа около недели.

### Lakekeeper

Переключение каталога сделано 08.10.2026: Spark и Trino работают через Lakekeeper. Шаг 1 раннбука `docs/runbooks/catalog-cutover.md` выполнил агент, шаги 3-6 владелец руками, после того как классификатор auto mode агента их заблокировал. Все проверки зелёные, protection стоит на 9 таблицах bronze и silver, числа в ADR-005, раздел «Cutover, 2026-10-08».

- Бесплатного отката больше нет: первый коммит bronze прошёл через Lakekeeper. JDBC-строки в `iceberg_catalog` держат указатели до переключения, откат только DML владельца по раннбуку.
- Spark с `CATALOG_TYPE=jdbc` и JDBC-версия `lake.properties` для Trino запрещены вне отката: истории каталогов разойдутся.
- Коммит `lake: spark and trino switched to lakekeeper`: конфиг, `protect.sh`, раннбук, документация, пункт blast radius в `CLAUDE.md`.
- Решения (a)-(f) в ADR-005, подробности в `.superpowers/sdd/05-w2-plan/design-final.md` (git-ignored).

### Задачи

| Задача | Состояние |
|---|---|
| W1-T01..T07 | сделано |
| W1-T08 гейт Kafka | **за владельцем**, просрочен, `LEARNING.md` пуст |
| W2-T00 `source_sequence` в bronze (ADR-022) | сделано, a4dec8a |
| W2-T01, T02 контракты и `silver_upsert` | сделано (23.09) |
| W2-T03 MoR и партиции `silver.orders` (ADR-010) | сделано, 84f6511 |
| W2-T04 `silver.quarantine` | сделано, 3c1fd3d |
| W2-T05 chaos 1-4 | сделано и перепрогнано скриптами с проверками: 47735c1, ec6f888, 45eb2ee, dcb8bb2 |
| W2-T06 `make iceberg-demo` | сделано, abc3aa4 |
| W2-T07 schema evolution, сторона реплеера | сделано, db3e27f; сторона silver это **Modify-гейт владельца** |
| W2-T08 гейты Spark и Iceberg | **за владельцем** |
| W2-T09 Lakekeeper | сделано: side by side 5cf0fec, переключение 08.10, коммит `lake: spark and trino switched to lakekeeper` |
| W3-T00 путь с чистого клона | сделано 2026-10-17, afa0584: `make bootstrap` на сэмпле 4 мин при собранных образах (повтор 75 с), холодная сборка образа Spark ещё около 80 с при скачанном базовом образе; healthcheck реплеера без curl (D16), `reconcile` по ключам и суммам (D17) |
| W3-T01 dbt: проект, staging, ядро | сделано 2026-10-17, 59dec70: 51 тест PASS, `fct_orders` равен живым строкам silver, повторный прогон без DROP |

Цифры прогонов (все в OPERATIONS, ADR-007, ADR-010, ADR-005):

- chaos 1: kill `spark-bronze` во время батча 80, Spark повторил батч, каждый offset Kafka в bronze ровно один раз, эпохи не повторяются.
- chaos 2a/2b: `docker restart` Connect 0 повторов; `docker kill` 253 повтора с тем же LSN; silver совпадает с Postgres.
- chaos 3: 95 no-op UPDATE на 972 смены статуса (9.8%), 0 повторов по LSN, silver держит все 90 повторов.
- chaos 4: старый INSERT заказа повторно отправлен в Kafka, silver остался `approved` с прежним `_last_lsn`.
- iceberg-demo: 21 снапшот, rollback 47 -> 1100 строк, compaction 21 -> 1 файл, после expire 1 снапшот, time travel на удалённый падает.
- schema evolution: на одноразовом Postgres миграция 003 применилась ровно один раз, в том числе после рестарта.

### Что живёт в стеке

- Запущены: postgres-oltp, postgres-meta, kafka, kafka-connect, minio, lakekeeper (теперь в `core`), spark-bronze на REST, trino на REST. Реплеер не запущен (порция при переключении была разовой).
- Реплей: виртуальное время 2026-07-11 09:58 (`make replay-status`), осталось 31 395 событий. Переключение потратило один виртуальный день, за неделю 2 потрачено 14 виртуальных дней из 20 (с 2026-06-27).
- Silver после переключения, живые строки, равны Postgres (`reconcile` ok): orders 94 406, order_items 106 994, payments 98 716, reviews 91 600, customers 99 441, products 32 951, sellers 3 095. Bronze до переключения 543 862 события, после него плюс один виртуальный день (число не снималось); quarantine до переключения 3.
- `.env`: `CATALOG_TYPE=rest` (назад только через откат раннбука), `LAKEKEEPER_ENCRYPTION_KEY` (никогда не менять: им зашифрован S3-ключ warehouse, которым Lakekeeper пишет metadata-файлы) и `REPLAY_SCHEMA_EVOLUTION_AT=` без inline-комментария (старая форма ломает реплеер).
- Память (`docker stats`, 08.10): trino 1.0 GiB, kafka 794 MiB, connect 566 MiB, postgres-oltp 236 MiB, minio 225 MiB, postgres-meta 164 MiB, lakekeeper 91 MiB из 256 после переключения; БД `lakekeeper` 12 MB. Внесено в RAM-таблицу §6 архитектурного ревью.

Проверки: `make lint`, `make test` (115 passed), `make test-spark` (132 passed).

### Проверки 17.10.2026, на простое, до реплея

Стек `core` без реплеера плюс `trino`, контейнеры подняты 8-10 дней, записей в источник и в lake нет с 08.10 (последний коммит bronze 2026-10-08 04:35 UTC). Все команды только читают.

| Что | Результат |
|---|---|
| Топики `oltp.shop.*` | 3 партиции, RF 1, `retention.ms=86400000` |
| Служебные топики Connect | `connect-offsets`, `connect-configs`, `connect-status`: `cleanup.policy=compact`, retention их не удаляет |
| Коннектор | `RUNNING`, Debezium 3.5.2.Final |
| Kafka после простоя | `oltp.shop.orders`: начало лога равно концу (74871, 75045, 75138 по партициям), в каталоге партиции пустой сегмент от 09.10. Retention удалил прочитанную историю вместе с активным сегментом, bronze прочитал её раньше |
| Слот `shop_slot` | `active`, `wal_status=reserved`, держит 1800 kB WAL; `max_slot_wal_keep_size = -1`; `pg_wal` 193 MB |
| Сдвигает ли heartbeat слот без изменений в `shop` | не определено: за минуту не сдвинулись ни `confirmed_flush_lsn`, ни `pg_current_wal_lsn()`, на простое WAL не пишется вообще. Проверять во время порции реплея |
| Образ реплеера | `curl` нет (`docker run --rm --entrypoint sh lakehouse/replayer:dev -c 'command -v curl \|\| echo no-curl'` печатает `no-curl`), healthcheck в compose всегда падает |
| Bronze | 127 снапшотов, все `append`, с 2026-09-22 по 2026-10-08; 459 файлов, медиана 17 KB, среднее 94 KB |
| `silver.orders` | 44 файла данных и 14 файлов position deletes, все на spec 1; снапшоты: 16 `overwrite`, 1 `replace`, 1 `append` |
| `reconcile` | 7 из 7 `ok` |
| Деньги, Postgres и silver | `payments`: 98 716 строк, `sum(payment_value)` 15 218 867.61; `order_items`: 106 994 строки, `sum(price)` 12 917 340.13, `sum(freight_value)` 2 137 203.35. Совпадают |
| Набор ключей `orders` | md5 отсортированных `order_id` `b4490c4e27ec2b6890ed1e20c1c46e17` в Postgres и в живых строках silver |
| `silver.quarantine` | `orders`, `unparsed_envelope`: 3 |
| Часовой пояс сессии Trino | `UTC` |
| Отсечение партиций `silver.orders` | 17 из 44 splits, 8 546 из 94 406 строк (команда ниже) |

Даты в silver сдвинуты реплеером: `order_purchase_timestamp` от 2024-08-09 до 2026-07-11. Фильтр по датам Olist (2016-2018) проходит все строки и отсечения не показывает. Проверка отсечения:

```
docker compose --env-file .env -f docker/compose.yaml exec -T trino trino --catalog lake --execute "explain analyze select count(*) from silver.orders where order_purchase_timestamp >= timestamp '2026-06-01 00:00:00'"
```

## Следующие шаги по порядку

1. **Lakekeeper через сутки**: сравнить память lakekeeper и размер БД `lakekeeper` с числами в OPERATIONS (bronze коммитит каждые 20 с, метаданные теперь пишутся и в Postgres).
2. **Гейты владельца**: W1-T08 Kafka, W2-T08 Spark и Iceberg, Modify-гейт W2-T07: добавить `sales_channel` в `contracts/silver/orders.json` (`{"type": ["string", "null"], "x-silver-type": "string"}`), `ALTER TABLE lake.silver.orders ADD COLUMN sales_channel string`, затем порция реплея с `REPLAY_SCHEMA_EVOLUTION_AT` внутри неё и проверка: колонка в Postgres, поле в `after` bronze, значения в silver.
3. **Сделано 17.10 (W3-T00, afa0584).** Было: P0 из аудита, путь с чистого клона. README «Run» не доводит до данных: нет `make migrate` и `make replay-load`, `make replay` запускает второй реплеер в контейнере, а `oltp-replayer` в `core` играет на полной скорости. Нужен ADR (вынести реплеер в профиль `replay` или старт по явной команде), затем `make bootstrap` и `make verify` (bronze `count > 0`, reconcile). Без этого W3 съест остаток реплея.
4. **Спека W3**: `docs/planning/07-w3-spec.md` от 09.10 по стандарту `06-spec-standard.md`, вопросы ниже и путь с чистого клона (п. 3, карточка W3-T00) сведены в решения D1-D13; вместе с D14 и D15 приняты владельцем 09.10. План для исполнителей по задачам: `docs/planning/08-w3-plan/`, начинать с W3-T00. Исходный список:
   - грейн клиента `customer_unique_id` (89 234), а не `customer_id` (на заказ);
   - 738 заказов без позиций, 277 заказов с расхождением payments и items (тест `warn`, не `error`);
   - фильтр soft delete по моделям, а не одним правилом в staging;
   - geolocation (1 млн строк) не seed;
   - инкрементальный `mart_daily_sales` с пересчётом затронутых дат;
   - dbt-trino `on_table_exists=replace` вместо `rename`: rename это DROP бэкапа на каждом прогоне, а под soft delete Lakekeeper ещё и 7 дней копии;
   - Airflow: латентный баг `AIRFLOW_FERNET_KEY` (32 символа, Fernet требует 44), DockerOperator с docker.sock против `compose run` (ADR), pool на 1 слот для `silver_upsert` и optimize (ADR-010);
   - две метрики дублей: повтор LSN (транспорт) и `before = after` (источник).
5. **W3**: dbt gold (W3-T01 сделан 17.10, дальше T02 и T03), профиль `orchestrate` (нет `airflow/Dockerfile` и DAG), DAG (W3-T05).
6. **W4**: в `observability/` нет `prometheus.yml`, правил алертов, provisioning Grafana; chaos 5-8; `StreamingQueryListener`.
7. **W5**: stateful job, CI (`make test-spark` в CI, `uv sync --locked`, digest образов), smoke, reconciliation, maintenance. Ограничения: `expire_snapshots` на bronze запрещён до решения по apache/iceberg#18000 (ADR-021); `metadata.json` bronze копятся; MERGE без изменений всё равно коммитит снапшот `silver.orders`.
8. **W6 и витрина** (аудит предлагает дешёвую часть раньше): честный README со статусом done/measured/planned и ссылками на доказательства, диаграмма в `docs/img/`, страница доказательств, 3 бизнес-SQL на gold, `interview-notes.md`.

Выбор порядка за владельцем: A, по роадмапу (витрина последней, первой под нож) или B, тонкий срез раньше (README и диаграмма, путь с нуля, тонкий gold с тестами и бизнес-ответами, потом Airflow и obs).

## Решения, которые ждут владельца

- Порядок недель 3-6 (A или B). ADR о реплеере принят: ADR-016, `make start`.
- ADR-021: apache/iceberg#18000, `expire_snapshots` на bronze сломает AvailableNow-чтение silver. Решить до W5.
- `source_sequence` есть в bronze (ADR-022), но silver его пока не использует: после простоя дольше retention `make cdc-snapshot` не перебивает streamed LSN (ADR-019).
- MERGE без изменённых строк коммитит снапшот `silver.orders`; лог `events merged` считает входные события, а не изменённые строки.
- `MODE=restart` в chaos 2a печатает повторы, но не валит сценарий (ADR-007 допускает повторы при медленной остановке).
- Судьба JDBC-строк в `iceberg_catalog`: до конца W3 это точка отката переключения (платный откат по раннбуку), потом решить, что с ними делать (удаление в blast radius).
- S3FileIO и vended credentials в Lakekeeper отдельной задачей. Сейчас HadoopFileIO и ключи у клиентов: HadoopFileIO не реализует `SupportsStorageCredentials`, а для S3FileIO в образе Spark нужен AWS SDK v2. После перехода от `push-s3-delete-disabled: false` зависит работа `expire_snapshots` и `remove_orphan_files` (ADR-005 (b)).
- dbt-trino `on_table_exists=replace` вместо `rename`: решено (D6), работает с W3-T01, повторный прогон без DROP.
- Два анонимных тома от одноразовых контейнеров исследования (удаление в blast radius): `docker volume rm 24fddd5f9b3da04014cbf027b837239460bb1cd4c0ac4b425f927bd7f71f88e2 179eb31fb74b947039c3e78e8d9cecf3380fbe6ee0b32db240ee1ee52333924d`.

## Мелочи, отложенные в ревью

- Реплеер: HTTP-сервер слушает `0.0.0.0` (`server.py`), против правила портов; `REPLAY_SCHEMA_EVOLUTION_AT` с часовым поясом падает на первом шаге (лучше `NaiveDatetime | None`); миграция применяется с точностью до шага реплея.
- Iceberg-demo: около 38 строк INFO Spark при старте (`spark.log.level` или `log4j2.properties` в образе); `show_time_travel_fails` принимает любую `PySparkException`.
- Bronze `ensure_table` сверяет только имена колонок; `converge_layout` silver только добавляет свойства.

## Открытые вопросы

См. `docs/planning/00-mini-architecture-review.md` §10 и аудиты 07.10 в `.superpowers/sdd/05-w2-plan/audit-*.md` (git-ignored).
