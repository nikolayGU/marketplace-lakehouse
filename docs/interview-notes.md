# Interview notes

Thirty questions a data engineer interviewer can ask about this project, each with a short general
answer and a concrete example from the repository. Numbers carry the date of the live run they come
from, with the source in the link. A `TODO` marker flags a fact that is not in the repository yet.

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
against for repeated and missing offsets ([OPERATIONS.md](../OPERATIONS.md), failure scenario 1).
Silver still does not rely on arrival order: it orders changes of a key by LSN (question 17).

**2. Where does at-least-once come from, and what is an offset and a consumer group?**

An offset is the position of a record inside one partition. A consumer group splits partitions
between its members and commits the offsets it has processed. If a producer or consumer crashes after
doing the work but before recording the position, the work is done again: that is at-least-once.
Exactly-once needs an idempotent or transactional sink on top.

In this project: Debezium re-sends events after a hard stop of Connect, 253 events in the run of
2026-10-07 ([OPERATIONS.md:813](../OPERATIONS.md), scenario 2b). Spark does not use a consumer group
at all: it keeps offsets in its checkpoint, so `kafka-exporter` shows no lag for it and a
`StreamingQueryListener` exports the lag instead ([DECISIONS.md:392](../DECISIONS.md), ADR-013).
`make kafka-groups` lists Connect only ([OPERATIONS.md:86](../OPERATIONS.md)).

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
([DECISIONS.md:458](../DECISIONS.md), ADR-019). Its limit is documented: once silver holds a streamed
LSN for a key, a snapshot read cannot change that row.

**4. Why log-based CDC, and what do the replication slot and `REPLICA IDENTITY FULL` cost?**

Reading the write-ahead log captures every insert, update and delete, deletes included, without
query load on the source and without a timestamp column to poll. The replication slot makes Postgres
keep WAL until the consumer confirms it, which is what makes the stream durable and also what can
fill the disk when the consumer stops. `REPLICA IDENTITY FULL` puts the whole old row into the WAL,
so `before` in an update event carries every column.

In this project: the connector uses `pgoutput`, slot `shop_slot` and `snapshot.mode=initial`
([connect/shop-connector.json:12](../connect/shop-connector.json)). All seven tables have `REPLICA
IDENTITY FULL` so one UPDATE envelope shows what changed; the price is more WAL ([DECISIONS.md:437](../DECISIONS.md),
ADR-018). The slot risk was measured on 2026-10-23: with the connector stopped, `ConnectorNotRunning`
fired 95 s after the stop and `SlotWalRetainedHigh` 326 s after it, with about 80 MB held and
`max_slot_wal_keep_size = -1` ([OPERATIONS.md:1014](../OPERATIONS.md), scenario 6; alert table at
[OPERATIONS.md:511](../OPERATIONS.md)).

**5. What does a Kafka Connect restart do to the data, compared with a kill?**

Connect stores source offsets periodically. A graceful stop waits for producer acknowledgements and
commits the final offset, so on resume Debezium can drop whatever Postgres sends again. A kill skips
that commit, so everything since the last periodic flush is produced a second time with the same LSN.
Nothing is lost in either case; only repeats differ.

In this project: on 2026-10-07 `docker restart` of Connect produced 0 events repeated with the same
LSN (1429 CDC events in the minute before the restart, 1593 after), recovery took about 32 s
([OPERATIONS.md:782](../OPERATIONS.md), scenario 2a). `docker kill` about 9 s after an offset flush
repeated 253 events, and live row counts of all seven silver tables still matched Postgres
([OPERATIONS.md:813](../OPERATIONS.md), scenario 2b). The repeat count follows the time since the
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
[DECISIONS.md:262](../DECISIONS.md), ADR-007). Both checkpoints live under
`s3a://lakehouse/checkpoints/` ([OPERATIONS.md:98](../OPERATIONS.md)).

