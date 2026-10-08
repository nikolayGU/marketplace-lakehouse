# HANDOFF

Обновляется в конце каждой недели или смыслового блока. Читать первым в каждой сессии.

## Состояние на 08.10.2026, 08:30 (+04)

Неделя 2 закрыта по коду, кроме переключения на Lakekeeper (W2-T09, шаги 3-7 раннбука). Отставание от роадмапа около недели.

### Сначала: живой стек в промежуточном состоянии

Переключение каталога остановлено на шаге 1 раннбука `docs/runbooks/catalog-cutover.md` (файл пока не в git):

- `spark-bronze` **остановлен** с 04:25 UTC 08.10 (шаг 1: writers стоп, `register.sh` 9 из 9 `same`, rc 0). Реплеер не играет, новых событий в Kafka нет, retention 24 ч, поэтому данные не теряются, но bronze стоит.
- `.env`: `CATALOG_TYPE=jdbc`. Trino работает на JDBC. Lakekeeper healthy, указатели 9 таблиц свежие. Логи шага 1 и `numbers-before.tsv` в `~/lakehouse-cutover/`.
- Рабочее дерево содержит незакоммиченную подготовку этапа C: `docker/compose.yaml` (Lakekeeper в `core`, `depends_on` на `lakekeeper-bootstrap`), `docker/trino/etc/catalog/lake.properties` **уже на REST**, `.env.example` и умолчание `settings.py` на `rest`, тесты, `scripts/lakekeeper/protect.sh`, раннбук. Ревью подготовки пройдено (GO). Образ `lakehouse/spark:dev` пересобран под это дерево.
- Шаг 3 (правка `.env` и пересоздание сервисов) и даже `docker start` bronze запретил классификатор auto mode агента. Решение за владельцем, два пути:
  - **A. Довести переключение** (рекомендую, всё проверено): шаги 3-6 раннбука руками. Затем документация коммита 2 (ADR-005 раздел «Cutover», OPERATIONS, пункт blast radius в `CLAUDE.md` из `design-final.md` (d), README, §5 и §6 `00-mini-architecture-review.md`) и коммит `lake: spark and trino switched to lakekeeper`.
  - **B. Отложить**: `docker start lakehouse-spark-bronze-1` (bronze продолжит на JDBC, указатели Lakekeeper станут инертны). **Не перезапускать Trino**, пока `lake.properties` в дереве на REST: после рестарта Trino прочтёт устаревшие указатели Lakekeeper. Перед любым рестартом вернуть файл: `git show HEAD:docker/trino/etc/catalog/lake.properties > docker/trino/etc/catalog/lake.properties`.
- Решения по Lakekeeper (a)-(f) владелец делегировал агенту, итог в `.superpowers/sdd/05-w2-plan/design-final.md` (git-ignored) и в ADR-005 «Side by side, verified 2026-10-08».

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
| W2-T09 Lakekeeper | side by side сделано, 5cf0fec; переключение см. выше |

Цифры прогонов (все в OPERATIONS, ADR-007, ADR-010, ADR-005):

- chaos 1: kill `spark-bronze` во время батча 80, Spark повторил батч, каждый offset Kafka в bronze ровно один раз, эпохи не повторяются.
- chaos 2a/2b: `docker restart` Connect 0 повторов; `docker kill` 253 повтора с тем же LSN; silver совпадает с Postgres.
- chaos 3: 95 no-op UPDATE на 972 смены статуса (9.8%), 0 повторов по LSN, silver держит все 90 повторов.
- chaos 4: старый INSERT заказа повторно отправлен в Kafka, silver остался `approved` с прежним `_last_lsn`.
- iceberg-demo: 21 снапшот, rollback 47 -> 1100 строк, compaction 21 -> 1 файл, после expire 1 снапшот, time travel на удалённый падает.
- schema evolution: на одноразовом Postgres миграция 003 применилась ровно один раз, в том числе после рестарта.

### Что живёт в стеке

- Запущены: postgres-oltp, postgres-meta, kafka, kafka-connect, minio, trino, lakekeeper. Остановлен: spark-bronze (см. выше). Реплеер не запущен.
- Реплей: виртуальное время 2026-07-10 10:00, осталось 32 033 события. За неделю 2 потрачено 13 виртуальных дней из 20 (с 2026-06-27).
- Bronze 543 862 события; silver: orders 94 113, order_items 106 698, payments 98 415, reviews 91 608, customers 99 441, products 32 951, sellers 3 095, quarantine 3.
- `.env`: новые строки `LAKEKEEPER_ENCRYPTION_KEY` (никогда не менять, им зашифрован S3-ключ warehouse) и `REPLAY_SCHEMA_EVOLUTION_AT=` без inline-комментария (старая форма ломает реплеер).
- Память (`docker stats`, 08.10): trino 1.0 GiB, kafka 794 MiB, connect 566 MiB, postgres-oltp 236 MiB, minio 225 MiB, postgres-meta 164 MiB, lakekeeper 88 MiB из 256. В RAM-таблицу §6 архитектурного ревью не внесено.

Проверки: `make lint`, `make test` (115 passed), `make test-spark` (132 passed).

## Следующие шаги по порядку

