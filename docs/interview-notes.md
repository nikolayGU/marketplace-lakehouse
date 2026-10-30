# Interview notes

Thirty questions a data engineer interviewer can ask about this project, each with a short general
answer and a concrete example from the repository. Numbers carry the date of the live run they come
from, with the source in the link.

Contents: [Kafka and CDC](#kafka-and-cdc) (5), [Spark Structured Streaming](#spark-structured-streaming) (5),
[Iceberg](#iceberg) (4), [Idempotency and exactly-once](#idempotency-and-exactly-once) (4),
[Data quality](#data-quality) (4), [Observability](#observability) (4),
[System design](#system-design-oltp-to-lakehouse-with-correct-end-state) (4).

## Kafka and CDC

**1. What is a partition, why key records by the primary key, and what does Kafka guarantee about order?**

A partition is an ordered, append-only log; a topic is split into partitions for parallelism. Kafka
orders records only inside one partition. A producer that keys by primary key sends every change of
one row to the same partition, so a consumer sees that row's changes in the order they were
written. Across partitions there is no order at all.

In this project: Debezium writes one topic per table, `oltp.shop.<table>`, keyed by primary key,
3 partitions each ([ARCHITECTURE.md](../ARCHITECTURE.md), data flow step 2;
[.env.example:29](../.env.example)). Seven tables make the 21 topic partitions that bronze is checked
against for repeated and missing offsets ([OPERATIONS.md, scenario 1](../OPERATIONS.md#1-spark-bronze-killed-mid-batch)).
Silver still does not rely on arrival order: it orders changes of a key by LSN (question 17).

**2. Where does at-least-once come from, and what is an offset and a consumer group?**

An offset is the position of a record inside one partition. A consumer group splits partitions
between its members and commits the offsets it has processed. If a producer or consumer crashes after
doing the work but before recording the position, the work is done again: that is at-least-once.
Exactly-once needs an idempotent or transactional sink on top.

In this project: Debezium re-sends events after a hard stop of Connect, 253 events in the run of
2026-10-07 ([OPERATIONS.md, scenario 2b](../OPERATIONS.md#2b-kafka-connect-killed)). Spark does not use a consumer group
at all: it keeps offsets in its checkpoint, so `kafka-exporter` shows no lag for it and a
`StreamingQueryListener` exports the lag instead ([ADR-013](../DECISIONS.md#adr-013-spark-metrics)).
`make kafka-groups` lists Connect only ([OPERATIONS.md, Daily commands](../OPERATIONS.md#daily-commands)).

**3. What happens when Kafka retention is shorter than the consumer's downtime? Replay or reprocess?**

Records the consumer never read are deleted. A consumer that silently skips the gap loses data, so
the safe setting is to fail. Replay means producing history again from the source; reprocess means
reading what Kafka still holds a second time, for example from a reset checkpoint. They fix different
problems: replay fills a gap that left Kafka, reprocess fixes logic over data that is still there.
Here "replay" also names the replayer that plays Olist history into Postgres
([ARCHITECTURE.md](../ARCHITECTURE.md), data flow step 1).

In this project: retention is 24 h ([.env.example:28](../.env.example)) and the bronze reader sets
`failOnDataLoss=true` ([streaming/spark_jobs/bronze_cdc_ingest.py:135](../streaming/spark_jobs/bronze_cdc_ingest.py)),
so the symptom is a restart loop, not a quiet skip. This happened on 2026-09-22: the stack had run
26 hours with nothing consuming Kafka. The fix was a Debezium incremental snapshot driven by a signal
table (`make cdc-snapshot`), which re-reads the source in key chunks without touching the slot
([ADR-019](../DECISIONS.md#adr-019-incremental-snapshots-through-a-signal-table)). Its limit is documented: once silver holds a streamed
LSN for a key, a snapshot read cannot change that row.

**4. Why log-based CDC, and what do the replication slot and `REPLICA IDENTITY FULL` cost?**

Reading the write-ahead log captures every insert, update and delete, deletes included, without
query load on the source and without a timestamp column to poll. The replication slot makes Postgres
keep WAL until the consumer confirms it, which is what makes the stream durable and also what can
fill the disk when the consumer stops. `REPLICA IDENTITY FULL` puts the whole old row into the WAL,
so `before` in an update event carries every column.

In this project: the connector uses `pgoutput`, slot `shop_slot` and `snapshot.mode=initial`
([connect/shop-connector.json:12](../connect/shop-connector.json)). All seven tables have `REPLICA
IDENTITY FULL` so one UPDATE envelope shows what changed; the price is more WAL ([ADR-018](../DECISIONS.md#adr-018-replica-identity-full-on-the-source-tables)). The slot risk was measured on 2026-10-23: with the connector stopped, `ConnectorNotRunning`
fired 95 s after the stop and `SlotWalRetainedHigh` 326 s after it, with about 80 MB held and
`max_slot_wal_keep_size = -1` ([OPERATIONS.md, scenario 6](../OPERATIONS.md#6-connector-stopped-for-30-minutes-wal-growth); alert table in
[OPERATIONS.md, Alerts](../OPERATIONS.md#alerts)).

**5. What does a Kafka Connect restart do to the data, compared with a kill?**

Connect stores source offsets periodically. A graceful stop waits for producer acknowledgements and
commits the final offset, so on resume Debezium can drop whatever Postgres sends again. A kill skips
that commit, so everything since the last periodic flush is produced a second time with the same LSN.
Nothing is lost in either case; only repeats differ.

In this project: on 2026-10-07 `docker restart` of Connect produced 0 events repeated with the same
LSN (1429 CDC events in the minute before the restart, 1593 after), recovery took about 32 s
([OPERATIONS.md, scenario 2a](../OPERATIONS.md#2a-kafka-connect-restart)). `docker kill` about 9 s after an offset flush
repeated 253 events, and live row counts of all seven silver tables still matched Postgres
([OPERATIONS.md, scenario 2b](../OPERATIONS.md#2b-kafka-connect-killed)). The repeat count follows the time since the
last flush, up to `offset.flush.interval.ms` = 60 s.

## Spark Structured Streaming

**6. How does the micro-batch model work, what is in a checkpoint, and how do `ProcessingTime` and `AvailableNow` differ?**

Structured Streaming plans a batch from the offsets since the last one, runs it, and records
progress in the checkpoint: planned offsets first, a commit marker after the sink succeeded, plus
operator state for stateful queries. `ProcessingTime` keeps a long-running query that starts a batch
at an interval. `AvailableNow` processes everything available in bounded micro-batches and then
stops, so it suits a scheduled job.

In this project: bronze is a continuous query with a 20 s trigger
([streaming/spark_jobs/bronze_cdc_ingest.py:144](../streaming/spark_jobs/bronze_cdc_ingest.py)).
Silver is a separate job that reads bronze as an Iceberg stream with `Trigger.AvailableNow`, started
every 5 minutes by Airflow, with its own checkpoint ([streaming/spark_jobs/silver_upsert.py:321](../streaming/spark_jobs/silver_upsert.py);
[ADR-007](../DECISIONS.md#adr-007-bronze-streaming-append-silver-batch-merge)). Both checkpoints live under
`s3a://lakehouse/checkpoints/` ([OPERATIONS.md, Bronze ingest](../OPERATIONS.md#bronze-ingest) and
[Silver upsert](../OPERATIONS.md#silver-upsert)).

**7. Why is `MERGE` done in `foreachBatch` and not in the streaming sink, and what does that cost?**

The Iceberg streaming sink is append-oriented, and issuing `MERGE INTO` straight from a streaming
query is unreliable, so the upsert has to run as batch SQL inside `foreachBatch`. That function is
at-least-once: Spark can re-run a batch whose completion it did not record. The MERGE must therefore
be idempotent by construction.

In this project: bronze is an append-only streaming sink; silver reads it as a stream and runs one
`MERGE` per table per micro-batch ([ADR-007](../DECISIONS.md#adr-007-bronze-streaming-append-silver-batch-merge);
[ADR-021](../DECISIONS.md#adr-021-silver-upsert-one-availablenow-job-idempotent-merge-per-table)). The cost is latency in minutes, not seconds, which
the ADR accepts for analytics. The idempotency lives in the guard
`when matched and (t._last_lsn is null or s._last_lsn > t._last_lsn)`
([streaming/spark_jobs/silver_upsert.py:158](../streaming/spark_jobs/silver_upsert.py)).

**8. What happens when the Spark driver is killed in the middle of a batch?**

On restart Spark reads the checkpoint. If the planned offsets for batch N exist but the commit marker
does not, it re-runs batch N from the same offsets, so nothing is skipped. Whether the sink then
writes the batch twice depends on the sink: a sink that records the epoch skips a batch it already
holds.

In this project: `make chaos-spark-kill` killed the bronze driver on 2026-10-07 four seconds after
`offsets/80` was written. The log said `Resuming at batch 80`, the replayed batch committed 28 s after
the kill with the same query id, and the script found no duplicate and no missing offset in any of the
21 topic partitions ([OPERATIONS.md, scenario 1](../OPERATIONS.md#1-spark-bronze-killed-mid-batch)). Both live kills landed
before the write stage, so the commit-window case is reproduced by a unit test
(question 16).

**9. What are a watermark and state, and how does the stateful job in this project use them?**

A watermark trails the largest event time seen by a delay. A windowed aggregate keeps one state entry
per open window; when the watermark passes a window's end, the entry is dropped and later rows for
that window are discarded. Without a watermark the state grows forever. The delay trades lateness
tolerance against memory.

In this project: `orders_per_minute` counts distinct new orders per one-minute window of
`order_purchase_timestamp`, watermark 5 minutes, `update` mode, `size(collect_set(order_id))` instead
of `count(*)` because Debezium repeats would inflate a plain count
([streaming/spark_jobs/orders_per_minute.py:68](../streaming/spark_jobs/orders_per_minute.py);
[ADR-024](../DECISIONS.md#adr-024-stateful-job-orders_per_minute)). Measured on 2026-10-23 after a 60 s burst: 164
windows equal to `count(*)` of `silver.orders` per minute, 0 differing, 0 rows dropped
([OPERATIONS.md, Stateful job](../OPERATIONS.md#stateful-job)). Spark drops a late row against the watermark of the previous
batch, which is why the demo needs three runs.

**10. What do you tune in a streaming job on a 16 GB laptop, and what cannot be changed after the first run?**

Rows per batch, shuffle partitions and executor memory decide whether a batch fits. The default 200
shuffle partitions is wasteful for a small job: it makes hundreds of small tasks and state files.
Some settings are stored in the checkpoint on the first run and win over later configuration.

In this project: silver uses 4 shuffle partitions ([streaming/spark_jobs/settings.py:43](../streaming/spark_jobs/settings.py)),
batches of about 200 000 rows ([streaming/spark_jobs/settings.py:39](../streaming/spark_jobs/settings.py)) and
a 2 GB container for the merge ([airflow/dags/silver_upsert.py:62](../airflow/dags/silver_upsert.py)).
Bronze caps a trigger at 20 000 offsets ([streaming/spark_jobs/settings.py:33](../streaming/spark_jobs/settings.py)).
`silver_shuffle_partitions` is frozen in the silver checkpoint: Spark
logs `Updating the value of conf 'spark.sql.shuffle.partitions'` and restores the stored value, and a
new value needs a new checkpoint, which is on the blast-radius list because the next run re-reads all
of bronze ([OPERATIONS.md, Silver upsert](../OPERATIONS.md#silver-upsert)).

## Iceberg

**11. What are a snapshot and a manifest, and how do time travel and rollback work?**

A table is a metadata file that points to snapshots; a snapshot points to manifest lists, manifests
and data files. A commit writes new metadata and atomically swaps the pointer in the catalog, so
readers see either the old or the new state. Time travel reads an older snapshot; rollback makes an
older snapshot current again.

In this project: every bronze micro-batch is one atomic Iceberg commit
([ARCHITECTURE.md](../ARCHITECTURE.md), data flow step 3). `make iceberg-demo` shows snapshots, time
travel, rollback, compaction and expiration on a sandbox copy, `lake.demo.orders`, never on bronze or
silver ([streaming/spark_jobs/iceberg_demo.py:1](../streaming/spark_jobs/iceberg_demo.py)). In
failure scenario 9 a failing dbt test left `mart_daily_sales` at its previous snapshot: 9 snapshots
before and after, read from `"mart_daily_sales$snapshots"`
([OPERATIONS.md, scenario 9](../OPERATIONS.md#9-airflow-task-failure-dbt-test)).
Time travel deeper than 7 days on silver and gold is gone by design
([ADR-025](../DECISIONS.md#adr-025-iceberg-maintenance-policy)).

**12. Copy-on-write or merge-on-read, and why is only `silver.orders` merge-on-read?**

Copy-on-write rewrites every data file that holds a changed row: cheap reads, expensive writes.
Merge-on-read writes small delete files and reads apply them: cheap writes, more expensive reads until
compaction folds the deletes. The choice follows how many rows change per batch.

In this project: replayed orders change status several times, while the other six tables rarely
change a row twice, so `silver.orders` is merge-on-read and partitioned by month, the rest are
copy-on-write. Measured on 2026-09-26 for one replay burst each: copy-on-write rewrote 4 of 4 data
files and wrote 5 735 311 bytes; merge-on-read rewrote 0 files and wrote 77 891 bytes. The cost moves
to reads and to compaction, and `optimize` can conflict with a merge-on-read MERGE, so
`iceberg_maintenance` must not overlap `silver_upsert` ([ADR-010](../DECISIONS.md#adr-010-silver-layout-orders-merge-on-read-the-rest-copy-on-write);
layout in [streaming/spark_jobs/silver_upsert.py:34](../streaming/spark_jobs/silver_upsert.py)).

**13. Why is hidden partitioning better than Hive directories, and how do you keep small files under control?**

With hidden partitioning the table stores a transform of a column, such as `days(ts)`, so queries
filter on the column and the engine prunes partitions; nobody has to know a directory layout. The
partition spec can evolve without rewriting old data. Frequent small commits create small files and
many snapshots, which compaction and snapshot expiry then clean up.

In this project: bronze is partitioned by `(source_table, days(ingest_ts))` and `silver.orders` by
`months(order_purchase_timestamp)` ([ADR-008](../DECISIONS.md#adr-008-bronze-keeps-the-payload-as-json-text);
[ADR-010](../DECISIONS.md#adr-010-silver-layout-orders-merge-on-read-the-rest-copy-on-write)); an older unpartitioned table converges with
`ADD PARTITION FIELD`, metadata only. Bronze commits every 20 s, so the maintenance policy compacts
past days of bronze, expires silver and gold snapshots after 7 days and never expires bronze
snapshots, because that breaks the streaming read of silver (apache/iceberg#18000)
([ADR-025](../DECISIONS.md#adr-025-iceberg-maintenance-policy)). The rules are enforced in code before
a Spark session starts ([streaming/spark_jobs/maintenance.py:67](../streaming/spark_jobs/maintenance.py)).

The first live run was on 2026-10-29 ([OPERATIONS.md, First live run](../OPERATIONS.md#first-live-run-2026-10-29);
[evidence](evidence.md#maintenance-before-and-after)). Bronze compaction rewrote 589 files (46 048 268
bytes) into 24, so the data files in partitions before today went from 595 in 27 partitions to 30,
with the row count (558 629) and `max(kafka_offset)` (77 659) equal. The real orphans run removed 21
metadata files (`metadata.json` objects 122 to 101), the same set the dry run had listed.
`silver.orders` went from 38 to 15 snapshots, with 51 data files and 111 position-delete files
deleted. The row count of every table was equal before and after, and `make reconcile` matched 7 of 7
tables after the silver expire.

The DAGs are no longer both paused. Since 2026-10-29 `iceberg_maintenance` is unpaused, and a
scheduled run only does `optimize`: expire and compaction run only with the conf
`{"expire_and_compact": true}`. `iceberg_orphans` is still paused
([OPERATIONS.md, Maintenance](../OPERATIONS.md#maintenance)).

**14. What does the Iceberg catalog do, and why a REST catalog?**

The catalog maps a table name to its current metadata file and makes the commit atomic. Every engine
that shares tables has to use the same catalog, otherwise their histories fork. A REST catalog gives
Spark and Trino one HTTP contract instead of a database schema each client must understand.

In this project: tables started on a JDBC catalog in Postgres and moved to Lakekeeper on 2026-10-08,
after a cutover that compared row counts and current snapshots of all nine tables through both
catalogs ([ADR-005, cutover](../DECISIONS.md#cutover-2026-10-08)). After the first commit through
Lakekeeper the pointer of `bronze.cdc_events` moved from `00121-...` to `00128-...`. Because the
catalog also owns deletion, any `DROP TABLE` from Spark, Trino or dbt deletes the table's files (soft
delete keeps them 7 days), so the nine
bronze and silver tables are protected and Lakekeeper answers 409 to a drop.

## Idempotency and exactly-once

**15. Is the pipeline exactly-once?**

No single component is. Debezium and Kafka are at-least-once, and Spark can re-run a batch after a
crash. The end state is still correct because the sinks that matter are idempotent: re-applying the
same change leaves the same result. A good answer names where the guarantee holds and where it does
not.

In this project: bronze is at-least-once by contract. Chaos scenario 1 found no repeated and no
missing Kafka offset after a Spark restart that kept the checkpoint. Both live kills landed before
the write stage, so the skip of an already committed epoch is shown by a unit test (question 16). A
Debezium re-send after a kill still lands in bronze
twice (253 events on 2026-10-07, question 2). Silver is where no-duplicates is enforced; dbt
incremental models merge on a unique key
([ARCHITECTURE.md, "Where exactly-once comes from"](../ARCHITECTURE.md#where-exactly-once-comes-from);
[ADR-007](../DECISIONS.md#adr-007-bronze-streaming-append-silver-batch-merge)). The evidence is the
chaos scenarios in [OPERATIONS.md, Failure scenarios](../OPERATIONS.md#failure-scenarios): they check
bronze offsets for repeats and gaps and silver against Postgres with `reconcile`.

**16. How does the Iceberg streaming sink skip an already committed batch?**

The sink stores the streaming query id and the epoch (batch) id in every snapshot summary. When Spark
re-runs a batch, the sink sees a snapshot of the same query with an equal or higher epoch and writes
nothing. A new checkpoint is a new query id, so the guarantee ends there.

In this project: a unit test deletes `commits/1` of a checkpoint, the state a kill in the commit
window leaves, and Spark re-runs batch 1 with no new rows and no new snapshot. With a new checkpoint
every file is appended again ([tests/unit/test_iceberg_sink.py:58](../tests/unit/test_iceberg_sink.py);
[ADR-007](../DECISIONS.md#adr-007-bronze-streaming-append-silver-batch-merge), Iceberg 1.11 `SparkWrite`).

**17. How does silver stay correct when events arrive twice or out of order?**

Silver keeps one row per primary key and applies a change only if it is newer than what the row
already holds. Within a batch the newest event per key wins; against the table, an LSN guard skips
anything not strictly newer. A replayed batch and a late event then both change nothing.

In this project: `latest_per_key` takes the highest LSN (null last) and `MERGE` updates a matched row
when the target LSN is null or lower ([streaming/spark_jobs/silver_upsert.py:132](../streaming/spark_jobs/silver_upsert.py);
[streaming/spark_jobs/silver_upsert.py:153](../streaming/spark_jobs/silver_upsert.py)). Tests: `test_replaying_a_batch_changes_nothing`
and `test_late_event_does_not_roll_a_row_back` ([tests/unit/test_silver_upsert.py:321](../tests/unit/test_silver_upsert.py),
[:334](../tests/unit/test_silver_upsert.py)).
Live, `make chaos-late` re-sent an old insert of an order whose row was already `approved` with
`_last_lsn` 1401679552 on 2026-10-07; the row and its LSN stayed and the second run's snapshot changed
no partition ([OPERATIONS.md, scenario 4](../OPERATIONS.md#4-late-events)). Deletes are soft (`_is_deleted`), and a
re-sent insert does not resurrect a deleted row.

**18. Where does the LSN guard break down?**

LSN is the start of a change's WAL record, not its commit position. With one writer per key it only
grows, so ordering by it is sound. With concurrent writers, a re-insert of a key that another
transaction just deleted can commit later with a lower LSN, and the guard would keep the row deleted.
Snapshot reads have no streamed LSN to compare with.

In this project: the replayer is a single writer (checked on 1 561 same-key pairs in Kafka, none
decreasing). Bronze already stores Debezium's `source.sequence`, which follows commit order, and
silver does not use it yet; switching is planned for when a second writer appears or a gap must be
repaired with a snapshot ([ADR-021](../DECISIONS.md#adr-021-silver-upsert-one-availablenow-job-idempotent-merge-per-table);
[ADR-022](../DECISIONS.md#adr-022-bronze-keeps-the-commit-position-sourcesequence)). A snapshot read can fill a missing key but never
overwrites a row that holds a streamed LSN ([ADR-019](../DECISIONS.md#adr-019-incremental-snapshots-through-a-signal-table)).

## Data quality

**19. Which checks run, and where?**

Layer them by what each can catch. Contracts at the boundary reject events that cannot be typed;
invariants such as key uniqueness run on the table; reconciliation against the source catches loss
and drift that no single layer sees; model tests guard the marts.

In this project: JSON Schema contracts per table feed silver and a quarantine table
([contracts/silver/orders.json](../contracts/silver/orders.json)). `dq_checks` runs every 15 minutes
and fails on a duplicate key in silver and on silver differing from Postgres at rest
([airflow/dags/dq_checks.py:1](../airflow/dags/dq_checks.py)). dbt tests run in `dbt_build` after every
silver merge ([airflow/dags/dbt_build.py:15](../airflow/dags/dbt_build.py)); CI only runs `dbt parse`,
because `build` needs Trino ([OPERATIONS.md, CI](../OPERATIONS.md#ci); [dbt/README.md](../dbt/README.md)).

**20. How do you reconcile the source with the lake, and why not just compare counts?**

A count can match while rows are wrong: a lost row can be offset by a row that should have been
deleted. Compare the count, a hash of the sorted key set and the sums of money columns, on both
sides, and only when nothing is in flight.

In this project: for each of the seven tables `make reconcile` compares live row count, `md5` of the
sorted primary keys, the sum of every decimal column at its contract scale and, since 2026-10-30,
the row fingerprint of every contract column, Postgres against `silver` where `not _is_deleted`.
The SQL is generated from the contracts
([scripts/reconcile_sql.py:1](../scripts/reconcile_sql.py); runner `reconcile` in
[scripts/chaos/lib.sh](../scripts/chaos/lib.sh)). With the fingerprint, `make verify-fast` on
2026-10-30 16:37 UTC printed `values ok` for all seven tables, then `verify ok`
([evidence, Reconciliation](evidence.md#reconciliation-source-against-silver)). `dq_checks` also
compares row fingerprints, source to silver and silver to gold; Postgres and Trino fingerprints were
equal on all seven tables on 2026-10-23
([ADR-020](../DECISIONS.md#adr-020-silver-contracts-and-timestamp-types)). "At rest" means bronze quiet
and silver caught up, otherwise the layers differ for a reason that is not an error
([airflow/dags/lakehouse/checks.py:19](../airflow/dags/lakehouse/checks.py)).

**21. What do you do with a corrupted or untypable event?**

Do not stop the stream and do not drop it silently. Keep the original, route it to a quarantine with
a reason, continue with the rest of the batch, and make the quarantine idempotent so a replay does not
duplicate it.

In this project: `make chaos-poison-event` produces a record that is not a Debezium envelope. Bronze
keeps it as raw text, the next `silver_upsert` run writes it to `silver.quarantine` with
`reason = unparsed_envelope`, and a second run adds nothing because the quarantine key is
`(topic, partition, offset)` ([OPERATIONS.md, scenario 7](../OPERATIONS.md#7-corrupted-event-in-topic)). Reasons are ordered
(`unknown_op`, `null_key`, `type_mismatch`, `null_required`, ...) and quarantined events are not
retried ([OPERATIONS.md, Silver upsert](../OPERATIONS.md#silver-upsert)). The count is only a line in the `dq_checks` log, not
a metric or alert, and detection today is manual: `select reason, count(*) from silver.quarantine
group by 1`.

**22. How do you test an incremental dbt model?**

An idempotent rerun proves little: it passes even when the watermark is wrong. Compare the
incrementally built table with a full recompute, and test the key and the failure path.

In this project: `mart_daily_sales` is incremental with `delete+insert` by purchase date and
reprocesses every date that has an order changed since the last run
([dbt/models/marts/mart_daily_sales.sql:5-7](../dbt/models/marts/mart_daily_sales.sql);
the date filter is at [dbt/models/marts/mart_daily_sales.sql:27](../dbt/models/marts/mart_daily_sales.sql)). The test
`assert_mart_daily_sales_matches_full_recompute` compares it with a recompute over all dates
([dbt/tests/assert_mart_daily_sales_matches_full_recompute.sql:1](../dbt/tests/assert_mart_daily_sales_matches_full_recompute.sql)).
Failure path: `make chaos-break-dbt-test` fails a test on `fct_orders`; dbt skips the children and the
marts keep their previous snapshot ([OPERATIONS.md, scenario 9](../OPERATIONS.md#9-airflow-task-failure-dbt-test)).

## Observability

**23. What is the difference between lag and freshness, and which one pages?**

Lag is how far a consumer is behind its input. Freshness is how old the newest data is. Freshness grows
whenever the source is quiet, so alerting on it pages for "no traffic". Lag measures work that is
waiting, so it is the better paging signal.

In this project: `lakehouse_silver_lag_seconds` is how long the oldest bronze snapshot silver has not
merged has waited, 0 at rest. `lakehouse_table_freshness_seconds` grows for hours between replay
bursts and does not alert ([OPERATIONS.md, Observability](../OPERATIONS.md#observability), series table). `FreshnessAbove15m`
fires on the lag; in the live test it fired 1561 s after bronze caught up with `silver_upsert` paused
(900 s plus up to 15 minutes until the next `dq_checks`, [OPERATIONS.md, Alerts](../OPERATIONS.md#alerts)). The
dbt source freshness check is separate: warn after 30 minutes, error after 2 hours, and with the
replay stopped it means "no traffic" ([dbt/README.md](../dbt/README.md)).

**24. Why can kafka-exporter not see Spark's lag, and what are gauge, counter and histogram?**

A Kafka exporter reads consumer groups, and Spark does not commit to one. A gauge is a value that
goes up and down (a queue length), a counter only increases and is read as a rate, a histogram counts
observations in buckets to give latency percentiles.

In this project: a `StreamingQueryListener` in the driver exports
`spark_streaming_kafka_lag{query,topic,partition}` as latest broker offset minus processed offset, 21
rows for bronze, 0 at rest, and `spark_streaming_input_rows_total` as a counter
([ADR-013](../DECISIONS.md#adr-013-spark-metrics); gauge at
[streaming/spark_jobs/metrics.py:28](../streaming/spark_jobs/metrics.py), counter at
[streaming/spark_jobs/metrics.py:23](../streaming/spark_jobs/metrics.py)).
`kafka-exporter` was rejected for the lag: it would need the processed offsets joined by labels in
PromQL, and its number keeps growing while Spark is down, which `SparkNoBatch5m` already catches.
The lag is above 0 only when a backlog exceeds one trigger (20 000 offsets); that path is covered by
unit tests, not yet by a live backlog.

**25. Why alert on "no batch for 5 minutes" and not on "container alive"?**

A container can be up while the query inside is stuck, for example waiting on object storage. An alert
on the result, a recent batch, catches a stuck or dead pipeline and ignores liveness noise. It also
has to handle the case where the metric disappears.

In this project: `SparkNoBatch5m` compares `time()` with the last-batch timestamp. Idle triggers
keep the timestamp moving, so only a stuck or dead query trips it, and a second rule uses `absent()`
for a dead driver; after `docker stop` of `spark-bronze` it fired at 315 s ([OPERATIONS.md, Alerts](../OPERATIONS.md#alerts), table).
The case it misses was found by a scenario: with Kafka stopped for 6 minutes on 2026-10-23, Spark
restarted 15 times and `SparkNoBatch5m` did not fire: the last-batch series was absent in one piece
(17:10:23 to 17:15:38 UTC) and Kafka was back before the 5 minutes of `for` of the `gone` rule were
over. `ContainerRestarting` fired instead ([OPERATIONS.md, scenario 8](../OPERATIONS.md#8-kafka-down-for-6-minutes)).
A week-6 rule, `SparkRestartLoop`, targets exactly that case; it is proven by promtool and by a
retro run over the stored 2026-10-23 data (true from 51 s after the first restart), not shown firing
live ([OPERATIONS.md, Alerts](../OPERATIONS.md#alerts), "Limits worth knowing" below the table).

**26. How do you know an alert works, and what are the blind spots?**

Test the rule on synthetic series, failure cases first, then cause the real failure and time how long
the alert takes. Record what the alert does not cover.

In this project: `make alerts-test` checks `alerts.yml` with promtool (`SUCCESS: 15 rules found` on
2026-10-30) and runs the rule tests in `alerts_test.yml` (`SUCCESS`,
[evidence](evidence.md#alerts-and-time-to-fire)). There are 12 alert names and 15
rules, because three names have two expressions each. Seven alerts were shown firing live, with
times. Six in their own scenarios on 2026-10-23: `ConnectorNotRunning` 95 s, `SlotWalRetainedHigh`
326 s, `SparkNoBatch5m` 315 s, `FreshnessAbove15m` 1561 s, `AirflowDagFailed` 17 s,
`ContainerRestarting` 15 s. The seventh, `CdcStalledSourceWrites`, fired on 2026-10-29 at 18:20:04 UTC
in chaos 6, 33 minutes after the connector was stopped at 17:47:02. `SparkRestartLoop` is not a live
firing: its expression was run over the stored data of chaos 8 and was true 51 s after the first
restart. `DqChecksStale`, `ScrapeTargetDown`, `SlotWalHeldIdle`, `SilverGoldNotCompared` and the
`absent` form of `FreshnessAbove15m` are proven by promtool only
([OPERATIONS.md, Alerts](../OPERATIONS.md#alerts), table). Known limits are written down: `absent()`
alerts burn when `core` is off, the `lakehouse_*` gauges arrive every 15 minutes so their alerts lag
by that much, and there is no Alertmanager, so alerts are read in the Prometheus UI
([OPERATIONS.md, Alerts](../OPERATIONS.md#alerts), "Limits worth knowing";
[ADR-023](../DECISIONS.md#adr-023-observability-metric-sources)).

## System design: OLTP to lakehouse with correct end state

**27. Walk me through the architecture in two minutes.**

Start from the guarantee, then the path. Source of truth is OLTP; CDC turns its log into events;
a raw layer keeps everything; a typed layer applies changes idempotently; a modelled layer serves
analytics; checks prove the end state.

In this project: a replayer writes Olist history into Postgres as real INSERT, UPDATE and DELETE
statements. Debezium reads the WAL into Kafka topics. A Spark stream appends raw envelopes to the
Iceberg table `bronze.cdc_events` every 20 s. `silver_upsert` merges them into seven typed tables every
5 minutes. dbt on Trino builds the marts in `gold` after every merge. `dq_checks` and `make reconcile`
compare the result with Postgres ([ARCHITECTURE.md](../ARCHITECTURE.md), data flow). Everything runs
on one 16 GB laptop in Compose profiles with memory limits
([OPERATIONS.md, Profiles](../OPERATIONS.md#profiles-and-what-runs-together)).

**28. How is the work orchestrated, and why is the stream not a DAG?**

A continuous query is a service: it restarts on failure and has no run to schedule. Batch steps with
dependencies belong in the scheduler, with concurrency limits where two writers would collide.

In this project: Airflow 3 with LocalExecutor orchestrates batch only. `silver_upsert` runs every 5
minutes with `max_active_runs=1`, and its first task skips the run if bronze has no new snapshot, so
no JVM starts for nothing. The merge task publishes the Asset `lake.silver`, which triggers
`dbt_build`. Pools serialise writers that would conflict: `lake_writers` for silver, `gold_writers` for
dbt and gold maintenance ([airflow/dags/silver_upsert.py:35](../airflow/dags/silver_upsert.py) for
`max_active_runs`, [airflow/dags/silver_upsert.py:66](../airflow/dags/silver_upsert.py) for the pool;
[airflow/dags/dbt_build.py:15](../airflow/dags/dbt_build.py) for the Asset trigger;
[ADR-011](../DECISIONS.md#adr-011-airflow-3-localexecutor-dbt-through-bashoperator-spark-through-dockeroperator);
[ADR-025](../DECISIONS.md#adr-025-iceberg-maintenance-policy)). The bronze stream is a Compose service.

Since the audit commit `e2ae619`, every task has an `execution_timeout` (the silver merge 10
minutes) and every DAG a `dagrun_timeout` (`silver_upsert` 30 minutes)
([airflow/dags/silver_upsert.py:35-40](../airflow/dags/silver_upsert.py)). The merge container has
the fixed name `lakehouse-silver-merge` ([airflow/dags/silver_upsert.py:56](../airflow/dags/silver_upsert.py)),
so a second Airflow merge fails at once with a 409 while it exists, and `make silver` refuses to run
too ([Makefile:104-112](../Makefile)). A timeout on a real merge has not been shown live
([OPERATIONS.md, Airflow](../OPERATIONS.md#airflow), "Timeouts").

**29. Why does bronze keep the payload as JSON text, and how do you handle a schema change in the source?**

A raw layer that parses content can fail on content. Keep the original, type it in one place, and make
the contract explicit so drift is visible rather than silently absorbed.

In this project: bronze has one fixed schema for all tables; `before` and `after` stay as JSON text, so
an `ALTER TABLE` in the source never stops ingestion ([ADR-008](../DECISIONS.md#adr-008-bronze-keeps-the-payload-as-json-text)).
Typing happens in silver from `contracts/silver/<table>.json`. A payload field the contract does not
declare is ignored and logged once per table and batch, and the row still merges; a table and its
contract that disagree on columns stop the job, so the fix is to add the column to the contract and
then `ALTER TABLE ... ADD COLUMN` ([OPERATIONS.md, Silver upsert](../OPERATIONS.md#silver-upsert);
[ADR-020](../DECISIONS.md#adr-020-silver-contracts-and-timestamp-types)). A unit test keeps every contract in step with the
migrations.

**30. What are the known limits of the design, and what would you change first?**

Name the limits that were measured or documented, not hypothetical ones, and say what each would cost
to fix.

In this project: silver latency is minutes by design ([ADR-007](../DECISIONS.md#adr-007-bronze-streaming-append-silver-batch-merge)).
Ordering by LSN is sound only for a single writer, and the fix, using `source.sequence`, is prepared
in bronze ([ADR-022](../DECISIONS.md#adr-022-bronze-keeps-the-commit-position-sourcesequence)). The `AvailableNow` read walks every retained
bronze snapshot on each run and cannot survive expiry of its first snapshot, which is why bronze is
never expired (apache/iceberg#16940 and #18000,
[ADR-021](../DECISIONS.md#adr-021-silver-upsert-one-availablenow-job-idempotent-merge-per-table)).
Kafka is a single broker and there is no Schema Registry, both on the list of what is deliberately
absent ([ARCHITECTURE.md, "What is deliberately absent"](../ARCHITECTURE.md#what-is-deliberately-absent)).
Lakekeeper and Trino have no authentication; their ports listen on 127.0.0.1, and Trino is also
reachable from every container on the `lake` network
([ADR-005, cutover](../DECISIONS.md#cutover-2026-10-08);
[OPERATIONS.md, Ports](../OPERATIONS.md#ports-all-on-127001);
[OPERATIONS.md, Access control](../OPERATIONS.md#access-control)). Trino access control only limits the
`grafana` user to `lake_ro.gold`, and the user name is only a label
([evidence, Trino access control](evidence.md#trino-access-control);
[ARCHITECTURE.md, data flow](../ARCHITECTURE.md#data-flow), item 9).
I would first change the guard to `source.sequence`, since it is the only limit that can produce a
wrong row rather than a slow one.