**7. Why is `MERGE` done in `foreachBatch` and not in the streaming sink, and what does that cost?**

The Iceberg streaming sink is append-oriented, and issuing `MERGE INTO` straight from a streaming
query is unreliable, so the upsert has to run as batch SQL inside `foreachBatch`. That function is
at-least-once: Spark can re-run a batch whose completion it did not record. The MERGE must therefore
be idempotent by construction.

In this project: bronze is an append-only streaming sink; silver reads it as a stream and runs one
`MERGE` per table per micro-batch ([DECISIONS.md:262](../DECISIONS.md), ADR-007;
[DECISIONS.md:523](../DECISIONS.md), ADR-021). The cost is latency in minutes, not seconds, which
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
21 topic partitions ([OPERATIONS.md:733](../OPERATIONS.md), scenario 1). Both live kills landed
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
[DECISIONS.md:638](../DECISIONS.md), ADR-024). Measured on 2026-10-23 after a 60 s burst: 164
windows equal to `count(*)` of `silver.orders` per minute, 0 differing, 0 rows dropped
([OPERATIONS.md:567](../OPERATIONS.md)). Spark drops a late row against the watermark of the previous
batch, which is why the demo needs three runs.

**10. What do you tune in a streaming job on a 16 GB laptop, and what cannot be changed after the first run?**

Rows per batch, shuffle partitions and executor memory decide whether a batch fits. The default 200
shuffle partitions is wasteful for a small job: it makes hundreds of small tasks and state files.
Some settings are stored in the checkpoint on the first run and win over later configuration.

In this project: silver uses 4 shuffle partitions, batches of about 200 000 rows and a 2 GB container
for the merge ([streaming/spark_jobs/settings.py:39](../streaming/spark_jobs/settings.py);
[airflow/dags/silver_upsert.py:51](../airflow/dags/silver_upsert.py)). Bronze caps a trigger at
20 000 offsets ([streaming/spark_jobs/settings.py:33](../streaming/spark_jobs/settings.py)). `silver_shuffle_partitions` is frozen in the silver checkpoint: Spark
logs `Updating the value of conf 'spark.sql.shuffle.partitions'` and restores the stored value, and a
new value needs a new checkpoint, which is on the blast-radius list because the next run re-reads all
of bronze ([OPERATIONS.md:143](../OPERATIONS.md)).

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
before and after, read from `"mart_daily_sales$snapshots"` ([OPERATIONS.md:1110](../OPERATIONS.md)).
Time travel deeper than 7 days on silver and gold is gone by design ([DECISIONS.md:684](../DECISIONS.md),
ADR-025).

**12. Copy-on-write or merge-on-read, and why is only `silver.orders` merge-on-read?**

Copy-on-write rewrites every data file that holds a changed row: cheap reads, expensive writes.
Merge-on-read writes small delete files and reads apply them: cheap writes, more expensive reads until
compaction folds the deletes. The choice follows how many rows change per batch.

In this project: replayed orders change status several times, while the other six tables rarely
change a row twice, so `silver.orders` is merge-on-read and partitioned by month, the rest are
copy-on-write. Measured on 2026-09-26 for one replay burst each: copy-on-write rewrote 4 of 4 data
files and wrote 5 735 311 bytes; merge-on-read rewrote 0 files and wrote 77 891 bytes. The cost moves
to reads and to compaction, and `optimize` can conflict with a merge-on-read MERGE, so
`iceberg_maintenance` must not overlap `silver_upsert` ([DECISIONS.md:318](../DECISIONS.md), ADR-010;
layout in [streaming/spark_jobs/silver_upsert.py:34](../streaming/spark_jobs/silver_upsert.py)).

**13. Why is hidden partitioning better than Hive directories, and how do you keep small files under control?**

With hidden partitioning the table stores a transform of a column, such as `days(ts)`, so queries
filter on the column and the engine prunes partitions; nobody has to know a directory layout. The
partition spec can evolve without rewriting old data. Frequent small commits create small files and
many snapshots, which compaction and snapshot expiry then clean up.