1. **Закрыть W2-T09** путём A или B выше. При A после проверок запустить `scripts/lakekeeper/protect.sh` (защита bronze и silver от DROP). Затем отметить чекбоксы задач 1-10 в `docs/planning/05-w2-plan.md` и строку RAM в §6 ревью.
2. **Гейты владельца**: W1-T08 Kafka, W2-T08 Spark и Iceberg, Modify-гейт W2-T07: добавить `sales_channel` в `contracts/silver/orders.json` (`{"type": ["string", "null"], "x-silver-type": "string"}`), `ALTER TABLE lake.silver.orders ADD COLUMN sales_channel string`, затем порция реплея с `REPLAY_SCHEMA_EVOLUTION_AT` внутри неё и проверка: колонка в Postgres, поле в `after` bronze, значения в silver.
3. **P0 из аудита: путь с чистого клона.** README «Run» не доводит до данных: нет `make migrate` и `make replay-load`, `make replay` запускает второй реплеер в контейнере, а `oltp-replayer` в `core` играет на полной скорости. Нужен ADR (вынести реплеер в профиль `replay` или старт по явной команде), затем `make bootstrap` и `make verify` (bronze `count > 0`, reconcile). Без этого W3 съест остаток реплея.
4. **Спека W3** (`superpowers:brainstorming`, потом `writing-plans`, в `docs/planning/`). Решить до кода:
   - грейн клиента `customer_unique_id` (89 234), а не `customer_id` (на заказ);
   - 738 заказов без позиций, 277 заказов с расхождением payments и items (тест `warn`, не `error`);
   - фильтр soft delete по моделям, а не одним правилом в staging;
   - geolocation (1 млн строк) не seed;
   - инкрементальный `mart_daily_sales` с пересчётом затронутых дат;
   - dbt-trino `on_table_exists=replace` вместо `rename`: rename это DROP бэкапа на каждом прогоне, а под soft delete Lakekeeper ещё и 7 дней копии;
   - Airflow: латентный баг `AIRFLOW_FERNET_KEY` (32 символа, Fernet требует 44), DockerOperator с docker.sock против `compose run` (ADR), pool на 1 слот для `silver_upsert` и optimize (ADR-010);
   - две метрики дублей: повтор LSN (транспорт) и `before = after` (источник).
5. **W3**: dbt gold (W3-T01..T03), профиль `orchestrate` (нет `airflow/Dockerfile` и DAG), DAG (W3-T05).
6. **W4**: в `observability/` нет `prometheus.yml`, правил алертов, provisioning Grafana; chaos 5-8; `StreamingQueryListener`.
7. **W5**: stateful job, CI (`make test-spark` в CI, `uv sync --locked`, digest образов), smoke, reconciliation, maintenance. Ограничения: `expire_snapshots` на bronze запрещён до решения по apache/iceberg#18000 (ADR-021); `metadata.json` bronze копятся; MERGE без изменений всё равно коммитит снапшот `silver.orders`.
8. **W6 и витрина** (аудит предлагает дешёвую часть раньше): честный README со статусом done/measured/planned и ссылками на доказательства, диаграмма в `docs/img/`, страница доказательств, 3 бизнес-SQL на gold, `interview-notes.md`.

Выбор порядка за владельцем: A, по роадмапу (витрина последней, первой под нож) или B, тонкий срез раньше (README и диаграмма, путь с нуля, тонкий gold с тестами и бизнес-ответами, потом Airflow и obs).

## Решения, которые ждут владельца

- Путь A или B для W2-T09 (см. выше) и пункт blast radius в `CLAUDE.md` про DROP на REST-каталоге.
- Порядок недель 3-6 (A или B) и ADR о профиле реплеера.
- ADR-021: apache/iceberg#18000, `expire_snapshots` на bronze сломает AvailableNow-чтение silver. Решить до W5.
- `source_sequence` есть в bronze (ADR-022), но silver его пока не использует: после простоя дольше retention `make cdc-snapshot` не перебивает streamed LSN (ADR-019).
- MERGE без изменённых строк коммитит снапшот `silver.orders`; лог `events merged` считает входные события, а не изменённые строки.
- `MODE=restart` в chaos 2a печатает повторы, но не валит сценарий (ADR-007 допускает повторы при медленной остановке).
- Судьба `iceberg_catalog` (JDBC) после W3: пока это точка отката переключения.
- S3FileIO и vended credentials в Lakekeeper отдельной задачей (сейчас HadoopFileIO, ключи у клиентов).
- Два анонимных тома от одноразовых контейнеров исследования (удаление в blast radius): `docker volume rm 24fddd5f9b3da04014cbf027b837239460bb1cd4c0ac4b425f927bd7f71f88e2 179eb31fb74b947039c3e78e8d9cecf3380fbe6ee0b32db240ee1ee52333924d`.

## Мелочи, отложенные в ревью

- Реплеер: HTTP-сервер слушает `0.0.0.0` (`server.py`), против правила портов; `REPLAY_SCHEMA_EVOLUTION_AT` с часовым поясом падает на первом шаге (лучше `NaiveDatetime | None`); миграция применяется с точностью до шага реплея.
- Iceberg-demo: около 38 строк INFO Spark при старте (`spark.log.level` или `log4j2.properties` в образе); `show_time_travel_fails` принимает любую `PySparkException`.
- Bronze `ensure_table` сверяет только имена колонок; `converge_layout` silver только добавляет свойства.

## Открытые вопросы

См. `docs/planning/00-mini-architecture-review.md` §10 и аудиты 07.10 в `.superpowers/sdd/05-w2-plan/audit-*.md` (git-ignored).
