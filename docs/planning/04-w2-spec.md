# 04. Спека: остаток недели 2

Версия 1.0, 26.09.2026. Подпроект большой сессии W2 → W3 → W4. Архитектура и DoD задач уже в `00-mini-architecture-review.md` и `01-roadmap.md`; здесь только то, что к ним добавляет реализация: решения владельца, проверенные факты, дизайн каждой задачи, порядок и проверки. Факты сверены 26.09 по исходникам Iceberg 1.11.0, Debezium 3.5, Trino 483, Lakekeeper 0.13.x и на живом стеке.

## 1. Цель и границы

Цель недели не меняется: silver отражает текущее состояние Postgres без дублей, late и DELETE обработаны, отказы воспроизводятся командой и описаны.

Входит:

| Задача | Суть |
|---|---|
| W2-T00 (новая) | `source_sequence` в bronze, ADR-022 |
| W2-T03 | `silver.orders` на merge-on-read и `months(order_purchase_timestamp)`, закрыть ADR-010 замером |
| W2-T04 | `silver.quarantine` |
| W2-T05 | chaos 1-4, раннбуки `spark-stalled` и `connector-failed` |
| W2-T06 | `make iceberg-demo` |
| W2-T07 | schema evolution: сторона реплеера |
| W2-T09 | Lakekeeper, лимит 3 ч |

За владельцем: гейты W1-T08 (Kafka) и W2-T08 (Spark, Iceberg); Modify-гейт W2-T07 (колонка `sales_channel` в контракте и `ALTER TABLE lake.silver.orders`). Агент готовит подсказку, но не код.

Решения владельца от 26.09:

- `source.sequence` пишется в bronze сейчас, порядок в silver остаётся по `lsn` до отдельного решения.
- ADR-020 принят.
- Lakekeeper делается в конце W2 с лимитом 3 ч; не завёлся, значит ADR-005 с причиной и JDBC.
- Заранее разрешено: DROP, rollback, expire_snapshots, remove_orphan_files на таблицах `lake.demo.*`, которые создаёт демо; удаление двух анонимных томов (сделано 26.09); удаление тестовых checkpoint и warehouse во временных каталогах. Всё остальное из blast radius спрашивается каждый раз.

## 2. Проверенные факты, на которых стоит дизайн

Iceberg 1.11.0 + Spark 3.5.9:

- MoR включается свойствами `write.merge.mode`, `write.update.mode`, `write.delete.mode` = `merge-on-read`. На format v2 Spark пишет position delete files (не deletion vectors). Гранулярность удалений в Spark по умолчанию `file`, хотя общая документация пишет `partition`; при `file` MERGE сливает старый delete file затронутого data file с новым, так что на один data file живёт примерно один delete file.
- `ADD PARTITION FIELD months(col)` на `timestamp_ntz` работает и меняет только метаданные: старые файлы остаются в spec 0, новые пишутся в spec 1. Партиция не отсекает файлы в MERGE, у которого в `on` только первичный ключ.
- `ADD COLUMN ... AFTER col` есть, `IF NOT EXISTS` нет: миграции колонок должны сами проверять схему.
- Streaming sink в Iceberg сверяет схему DataFrame с таблицей по имени, а порядок проверяет (`check-ordering`, по умолчанию on): колонка не на своём месте роняет запрос. Checkpoint Kafka-источника схемы не хранит, поэтому новая колонка в bronze не требует сброса checkpoint.
- Повтор эпохи streaming sink пропускает по `spark.sql.streaming.queryId` и `epochId` в summary снапшота (`Skipping epoch N ... as it was already committed`). Окно, в котором это срабатывает (Iceberg закоммитил, Spark не записал `commits/N`), длится миллисекунды. Файлы пропущенной эпохи остаются сиротами.
- Streaming-чтение Iceberg (silver) переживает новую колонку в bronze; снапшоты `replace` (compaction) пропускает, `delete` и `overwrite` роняют чтение.
- Внутри `foreachBatch` AQE выключен, а `spark.sql.shuffle.partitions` заморожен в checkpoint: у silver 4, у bronze 200.
- apache/iceberg#18000 и #16940 открыты. AvailableNow каждый запуск идёт от **первого** снапшота bronze, который silver видел, поэтому время запуска растёт с историей bronze, а любой `expire_snapshots` на bronze ломает silver.

