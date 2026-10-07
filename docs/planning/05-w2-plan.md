# 05. План реализации: остаток недели 2

> **Для агента-исполнителя:** обязательный sub-skill `superpowers:executing-plans` (исполнение в этой сессии) или `superpowers:subagent-driven-development`. Шаги отмечаются чекбоксами `- [ ]`.

**Цель:** закрыть W2 по спеке: `source_sequence` в bronze, раскладка silver, карантин, chaos 1-4, Iceberg-демо, schema evolution в реплеере, попытка Lakekeeper.

**Архитектура:** все изменения внутри существующих звеньев. Bronze остаётся append-only стримом, silver остаётся одним AvailableNow-job с MERGE по таблице; добавляются таблица `silver.quarantine`, демо-job в том же образе, chaos-скрипты в `scripts/chaos/`, миграция 003 вне `make migrate`.

**Стек:** PySpark 3.5.9 + Iceberg 1.11.0 (JDBC catalog), Debezium 3.5, Kafka 4.3.1, Trino 483, PostgreSQL 17, Python 3.12 на хосте и 3.10 в Spark-образе, bash.

**Спека:** `docs/planning/04-w2-spec.md` (утверждена 26.09.2026). Исполнитель читает обе.

## Глобальные ограничения

- Код в `streaming/` работает на Python 3.10: никакого синтаксиса 3.11+, никаких `datetime.UTC`.
- Колонки Iceberg добавляются только nullable; `ADD COLUMN IF NOT EXISTS` не существует, код проверяет схему сам.
- Streaming sink в bronze требует порядок колонок DataFrame, равный порядку в таблице.
- Порты только `127.0.0.1`, секреты только из `.env`.
- Ни одного `DROP`, `DELETE`, `expire_snapshots`, `remove_orphan_files`, `rollback` вне `lake.demo.*` без «ок» владельца.
- Порции реплея: `PYTHONPATH=oltp REPLAY_SPEED=<скорость> timeout <сек> .venv/bin/python -m replayer start` (не через `make`: `timeout` должен попасть в сам процесс реплеера). Замеры W2-T03 на 1440, chaos на 720; в сумме не больше 20 виртуальных дней за неделю. Запуск `make up PROFILE=core` запрещён: он поднимет контейнер реплеера на полной скорости. Сервисы поднимаются по имени.
- Коммит `<область>: <что>`, без строк атрибуции, после зелёных `make lint`, `make test`, `make test-spark` и ревью.
- Новые Spark-файлы тестов вписываются в `SPARK_TESTS` в `Makefile`.
- Тексты для владельца на русском, код, README, OPERATIONS, DECISIONS на английском; нигде нет длинного тире.

## Review Focus

Входы, которые спека подразумевает, но легко упустить; тест на каждый вписан в задачу-владельца:

1. Повторный старт `spark-bronze` после того, как колонка уже добавлена (второй `ensure_table`), не должен падать и не должен писать метаданные. Задача 1.
2. Батч, в котором все события таблицы невалидны, не меняет ни одной строки silver и не падает на пустом MERGE. Задача 3.
3. Одни и те же координаты Kafka дважды в одном батче (дубль в bronze) не дублируют карантин. Задача 3.
4. Явный JSON `null` в nullable колонке это валидное событие, не `type_mismatch`. Задача 3.
5. `REPLAY_SCHEMA_EVOLUTION_AT` раньше текущего виртуального времени при старте реплеера применяет миграцию на первом шаге, а после рестарта не применяет второй раз. Задача 9.

---

### Задача 1: W2-T00 `source_sequence` в bronze

**Файлы:**
- Изменить: `streaming/spark_jobs/bronze_cdc_ingest.py`
- Изменить: `contracts/cdc-envelope.schema.json`, `tests/fixtures/envelopes/orders_r_initial.json`
- Изменить: `tests/unit/test_bronze_cdc_ingest.py`, `tests/unit/test_silver_upsert.py`
- Изменить: `DECISIONS.md` (ADR-022, строка в ADR-021), `OPERATIONS.md` (Bronze ingest)

**Интерфейсы:**
- Производит: колонку `source_sequence string` сразу после `lsn` в `lake.bronze.cdc_events`; функцию `ensure_table(spark: SparkSession) -> None` в `bronze_cdc_ingest`; константу `ADDED_COLUMNS: tuple[tuple[str, str, str], ...]`.

- [ ] **Шаг 1: падающие тесты в `test_bronze_cdc_ingest.py`**

`envelope()` получает параметр `sequence`, в `source` он пишется только если не `None`:

```python
def envelope(
    op: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    sequence: str | None = '["40","42"]',
) -> bytes:
    source: dict[str, Any] = {
        "lsn": 42,
        "ts_ms": 1_700_000_000_000,
        "table": "orders",
        "schema": "shop",
    }
    if sequence is not None:
        source["sequence"] = sequence
    event = {
        "op": op,
        "ts_ms": 1_700_000_000_500,
        "before": before,
        "after": after,
        "source": source,
    }
    return json.dumps(event).encode()
```

Новые тесты:

```python
@needs_java
def test_sequence_is_kept_as_the_text_debezium_sent(spark: SparkSession) -> None:
    [row] = bronze(spark, kafka_row(envelope("u", {"order_id": "o1"}, {"order_id": "o1"})))

    assert row.source_sequence == '["40","42"]'


@needs_java
def test_envelope_without_sequence_gives_null(spark: SparkSession) -> None:
    [row] = bronze(spark, kafka_row(envelope("c", None, {"order_id": "o1"}, sequence=None)))

    assert row.source_sequence is None


def ddl_columns() -> list[str]:
    body = re.search(r"\((.*?)\n\)", DDL, re.S)
    assert body is not None
    return [line.split()[0] for line in body.group(1).strip().splitlines()]


@needs_java
def test_columns_come_out_in_table_order(spark: SparkSession) -> None:
    """The Iceberg sink checks column order; a column out of place fails the stream."""
    frame = to_bronze(spark.createDataFrame([kafka_row(b"{}")], KAFKA_SOURCE))

    assert frame.columns == ddl_columns()


def test_every_added_column_is_in_the_ddl_after_its_neighbour() -> None:
    columns = ddl_columns()
    for name, _, after in ADDED_COLUMNS:
        assert columns.index(name) == columns.index(after) + 1
```

Импорты: `import re`, `from spark_jobs.bronze_cdc_ingest import ADDED_COLUMNS, DDL, ENVELOPE, to_bronze`.

- [ ] **Шаг 2: убедиться, что тесты падают**

Run: `make test-spark`
Expected: FAIL, `ImportError: cannot import name 'ADDED_COLUMNS'`.

- [ ] **Шаг 3: реализация в `bronze_cdc_ingest.py`**

В `ENVELOPE.source` добавить поле:

```python
(StructField("lsn", LongType()),)
(StructField("sequence", StringType()),)
```

В `DDL` после `lsn bigint,`:

```
    lsn bigint,
    source_sequence string,
```

После `DDL`:

```python
# Columns added after the table first shipped, as (name, type, after). The DDL above already has
# them in place for a fresh start; ensure_table adds them to an older table, where they must land
# in the same position because the streaming sink checks column order.
ADDED_COLUMNS = (("source_sequence", "string", "lsn"),)


def ensure_table(spark: SparkSession) -> None:
    """Create bronze, or add the columns it gained since. Iceberg has no ADD COLUMN IF NOT
    EXISTS, so the check is ours; a second run changes nothing."""
    spark.sql(DDL)
    existing = set(spark.table(TABLE).columns)
    for name, kind, after in ADDED_COLUMNS:
        if name not in existing:
            spark.sql(f"alter table {TABLE} add column {name} {kind} after {after}")
```

В `to_bronze` после `env["source"]["lsn"].alias("lsn"),`:

```python
# [end of the previous transaction's commit record, this change's LSN] as text (ADR-022).
(env["source"]["sequence"].alias("source_sequence"),)
```

В `main()` заменить `spark.sql(DDL)` на `ensure_table(spark)`; импорт `SparkSession` из `pyspark.sql`.

- [ ] **Шаг 4: контракт и фикстура**

`contracts/cdc-envelope.schema.json`, в `source.required` добавить `"sequence"`, в `source.properties`:

```json
"sequence": {"type": ["string", "null"], "description": "[end LSN of the previous transaction's commit, LSN of this change] as a JSON array in a string; the first element is null until the connector has seen a commit (ADR-022)"}
```

`orders_r_initial.json`: `"sequence": "[null,\"987654320\"]"` (так выглядит строка initial snapshot).

- [ ] **Шаг 5: silver переживает новую колонку в bronze**

В `test_silver_upsert.py`: `BRONZE_COLUMNS` получает `source_sequence string` после `lsn bigint`, `event()` получает параметр `sequence: str | None = None` и поле `source_sequence=sequence` сразу после `lsn=lsn`. Новый тест:

```python
from spark_jobs.bronze_cdc_ingest import ensure_table as ensure_bronze

OLD_BRONZE_DDL = BRONZE_DDL.replace("    source_sequence string,\n", "")


@needs_iceberg
@pytest.mark.usefixtures("fresh_silver")
def test_run_survives_a_column_added_to_bronze_between_runs(
    spark: SparkSession, tmp_path: Path
) -> None:
    spark.sql(f"create namespace if not exists {BRONZE_NAMESPACE}")
    spark.sql(f"drop table if exists {BRONZE}")
    spark.sql(OLD_BRONZE_DDL)
    checkpoint = f"file://{tmp_path}/checkpoint"
    bronze(spark, event("c", order(), lsn=100)).drop("source_sequence").writeTo(BRONZE).append()
    run(spark, CONTRACTS, checkpoint, max_rows_per_batch=10)

    ensure_bronze(spark)
    ensure_bronze(spark)
    columns = spark.table(BRONZE).columns
    bronze(spark, event("u", order(status="approved"), lsn=120, sequence='["110","120"]')).writeTo(
        BRONZE
    ).append()
    run(spark, CONTRACTS, checkpoint, max_rows_per_batch=10)

    assert columns[columns.index("lsn") + 1] == "source_sequence"
    assert silver(spark)["o1"].order_status == "approved"
```

- [ ] **Шаг 6: тесты зелёные**

Run: `make test && make test-spark`
Expected: всё PASS, новые тесты в числе прошедших.

- [ ] **Шаг 7: ADR и OPERATIONS**

`DECISIONS.md`: строка таблицы `| ADR-022 | Bronze keeps Debezium's source.sequence as text; silver keeps ordering by lsn until concurrent writers appear | accepted |` и раздел:

```markdown
## ADR-022 Bronze keeps the commit position (`source.sequence`)

Context: ADR-021 orders changes of one key by `lsn`, the start of the change's WAL record. That
is commit order only with a single writer. Debezium's `source.sequence` is a JSON array in a
string, `[end of the previous transaction's commit record, LSN of this change]`, and compared as
two numbers it follows commit order across transactions and WAL order inside one. Incremental
snapshot reads have a null `lsn` but a sequence: the position of the chunk's close watermark,
which is what would let a snapshot read be compared with streamed changes (ADR-019).

Decision: bronze stores it verbatim as `source_sequence string`, right after `lsn`. Silver keeps
ordering by `lsn` for now; parsing the pair and switching the MERGE guard is a separate change
once there is a second writer or a real gap to repair. Bronze adds the column on start
(`ensure_table`), without a rewrite and without touching the checkpoint.

Consequences: rows ingested before 2026-09-26 have a null sequence and cannot be backfilled,
Kafka no longer holds them. The first element is null for initial snapshot rows and for the
first transaction after one. After a `docker kill` of Connect the first re-sent transaction can
carry a first element that is too small, because the slot is flushed from the last acked record,
not from the stored offset; a sequence-based guard would have to tolerate that.
```

В ADR-021 заменить `` (`[last commit LSN, LSN]`) `` на `` (`[end of the previous transaction's commit, LSN]`, ADR-022) `` и `which bronze does not store; adding it is a bronze contract change for the owner to decide.` на `which bronze stores since ADR-022; silver does not use it yet.`

`OPERATIONS.md`, раздел Bronze ingest, пункт: `Schema changes of bronze itself are additive and applied on start: ensure_table adds a missing column in its table position; the checkpoint is unaffected.`

- [ ] **Шаг 8: живая проверка**

```bash
docker compose --env-file .env -f docker/compose.yaml --profile core up -d --build spark-bronze
docker logs lakehouse-spark-bronze-1 2>&1 | grep -i 'source_sequence\|Resuming at batch'
make trino   # describe bronze.cdc_events;  -> source_sequence varchar после lsn
PYTHONPATH=oltp REPLAY_SPEED=1440 timeout 30 .venv/bin/python -m replayer start; sleep 30
make trino   # select count(*), count(source_sequence) from bronze.cdc_events where ingest_ts > current_timestamp - interval '5' minute;  -> оба > 0 и равны
make silver  # отрабатывает без ошибок
```

Ожидаемо: контейнер healthy, `Resuming at batch N` (checkpoint жив), у новых строк `source_sequence` заполнен.

- [ ] **Шаг 9: ревью и коммит**

Ревью-воркфлоу по диффу, правки, затем:

```bash
git add streaming/spark_jobs/bronze_cdc_ingest.py contracts/cdc-envelope.schema.json tests/fixtures/envelopes/orders_r_initial.json tests/unit/test_bronze_cdc_ingest.py tests/unit/test_silver_upsert.py DECISIONS.md OPERATIONS.md
git commit -m "stream: source_sequence in bronze, commit position kept for later ordering"
```

---

### Задача 2: W2-T03 раскладка silver (ADR-010)

**Файлы:**
- Изменить: `streaming/spark_jobs/silver_upsert.py`, `streaming/spark_jobs/settings.py`
- Изменить: `tests/unit/test_silver_upsert.py`
- Изменить: `DECISIONS.md` (ADR-010), `OPERATIONS.md` (Silver upsert)

**Интерфейсы:**
- Потребляет: `ensure_table(spark, contract)` из текущего `silver_upsert.py`.
- Производит: `MERGE_ON_READ: dict[str, str]`, `PARTITIONS: dict[str, tuple[str, ...]]`, `PROPERTIES: dict[str, dict[str, str]]`, `partition_fields(spark, table) -> set[str]`, `converge_layout(spark, table, partitions, properties) -> None`; строка лога `batch %s: %s events merged into %s.%s in %.1f s`.

- [ ] **Шаг 1: падающие тесты**

```python
from spark_jobs.silver_upsert import MERGE_ON_READ, METADATA, partition_fields


def properties(spark: SparkSession, table: str) -> dict[str, str]:
    return {r.key: r.value for r in spark.sql(f"show tblproperties {table}").collect()}


@needs_iceberg
@pytest.mark.usefixtures("fresh_silver")
def test_orders_is_merge_on_read_and_partitioned_by_month(spark: SparkSession) -> None:
    table = f"{SILVER}.orders"
    merge_batch(bronze(spark, event("c", order(), lsn=100)), 0, CONTRACTS)
    merge_batch(bronze(spark, event("u", order(status="shipped"), lsn=200)), 1, CONTRACTS)

    assert {k: properties(spark, table).get(k) for k in MERGE_ON_READ} == MERGE_ON_READ
    assert partition_fields(spark, table) == {"months(order_purchase_timestamp)"}
    # The update masked the inserted row with a position delete instead of rewriting its file.
    assert spark.table(f"{table}.delete_files").count() == 1
    assert silver(spark)["o1"].order_status == "shipped"


@needs_iceberg
@pytest.mark.usefixtures("fresh_silver")
def test_other_tables_stay_copy_on_write_and_unpartitioned(spark: SparkSession) -> None:
    table = f"{SILVER}.customers"

    assert "write.merge.mode" not in properties(spark, table)
    assert partition_fields(spark, table) == set()


@needs_iceberg
@pytest.mark.usefixtures("fresh_silver")
def test_existing_copy_on_write_orders_converges_once(spark: SparkSession) -> None:
    table = f"{SILVER}.orders"
    spark.sql(f"drop table {table}")
    metadata = ", ".join(f"{name} {kind}" for name, kind in METADATA)
    spark.sql(
        f"create table {table} ({ORDERS.column_ddl}, {metadata}) "
        "using iceberg tblproperties ('format-version' = '2')"
    )

    ensure_table(spark, ORDERS)
    versions = spark.table(f"{table}.metadata_log_entries").count()
    ensure_table(spark, ORDERS)

    assert spark.table(f"{table}.metadata_log_entries").count() == versions
    assert properties(spark, table)["write.merge.mode"] == "merge-on-read"
    assert partition_fields(spark, table) == {"months(order_purchase_timestamp)"}
```

- [ ] **Шаг 2: убедиться, что тесты падают**

Run: `make test-spark`
Expected: FAIL, `ImportError: cannot import name 'MERGE_ON_READ'`.

- [ ] **Шаг 3: реализация**

После `METADATA`:

```python
# Physical layout (ADR-010). An order changes status several times after it is inserted, so its
# MERGE writes position deletes instead of rewriting whole files; the other tables rarely change
# a row twice and stay copy-on-write.
MERGE_ON_READ = {
    "write.merge.mode": "merge-on-read",
    "write.update.mode": "merge-on-read",
    "write.delete.mode": "merge-on-read",
    # Already Spark's default, but the Iceberg docs list `partition`, so it is spelled out.
    "write.delete.granularity": "file",
}
PARTITIONS: dict[str, tuple[str, ...]] = {"orders": ("months(order_purchase_timestamp)",)}
PROPERTIES: dict[str, dict[str, str]] = {"orders": MERGE_ON_READ}
```

Новые функции и `ensure_table`:

```python
def partition_fields(spark: SparkSession, table: str) -> set[str]:
    """Partition transforms as DESCRIBE prints them, e.g. `months(order_purchase_timestamp)`."""
    rows = spark.sql(f"describe table {table}").collect()
    return {r["data_type"] for r in rows if r["col_name"].startswith("Part ")}


def converge_layout(
    spark: SparkSession, table: str, partitions: tuple[str, ...], properties: dict[str, str]
) -> None:
    """Bring an existing table to its layout. Metadata only: files already written keep their
    old spec and write mode until compaction rewrites them."""
    current = {r["key"]: r["value"] for r in spark.sql(f"show tblproperties {table}").collect()}
    missing = {k: v for k, v in properties.items() if current.get(k) != v}
    if missing:
        pairs = ", ".join(f"'{k}' = '{v}'" for k, v in sorted(missing.items()))
        spark.sql(f"alter table {table} set tblproperties ({pairs})")
        log.info("%s: set %s", table, pairs)
    fields = partition_fields(spark, table)
    for transform in partitions:
        if transform not in fields:
            spark.sql(f"alter table {table} add partition field {transform}")
            log.info("%s: partitioned by %s from now on", table, transform)


def ensure_table(spark: SparkSession, contract: TableContract) -> None:
    """Create the silver table, or fail with the fix if it no longer matches its contract, then
    converge its layout. Schema evolution is deliberate: contract first, then ALTER TABLE
    (contracts/README.md). Layout is physical and converges on its own."""
    table = f"{SILVER}.{contract.table}"
    partitions = PARTITIONS.get(contract.table, ())
    properties = PROPERTIES.get(contract.table, {})
    metadata_ddl = ", ".join(f"{name} {kind}" for name, kind in METADATA)
    partitioned = f" partitioned by ({', '.join(partitions)})" if partitions else ""
    pairs = ", ".join(f"'{k}' = '{v}'" for k, v in {"format-version": "2", **properties}.items())
    spark.sql(
        f"create table if not exists {table} ({contract.column_ddl}, {metadata_ddl}) "
        f"using iceberg{partitioned} tblproperties ({pairs})"
    )
    expected = {(c.name, c.silver_type) for c in contract.columns} | set(METADATA)
    actual = {(f.name, f.dataType.simpleString()) for f in spark.table(table).schema.fields}
    if actual != expected:
        raise RuntimeError(
            f"{table} does not match contracts/silver/{contract.table}.json: "
            f"missing {sorted(expected - actual)}, unexpected {sorted(actual - expected)}. "
            "Align the contract and the table (ALTER TABLE ... ADD COLUMN) first."
        )
    converge_layout(spark, table, partitions, properties)
```

В `merge_batch` время MERGE в лог:

```python
started = time.monotonic()
spark.sql(merge_sql(f"{SILVER}.{table}", view, contract))
images.unpersist()
log.info(
    "batch %s: %s events merged into %s.%s in %.1f s",
    batch_id,
    events,
    SILVER,
    table,
    time.monotonic() - started,
)
```

`settings.py`, комментарий к `silver_shuffle_partitions`:

```python
    # local[2] has two cores; the default 200 would write up to 200 small files per MERGE.
    # Spark stores the value in the checkpoint on the first run and restores it on every later
    # one, so changing it takes effect only with a new checkpoint.
```

- [ ] **Шаг 4: тесты зелёные**

Run: `make test && make test-spark`
Expected: PASS. Если `partition_fields` не видит поле, распечатать `describe table` в тесте и поправить фильтр по фактическому выводу.

- [ ] **Шаг 5: замер CoW на живом стеке (образ ещё со старым silver)**

```bash
PYTHONPATH=oltp REPLAY_SPEED=1440 timeout 120 .venv/bin/python -m replayer start; sleep 40
make silver 2>&1 | grep 'merged into lake.silver.orders'
make trino   # select committed_at, operation, element_at(summary,'added-data-files') add_f, element_at(summary,'deleted-data-files') del_f, element_at(summary,'added-files-size') add_b, element_at(summary,'removed-files-size') rem_b, element_at(summary,'added-position-delete-files') pos_f from silver."orders$snapshots" order by committed_at desc limit 3;
```

Записать: число событий orders, время MERGE, байты added/removed.

- [ ] **Шаг 6: применить раскладку и замерить MoR**

```bash
docker compose --env-file .env -f docker/compose.yaml --profile core build spark-bronze
PYTHONPATH=oltp REPLAY_SPEED=1440 timeout 120 .venv/bin/python -m replayer start; sleep 40
make silver 2>&1 | grep -E 'lake.silver.orders: set|partitioned by|merged into lake.silver.orders'
make trino   # тот же запрос по $snapshots; select content, spec_id, count(*), sum(record_count) from silver."orders$files" group by 1, 2;
```

Ожидаемо: строки `set 'write.delete.granularity' ...` и `partitioned by months(...)` один раз, MERGE пишет новые файлы в spec 1 и position delete files вместо переписывания четырёх файлов.

- [ ] **Шаг 7: compaction в Trino**

```bash
make trino   # alter table silver.orders execute optimize;
make trino   # select content, spec_id, count(*) from silver."orders$files" group by 1, 2;  -> только content 0, spec_id 1
             # select count(*) from silver.orders where not _is_deleted; -> = shop.orders
```

Это снапшот `replace`, silver его не стримит, blast radius нет.

- [ ] **Шаг 8: ADR-010 и OPERATIONS**

Статус ADR-010 в таблице: `accepted, measured 2026-09-26`. Раздел ADR-010 с цифрами из шагов 5-7 (время MERGE, bytes added/removed на порцию, delete files, результат optimize) и выводом. `OPERATIONS.md`, Silver upsert: `silver.orders is merge-on-read and partitioned by month; ensure_table converges an older table on the next run (metadata only). Delete files accumulate until compaction: alter table silver.orders execute optimize (Trino) folds them and rewrites old files into the current spec.`

- [ ] **Шаг 9: ревью и коммит**

```bash
git add streaming/spark_jobs/silver_upsert.py streaming/spark_jobs/settings.py tests/unit/test_silver_upsert.py DECISIONS.md OPERATIONS.md
git commit -m "lake: silver.orders merge-on-read, partitioned by month, adr-010 measured"
```

---

### Задача 3: W2-T04 `silver.quarantine`

**Файлы:**
- Изменить: `streaming/spark_jobs/silver_upsert.py`
- Изменить: `tests/unit/test_silver_upsert.py`
- Создать: `scripts/chaos/lib.sh`, `scripts/chaos/poison-event.sh`
- Изменить: `OPERATIONS.md` (Silver upsert, chaos 7), `contracts/README.md` (строка про неверный тип)

**Интерфейсы:**
- Потребляет: `latest_per_key`, `merge_sql`, `ensure_table` из задачи 2.
- Производит: `QUARANTINE`, `QUARANTINE_DDL`, `row_images(events, contract)` с колонками `_reason`, `_fields`, `_payload` и сохранёнными колонками bronze; `reason(contract) -> Column`; `unknown_fields(images, contract) -> list[str]`; `quarantine_rows(events, reason, payload, batch_id) -> DataFrame`; `quarantine(rows) -> None`; `merge_table(events, count, batch_id, contract) -> None`. Функция `valid` удаляется. В `lib.sh`: `trino`, `trino_value`, `psql_value`, `kafka`, `wait_until`, `run_silver`.

- [ ] **Шаг 1: падающие тесты**

Хелперы в тесте:

```python
from spark_jobs.silver_upsert import QUARANTINE, QUARANTINE_DDL, unknown_fields


def latest(spark: SparkSession, *events: Row, contract: TableContract = ORDERS) -> list[Row]:
    images = row_images(bronze(spark, *events), contract)
    rows = latest_per_key(images.where("_reason is null"), contract).collect()
    return sorted(rows, key=lambda r: tuple(r[k] for k in contract.primary_key))


def reasons(spark: SparkSession, *events: Row, contract: TableContract = ORDERS) -> list[Any]:
    return [r._reason for r in row_images(bronze(spark, *events), contract).collect()]
```

Параметризованный тест вместо `test_invalid_event_is_not_merged`:

```python
@needs_java
@pytest.mark.parametrize(
    ("bad", "why"),
    [
        (event(None, raw="not json at all {"), "unparsed_envelope"),
        (event("t", order()), "unknown_op"),
        (event("c", after=None), "null_key"),
        (event("c", after={"order_status": "created"}), "null_key"),
        (event("c", order(order_purchase_timestamp="yesterday")), "type_mismatch"),
        (event("c", order(order_approved_at="yesterday")), "type_mismatch"),
        (event("c", order(order_estimated_delivery_date=None)), "null_required"),
    ],
    ids=[
        "unparsed-envelope",
        "truncate",
        "no-payload",
        "no-key",
        "wrong-type-required",
        "wrong-type-nullable",
        "null-required",
    ],
)
def test_invalid_event_is_not_merged_and_says_why(spark: SparkSession, bad: Row, why: str) -> None:
    rows = latest(spark, bad, event("c", order("o2"), lsn=100))

    assert [r.order_id for r in rows] == ["o2"]
    assert reasons(spark, bad) == [why]


@needs_java
def test_explicit_json_null_in_a_nullable_column_is_valid(spark: SparkSession) -> None:
    assert reasons(spark, event("c", order(order_approved_at=None))) == [None]


@needs_java
def test_fields_the_contract_does_not_know_are_reported(spark: SparkSession) -> None:
    images = row_images(bronze(spark, event("c", order(sales_channel="web"))), ORDERS)

    assert unknown_fields(images, ORDERS) == ["sales_channel"]
```

Iceberg-тесты; фикстура `fresh_silver` дополнительно делает `drop table if exists {QUARANTINE}` и `spark.sql(QUARANTINE_DDL)`:

```python
def quarantined(spark: SparkSession) -> list[Row]:
    return sorted(spark.table(QUARANTINE).collect(), key=lambda r: r.kafka_offset)


@needs_iceberg
@pytest.mark.usefixtures("fresh_silver")
def test_rejected_events_land_in_quarantine_once(spark: SparkSession) -> None:
    poison = event(None, raw="not json at all {")
    batch = bronze(
        spark,
        event("c", order(), lsn=100),
        poison,
        event("c", order("o3", order_approved_at="yesterday"), lsn=101),
        event("c", {"id": 1}, table="wishlists"),
    )

    merge_batch(batch, 7, CONTRACTS)
    merge_batch(batch, 7, CONTRACTS)

    rows = quarantined(spark)
    assert [(r.source_table, r.reason, r.batch_id) for r in rows] == [
        ("orders", "unparsed_envelope", 7),
        ("orders", "type_mismatch", 7),
        ("wishlists", "no_contract", 7),
    ]
    assert rows[0].payload == "not json at all {"
    assert silver(spark).keys() == {"o1"}


@needs_iceberg
@pytest.mark.usefixtures("fresh_silver")
def test_same_kafka_coordinates_twice_in_a_batch_quarantine_once(spark: SparkSession) -> None:
    poison = event(None, raw="garbage")
    batch = bronze(spark, poison, poison)

    merge_batch(batch, 0, CONTRACTS)

    assert len(quarantined(spark)) == 1


@needs_iceberg
@pytest.mark.usefixtures("fresh_silver")
def test_batch_of_only_invalid_events_changes_no_silver_row(spark: SparkSession) -> None:
    merge_batch(bronze(spark, event("c", order(), lsn=100)), 0, CONTRACTS)
    before = silver(spark)

    merge_batch(
        bronze(spark, event("u", order(order_estimated_delivery_date=None), lsn=200)), 1, CONTRACTS
    )

    assert silver(spark)["o1"]._last_lsn == before["o1"]._last_lsn == 100
```

- [ ] **Шаг 2: убедиться, что тесты падают**

Run: `make test-spark`
Expected: FAIL, `ImportError: cannot import name 'QUARANTINE'`.

- [ ] **Шаг 3: реализация**

Константы:

```python
QUARANTINE = f"{SILVER}.quarantine"
# Bronze columns an image keeps: ordering needs some, quarantine needs the rest.
BRONZE_KEPT = (
    "topic",
    "kafka_partition",
    "kafka_offset",
    "key",
    "op",
    "lsn",
    "ts_ms",
    "raw",
    "ingest_ts",
    "source_table",
)
QUARANTINE_DDL = f"""
create table if not exists {QUARANTINE} (
    topic string,
    kafka_partition int,
    kafka_offset bigint,
    source_table string,
    reason string,
    op string,
    key string,
    lsn bigint,
    payload string,
    ingest_ts timestamp,
    quarantined_at timestamp,
    batch_id bigint
)
using iceberg
tblproperties ('format-version' = '2')
"""
```

`row_images`, `reason`, `unknown_fields` (заменяют `row_images` и `valid`):

```python
def row_images(events: DataFrame, contract: TableContract) -> DataFrame:
    """One row per bronze event: the typed silver columns, what ordering and quarantine need,
    and `_reason`, null when the event can become a silver row. A delete carries its row in
    `before`, everything else in `after`."""
    payload = F.when(F.col("op") == "d", F.col("before")).otherwise(F.col("after"))
    parsed = events.select(
        F.from_json(payload, contract.wire_schema).alias("_p"),
        # The same payload with every value as text: present here but null once typed means the
        # value did not fit its column.
        F.from_json(payload, "map<string,string>").alias("_fields"),
        payload.alias("_payload"),
        *BRONZE_KEPT,
    )
    images = parsed.select(
        *contract.typed("_p"),
        (F.col("op") == "d").alias("_is_deleted"),
        F.col("lsn").alias("_last_lsn"),
        "_fields",
        "_payload",
        *BRONZE_KEPT,
    )
    return images.withColumn("_reason", reason(contract))


def reason(contract: TableContract) -> Column:
    """Why an event cannot become a silver row, or null. The first match wins. A delete only
    needs its key: with REPLICA IDENTITY DEFAULT its `before` would hold nothing else (ADR-018)."""
    key_missing = reduce(Column.__or__, [F.col(k).isNull() for k in contract.primary_key])
    mismatch = reduce(
        Column.__or__,
        [F.col("_fields")[c.name].isNotNull() & F.col(c.name).isNull() for c in contract.columns],
    )
    required_missing = reduce(
        Column.__or__, [F.col(c.name).isNull() for c in contract.columns if not c.nullable]
    )
    return (
        F.when(F.col("op").isNull(), "unparsed_envelope")
        .when(~F.col("op").isin(*OPS), "unknown_op")
        .when(key_missing, "null_key")
        .when(mismatch, "type_mismatch")
        .when((F.col("op") != "d") & required_missing, "null_required")
    )


def unknown_fields(images: DataFrame, contract: TableContract) -> list[str]:
    """Payload fields the contract does not declare: the source gained a column (W2-T07)."""
    known = [c.name for c in contract.columns]
    keys = images.select(F.explode(F.map_keys("_fields")).alias("field"))
    return sorted(r["field"] for r in keys.where(~F.col("field").isin(*known)).distinct().collect())
```

Карантин и разбор по таблице:

```python
def quarantine_rows(events: DataFrame, why: Column, payload: Column, batch_id: int) -> DataFrame:
    return events.select(
        "topic",
        "kafka_partition",
        "kafka_offset",
        "source_table",
        why.alias("reason"),
        "op",
        "key",
        "lsn",
        F.coalesce(payload, F.col("raw")).alias("payload"),
        "ingest_ts",
        F.current_timestamp().alias("quarantined_at"),
        F.lit(batch_id).cast("bigint").alias("batch_id"),
    )


def quarantine(rows: DataFrame) -> None:
    """Keyed by Kafka coordinates, so a replayed batch finds its events already there."""
    view = "silver_upsert_quarantine"
    rows.dropDuplicates(["topic", "kafka_partition", "kafka_offset"]).createOrReplaceTempView(view)
    rows.sparkSession.sql(
        f"merge into {QUARANTINE} q using {view} s "
        "on q.topic = s.topic and q.kafka_partition = s.kafka_partition "
        "and q.kafka_offset = s.kafka_offset "
        "when not matched then insert *"
    )


def merge_table(events: DataFrame, count: int, batch_id: int, contract: TableContract) -> None:
    images = row_images(events, contract).persist()
    try:
        rejected = images.where(F.col("_reason").isNotNull())
        why = {r["_reason"]: r["count"] for r in rejected.groupBy("_reason").count().collect()}
        if why:
            quarantine(quarantine_rows(rejected, F.col("_reason"), F.col("_payload"), batch_id))
            log.warning("batch %s: %s events quarantined: %s", batch_id, contract.table, why)
        extra = unknown_fields(images, contract)
        if extra:
            log.warning(
                "batch %s: %s payloads carry fields contracts/silver/%s.json does not declare: %s",
                batch_id,
                contract.table,
                contract.table,
                extra,
            )
        view = f"silver_upsert_{contract.table}"
        latest_per_key(images.where(F.col("_reason").isNull()), contract).createOrReplaceTempView(
            view
        )
        started = time.monotonic()
        events.sparkSession.sql(merge_sql(f"{SILVER}.{contract.table}", view, contract))
        log.info(
            "batch %s: %s events merged into %s.%s in %.1f s",
            batch_id,
            count,
            SILVER,
            contract.table,
            time.monotonic() - started,
        )
    finally:
        images.unpersist()


def merge_batch(batch: DataFrame, batch_id: int, contracts: dict[str, TableContract]) -> None:
    # The batch is read once per table; without persist each read goes back to MinIO.
    batch.persist()
    try:
        counts = batch.groupBy("source_table").count().collect()
        for table, count in sorted((r["source_table"], r["count"]) for r in counts):
            events = batch.where(F.col("source_table") == table)
            contract = contracts.get(table)
            if contract is None:
                payload = F.coalesce(F.col("after"), F.col("before"))
                quarantine(quarantine_rows(events, F.lit("no_contract"), payload, batch_id))
                log.warning(
                    "batch %s: %s %s events quarantined, no contract", batch_id, count, table
                )
                continue
            merge_table(events, count, batch_id, contract)
    finally:
        batch.unpersist()
```

В `run()` после `create namespace`: `spark.sql(QUARANTINE_DDL)`. Докстринг модуля: одна фраза «Events silver cannot type go to `silver.quarantine` with a reason, keyed by Kafka coordinates.»

- [ ] **Шаг 4: тесты зелёные**

Run: `make lint && make test && make test-spark`
Expected: PASS.

- [ ] **Шаг 5: `scripts/chaos/lib.sh`**

```bash
#!/usr/bin/env bash
# Helpers for scripts/chaos/*.sh. Sourced, not run.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
set -a
# shellcheck source=/dev/null
. "$ROOT/.env"
set +a
COMPOSE=(docker compose --env-file "$ROOT/.env" -f "$ROOT/docker/compose.yaml")

# Aligned table for people, bare values for scripts.
trino() { "${COMPOSE[@]}" exec -T trino trino --catalog lake --output-format ALIGNED --execute "$1"; }
trino_value() { "${COMPOSE[@]}" exec -T trino trino --catalog lake --output-format TSV --execute "$1"; }
psql_value() { "${COMPOSE[@]}" exec -T postgres-oltp psql -U "$OLTP_USER" -d "$OLTP_DB" -Atc "$1"; }
kafka() { "${COMPOSE[@]}" exec -T kafka "/opt/kafka/bin/$1" --bootstrap-server localhost:9092 "${@:2}"; }

# wait_until <seconds> <what> <command...>: poll the command every 3 s until it succeeds.
wait_until() {
  local deadline=$((SECONDS + $1)) what=$2
  shift 2
  until "$@" >/dev/null 2>&1; do
    if ((SECONDS >= deadline)); then
      echo "timed out after $1 s waiting for $what" >&2
      return 1
    fi
    sleep 3
  done
}

run_silver() { make -C "$ROOT" --no-print-directory silver >/dev/null 2>&1 || make -C "$ROOT" silver; }
```

`run_silver` запускает тихо, а при ошибке повторяет с полным выводом, чтобы причина была видна. Повтор безопасен: silver идемпотентен (ADR-021).

- [ ] **Шаг 6: `scripts/chaos/poison-event.sh`**

```bash
#!/usr/bin/env bash
# Chaos 7, data half: a record that is not a Debezium envelope lands in oltp.shop.orders.
# Bronze keeps it as raw text, silver routes it to silver.quarantine and carries on.
. "$(dirname "$0")/lib.sh"

marker="poison-$(date +%s)"
echo "not json at all {$marker" | kafka kafka-console-producer.sh --topic oltp.shop.orders
echo "produced one garbage record ($marker)"

ingested() { [ "$(trino_value "select count(*) from bronze.cdc_events where raw like '%$marker%'")" -ge 1 ]; }
wait_until 120 "bronze to ingest it" ingested
run_silver

trino "select reason, topic, kafka_partition, kafka_offset, payload
       from silver.quarantine where payload like '%$marker%'"
echo "expected: one row, reason unparsed_envelope; silver_upsert exited 0"
```

`chmod +x` не нужен: Makefile вызывает `bash scripts/chaos/$*.sh`.

- [ ] **Шаг 7: живая проверка**

```bash
docker compose --env-file .env -f docker/compose.yaml --profile core build spark-bronze
make silver                 # создаёт silver.quarantine, ничего не мержит
make chaos-poison-event     # одна строка unparsed_envelope
make chaos-poison-event     # вторая строка, первая не задвоилась
make trino                  # select reason, count(*) from silver.quarantine group by 1;  -> unparsed_envelope 2
```

- [ ] **Шаг 8: документация**

`OPERATIONS.md`, Silver upsert: заменить фразу про `invalid ... events skipped` на описание карантина (причины, ключ, как смотреть: `select reason, source_table, count(*) from silver.quarantine group by 1, 2`, что после добавления контракта события `no_contract` не перечитываются сами). Таблица сценариев: chaos 7 `data half done (W2-T04), alert in week 4`. `contracts/README.md`: фраза «A field that fails to parse ... comes out null while the rest of the row survives» заменяется на «A field that is present in the payload but fails to parse or to fit its silver type sends the event to `silver.quarantine` (`type_mismatch`); a field that is absent or JSON null stays null.»

- [ ] **Шаг 9: ревью и коммит**

```bash
git add streaming/spark_jobs/silver_upsert.py tests/unit/test_silver_upsert.py scripts/chaos/lib.sh scripts/chaos/poison-event.sh OPERATIONS.md contracts/README.md
git commit -m "lake: silver.quarantine for events silver cannot type, poison-event scenario"
```

---

### Задача 4: W2-T05 chaos 1, `chaos-spark-kill`

**Файлы:**
- Изменить: `scripts/chaos/lib.sh` (реплей, догон bronze)
- Создать: `scripts/chaos/spark-kill.sh`, `tests/unit/test_iceberg_sink.py`, `docs/runbooks/spark-stalled.md`
- Изменить: `Makefile` (`SPARK_TESTS`), `OPERATIONS.md`, `DECISIONS.md` (ADR-007)

**Интерфейсы:**
- Потребляет: `lib.sh` из задачи 3.
- Производит: в `lib.sh` `replay_burst <seconds> [VAR=value ...]`, `no_other_replayer`, `bronze_caught_up`, `healthy <container>`, `bronze_offsets_report`.

- [ ] **Шаг 1: падающий тест пропуска эпохи (`tests/unit/test_iceberg_sink.py`)**

```python
"""The Iceberg streaming sink skips an epoch it already committed (ADR-007, chaos 1).

A crash between Iceberg's commit and Spark's own commit log makes Spark replay the batch. On the
live stack that window is milliseconds wide, so here it is reproduced by deleting the checkpoint's
commit entry by hand. The skip is keyed by query id, so a new checkpoint is the negative control.
"""

import os
import shutil
from collections.abc import Iterator
from glob import glob
from pathlib import Path

import pytest
from pyspark.sql import SparkSession

HAS_JAVA = shutil.which("java") is not None
SPARK_JARS = f"{os.environ.get('SPARK_HOME', '/opt/spark')}/jars"
HAS_ICEBERG = bool(glob(f"{SPARK_JARS}/iceberg-spark-runtime-*"))
needs_iceberg = pytest.mark.skipif(
    not (HAS_JAVA and HAS_ICEBERG), reason="needs the Iceberg runtime jar: run `make test-spark`"
)
TABLE = "lake.probe.sink"


@pytest.fixture(scope="module")
def spark(tmp_path_factory: pytest.TempPathFactory) -> Iterator[SparkSession]:
    warehouse = tmp_path_factory.mktemp("warehouse")
    session = (
        SparkSession.builder.master("local[2]")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "2")
        .config(
            "spark.sql.extensions",
            "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        )
        .config("spark.sql.catalog.lake", "org.apache.iceberg.spark.SparkCatalog")
        .config("spark.sql.catalog.lake.type", "hadoop")
        .config("spark.sql.catalog.lake.warehouse", f"file://{warehouse}")
        .config("spark.sql.catalog.lake.cache-enabled", "false")
        .getOrCreate()
    )
    yield session
    session.stop()


def epochs(spark: SparkSession) -> list[str]:
    return [
        r.epoch
        for r in spark.sql(
            f"select summary['spark.sql.streaming.epochId'] as epoch from {TABLE}.snapshots "
            "order by committed_at"
        ).collect()
    ]


@needs_iceberg
def test_replayed_epoch_is_skipped(spark: SparkSession, tmp_path: Path) -> None:
    source, checkpoint = tmp_path / "in", tmp_path / "checkpoint"
    source.mkdir()
    spark.sql("create namespace if not exists lake.probe")
    spark.sql(f"create table {TABLE} (id bigint) using iceberg")

    def run(location: Path = checkpoint) -> None:
        (
            spark.readStream.schema("id bigint")
            .json(str(source))
            .writeStream.format("iceberg")
            .outputMode("append")
            .trigger(availableNow=True)
            .option("checkpointLocation", str(location))
            .toTable(TABLE)
            .awaitTermination()
        )

    (source / "1.json").write_text('{"id": 1}\n')
    run()
    (source / "2.json").write_text('{"id": 2}\n')
    run()
    assert epochs(spark) == ["0", "1"]

    # Iceberg holds epoch 1, Spark's commit log does not: the state a kill leaves in the window.
    commit = checkpoint / "commits" / "1"
    for entry in (checkpoint / "commits").glob("*1*"):  # "1" and its ".1.crc"
        entry.unlink()
    assert not commit.exists()
    run()
    assert commit.exists()  # Spark re-ran batch 1 ...
    assert sorted(r.id for r in spark.table(TABLE).collect()) == [1, 2]
    assert epochs(spark) == ["0", "1"]  # ... and Iceberg added no rows and no snapshot for it
    (source / "3.json").write_text('{"id": 3}\n')
    run()

    assert sorted(r.id for r in spark.table(TABLE).collect()) == [1, 2, 3]
    assert epochs(spark) == ["0", "1", "2"]

    # A new checkpoint is a new query id: Iceberg finds no epoch of its own and appends again.
    run(tmp_path / "checkpoint-new")
    assert sorted(r.id for r in spark.table(TABLE).collect()) == [1, 1, 2, 2, 3, 3]
    assert epochs(spark).count("0") == 2
```

Makefile: `SPARK_TESTS := ... test_iceberg_sink.py`.

- [ ] **Шаг 2: прогнать тест**

Run: `make test-spark`
Expected: тест проходит сразу (он проверяет поведение Iceberg, а не наш код). Чтобы убедиться, что он умеет падать, временно заменить удаление `commits/1` на удаление всего checkpoint (новый queryId, пропуска нет): тест должен упасть на `assert commit.exists()`, потому что новый checkpoint пишет только `commits/0`. Если убрать и проверки существования, падение будет на `[1, 1, 2, 2] == [1, 2]`. Вернуть.

- [ ] **Шаг 3: `lib.sh`, добавить**

```bash
healthy() { [ "$(docker inspect -f '{{.State.Health.Status}}' "$1" 2>/dev/null)" = healthy ]; }

# replay_burst <real seconds> [VAR=value ...]: play the schedule on the host, then stop. The
# replayer resumes from its saved virtual clock, so a burst spends only what it plays. It never
# exits by itself, so any status but timeout's 124 is a failure and shows the log tail.
# --foreground keeps timeout in the caller's process group, so a script that runs the burst as a
# job of its own group stops all of it with one kill.
replay_burst() {
  local seconds=$1 rc=0 log
  shift
  log=$(mktemp -t replay_burst.XXXXXX.log)
  (cd "$ROOT" && env REPLAY_SPEED="${CHAOS_REPLAY_SPEED:-720}" "$@" PYTHONPATH=oltp \
    timeout --foreground "$seconds" .venv/bin/python -m replayer start >"$log" 2>&1) || rc=$?
  if [ "$rc" -ne 124 ]; then
    tail -20 "$log" >&2
    echo "replayer exited $rc, full log: $log" >&2
    return 1
  fi
  rm -f "$log"
}

# Returns 2, so a script under set -e stops with 2 before it touches anything.
no_other_replayer() {
  if curl -sf -o /dev/null --max-time 2 http://127.0.0.1:8000/health; then
    echo "a replayer already answers on :8000 (oltp-replayer or make replay-start); stop it" \
      "first: the burst cannot bind the port and that replayer keeps playing at REPLAY_SPEED" >&2
    return 2
  fi
}

# Every record of the CDC topics is in bronze: the end offset of each non-empty partition equals
# bronze's highest offset there plus one. A failed or empty Kafka listing counts as not caught up.
kafka_ends() {
  kafka kafka-get-offsets.sh --topic 'oltp\.shop\..*' --time -1 | awk -F: '$3 > 0' | sort
}
bronze_ends() {
  trino_value "select topic || ':' || cast(kafka_partition as varchar) || ':'
                      || cast(max(kafka_offset) + 1 as varchar)
               from bronze.cdc_events group by topic, kafka_partition" | sort
}
bronze_caught_up() {
  local k b
  k=$(kafka_ends) && [ -n "$k" ] && b=$(bronze_ends) || return 1
  [ -z "$(comm -23 <(printf '%s\n' "$k") <(printf '%s\n' "$b"))" ]
}

# Per topic partition: copies of one offset, and holes between the lowest and highest offset.
bronze_offsets_report() {
  trino "select topic, kafka_partition, count(*) - count(distinct kafka_offset) as duplicates,
                max(kafka_offset) - min(kafka_offset) + 1 - count(distinct kafka_offset) as missing
         from bronze.cdc_events group by 1, 2 order by 1, 2"
}
```

- [ ] **Шаг 4: `scripts/chaos/spark-kill.sh`**

```bash
#!/usr/bin/env bash
# Chaos 1: kill spark-bronze while a micro-batch is running, start it again, and prove bronze
# holds every Kafka offset exactly once (OPERATIONS.md, scenario 1).
. "$(dirname "$0")/lib.sh"

container=lakehouse-spark-bronze-1
ui=http://127.0.0.1:4040/api/v1/applications
running_job() {
  local app
  app=$(curl -sf "$ui" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["id"])')
  curl -sf "$ui/$app/jobs?status=running" |
    python3 -c 'import json,sys; sys.exit(not json.load(sys.stdin))'
}

no_other_replayer
# The burst runs in a process group of its own, so an early exit or ctrl-c stops all of it.
set -m
replay_burst 150 &
burst=$!
set +m
stop_burst() { kill -TERM -- -"$burst" 2>/dev/null || true; }
trap stop_burst EXIT

wait_until 120 "a running micro-batch" running_job
kill -0 "$burst" 2>/dev/null ||
  { echo "the replay burst ended before the kill; its log is above" >&2; exit 1; }
# docker kill counts as a manual stop: restart: unless-stopped will not bring it back.
trap 'stop_burst; docker start "$container" >/dev/null' EXIT
docker kill "$container" >/dev/null
echo "killed $container at $(date -u +%T) after the Spark UI reported a running job"
sleep 5
docker start "$container" >/dev/null
trap stop_burst EXIT
started=$(docker inspect -f '{{.State.StartedAt}}' "$container")
wait_until 300 "$container to turn healthy" healthy "$container"
echo "started $container at ${started:11:8}, healthy at $(date -u +%T)"

# Spark logs "Resuming at batch N" on every start. Only a batch that was planned and never
# committed resumes with committed offsets (end of N-1) different from available ones (end of N).
resume=$(docker logs --since "$started" "$container" 2>&1 | grep -m1 'Resuming at batch') || true
batch=${resume#*Resuming at batch }
batch=${batch%% *}
committed=${resume#*with committed offsets }
committed=${committed%% and available offsets *}
if [ -z "$resume" ] || [ "$committed" = "${resume##* and available offsets }" ]; then
  echo "inconclusive: Spark replayed no uncommitted batch, the kill landed between batches;" \
    "run again" >&2
  exit 1
fi
echo "Spark replayed batch $batch, which the kill interrupted"

wait "$burst"
trap - EXIT
wait_until 300 "bronze to catch up with Kafka" bronze_caught_up

docker logs --since "$started" "$container" 2>&1 | grep 'Skipping epoch' | cut -c1-110 || true
bronze_offsets_report
trino "with s as (
         select committed_at, element_at(summary, 'spark.sql.streaming.queryId') as query_id,
                cast(element_at(summary, 'spark.sql.streaming.epochId') as bigint) as epoch,
                element_at(summary, 'added-records') as records
         from bronze.\"cdc_events\$snapshots\"
         where element_at(summary, 'spark.sql.streaming.queryId') is not null)
       select committed_at, epoch, records from s
       where query_id = (select max_by(query_id, committed_at) from s)
         and epoch between $batch - 1 and $batch + 1
       order by committed_at"

bad=$(trino_value "select count(*) from (
                     select topic, kafka_partition from bronze.cdc_events group by 1, 2
                     having count(*) > count(distinct kafka_offset)
                       or max(kafka_offset) - min(kafka_offset) + 1
                         > count(distinct kafka_offset))")
if [ "$bad" != 0 ]; then
  echo "FAIL: $bad topic partitions with duplicate or missing offsets" >&2
  exit 1
fi
# Grouped by query id: a new checkpoint starts a new query whose epochs count from 0 again.
repeated=$(trino_value "select count(*) from (
                          select 1 from bronze.\"cdc_events\$snapshots\"
                          where element_at(summary, 'spark.sql.streaming.epochId') is not null
                          group by element_at(summary, 'spark.sql.streaming.queryId'),
                                   element_at(summary, 'spark.sql.streaming.epochId')
                          having count(*) > 1)")
if [ "$repeated" != 0 ]; then
  echo "FAIL: $repeated epochs committed twice by one query" >&2
  exit 1
fi
echo "ok: every Kafka offset is in bronze exactly once; no epoch was committed twice"
```

- [ ] **Шаг 5: прогон на живом стеке**

Run: `make chaos-spark-kill`
Expected: `Resuming at batch N`, отчёт по offsets с нулями, эпохи без повторов. Прогнать дважды; записать число событий в порции, время до healthy, N.

- [ ] **Шаг 6: документация**

`OPERATIONS.md`: раздел `## 1. Spark bronze killed mid-batch` по шаблону (what happened, monitoring, data at risk, recovery, why no loss or duplication, verification SQL) с цифрами из шага 5 и ссылкой на `test_iceberg_sink.py`; статус в таблице `done`. Пункт в Bronze ingest про ручной `docker start` уже есть, дополнить: файлы отменённого батча остаются сиротами до `remove_orphan_files` (W5). ADR-007: абзац `Verified on 2026-09-26: ...` с результатом. `docs/runbooks/spark-stalled.md`:

```markdown
# Spark job without a batch for 5 minutes

Symptom: `spark_streaming_last_batch_timestamp` older than 5 minutes, container unhealthy or
restarting.

1. `make status`, `docker inspect -f '{{.State.Status}} {{.RestartCount}}' lakehouse-spark-bronze-1`.
   Exited after `docker kill` or `docker stop`: `docker start lakehouse-spark-bronze-1`; the
   restart policy does not cover manual stops.
2. Restart loop with `OffsetOutOfRange` or "data loss" in `make logs S=spark-bronze`: the job was
   down longer than Kafka retention. Do not delete the checkpoint; see OPERATIONS.md, Bronze
   ingest, and recover with `make cdc-snapshot`.
3. Running but unhealthy: the query is stuck in a commit. Check `postgres-meta` and `minio`
   health, then `docker restart lakehouse-spark-bronze-1`. The checkpoint replays the unfinished
   batch; Iceberg skips an epoch it already committed.
4. Verify: `bronze_offsets_report` from `scripts/chaos/lib.sh` shows no duplicates and no holes.
```

- [ ] **Шаг 7: ревью и коммит**

```bash
git add scripts/chaos/lib.sh scripts/chaos/spark-kill.sh tests/unit/test_iceberg_sink.py docs/runbooks/spark-stalled.md Makefile OPERATIONS.md DECISIONS.md
git commit -m "stream: chaos-spark-kill, bronze exactly once across restarts proven"
```

---

### Задача 5: W2-T05 chaos 2, `chaos-connect-restart`

**Файлы:**
- Изменить: `scripts/chaos/lib.sh`
- Создать: `scripts/chaos/connect-restart.sh`, `docs/runbooks/connector-failed.md`
- Изменить: `OPERATIONS.md`, `DECISIONS.md` (ADR-007), `docs/planning/00-mini-architecture-review.md` (§8)

**Интерфейсы:**
- Производит: в `lib.sh` `connector_running`, `slot_reattached <pid>`, `reconcile`, `lsn_duplicates_since <utc timestamp>`.

- [ ] **Шаг 1: `lib.sh`, добавить**

```bash
connector_running() {
  curl -sf http://127.0.0.1:8083/connectors/shop-connector/status | python3 -c '
import json, sys
d = json.load(sys.stdin)
running = d["connector"]["state"] == "RUNNING"
sys.exit(not (running and d["tasks"] and all(t["state"] == "RUNNING" for t in d["tasks"])))'
}

# slot_reattached <pid>: a walsender other than <pid> streams shop_slot. After a kill,
# connect-status can still hold the dead worker's RUNNING records; Postgres cannot.
slot_reattached() {
  [ "$(psql_value "select active and active_pid <> $1 from pg_replication_slots
                   where slot_name = 'shop_slot'")" = t ]
}

# Live row counts per table, Postgres against silver: 1 when any table differs, 2 when a count
# query fails.
reconcile() {
  local t pg lake status=0
  for t in customers sellers products orders order_items payments reviews; do
    pg=$(psql_value "select count(*) from shop.$t") || return 2
    lake=$(trino_value "select count(*) from silver.$t where not _is_deleted") || return 2
    printf '%-12s postgres %8s  silver %8s  %s\n' "$t" "$pg" "$lake" \
      "$([ "$pg" = "$lake" ] && echo ok || echo DIFF)"
    [ "$pg" = "$lake" ] || status=1
  done
  return "$status"
}

# Events bronze holds more than once with the same LSN, ingested since <utc 'YYYY-MM-DD HH:MM:SS'>.
# Both copies must be ingested after that time: after a Connect kill the first copy can be up to
# offset.flush.interval.ms (60 s) older than the kill, so start the window before that.
lsn_duplicates_since() {
  trino "select source_table, count(distinct key) as keys_repeated, count(*) as events_repeated,
                sum(copies - 1) as extra_events
         from (select source_table, key, lsn, count(*) as copies from bronze.cdc_events
               where ingest_ts >= timestamp '$1' and lsn is not null
               group by 1, 2, 3 having count(*) > 1)
         group by 1 order by 1"
}
```

- [ ] **Шаг 2: `scripts/chaos/connect-restart.sh`**

```bash
#!/usr/bin/env bash
# Chaos 2: restart Kafka Connect during a replay. MODE=restart (default, SIGTERM): Connect commits
# offsets and the connector flushes the slot, so about zero repeats. MODE=kill: no final commit,
# so everything since the last offset flush (offset.flush.interval.ms, 60 s) is sent again with
# the same LSN. Silver absorbs both (OPERATIONS.md, scenarios 2a and 2b).
. "$(dirname "$0")/lib.sh"

mode=${MODE:-restart}
container=lakehouse-kafka-connect-1
case "$mode" in
  restart | kill) ;;
  *) echo "MODE must be restart or kill" >&2; exit 2 ;;
esac
t0=$(date -u +'%Y-%m-%d %H:%M:%S')

no_other_replayer
# The burst runs in a process group of its own, so an early exit or ctrl-c stops all of it.
set -m
replay_burst 180 &
burst=$!
set +m
stop_burst() { kill -TERM -- -"$burst" 2>/dev/null || true; }
trap stop_burst EXIT

sleep 90
kill -0 "$burst" 2>/dev/null ||
  { echo "the replay burst ended before the $mode; its log is above" >&2; exit 1; }
pid0=$(psql_value "select coalesce(active_pid, 0) from pg_replication_slots
                   where slot_name = 'shop_slot'")
t1=$(date -u +'%Y-%m-%d %H:%M:%S')
if [ "$mode" = restart ]; then
  docker restart "$container" >/dev/null
else
  # docker kill is a manual stop: if the script dies before docker start, Connect stays down.
  trap 'stop_burst; docker start "$container" >/dev/null' EXIT
  docker kill "$container" >/dev/null
  sleep 5
  docker start "$container" >/dev/null
  trap stop_burst EXIT
fi
echo "$mode of $container at ${t1#* }, running again at $(date -u +%T)"
wait_until 180 "connector and task RUNNING" connector_running
wait_until 180 "shop_slot streaming to a new walsender" slot_reattached "$pid0"
wait "$burst"
trap - EXIT
wait_until 300 "bronze to catch up with Kafka" bronze_caught_up

# kafka_ts is when Connect produced the record. The minute before the stop is one offset flush
# interval: without traffic there, "0 repeats" would prove nothing.
counts=$(trino_value "
  select count_if(kafka_ts >= timestamp '$t1 UTC' - interval '60' second
                  and kafka_ts < timestamp '$t1 UTC'),
         count_if(kafka_ts >= timestamp '$t1 UTC')
  from bronze.cdc_events where ingest_ts >= timestamp '$t0 UTC'")
read -r before after <<<"$counts"
echo "CDC events produced in the 60 s before the $mode: $before, after it: $after"
if ! [ "$before" -gt 0 ] || ! [ "$after" -gt 0 ]; then
  echo "inconclusive: no CDC traffic on one side of the $mode (schedule drained?); run again" >&2
  exit 1
fi

lsn_duplicates_since "$t0"
if [ "$mode" = kill ]; then
  repeated=$(trino_value "select count(*) from (
                            select 1 from bronze.cdc_events
                            where ingest_ts >= timestamp '$t0' and lsn is not null
                            group by source_table, key, lsn having count(*) > 1)")
  if ! [ "$repeated" -gt 0 ]; then
    echo "inconclusive: the kill repeated no event, it came right after an offset flush;" \
      "run again" >&2
    exit 1
  fi
fi

run_silver
reconcile
echo "expected: MODE=restart no rows above; MODE=kill repeated events; reconcile ok (live row" \
  "counts) either way"
```

- [ ] **Шаг 3: прогон обоих режимов**

Run: `make chaos-connect-restart`, затем `MODE=kill make chaos-connect-restart`.
Expected: restart даёт 0 или единицы повторов, kill даёт повторы с теми же LSN; `reconcile` всё `ok` в обоих. Записать цифры.

- [ ] **Шаг 4: документация**

`OPERATIONS.md`: разделы `## 2a. Kafka Connect restart` и `## 2b. Kafka Connect killed` по шаблону с цифрами, строки таблицы сценариев разделены на 2a/2b. ADR-007: абзац о фактическом числе дублей и о том, что их источник это `docker kill`, а не рестарт. `00-mini-architecture-review.md` §8: строка 2 делится на 2a (`docker restart`, ожидаем 0 дублей) и 2b (`docker kill` + `docker start`, дубли с теми же LSN в пределах 60 с). `docs/runbooks/connector-failed.md`:

```markdown
# Connector status FAILED

Symptom: `make connector-status` shows FAILED for the connector or its task; bronze stops
growing while the replayer writes.

1. Read the trace: `curl -s 127.0.0.1:8083/connectors/shop-connector/status | python -m json.tool`.
2. Postgres was restarted or unreachable: once `postgres-oltp` is healthy,
   `curl -X POST '127.0.0.1:8083/connectors/shop-connector/restart?includeTasks=true'`. The slot
   kept the position; the connector resumes from its stored offset.
3. Topic missing (producer blocked, "UNKNOWN_TOPIC_OR_PARTITION"): `bash connect/register.sh`
   creates the topics and re-applies the config; it is idempotent.
4. After a hard kill expect repeated events with the same LSN in bronze: silver absorbs them
   (ADR-021). Check with `lsn_duplicates_since` and `reconcile` from `scripts/chaos/lib.sh`.
5. Never drop the replication slot or `connect-offsets` to "fix" it: that is a new initial
   snapshot and on the blast-radius list.
```

- [ ] **Шаг 5: ревью и коммит**

```bash
git add scripts/chaos/lib.sh scripts/chaos/connect-restart.sh docs/runbooks/connector-failed.md OPERATIONS.md DECISIONS.md docs/planning/00-mini-architecture-review.md
git commit -m "cdc: chaos-connect-restart, graceful restart vs kill measured"
```

---

### Задача 6: W2-T05 chaos 3, `chaos-duplicates`

**Файлы:**
- Создать: `scripts/chaos/duplicates.sh`
- Изменить: `OPERATIONS.md`, `docs/planning/00-mini-architecture-review.md` (§8, строка 3)

- [ ] **Шаг 1: `scripts/chaos/duplicates.sh`**

```bash
#!/usr/bin/env bash
# Chaos 3: the source repeats itself. REPLAY_DUPLICATE_RATIO picks that share of orders (md5 of
# duplicate:<order_id>) and runs each status UPDATE of a picked order twice with the same values:
# a new WAL record, a new LSN, before = after. Bronze gets an extra event that dedup by LSN cannot
# see. The repeat commits with its original, so silver usually reads both in one batch:
# latest_per_key keeps the repeat (higher LSN, same values) and MERGE writes the row once. If a
# batch boundary splits the pair, the _last_lsn guard lets the repeat rewrite the row with the
# same values. Either way silver ends equal to Postgres (OPERATIONS.md, scenario 3).
. "$(dirname "$0")/lib.sh"

ratio=0.1
no_other_replayer
# The window must hold only this burst: anything still on its way from Kafka would land in it.
wait_until 300 "bronze to catch up before the burst" bronze_caught_up
t0=$(date -u +'%Y-%m-%d %H:%M:%S')
echo "window: ingest_ts >= timestamp '$t0' (UTC), REPLAY_DUPLICATE_RATIO=$ratio"
replay_burst 120 REPLAY_DUPLICATE_RATIO=$ratio
wait_until 300 "bronze to catch up with Kafka" bronze_caught_up
echo "bronze caught up at $(date -u +%T)"

# The ratio picks orders, so pct_of_status_updates varies around it with the orders in the burst.
trino "select source_table, count(*) as events, count_if(op = 'u') as updates,
              count_if(op = 'u' and before = after) as no_op_updates,
              cast(100.0 * count_if(op = 'u' and before = after)
                   / nullif(count_if(op = 'u' and before <> after), 0) as decimal(5, 1))
                as pct_of_status_updates,
              count(distinct key) filter (where op = 'u') as keys_updated,
              count(distinct key) filter (where op = 'u' and before = after) as keys_repeated
       from bronze.cdc_events where ingest_ts >= timestamp '$t0' group by 1 order by 1"
lsn_duplicates_since "$t0"

no_ops=$(trino_value "select count_if(op = 'u' and before = after) from bronze.cdc_events
                      where source_table = 'orders' and ingest_ts >= timestamp '$t0'")
if ! [ "$no_ops" -gt 0 ]; then
  echo "FAIL: no no-op UPDATE on orders since $t0 UTC, the burst proved nothing" >&2
  exit 1
fi
repeats=$(trino_value "select count(*) from (select 1 from bronze.cdc_events
                         where ingest_ts >= timestamp '$t0' and lsn is not null
                         group by source_table, key, lsn having count(*) > 1)")
if [ "$repeats" != 0 ]; then
  echo "FAIL: $repeats changes arrived twice with the same LSN: a delivery repeat (chaos 2b)" \
    "mixed into the window" >&2
  exit 1
fi

echo "silver run at $(date -u +%T)"
run_silver
# Positive control: a repeat never changes a row count, so reconcile alone cannot show that silver
# read it. An order with a repeat ends on one, and silver must hold exactly that LSN and status.
counts=$(trino_value "
  with ev as (
    select json_extract_scalar(key, '\$.order_id') as order_id, lsn,
           op = 'u' and before = after as no_op,
           json_extract_scalar(after, '\$.order_status') as status,
           max(lsn) over (partition by key) as last_lsn
    from bronze.cdc_events
    where source_table = 'orders' and ingest_ts >= timestamp '$t0')
  select count(*), count_if(s._last_lsn = ev.lsn and s.order_status = ev.status)
  from ev left join silver.orders s on s.order_id = ev.order_id
  where ev.no_op and ev.lsn = ev.last_lsn")
read -r repeated held <<<"$counts"
echo "orders whose last event is a repeat: $repeated, silver holds that repeat: $held"
if ! [ "$repeated" -gt 0 ] || [ "$held" != "$repeated" ]; then
  echo "FAIL: silver holds the repeat of $held of $repeated orders that end on one" >&2
  exit 1
fi
reconcile || { echo "FAIL: reconcile, see the lines above" >&2; exit 1; }
echo "ok: $no_ops no-op UPDATEs on orders, none repeated by LSN; silver holds every repeat and" \
  "matches Postgres"
```

- [ ] **Шаг 2: прогон**

Run: `make chaos-duplicates`
Expected: напечатаны окно (`window: ingest_ts >= timestamp '...'`) и время догона bronze; у `orders` no-op UPDATE больше 0, их доля от UPDATE статуса около `REPLAY_DUPLICATE_RATIO` с разбросом (ratio выбирает заказы, а не UPDATE; первый прогон дал 15.0%, 16 из 114 заказов; прогон 07.10 (UTC) дал 9.8%, 90 из 926), повторов по LSN 0, silver держит LSN и статус повтора у каждого такого заказа, `reconcile` ok, последняя строка `ok: ...`. Скрипт выходит с кодом 2 (make печатает `Error 2`), если уже работает другой реплеер на `:8000`; FAIL-проверки дают `Error 1`.

- [ ] **Шаг 3: документация**

`OPERATIONS.md`: `### 3. Duplicate events from the source` с цифрами; отдельной фразой, что проверка повторов по `(source_table, key, lsn)` (`lsn_duplicates_since`; `bronze_duplicate_ratio` в `dq_checks` это план W3-T05, метрики ещё нет) видит только повторы доставки (chaos 2b), а повторы источника видны как `before = after`. `00-mini-architecture-review.md` §8, строка 3: метрика по LSN такие повторы не видит и не растёт.

- [ ] **Шаг 4: ревью и коммит**

```bash
git add scripts/chaos/duplicates.sh OPERATIONS.md docs/planning/00-mini-architecture-review.md
git commit -m "oltp: chaos-duplicates, repeated source updates absorbed by silver"
```

---

### Задача 7: W2-T05 chaos 4, `chaos-late`

**Файлы:**
- Создать: `scripts/chaos/late.sh`
- Изменить: `oltp/replayer/settings.py` (комментарий), `OPERATIONS.md`

- [ ] **Шаг 1: `scripts/chaos/late.sh`**

```bash
#!/usr/bin/env bash
# Chaos 4: an older change of an order arrives after a newer one, the way Debezium re-sends after
# a restart. The script re-publishes an earlier envelope of an order silver already moved past
# and checks that silver keeps the newer state (the _last_lsn guard, ADR-021).
. "$(dirname "$0")/lib.sh"

t0=$(date -u +'%Y-%m-%d %H:%M:%S')
replay_burst 120
wait_until 300 "bronze to catch up with Kafka" bronze_caught_up
run_silver

read -r order_id partition offset stale_lsn < <(trino_value "
  with ev as (
    select json_extract_scalar(after, '\$.order_id') as order_id, kafka_partition, kafka_offset, lsn,
           row_number() over (partition by json_extract_scalar(after, '\$.order_id') order by lsn) as n,
           count(*) over (partition by json_extract_scalar(after, '\$.order_id')) as changes
    from bronze.cdc_events
    where source_table = 'orders' and op = 'u' and ingest_ts >= timestamp '$t0')
  select order_id, kafka_partition, kafka_offset, lsn from ev where changes >= 2 and n = 1 limit 1")
[ -n "${order_id:-}" ] || { echo "no order changed twice in this burst; run again" >&2; exit 1; }
state="select order_status, _last_lsn from silver.orders where order_id = '$order_id'"
before=$(trino_value "$state")
echo "order $order_id: silver has [$before]; re-sending its change at lsn $stale_lsn"

record=$(kafka kafka-console-consumer.sh --topic oltp.shop.orders --partition "$partition" \
  --offset "$offset" --max-messages 1 --timeout-ms 20000 \
  --property print.key=true --property key.separator=$'\t')
printf '%s\n' "$record" | kafka kafka-console-producer.sh --topic oltp.shop.orders \
  --property parse.key=true --property key.separator=$'\t'

resent() {
  [ "$(trino_value "select count(*) from bronze.cdc_events
                    where lsn = $stale_lsn and source_table = 'orders'")" -ge 2 ]
}
wait_until 120 "bronze to hold the stale event twice" resent
run_silver
after=$(trino_value "$state")
trino "select kafka_partition, kafka_offset, lsn, json_extract_scalar(after, '\$.order_status') as status, ingest_ts
       from bronze.cdc_events where lsn = $stale_lsn and source_table = 'orders'"
echo "silver before [$before], after [$after]"
[ "$before" = "$after" ] && echo "ok: the late event did not roll the order back" || { echo "FAIL" >&2; exit 1; }
```

- [ ] **Шаг 2: прогон**

Run: `make chaos-late`
Expected: две строки в bronze с одним LSN (исходная и повтор, в той же партиции), состояние silver до и после совпадает, `ok`. Если `kafka-console-consumer` в Kafka 4.3 не принимает `--property`, заменить на `--formatter-property` и повторить.

- [ ] **Шаг 3: комментарий в `oltp/replayer/settings.py`**

```python
    # Share of delivery updates pushed back by replay_late_delay_seconds of VIRTUAL time: late in
    # event time for the windowed job (W5-T01). The update still commits later, so it reaches
    # Kafka in order with a higher LSN; out-of-order arrival is chaos 4 (scripts/chaos/late.sh).
```

- [ ] **Шаг 4: документация**

`OPERATIONS.md`: `## 4. Late events` с цифрами и объяснением двух смыслов «late» (приход не по порядку для silver и event time для W5-T01). Таблица сценариев: 1-4 `done`.

- [ ] **Шаг 5: ревью и коммит**

```bash
git add scripts/chaos/late.sh oltp/replayer/settings.py OPERATIONS.md
git commit -m "lake: chaos-late, a stale change re-sent through kafka does not roll silver back"
```

---

### Задача 8: W2-T06 `make iceberg-demo`

**Файлы:**
- Создать: `streaming/spark_jobs/iceberg_demo.py`, `tests/unit/test_iceberg_demo.py`
- Изменить: `Makefile` (цель `iceberg-demo`, `SPARK_TESTS`), `scripts/README.md`, `streaming/README.md`, `OPERATIONS.md`

**Интерфейсы:**
- Потребляет: `build_session`, `CATALOG` из `catalog.py`; `lake.silver.orders` только на чтение.
- Производит: `walkthrough(spark, rows=1000, appends=20) -> dict[str, int]` с ключами `rows`, `after_accident`, `after_rollback`, `files_before`, `files_after`, `snapshots_after_expire`.

- [ ] **Шаг 1: падающий тест (`tests/unit/test_iceberg_demo.py`)**

Фикстура сессии такая же, как в `test_iceberg_sink.py` (локальный hadoop-каталог `lake`, `cache-enabled=false`), плюс `spark.sql.session.timeZone=UTC`. Тест:

```python
from spark_jobs.contracts import load_contracts
from spark_jobs.iceberg_demo import DEMO, walkthrough
from spark_jobs.silver_upsert import SILVER, ensure_table


@needs_iceberg
def test_walkthrough_ends_compacted_with_one_snapshot(spark: SparkSession) -> None:
    contracts = load_contracts(Path(__file__).parents[2] / "contracts" / "silver")
    spark.sql(f"create namespace if not exists {SILVER}")
    ensure_table(spark, contracts["orders"])
    spark.sql(
        f"insert into {SILVER}.orders select concat('o', id), 'c1', "
        "case when id % 2 = 0 then 'delivered' else 'shipped' end, "
        "timestamp_ntz'2026-06-01 10:00:00', null, null, null, timestamp_ntz'2026-06-10 00:00:00', "
        "false, id, current_timestamp() from range(40)"
    )

    result = walkthrough(spark, rows=10, appends=3)

    assert result["after_rollback"] == result["rows"] + 15
    assert result["after_accident"] < result["after_rollback"]
    assert result["files_before"] > result["files_after"] == 1
    assert result["snapshots_after_expire"] == 1
    assert spark.table(f"{DEMO}.snapshots").count() == 1
```

- [ ] **Шаг 2: убедиться, что тест падает**

Run: `make test-spark`
Expected: FAIL, `ModuleNotFoundError: spark_jobs.iceberg_demo`.

- [ ] **Шаг 3: `streaming/spark_jobs/iceberg_demo.py`**

```python
"""`make iceberg-demo`: snapshots, time travel, rollback, small files and expiration, shown on a
sandbox copy of silver.orders.

Bronze and silver are never touched: a rollback or an expired snapshot there would break the
streams that read them (ADR-021). The sandbox `lake.demo.orders` is rebuilt on every run.
"""

from pyspark.errors import PySparkException
from pyspark.sql import SparkSession

from spark_jobs.catalog import CATALOG, build_session
from spark_jobs.settings import Settings

DEMO = f"{CATALOG}.demo.orders"
NAME = "demo.orders"
SOURCE = f"{CATALOG}.silver.orders"


def show(spark: SparkSession, title: str, sql: str) -> None:
    print(f"\n=== {title}\n{sql.strip()}")
    spark.sql(sql).show(truncate=False)


def scalar(spark: SparkSession, sql: str) -> int:
    return int(spark.sql(sql).first()[0])  # type: ignore[index]


def now_literal(spark: SparkSession) -> str:
    """CALL accepts only literals, so the time is formatted, not written as a function."""
    value = spark.sql(
        "select date_format(current_timestamp(), 'yyyy-MM-dd HH:mm:ss.SSSSSS')"
    ).first()
    return f"TIMESTAMP '{value[0]}'"  # type: ignore[index]


def build(spark: SparkSession, rows: int, appends: int) -> None:
    spark.sql(f"create namespace if not exists {CATALOG}.demo")
    spark.sql(f"drop table if exists {DEMO} purge")
    spark.sql(
        f"create table {DEMO} using iceberg tblproperties ('format-version' = '2') as "
        f"select * from {SOURCE} where not _is_deleted limit {rows}"
    )
    # One commit per insert: every one adds a snapshot and a tiny file, the small-files problem.
    for i in range(appends):
        spark.sql(
            f"insert into {DEMO} select * from {SOURCE} where not _is_deleted "
            f"limit 5 offset {rows + 5 * i}"
        )


def walkthrough(spark: SparkSession, rows: int = 1000, appends: int = 20) -> dict[str, int]:
    result: dict[str, int] = {}
    build(spark, rows, appends)
    count = f"select count(*) from {DEMO}"
    result["rows"] = scalar(spark, f"select count(*) from {DEMO}") - 5 * appends

    show(
        spark,
        "Every commit is a snapshot",
        f"select committed_at, snapshot_id, operation, summary['added-records'] as added "
        f"from {DEMO}.snapshots order by committed_at",
    )
    first = scalar(spark, f"select snapshot_id from {DEMO}.snapshots order by committed_at limit 1")
    show(
        spark,
        "Time travel: the first snapshot against now",
        f"select (select count(*) from {DEMO} version as of {first}) as first_snapshot, "
        f"({count}) as now",
    )

    good = scalar(
        spark, f"select snapshot_id from {DEMO}.snapshots order by committed_at desc limit 1"
    )
    spark.sql(f"delete from {DEMO} where order_status = 'delivered'")
    result["after_accident"] = scalar(spark, count)
    accident = scalar(
        spark, f"select snapshot_id from {DEMO}.snapshots order by committed_at desc limit 1"
    )
    show(spark, "An accidental DELETE", count)
    show(
        spark,
        "Rollback moves the pointer; nothing is rewritten",
        f"call {CATALOG}.system.rollback_to_snapshot(table => '{NAME}', snapshot_id => {good})",
    )
    result["after_rollback"] = scalar(spark, count)
    show(
        spark,
        "The rolled-back snapshot still exists, off the current line",
        f"select snapshot_id, is_current_ancestor from {DEMO}.history order by made_current_at",
    )
    show(
        spark,
        "...so the rollback itself can be undone",
        f"call {CATALOG}.system.set_current_snapshot(table => '{NAME}', snapshot_id => {accident})",
    )
    spark.sql(
        f"call {CATALOG}.system.rollback_to_snapshot(table => '{NAME}', snapshot_id => {good})"
    )

    files = f"select count(*) from {DEMO}.files"
    result["files_before"] = scalar(spark, files)
    show(
        spark,
        "Small files",
        f"select count(*) as files, sum(file_size_in_bytes) as bytes from {DEMO}.files",
    )
    show(
        spark,
        "Compaction: many small files into one",
        f"call {CATALOG}.system.rewrite_data_files(table => '{NAME}', "
        "options => map('min-input-files', '2'))",
    )
    result["files_after"] = scalar(spark, files)
    show(
        spark,
        "Old files are still referenced by old snapshots",
        f"select count(distinct file_path) as all_data_files from {DEMO}.all_data_files",
    )

    show(
        spark,
        "Expire every snapshot but the current one",
        f"call {CATALOG}.system.expire_snapshots(table => '{NAME}', "
        f"older_than => {now_literal(spark)}, retain_last => 1)",
    )
    result["snapshots_after_expire"] = scalar(spark, f"select count(*) from {DEMO}.snapshots")
    show(
        spark,
        "Unreferenced files are gone",
        f"select count(distinct file_path) as all_data_files from {DEMO}.all_data_files",
    )
    try:
        spark.sql(f"select count(*) from {DEMO} version as of {first}").collect()
        print(f"\nunexpected: snapshot {first} still readable")
    except PySparkException as error:
        print(f"\n=== Time travel to an expired snapshot fails\n{str(error).splitlines()[0]}")

    print(
        "\nThe same in Trino (make trino):\n"
        f'  select * from demo."orders$snapshots";\n'
        f"  select count(*) from demo.orders for version as of <snapshot_id>;\n"
        f'  select content, count(*) from demo."orders$files" group by 1;'
    )
    return result


def main() -> None:
    spark = build_session("iceberg_demo", Settings())
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    walkthrough(spark)
    spark.stop()


if __name__ == "__main__":
    main()
```

- [ ] **Шаг 4: Makefile и README**

```make
iceberg-demo: ## snapshots, time travel, rollback, compaction, expiration on lake.demo.orders
	$(COMPOSE) --profile core run --rm --no-deps spark-silver iceberg_demo
```

`SPARK_TESTS` += `test_iceberg_demo.py`. `scripts/README.md`: строку про `iceberg/demo.sh` заменить на `make iceberg-demo` → `streaming/spark_jobs/iceberg_demo.py`. `streaming/README.md`: строка про `iceberg_demo.py`. `OPERATIONS.md`: `make iceberg-demo` в Daily commands уже есть, добавить фразу «works on lake.demo.orders only».

- [ ] **Шаг 5: тесты зелёные**

Run: `make lint && make test && make test-spark`
Expected: PASS.

- [ ] **Шаг 6: живой прогон**

```bash
docker compose --env-file .env -f docker/compose.yaml --profile core build spark-bronze
make iceberg-demo
make trino   # select count(*) from demo.orders; select * from demo."orders$snapshots";
```

Перенаправлять stderr не нужно: job сам понижает логирование Spark до WARN (`setLogLevel` в `main()`). Из терминала `docker compose run` выделяет TTY и сливает stderr контейнера в stdout, так что `2>/dev/null` всё равно не помогло бы. До создания сессии остаются около 38 строк INFO при старте: почти все убирает `spark.log.level=WARN` при сборке сессии (остаются 3 строки SparkContext) или `log4j2.properties` в `SPARK_CONF_DIR` образа (вне этой задачи).

Expected: все секции напечатаны, после первого rollback снова все строки, файлов после compaction 1, после expire снапшот 1, последняя секция показывает ошибку time travel.

- [ ] **Шаг 7: ревью и коммит**

```bash
git add streaming/spark_jobs/iceberg_demo.py tests/unit/test_iceberg_demo.py Makefile scripts/README.md streaming/README.md OPERATIONS.md
git commit -m "lake: iceberg demo on a sandbox table, snapshots to expiration"
```

---

### Задача 9: W2-T07 schema evolution, сторона реплеера

**Файлы:**
- Создать: `oltp/migrations/evolution/003_orders_sales_channel.sql`, `tests/unit/test_replay_evolution.py`
- Изменить: `oltp/replayer/settings.py`, `oltp/replayer/replay.py`, `tests/unit/test_settings.py`, `tests/unit/test_contracts.py`, `oltp/README.md`, `.env.example` (комментарий)

**Интерфейсы:**
- Производит: `Settings.replay_schema_evolution_at: datetime | None`; `evolution_due(at, now, applied) -> bool`, `EVOLUTION: Path`, `INSERT_ORDER_WITH_CHANNEL` в `replay.py`; в `test_contracts.py` `evolution_columns() -> dict[str, list[tuple[str, str, str]]]`.

- [ ] **Шаг 1: падающие тесты**

`tests/unit/test_replay_evolution.py`:

```python
from datetime import datetime

from replayer.replay import EVOLUTION, evolution_due

AT = datetime(2026, 7, 1, 12, 0)


def test_not_configured_never_fires() -> None:
    assert not evolution_due(None, datetime(2030, 1, 1), applied=False)


def test_fires_once_the_virtual_clock_reaches_the_mark() -> None:
    assert not evolution_due(AT, datetime(2026, 7, 1, 11, 59), applied=False)
    assert evolution_due(AT, AT, applied=False)


def test_mark_already_behind_the_clock_fires_on_the_first_step() -> None:
    assert evolution_due(AT, datetime(2026, 9, 1), applied=False)


def test_applied_never_fires_again() -> None:
    assert not evolution_due(AT, datetime(2026, 9, 1), applied=True)


def test_migration_lives_outside_make_migrate() -> None:
    assert EVOLUTION.is_file()
    assert EVOLUTION.parent.name == "evolution"
```

`test_settings.py`:

```python
def test_empty_schema_evolution_mark_means_never(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPLAY_SCHEMA_EVOLUTION_AT", "")

    assert Settings().replay_schema_evolution_at is None


def test_schema_evolution_mark_is_a_virtual_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPLAY_SCHEMA_EVOLUTION_AT", "2026-07-01T12:00:00")

    assert Settings().replay_schema_evolution_at == datetime(2026, 7, 1, 12, 0)
```

`test_contracts.py`: разбор `evolution/` и ослабленное сравнение:

```python
EVOLUTION = ROOT / "oltp" / "migrations" / "evolution"
ADD_COLUMN = re.compile(
    r"alter table shop\.(\w+) add column (\w+) (varchar\(\d+\)|text|integer|timestamp)"
)


def silver_types(pg_type: str) -> tuple[str, str]:
    if pg_type.startswith("numeric"):
        precision, scale = re.findall(r"\d+", pg_type)
        return "number", f"decimal({precision},{scale})"
    if pg_type in ("integer", "smallint"):
        return "integer", "int"
    if pg_type == "timestamp":
        return "integer", "timestamp_ntz"
    return "string", "string"


def evolution_columns() -> dict[str, list[tuple[str, str, str]]]:
    """Columns that later migrations add; a contract may adopt them or not yet."""
    added: dict[str, list[tuple[str, str, str]]] = {}
    for path in sorted(EVOLUTION.glob("*.sql")):
        for table, column, pg_type in ADD_COLUMN.findall(path.read_text()):
            added.setdefault(table, []).append((column, *silver_types(pg_type)))
    return added


@pytest.mark.parametrize("table", sorted(source_tables()))
def test_contract_matches_the_source_table(table: str) -> None:
    source = source_tables()[table]
    contract = load_contracts(CONTRACTS)[table]
    columns = [(c.name, c.wire_type, c.silver_type) for c in contract.columns]
    base = source["columns"]

    assert contract.source_table == f"shop.{table}"
    assert columns[: len(base)] == base
    assert columns[len(base) :] == [c for c in evolution_columns().get(table, []) if c in columns]
    assert {c.name for c in contract.columns if not c.nullable} == source["not_null"]
    assert list(contract.primary_key) == source["primary_key"]


def test_evolution_migration_adds_sales_channel() -> None:
    assert ("sales_channel", "string", "string") in evolution_columns()["orders"]
```

Функция `source_tables()` использует `silver_types()` вместо своей ветки `if/elif`.

- [ ] **Шаг 2: убедиться, что тесты падают**

Run: `make test`
Expected: FAIL, `ImportError: cannot import name 'EVOLUTION'` и `KeyError: 'orders'`.

- [ ] **Шаг 3: миграция**

`oltp/migrations/evolution/003_orders_sales_channel.sql`:

```sql
-- Schema evolution scenario (W2-T07). `make migrate` does not see this directory: the replayer
-- applies the file when its virtual clock reaches REPLAY_SCHEMA_EVOLUTION_AT, so the change
-- lands in the middle of the stream. Nullable with no default: orders written before stay null.
alter table shop.orders add column sales_channel varchar(16);

alter table shop.orders add constraint orders_sales_channel_check
check (sales_channel in ('web', 'app', 'marketplace'));
```

- [ ] **Шаг 4: настройки**

`oltp/replayer/settings.py`:

```python
# Virtual time at which evolution/003 is applied; empty means never.
replay_schema_evolution_at: datetime | None = None


@field_validator("replay_schema_evolution_at", mode="before")
@classmethod
def _empty_means_never(cls, value: object) -> object:
    return None if value == "" else value
```

Импорты `from datetime import datetime`, `from pydantic import Field, field_validator`.

- [ ] **Шаг 5: реплеер**

В `replay.py`:

```python
from replayer import migrations, server, state

EVOLUTION = migrations.migrations_dir() / "evolution" / "003_orders_sales_channel.sql"

INSERT_ORDER_WITH_CHANNEL = """
insert into shop.orders (order_id, customer_id, order_status, order_purchase_timestamp,
                         order_estimated_delivery_date, sales_channel)
select order_id, customer_id, 'created', order_purchase_timestamp, order_estimated_delivery_date,
       (array['web', 'app', 'marketplace'])[1 + mod(('x' || substr(md5(order_id), 1, 7))::bit(28)::int, 3)]
from replay.orders where order_id = %s
on conflict (order_id) do nothing
"""


def evolution_due(at: datetime | None, now: datetime, applied: bool) -> bool:
    return at is not None and not applied and now >= at


def has_column(conn: Conn, table: str, column: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "select 1 from information_schema.columns "
            "where table_schema = 'shop' and table_name = %s and column_name = %s",
            (table, column),
        )
        found = cur.fetchone() is not None
    conn.commit()
    return found
```

В `Replayer.__init__`: `self.channel = has_column(conn, "orders", "sales_channel")`. В начале `step()` после `now = self.virtual_now()`:

```python
        if evolution_due(self.settings.replay_schema_evolution_at, now, self.channel):
            migrations.apply(self.conn, EVOLUTION)
            self.channel = True
            server.EVENTS.labels(kind="schema_evolution").inc()
            log.info("applied %s at virtual %s", EVOLUTION.name, now)
```

В `execute()` для `order_insert`: `cur.execute(INSERT_ORDER_WITH_CHANNEL if self.channel else INSERT_ORDER, (event.order_id,))`. Колонка существует, значит миграция применена, поэтому рестарт её не повторяет.

- [ ] **Шаг 6: тесты зелёные**

Run: `make lint && make test && make test-spark`
Expected: PASS (`sqlfluff` проверяет и новый файл).

- [ ] **Шаг 7: проверка на одноразовом Postgres (живой стек не трогается)**

Колонка на живом `shop.orders` это момент Modify-гейта владельца, поэтому механизм проверяется на отдельном контейнере:

```bash
probe=$(mktemp -d) && mkdir "$probe/raw" && cp data/sample/*.csv "$probe/raw/"
docker run -d --rm --name evolution-probe -p 127.0.0.1:55432:5432 \
  -e POSTGRES_DB=shop -e POSTGRES_USER=shop -e POSTGRES_PASSWORD=probe \
  -e DEBEZIUM_USER=debezium -e DEBEZIUM_PASSWORD=probe \
  -v "$PWD/oltp/init:/docker-entrypoint-initdb.d:ro" postgres:17
sleep 8
export OLTP_DSN=postgresql://shop:probe@127.0.0.1:55432/shop DATA_DIR="$probe"
make migrate && make replay-load
q() { docker exec evolution-probe psql -U shop -d shop -Atc "$1"; }
mark=$(q "select virtual_now + interval '1 day' from replay.state")
PYTHONPATH=oltp REPLAY_SPEED=86400 REPLAY_SCHEMA_EVOLUTION_AT="$mark" timeout 20 \
  .venv/bin/python -m replayer start 2>&1 | grep -i 'applied 003'
q "select sales_channel, count(*) from shop.orders group by 1"
docker stop evolution-probe && rm -rf "$probe"
```

Ожидаемо: `applied 003_orders_sales_channel.sql at virtual ...`, в Postgres строки с `null` (старые) и с тремя значениями (новые). Контейнер запущен с `--rm`, его анонимный том удаляется вместе с ним; это одноразовый стенд, не данные проекта.

- [ ] **Шаг 8: документация**

`oltp/README.md`: абзац про `migrations/evolution/` и `REPLAY_SCHEMA_EVOLUTION_AT` (формат ISO, виртуальное время, применяется один раз). `.env.example`: комментарий `# virtual time, ISO (2026-07-01T12:00:00), applies migrations/evolution/003; empty = never`.

- [ ] **Шаг 9: ревью и коммит**

```bash
git add oltp/migrations/evolution/003_orders_sales_channel.sql oltp/replayer/settings.py oltp/replayer/replay.py tests/unit/test_replay_evolution.py tests/unit/test_settings.py tests/unit/test_contracts.py oltp/README.md .env.example
git commit -m "oltp: schema evolution at a virtual time, orders gain sales_channel mid-stream"
```

---

### Задача 10: W2-T09 Lakekeeper (лимит 3 ч)

**Файлы:**
- Изменить: `docker/compose.yaml` (lakekeeper, lakekeeper-migrate, lakekeeper-bootstrap, Spark env), `.env.example`, `scripts/make_env.py`
- Создать: `scripts/lakekeeper/bootstrap.sh`, `scripts/lakekeeper/register.sh`, `docs/runbooks/catalog-cutover.md`
- Изменить: `streaming/spark_jobs/settings.py`, `streaming/spark_jobs/catalog.py`, `tests/unit/test_spark_settings.py`, `docker/trino/etc/catalog/lake.properties`
- Изменить: `DECISIONS.md` (ADR-005), `OPERATIONS.md`, `docs/planning/00-mini-architecture-review.md` (§5, версия)

Таймер: старт фиксируется в начале шага 1. На 3:00 стоп и ADR-005 с причиной, если не пройден шаг 6.

- [ ] **Шаг 1: решения владельца (всплывающий вопрос)**

Четыре вопроса: (a) новые таблицы на `s3://` с `fs.s3.impl` → S3A в Spark (рекомендация: стандартная схема, нужна и для `remove_orphan_files`) или принудительно `s3a://` в `ensure_table`; (b) warehouse `delete-profile: soft` на 7 дней (рекомендация: да); (c) отдельный `LAKEKEEPER_ENCRYPTION_KEY` в `.env` вместо `META_PASSWORD` (рекомендация: да, это изменение `.env`-контракта); (d) строка «DROP TABLE через REST-каталог удаляет файлы» в blast radius `CLAUDE.md` (рекомендация: да).

- [ ] **Шаг 2: compose без переключения**

```yaml
  lakekeeper-migrate:
    # digest: docker pull quay.io/lakekeeper/catalog:v0.13.6 && docker inspect -f '{{index .RepoDigests 0}}' quay.io/lakekeeper/catalog:v0.13.6
    image: quay.io/lakekeeper/catalog:v0.13.6@sha256:<RepoDigest из команды выше>
    profiles: [rest]
    depends_on:
      postgres-meta:
        condition: service_healthy
    command: ["migrate"]
    environment: &lakekeeper-env
      LAKEKEEPER__PG_DATABASE_URL_WRITE: postgresql://${META_USER}:${META_PASSWORD}@postgres-meta:5432/${LAKEKEEPER_DB}
      LAKEKEEPER__PG_ENCRYPTION_KEY: ${LAKEKEEPER_ENCRYPTION_KEY}
    restart: "no"
    logging: *logging
    networks: [lake]

  lakekeeper:
    <<: *common
    image: quay.io/lakekeeper/catalog:v0.13.6@sha256:<тот же RepoDigest>
    profiles: [rest]
    depends_on:
      lakekeeper-migrate:
        condition: service_completed_successfully
      minio-init:
        condition: service_completed_successfully
    command: ["serve"]
    environment: *lakekeeper-env
    ports:
      - "${BIND_IP}:8181:8181"
    healthcheck:
      # Distroless image: no shell, no curl. The binary checks its own /health.
      test: ["CMD", "/home/nonroot/lakekeeper", "healthcheck"]
      interval: 10s
      timeout: 5s
      retries: 10
    deploy:
      resources:
        limits:
          memory: 256M
    networks: [lake]
```

`.env.example`: `LAKEKEEPER_ENCRYPTION_KEY=change_me`; `scripts/make_env.py` генерирует его как остальные секреты (проверить, как он находит `change_me`). Проверка: `docker compose ... config -q`, затем `docker compose ... --profile rest up -d lakekeeper`, `docker inspect -f '{{.State.Health.Status}}' lakehouse-lakekeeper-1` → `healthy`.

- [ ] **Шаг 3: bootstrap и warehouse (`scripts/lakekeeper/bootstrap.sh`)**

```bash
#!/usr/bin/env bash
# Bootstrap Lakekeeper once and create warehouse `lake` on MinIO. Safe to re-run: it checks state
# first. Clients keep their own S3 keys: no STS, no remote signing (ADR-005).
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
set -a; . "$root/.env"; set +a
api=${LAKEKEEPER_API:-http://127.0.0.1:8181}

if [ "$(curl -sf "$api/management/v1/info" | python3 -c 'import json,sys; print(json.load(sys.stdin)["bootstrapped"])')" = False ]; then
  curl -sf -X POST "$api/management/v1/bootstrap" -H 'Content-Type: application/json' \
    -d '{"accept-terms-of-use": true}'
  echo "bootstrapped"
fi

if curl -sf "$api/management/v1/warehouse" | grep -q '"name":"lake"'; then
  echo "warehouse lake exists"; exit 0
fi
python3 - "$api" <<'EOF' | curl -sf -X POST "$api/management/v1/warehouse" -H 'Content-Type: application/json' --data @-
import json, os
print(json.dumps({
    "warehouse-name": "lake",
    "storage-profile": {
        "type": "s3", "bucket": os.environ["S3_BUCKET"], "key-prefix": "warehouse",
        "endpoint": "http://minio:9000", "region": "us-east-1", "path-style-access": True,
        "flavor": "s3-compat", "sts-enabled": False, "remote-signing-enabled": False,
        # Spark wrote every existing table under s3a://; registering them needs this.
        "allow-alternative-protocols": True,
    },
    "storage-credential": {
        "type": "s3", "credential-type": "access-key",
        "access-key-id": os.environ["S3_ACCESS_KEY"], "secret-access-key": os.environ["S3_SECRET_KEY"],
    },
    "delete-profile": {"type": "soft", "expiration-seconds": 604800},
}))
EOF
echo "warehouse lake created"
```

Проверка: повторный запуск печатает `warehouse lake exists`; `curl -s '127.0.0.1:8181/catalog/v1/config?warehouse=lake'` отдаёт `defaults.prefix`.

- [ ] **Шаг 4: Spark rest-ветка (TDD)**

Тест в `test_spark_settings.py` заменяет `test_rest_catalog_is_refused_until_w2_t09`:

```python
def test_unknown_catalog_type_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CATALOG_TYPE", "glue")

    with pytest.raises(ValidationError):
        Settings()


def test_rest_catalog_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CATALOG_TYPE", "rest")

    assert Settings().catalog_type == "rest"
```

И тест конфигурации сессии без JVM (`catalog.py` получает чистую функцию `catalog_conf(settings) -> dict[str, str]`, `build_session` применяет её):

```python
from spark_jobs.catalog import catalog_conf


def test_rest_catalog_pins_hadoop_file_io(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CATALOG_TYPE", "rest")

    conf = catalog_conf(Settings())

    assert conf["spark.sql.catalog.lake.type"] == "rest"
    assert conf["spark.sql.catalog.lake.io-impl"] == "org.apache.iceberg.hadoop.HadoopFileIO"
    assert conf["spark.hadoop.fs.s3.impl"] == "org.apache.hadoop.fs.s3a.S3AFileSystem"
```

Реализация. `settings.py`: `catalog_type: Literal["jdbc", "rest"] = "jdbc"`, `lakekeeper_uri: str = "http://lakekeeper:8181/catalog"`, `lakekeeper_warehouse: str = "lake"`. `catalog.py`:

```python
def catalog_conf(settings: Settings) -> dict[str, str]:
    """Spark conf for catalog `lake` and S3A. Kept apart from the builder so it is testable
    without a JVM."""
    cat = f"spark.sql.catalog.{CATALOG}"
    conf = {
        "spark.sql.extensions": "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        cat: "org.apache.iceberg.spark.SparkCatalog",
        "spark.hadoop.fs.s3a.impl": "org.apache.hadoop.fs.s3a.S3AFileSystem",
        "spark.hadoop.fs.s3a.endpoint": settings.s3_endpoint,
        "spark.hadoop.fs.s3a.access.key": settings.s3_access_key,
        "spark.hadoop.fs.s3a.secret.key": settings.s3_secret_key,
        "spark.hadoop.fs.s3a.path.style.access": "true",
        "spark.hadoop.fs.s3a.connection.ssl.enabled": "false",
    }
    if settings.catalog_type == "jdbc":
        conf |= {
            f"{cat}.type": "jdbc",
            f"{cat}.uri": settings.catalog_jdbc_url,
            f"{cat}.jdbc.user": settings.catalog_jdbc_user,
            f"{cat}.jdbc.password": settings.catalog_jdbc_password,
            f"{cat}.warehouse": settings.catalog_warehouse,
        }
    else:
        conf |= {
            f"{cat}.type": "rest",
            f"{cat}.uri": settings.lakekeeper_uri,
            f"{cat}.warehouse": settings.lakekeeper_warehouse,
            # The REST client would pick S3FileIO for s3 paths, and the image has no AWS SDK v2.
            f"{cat}.io-impl": "org.apache.iceberg.hadoop.HadoopFileIO",
            # Lakekeeper places new tables under s3://; Hadoop 3.3 only knows s3a.
            "spark.hadoop.fs.s3.impl": "org.apache.hadoop.fs.s3a.S3AFileSystem",
        }
    return conf


def build_session(app_name: str, settings: Settings) -> SparkSession:
    """Master and driver memory come from spark-submit, because in local mode the driver JVM
    is already running by the time this builder sees any config."""
    builder = SparkSession.builder.appName(app_name)
    for key, value in catalog_conf(settings).items():
        builder = builder.config(key, value)
    return builder.getOrCreate()
```

Если в шаге 1 выбран вариант (b), строки `fs.s3.impl` нет, а `ensure_table` в silver и `DDL` в bronze получают явный `location 's3a://...'`. В compose сервисам `spark-bronze` и `spark-silver` передать `LAKEKEEPER_URI`, `LAKEKEEPER_WAREHOUSE` (у bronze уже есть). Run: `make test`. Expected: PASS.

- [ ] **Шаг 5: регистрация и сверка side-by-side (без переключения)**

`scripts/lakekeeper/register.sh`:

```bash
#!/usr/bin/env bash
# Register every table of the JDBC catalog `lake` in Lakekeeper at its current metadata file.
# Writers must be stopped first, or the two catalogs fork. Re-running overwrites the pointer and
# never drops anything: a DROP on Lakekeeper deletes the files both catalogs share.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
set -a; . "$root/.env"; set +a
api=${LAKEKEEPER_API:-http://127.0.0.1:8181}
compose=(docker compose --env-file "$root/.env" -f "$root/docker/compose.yaml")

if docker ps --format '{{.Names}}' | grep -q '^lakehouse-spark-bronze-1$'; then
  echo "spark-bronze is running; stop it first (docker stop lakehouse-spark-bronze-1)" >&2
  exit 1
fi
prefix=$(curl -sf "$api/catalog/v1/config?warehouse=${LAKEKEEPER_WAREHOUSE}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["defaults"]["prefix"])')

"${compose[@]}" exec -T postgres-meta psql -U "$META_USER" -d "$CATALOG_DB" -At -F $'\t' -c \
  "select table_namespace, table_name, metadata_location from iceberg_tables
   where catalog_name = 'lake' and coalesce(iceberg_type, 'TABLE') = 'TABLE' order by 1, 2" |
while IFS=$'\t' read -r ns name location; do
  curl -s -o /dev/null -X POST "$api/catalog/v1/$prefix/namespaces" \
    -H 'Content-Type: application/json' -d "{\"namespace\": [\"$ns\"]}" || true
  curl -sf -X POST "$api/catalog/v1/$prefix/namespaces/$ns/register" \
    -H 'Content-Type: application/json' \
    -d "{\"name\": \"$name\", \"metadata-location\": \"$location\", \"overwrite\": true}" >/dev/null
  echo "registered $ns.$name at $location"
done
```

Создание namespace, который уже есть, отвечает 409; это ожидаемо, поэтому ответ не проверяется, а ошибка регистрации ловится `-sf` на следующем вызове. Перед запуском: `docker stop lakehouse-spark-bronze-1` (writer остановлен, иначе каталоги разойдутся) и не запускать silver.

Временный `docker/trino/etc/catalog/lake_rest.properties` (rest-конфиг), `docker restart lakehouse-trino-1`, сравнить для всех таблиц `count(*)` и последний `snapshot_id` в `lake` и `lake_rest`. Expected: совпадают. Если не совпали или не прошла регистрация и таймер за 3:00: удалить `lake_rest.properties`, `docker start lakehouse-spark-bronze-1`, записать ADR-005 с причиной, коммит `docs: adr-005, lakekeeper postponed`, задача закрыта.

- [ ] **Шаг 6: переключение (отдельное «ок» владельца)**

Runbook `docs/runbooks/catalog-cutover.md` (шаги, откат до первого REST-коммита бесплатный, после него откат через `register` в JDBC, это blast radius). После «ок»: `CATALOG_TYPE=rest` в `.env`, `lake.properties` на rest (JDBC-ключи убрать), `lake_rest.properties` удалить, `docker compose ... --profile core --profile query --profile rest up -d spark-bronze trino lakekeeper`. Проверки: `Resuming at batch` в bronze, `make silver` без новых строк (checkpoint silver жив), короткая порция реплея, `bronze_offsets_report` без дублей, `reconcile` ok. `docker stats --no-stream lakehouse-lakekeeper-1` в OPERATIONS.

- [ ] **Шаг 7: документация и коммит**

ADR-005: итог (принят REST с деталями или отложен с причиной), `00-mini-architecture-review.md` §5 версия v0.13.6, OPERATIONS (профиль `rest` теперь в рабочих комбинациях, порт 8181, bootstrap, DROP на REST).

```bash
git add docker/compose.yaml .env.example scripts/make_env.py scripts/lakekeeper streaming/spark_jobs/settings.py streaming/spark_jobs/catalog.py tests/unit/test_spark_settings.py docker/trino/etc/catalog/lake.properties docs/runbooks/catalog-cutover.md DECISIONS.md OPERATIONS.md docs/planning/00-mini-architecture-review.md
git commit -m "lake: lakekeeper rest catalog, tables registered, spark and trino switched"
```

---

### Задача 11: итоги W2

**Файлы:** `docs/HANDOFF.md`, `docs/planning/00-mini-architecture-review.md` (§6, `docker stats`)

- [ ] **Шаг 1:** `docker stats --no-stream` в RAM-таблицу §6 с датой.
- [ ] **Шаг 2:** `HANDOFF.md`: состояние задач W2, что живёт в стеке, израсходованный реплей (виртуальное время до и после), подсказка к Modify-гейту W2-T07 (файлы `contracts/silver/orders.json`, `ALTER TABLE lake.silver.orders ADD COLUMN sales_channel string` в Trino или Spark, затем `REPLAY_SCHEMA_EVOLUTION_AT` и проверка SQL), решения, ждущие владельца (раздел 6 спеки), следующий шаг W3.
- [ ] **Шаг 3:** коммит `docs: handoff after week 2`.