In this project: bronze is partitioned by `(source_table, days(ingest_ts))` and `silver.orders` by
`months(order_purchase_timestamp)` ([DECISIONS.md:303](../DECISIONS.md), ADR-008;
[DECISIONS.md:318](../DECISIONS.md), ADR-010); an older unpartitioned table converges with
`ADD PARTITION FIELD`, metadata only. Bronze commits every 20 s, so the maintenance policy compacts
past days of bronze, expires silver and gold snapshots after 7 days and never expires bronze
snapshots, because that breaks the streaming read of silver (apache/iceberg#18000)
([DECISIONS.md:684](../DECISIONS.md), ADR-025). The rules are enforced in code before a Spark session
starts ([streaming/spark_jobs/maintenance.py:67](../streaming/spark_jobs/maintenance.py)), and the
DAGs are created paused ([OPERATIONS.md:602](../OPERATIONS.md)).
TODO(verify: files and snapshots before and after the first live expire and orphan runs, W5-T05b,
in OPERATIONS.md "Maintenance" and ADR-025).

**14. What does the Iceberg catalog do, and why a REST catalog?**

The catalog maps a table name to its current metadata file and makes the commit atomic. Every engine
that shares tables has to use the same catalog, otherwise their histories fork. A REST catalog gives
Spark and Trino one HTTP contract instead of a database schema each client must understand.

In this project: tables started on a JDBC catalog in Postgres and moved to Lakekeeper on 2026-10-08,
after a cutover that compared row counts and current snapshots of all nine tables through both
catalogs ([DECISIONS.md:69](../DECISIONS.md), ADR-005, cutover section). After the first commit through
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

In this project: bronze is exactly once across Spark restarts that keep the checkpoint, and
at-least-once across Debezium re-sends and checkpoint loss, by contract. Silver is where
no-duplicates is enforced; dbt incremental models merge on a unique key
([ARCHITECTURE.md](../ARCHITECTURE.md), "Where exactly-once comes from";
[DECISIONS.md:262](../DECISIONS.md), ADR-007). The evidence is the chaos scenarios in
[OPERATIONS.md:692](../OPERATIONS.md): they check bronze offsets for repeats and gaps and silver
against Postgres with `reconcile`.

**16. How does the Iceberg streaming sink skip an already committed batch?**

The sink stores the streaming query id and the epoch (batch) id in every snapshot summary. When Spark
re-runs a batch, the sink sees a snapshot of the same query with an equal or higher epoch and writes
nothing. A new checkpoint is a new query id, so the guarantee ends there.

In this project: a unit test deletes `commits/1` of a checkpoint, the state a kill in the commit
window leaves, and Spark re-runs batch 1 with no new rows and no new snapshot. With a new checkpoint
every file is appended again ([tests/unit/test_iceberg_sink.py:58](../tests/unit/test_iceberg_sink.py);
[DECISIONS.md:262](../DECISIONS.md), ADR-007, Iceberg 1.11 `SparkWrite`).

**17. How does silver stay correct when events arrive twice or out of order?**

Silver keeps one row per primary key and applies a change only if it is newer than what the row
already holds. Within a batch the newest event per key wins; against the table, an LSN guard skips
anything not strictly newer. A replayed batch and a late event then both change nothing.

In this project: `latest_per_key` takes the highest LSN (null last) and `MERGE` updates a matched row
when the target LSN is null or lower ([streaming/spark_jobs/silver_upsert.py:132](../streaming/spark_jobs/silver_upsert.py);
[streaming/spark_jobs/silver_upsert.py:153](../streaming/spark_jobs/silver_upsert.py)). Tests: `test_replaying_a_batch_changes_nothing`
and `test_late_event_does_not_roll_a_row_back` ([tests/unit/test_silver_upsert.py:321](../tests/unit/test_silver_upsert.py)).
Live, `make chaos-late` re-sent an old insert of an order whose row was already `approved` with
`_last_lsn` 1401679552 on 2026-10-07; the row and its LSN stayed and the second run's snapshot changed
no partition ([OPERATIONS.md:915](../OPERATIONS.md), scenario 4). Deletes are soft (`_is_deleted`), and a
re-sent insert does not resurrect a deleted row.

**18. Where does the LSN guard break down?**

LSN is the start of a change's WAL record, not its commit position. With one writer per key it only
grows, so ordering by it is sound. With concurrent writers, a re-insert of a key that another
transaction just deleted can commit later with a lower LSN, and the guard would keep the row deleted.
Snapshot reads have no streamed LSN to compare with.

In this project: the replayer is a single writer (checked on 1 561 same-key pairs in Kafka, none
decreasing). Bronze already stores Debezium's `source.sequence`, which follows commit order, and
silver does not use it yet; switching is planned for when a second writer appears or a gap must be
repaired with a snapshot ([DECISIONS.md:523](../DECISIONS.md), ADR-021;
[DECISIONS.md:558](../DECISIONS.md), ADR-022). A snapshot read can fill a missing key but never
overwrites a row that holds a streamed LSN ([DECISIONS.md:458](../DECISIONS.md), ADR-019).

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
because `build` needs Trino ([OPERATIONS.md:635](../OPERATIONS.md)).

**20. How do you reconcile the source with the lake, and why not just compare counts?**

A count can match while rows are wrong: a lost row can be offset by a row that should have been
deleted. Compare the count, a hash of the sorted key set and the sums of money columns, on both
sides, and only when nothing is in flight.

In this project: for each of the seven tables `make reconcile` compares live row count, `md5` of the
sorted primary keys and the sum of every decimal column at its contract scale, Postgres against
`silver` where `not _is_deleted`. The SQL is generated from the contracts
([scripts/reconcile_sql.py:1](../scripts/reconcile_sql.py); runner `reconcile` in
[scripts/chaos/lib.sh:158](../scripts/chaos/lib.sh)). `make verify-fast` reported `verify ok` with
7 of 7 tables on 2026-10-29 ([HANDOFF](HANDOFF.md), section «Состояние на 29.10.2026, харнесс
v0.3», row «Стек», ru). `dq_checks` also compares row
fingerprints, source to silver and silver to gold; Postgres and Trino fingerprints were equal on all
seven tables on 2026-10-23 ([DECISIONS.md:496](../DECISIONS.md), ADR-020). "At rest" means bronze quiet
and silver caught up, otherwise the layers differ for a reason that is not an error
([airflow/dags/lakehouse/checks.py:18](../airflow/dags/lakehouse/checks.py)).

**21. What do you do with a corrupted or untypable event?**

Do not stop the stream and do not drop it silently. Keep the original, route it to a quarantine with
a reason, continue with the rest of the batch, and make the quarantine idempotent so a replay does not
duplicate it.

In this project: `make chaos-poison-event` produces a record that is not a Debezium envelope. Bronze
keeps it as raw text, the next `silver_upsert` run writes it to `silver.quarantine` with
`reason = unparsed_envelope`, and a second run adds nothing because the quarantine key is
`(topic, partition, offset)` ([OPERATIONS.md:1056](../OPERATIONS.md), scenario 7). Reasons are ordered
(`unknown_op`, `null_key`, `type_mismatch`, `null_required`, ...) and quarantined events are not
retried ([OPERATIONS.md:143](../OPERATIONS.md)). The count is only a line in the `dq_checks` log, not
a metric or alert, and detection today is manual: `select reason, count(*) from silver.quarantine
group by 1`.

**22. How do you test an incremental dbt model?**

An idempotent rerun proves little: it passes even when the watermark is wrong. Compare the
incrementally built table with a full recompute, and test the key and the failure path.

In this project: `mart_daily_sales` is incremental with `delete+insert` by purchase date and
reprocesses every date that has an order changed since the last run
([dbt/models/marts/mart_daily_sales.sql:1](../dbt/models/marts/mart_daily_sales.sql)). The test
`assert_mart_daily_sales_matches_full_recompute` compares it with a recompute over all dates
([dbt/tests/assert_mart_daily_sales_matches_full_recompute.sql:1](../dbt/tests/assert_mart_daily_sales_matches_full_recompute.sql)).
Failure path: `make chaos-break-dbt-test` fails a test on `fct_orders`; dbt skips the children and the
marts keep their previous snapshot ([OPERATIONS.md:1110](../OPERATIONS.md), scenario 9).

## Observability

**23. What is the difference between lag and freshness, and which one pages?**

Lag is how far a consumer is behind its input. Freshness is how old the newest data is. Freshness grows
whenever the source is quiet, so alerting on it pages for "no traffic". Lag measures work that is
waiting, so it is the better paging signal.

In this project: `lakehouse_silver_lag_seconds` is how long the oldest bronze snapshot silver has not
merged has waited, 0 at rest. `lakehouse_table_freshness_seconds` grows for hours between replay
bursts and does not alert ([OPERATIONS.md:433](../OPERATIONS.md), series table). `FreshnessAbove15m`
fires on the lag; in the live test it fired 1561 s after bronze caught up with `silver_upsert` paused
(900 s plus up to 15 minutes until the next `dq_checks`, [OPERATIONS.md:511](../OPERATIONS.md)). The
dbt source freshness check is separate: warn after 30 minutes, error after 2 hours, and with the
replay stopped it means "no traffic" ([dbt/README.md](../dbt/README.md)).

**24. Why can kafka-exporter not see Spark's lag, and what are gauge, counter and histogram?**

A Kafka exporter reads consumer groups, and Spark does not commit to one. A gauge is a value that
goes up and down (a queue length), a counter only increases and is read as a rate, a histogram counts
observations in buckets to give latency percentiles.

In this project: a `StreamingQueryListener` in the driver exports
`spark_streaming_kafka_lag{query,topic,partition}` as latest broker offset minus processed offset, 21
rows for bronze, 0 at rest, and `spark_streaming_input_rows_total` as a counter
([DECISIONS.md:392](../DECISIONS.md), ADR-013; [streaming/spark_jobs/metrics.py:18](../streaming/spark_jobs/metrics.py)).
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
for a dead driver; after `docker stop` of `spark-bronze` it fired at 315 s ([OPERATIONS.md:511](../OPERATIONS.md)).
The case it misses was found by a scenario: with Kafka stopped for 6 minutes on 2026-10-23, Spark
restarted 15 times and `SparkNoBatch5m` did not fire: the last-batch series was absent in one piece
(17:10:23 to 17:15:38 UTC) and Kafka was back before the 5 minutes of `for` of the `gone` rule were
over. `ContainerRestarting` fired instead ([OPERATIONS.md:1080](../OPERATIONS.md), scenario 8).
A week-6 rule, `SparkRestartLoop`, targets exactly that case; it is proven by promtool and by a
retro run over the stored 2026-10-23 data (true from 51 s after the first restart), not shown firing live ([OPERATIONS.md:511](../OPERATIONS.md), limits below the alert table).

**26. How do you know an alert works, and what are the blind spots?**

Test the rule on synthetic series, failure cases first, then cause the real failure and time how long
the alert takes. Record what the alert does not cover.

In this project: `make alerts-test` runs promtool against `alerts_test.yml`. Six alerts were shown
firing in their own scenarios on 2026-10-23, with times: `ConnectorNotRunning` 95 s,
`SlotWalRetainedHigh` 326 s, `SparkNoBatch5m` 315 s, `FreshnessAbove15m` 1561 s,
`AirflowDagFailed` 17 s, `ContainerRestarting` 15 s. The three alerts on a silent source
(`DqChecksStale`, `ScrapeTargetDown` and the `absent` form of `FreshnessAbove15m`) and the two
week-6 rules (`SlotWalHeldIdle`, `SparkRestartLoop`) are proven by promtool only (`SparkRestartLoop`
also replayed over the stored chaos 8 data of 23.10, not live)
([OPERATIONS.md:511](../OPERATIONS.md)). Known limits are written down: `absent()` alerts burn when
`core` is off, the `lakehouse_*` gauges arrive every 15 minutes so their alerts lag by that much, and
there is no Alertmanager, so alerts are read in the Prometheus UI ([DECISIONS.md:578](../DECISIONS.md),
ADR-023).

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
on one 16 GB laptop in Compose profiles with memory limits ([OPERATIONS.md:3](../OPERATIONS.md)).

**28. How is the work orchestrated, and why is the stream not a DAG?**

A continuous query is a service: it restarts on failure and has no run to schedule. Batch steps with
dependencies belong in the scheduler, with concurrency limits where two writers would collide.

In this project: Airflow 3 with LocalExecutor orchestrates batch only. `silver_upsert` runs every 5
minutes with `max_active_runs=1`, and its first task skips the run if bronze has no new snapshot, so
no JVM starts for nothing. The merge task publishes the Asset `lake.silver`, which triggers
`dbt_build`. Pools serialise writers that would conflict: `lake_writers` for silver, `gold_writers` for
dbt and gold maintenance ([airflow/dags/silver_upsert.py:27](../airflow/dags/silver_upsert.py);
[airflow/dags/dbt_build.py:15](../airflow/dags/dbt_build.py); [DECISIONS.md:354](../DECISIONS.md),
ADR-011; [DECISIONS.md:684](../DECISIONS.md), ADR-025). The bronze stream is a Compose service.

**29. Why does bronze keep the payload as JSON text, and how do you handle a schema change in the source?**

A raw layer that parses content can fail on content. Keep the original, type it in one place, and make
the contract explicit so drift is visible rather than silently absorbed.

In this project: bronze has one fixed schema for all tables; `before` and `after` stay as JSON text, so
an `ALTER TABLE` in the source never stops ingestion ([DECISIONS.md:303](../DECISIONS.md), ADR-008).
Typing happens in silver from `contracts/silver/<table>.json`. A payload field the contract does not
declare is ignored and logged once per table and batch, and the row still merges; a table and its
contract that disagree on columns stop the job, so the fix is to add the column to the contract and
then `ALTER TABLE ... ADD COLUMN` ([OPERATIONS.md:143](../OPERATIONS.md);
[DECISIONS.md:496](../DECISIONS.md), ADR-020). A unit test keeps every contract in step with the
migrations.

**30. What are the known limits of the design, and what would you change first?**

Name the limits that were measured or documented, not hypothetical ones, and say what each would cost
to fix.

In this project: silver latency is minutes by design ([DECISIONS.md:262](../DECISIONS.md), ADR-007).
Ordering by LSN is sound only for a single writer, and the fix, using `source.sequence`, is prepared
in bronze ([DECISIONS.md:558](../DECISIONS.md), ADR-022). The `AvailableNow` read walks every retained
bronze snapshot on each run and cannot survive expiry of its first snapshot, which is why bronze is
never expired (apache/iceberg#16940 and #18000, [DECISIONS.md:523](../DECISIONS.md)). Kafka is a single
broker, Schema Registry is absent, and Lakekeeper runs without authentication on 127.0.0.1
([ARCHITECTURE.md](../ARCHITECTURE.md), "What is deliberately absent"; [DECISIONS.md:192](../DECISIONS.md)).
I would first change the guard to `source.sequence`, since it is the only limit that can produce a
wrong row rather than a slow one.