Debezium 3.5 (Connect runtime 4.2.0):

- `source.sequence` это строка `["<конец commit-записи ПРЕДЫДУЩЕЙ транзакции>","<LSN изменения>"]`. Если сравнивать оба элемента как числа, порядок совпадает с порядком коммитов. Первый элемент бывает null (initial snapshot, первая транзакция после него). У событий incremental snapshot `lsn` null, а `sequence` содержит позицию close-watermark. Формулировку в ADR-021 надо поправить.
- `docker restart kafka-connect` (SIGTERM) коммитит offsets и сбрасывает LSN в slot: дублей ожидается около нуля. `docker kill` не коммитит: повторяется всё, что вышло после последнего `Committing offsets` (`offset.flush.interval.ms` = 60 с), с теми же LSN.
- `ALTER TABLE ... ADD COLUMN` в источнике Debezium подхватывает сам на первом DML после ALTER, настройки не нужны.
- После `docker kill` политика `unless-stopped` контейнер не поднимает, скрипт делает `docker start`.

Реплеер (прочитано в коде):

- `REPLAY_DUPLICATE_RATIO` делает повторный UPDATE с теми же значениями. Это новая WAL-запись с **новым** LSN, `before` = `after`. Метрика дублей по `(source_table, key, lsn)` его не видит.
- `REPLAY_LATE_RATIO` сдвигает событие `delivered` в виртуальном времени, а комментарий в `settings.py` говорит «real time». Сдвинутое событие всё равно получает больший LSN, так что guard в silver этой ручкой не проверяется.

Живой стек 26.09: в bronze 518 461 событие, невалидных 0 (бэкфилл карантина не нужен); silver.orders 4 файла в spec 0, CoW; Kafka-топики CDC пусты по retention; реплей стоит на виртуальном 2026-06-27, до горизонта 86 виртуальных дней (43 мин при 2880x).

## 3. Дизайн по задачам

### W2-T00 `source_sequence` в bronze (ADR-022)

- `ENVELOPE.source` получает `sequence` (string). Bronze хранит его как есть, текстом, колонкой `source_sequence string` сразу после `lsn`. Разбор в два bigint откладывается до момента, когда silver начнёт по нему упорядочивать: bronze хранит источник, а не интерпретацию (ADR-008).
- DDL для чистого старта содержит колонку на месте. Для живой таблицы job при старте проверяет схему и делает `alter table ... add column source_sequence string after lsn`, если колонки нет; второй запуск ничего не делает.
- `contracts/cdc-envelope.schema.json`: `source.sequence`, строка или null, в `required` (тест требует, чтобы bronze читал только обязательные поля). Фикстура `orders_r_initial.json` получает реальную форму `[null,"..."]`.
- Тесты: `to_bronze` сохраняет текст; событие без `sequence` даёт null; порядок колонок `to_bronze` равен порядку DDL (иначе check-ordering роняет стрим); миграция на локальном Iceberg идемпотентна.
- Пайплайн: checkpoint bronze не трогается, нужен rebuild образа и рестарт `spark-bronze`. Silver читает bronze по именам колонок, новая колонка ему не мешает; проверяется тестом со сменой схемы bronze между двумя запусками одного checkpoint.
- ADR-022 фиксирует семантику элементов и ограничения (первый элемент null, устаревший первый элемент после `docker kill` Connect). ADR-021 правится в одной фразе о формате sequence.

### W2-T03 layout silver (ADR-010)

- В `silver_upsert.py` словарь раскладки: `orders` получает партицию `months(order_purchase_timestamp)` и свойства `write.merge.mode`, `write.update.mode`, `write.delete.mode` = `merge-on-read`, `write.delete.granularity` = `file` явно. Остальные таблицы без изменений (CoW по умолчанию).
- `ensure_table` сводит таблицу к раскладке: при создании пишет `partitioned by` и `tblproperties`; для существующей читает `show tblproperties` и `describe table` и применяет только недостающее (`set tblproperties`, `add partition field`), с одной строкой в лог. Это только метаданные, без переписывания. Схема, наоборот, по-прежнему не сводится, а роняет job (изменение схемы идёт через контракт).
- Замер для ADR-010: порция реплея на CoW, `make silver`, замер; раскладка применяется; такая же порция, `make silver`, замер. Метрики: время MERGE по `orders` из лога, из `$snapshots.summary` added/removed files и bytes, число delete files из `$files`. Потом `ALTER TABLE lake.silver.orders EXECUTE optimize` в Trino: delete files уходят, старые файлы переписываются в spec 1. Это снапшот `replace`, silver его не стримит.
- Комментарий к `silver_shuffle_partitions` в `settings.py`: значение заморожено в checkpoint.

### W2-T04 `silver.quarantine`

- Таблица `lake.silver.quarantine`, format v2, без партиций: `topic, kafka_partition, kafka_offset, source_table, reason, op, key, lsn, payload, ingest_ts, quarantined_at, batch_id`. `payload` это `after`, для delete `before`, для неразобранного конверта `raw`.
- Одна причина на событие, первая по порядку:

| reason | Когда |
|---|---|
| `unparsed_envelope` | `op` null (bronze сохранил `raw`) |
| `unknown_op` | `op` не из `c, u, d, r` |
| `no_contract` | для `source_table` нет контракта |
| `null_key` | колонка ключа null после разбора (в том числе нечитаемый JSON) |
| `type_mismatch` | поле есть в payload, а после разбора и приведения null |
| `null_required` | NOT NULL колонка null, для всего, кроме delete |

- `type_mismatch` новый. Сейчас неверный тип в nullable колонке молча превращается в null и строка мержится. Ловится вторым разбором payload как `map<string,string>`: значение в map есть, типизированное null. Цена: ещё один `from_json` на строку.
- Попутно тот же map даёт список ключей, которых нет в контракте. Silver пишет их одной строкой в лог на таблицу и батч (`orders: 12 events carry fields the contract does not know: [sales_channel]`). Это не карантин, а сигнал для schema evolution в W2-T07.
- Запись: `merge into quarantine ... on (topic, kafka_partition, kafka_offset) when not matched then insert *`. Повтор батча не дублирует карантин.
- `scripts/chaos/poison-event.sh` появляется здесь, потому что DoD задачи это «poison event не роняет job»: пишет мусор в `oltp.shop.orders`, ждёт bronze, запускает silver, показывает строку в карантине. Мониторинг части chaos 7 остаётся на W4. Метрика `quarantine_rows_total` не делается: это Modify-гейт observability владельца.

### W2-T05 chaos 1-4

Общее: `scripts/chaos/lib.sh` (env, compose, запрос в Trino, ожидание healthy, порция реплея, сверка `count(*)` Postgres против silver по семи таблицам). Каждый сценарий печатает проверочный SQL и итог, в `OPERATIONS.md` пять ответов с фактическими цифрами. Порция реплея запускается на хосте (`timeout <сек> uv run python -m replayer start`) с пониженной скоростью.

1. `chaos-spark-kill`: во время порции ждёт идущий Spark job (REST API UI на 4040), `docker kill`, `docker start`, ждёт healthy и догона. Проверка: нет дублей и дыр по `(topic, kafka_partition, kafka_offset)`, `Resuming at batch N` в логе, последние снапшоты с `epochId`. Сам пропуск эпохи доказывается детерминированно тестом в `make test-spark`: стрим в локальный Iceberg, удалить `commits/N` своего checkpoint, перезапуск, строк и снапшотов не прибавилось. Результат в ADR-007. Раннбук `docs/runbooks/spark-stalled.md`.
2. `chaos-connect-restart`: `MODE=restart` (по умолчанию, ожидаем 0 дублей) и `MODE=kill` (ожидаем дубли с теми же LSN). Проверка: дубли по `(source_table, key, lsn)` в окне, silver совпадает с Postgres. Раздел 8 архитектурного ревью и таблица в `OPERATIONS.md` получают 2a и 2b. Раннбук `docs/runbooks/connector-failed.md`.
3. `chaos-duplicates`: порция с `REPLAY_DUPLICATE_RATIO=0.1`. Проверка: доля no-op UPDATE (`op = 'u'` и `before = after`) в окне, дублей по LSN 0, silver совпадает с Postgres. В тексте: такие дубли не видны метрике по LSN и безвредны для silver, потому что MERGE перезаписывает строку теми же значениями.
4. `chaos-late`: ручка реплея позднего прихода не создаёт, поэтому сценарий делает то, что делает Debezium при повторе: берёт из Kafka более старое событие того же заказа (например `shipped`, когда silver уже видел `delivered`) и публикует его заново с тем же ключом. Проверка: bronze получил событие с меньшим LSN, silver после `make silver` по-прежнему `delivered` и `_last_lsn` не изменился. Комментарий в `settings.py` про «real time» исправляется на виртуальное время, в OPERATIONS пояснение, для чего ручка нужна (event time в W5-T01).

Коммиты: по одному на сценарий. Это отступление от «одна задача, один коммит» в сторону меньших диффов.

### W2-T06 `make iceberg-demo`

- Spark-job `spark_jobs/iceberg_demo.py`, запускается в контейнере `spark-silver` с другой командой: `make iceberg-demo` = `compose run --rm --no-deps spark-silver iceberg_demo`. Spark, а не Trino, потому что процедуры `CALL lake.system.*` это каноничный API Iceberg.
- Песочница `lake.demo.orders`, пересоздаётся на каждом запуске (`drop table ... purge`, разрешено). Шаги: CTAS 1 000 строк из `silver.orders` (только чтение), 20 маленьких вставок; снапшоты и `.files`; `VERSION AS OF` первого снапшота против текущего; «случайный» DELETE, `rollback_to_snapshot`, `set_current_snapshot` для отмены отката; `rewrite_data_files(options => map('min-input-files','2'))` и файлы до/после; `expire_snapshots(older_than => TIMESTAMP '<сейчас>', retain_last => 1)` и падение time travel на удалённый снапшот. Время для `CALL` форматируется в Python литералом (грамматика не принимает функции), сессия в UTC.
- В конце печатаются те же запросы для Trino (`FOR VERSION AS OF`, `$snapshots`, `$files`), чтобы Operate-гейт делался руками.
- `bronze` и `silver` демо не трогает. Тест в `make test-spark` прогоняет демо целиком на локальном каталоге.

### W2-T07 schema evolution, сторона реплеера

- `oltp/migrations/evolution/003_orders_sales_channel.sql`: `alter table shop.orders add column sales_channel varchar(16)` с check на три значения, без default (старые строки null). Подкаталог, потому что `make migrate` берёт только `migrations/*.sql`.
- Реплеер: если `REPLAY_SCHEMA_EVOLUTION_AT` задан, миграция ещё не записана в `public.schema_migrations` и виртуальное время дошло до отметки, применяет её тем же `migrations.apply`, пишет в лог и метрику, дальше вставляет заказы с `sales_channel` (детерминированно по `md5(order_id)`). Настройка парсится в `datetime | None`, пустая строка это «никогда».
- `test_contracts` читает колонки из `001_schema.sql` и из `evolution/`: контракт обязан содержать все колонки 001 в порядке, колонки из evolution может содержать или нет. После гейта владельца тест не краснеет.
- Проверка на живом стеке: порция реплея с отметкой в её середине; колонка в Postgres, новые заказы с `sales_channel`, в bronze `after` с полем, silver не упал и пишет строку про неизвестное поле (из W2-T04).
- Подсказка для гейта: какие файлы и какой `ALTER`, в `HANDOFF.md`.

### W2-T09 Lakekeeper (лимит 3 ч)

Факты, которые меняют план из ADR-005:

- Пин `v0.13.1` меняется на `v0.13.6` по digest: в 0.13.1 два бага, мешающих этому стеку (#1923, #1952).
- Образ distroless, без shell и curl: healthcheck в compose никогда не пройдёт. Нужен one-shot `lakekeeper-migrate` перед `serve` и exec-healthcheck `/home/nonroot/lakekeeper healthcheck`; bootstrap и warehouse делает one-shot на `curl` или скрипт с хоста, идемпотентно.
- `s3a://` принимается только с `allow-alternative-protocols: true` в storage profile. Новые таблицы Lakekeeper создаёт по `s3://...`, которые Hadoop 3.3.4 без `fs.s3.impl` не открывает.
- Spark: `io-impl` надо закрепить на `HadoopFileIO`, иначе REST-клиент пытается взять `S3FileIO` без AWS SDK v2 в образе.
- `DROP TABLE` через Lakekeeper удаляет файлы и у зарегистрированных таблиц, а они общие с JDBC-каталогом. Отмена регистрации только через `purgeRequested=false` или `overwrite`.
- Переключение: остановить writers, зарегистрировать текущие `metadata_location` из `iceberg_catalog.iceberg_tables`, сравнить в Trino через временный второй каталог, переключить `CATALOG_TYPE=rest` и `lake.properties`, запустить. JDBC-строки не трогаются и остаются точкой отката.

Порядок: (1) compose и bootstrap без переключения, обратимо; (2) регистрация и сверка side-by-side; (3) переключение. Перед (1) владелец решает во всплывающем вопросе: `s3://` или `s3a://` для новых таблиц, soft delete profile, отдельный ключ шифрования в `.env`, добавить «DROP TABLE на REST = удаление файлов» в blast radius. Перед (3) отдельное «ок». Лимит превышен на (1) или (2): ADR-005 с причиной, JDBC остаётся.

## 4. Порядок и коммиты

| # | Задача | Область | Зависит от |
|---|---|---|---|
| 1 | W2-T00 `source_sequence` | `stream` | |
| 2 | W2-T03 layout | `lake` | |
| 3 | W2-T04 quarantine | `lake` | |
| 4 | W2-T05 chaos 1 | `stream` | 1 |
| 5 | W2-T05 chaos 2 | `cdc` | 1 |
| 6 | W2-T05 chaos 3 | `oltp` | 3 |
| 7 | W2-T05 chaos 4 | `lake` | 3 |
| 8 | W2-T06 demo | `lake` | |
| 9 | W2-T07 schema evolution | `oltp` | 3 |
| 10 | W2-T09 Lakekeeper | `lake` | все выше |
| 11 | HANDOFF, итоги W2 | `docs` | |

Бюджет реплея: на всю неделю не больше 20 виртуальных дней из 86 (порции по 1-3 дня на скорости 1440, то есть день в минуту). Остальное остаётся на Operate-гейты владельца. Реплеер между порциями стоит и продолжает с сохранённого виртуального времени.

## 5. Проверки для каждой задачи

- `make lint`, `make test`, `make test-spark` (новые Spark-файлы тестов вписываются в `SPARK_TESTS`).
- Первый тест пишется на отказ (дубль, late, невалидный JSON, повтор батча).
- Живая проверка DoD на стеке, вывод в сообщении коммита не нужен, но цифры идут в `OPERATIONS.md` или ADR.
- Ревью диффа в несколько линз (баги, silent failures, качество тестов, безопасность); каждая находка перепроверяется отдельным агентом до правки.
- Влияние на checkpoint, таблицы и offsets пишется явно. Если нужно что-то удалить, стоп и вопрос.
- Коммит `<область>: <что>` от имени владельца, без строк атрибуции.

## 6. Что замечено по дороге и не входит в W2

Кандидаты в `HANDOFF.md` на решение владельца:

- Bronze пишет каждые 20 с с 200 shuffle-партициями, замороженными в checkpoint: почти все 200 задач пустые. Поменять можно только новым checkpoint или опцией записи, это тема Spark Modify-гейта.
- Слот репликации не двигается, пока в `shop` нет изменений (pgoutput пропускает пустые транзакции, heartbeat не флашит LSN). Для chaos 6 и алерта `SlotWalRetainedHigh`: на простое растёт незахваченный WAL реплеера, а не отказ коннектора. Лечится `heartbeat.action.query`, это новая таблица и топик, значит ADR.
- Bronze копит `metadata.json` (около 4 300 в день); `expire_snapshots` их не удаляет. Свойство `write.metadata.delete-after-commit.enabled` или `remove_orphan_files` в W5.
- `expire_snapshots` на bronze запрещён до решения по #18000; кандидат это async planner, он требует эксперимента на песочнице и может молча пропустить данные, если истёк закоммиченный снапшот.
- W3: у dbt-trino `on_table_exists` по умолчанию `rename`, это `DROP TABLE` бэкапа на каждом прогоне (blast radius и потеря истории). Предложение `replace`, решение в спеке W3.
- Env `KEY_CONVERTER_SCHEMAS_ENABLE` в compose Connect игнорируется образом; безвредно, потому что конфиг коннектора ставит false сам.
