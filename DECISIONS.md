# Decisions

Short ADRs. One entry per decision that someone might question. Status: proposed / accepted /
superseded. Measurements behind the decisions:
[docs/evidence.md](docs/evidence.md#decision-measurements).

| ID | Decision | Status |
|---|---|---|
| ADR-001 | Real data via Olist replay, not synthetic generators | accepted |
| ADR-002 | Two PostgreSQL instances: `postgres-oltp` (CDC source) and `postgres-meta`, which holds the metadata of Lakekeeper, Airflow and Superset | accepted |
| ADR-003 | Kafka 4 KRaft, single broker, RF=1, 3 partitions per topic, retention 24h | accepted |
| ADR-004 | Object storage: MinIO, a pinned community release (2025-09-07), first pulled from quay.io | accepted; the image source is superseded by ADR-026 |
| ADR-005 | Iceberg catalog: JDBC first, then Lakekeeper (REST) | accepted; cutover 2026-10-08, JDBC layer removed 2026-11-20 |
| ADR-006 | Spark 3.5 + Iceberg 1.11 runtime in `local[2]`, no standalone cluster | accepted |
| ADR-007 | Bronze append-only stream (at-least-once); silver AvailableNow + MERGE is the no-duplicates guarantee | accepted |
| ADR-008 | Bronze keeps the payload as JSON text; typed in silver from contracts | accepted |
| ADR-009 | Soft deletes in silver (`_is_deleted`; Iceberg reserves `_deleted`), filtered in dbt | accepted |
| ADR-010 | `silver.orders` merge-on-read, partitioned by month; other silver tables copy-on-write | accepted |
| ADR-011 | Airflow 3 LocalExecutor, batch only, dbt through BashOperator, Spark through DockerOperator | accepted |
| ADR-012 | No Schema Registry: JSON envelopes and JSON Schema contracts | accepted |
| ADR-013 | Spark metrics from a `StreamingQueryListener`; kafka-exporter cannot see Spark offsets | accepted |
| ADR-014 | Superset optional; marts shown through Grafana | superseded by ADR-027 |
| ADR-015 | Removed: ClickHouse, k8s, Terraform, Ansible, Loki, Alertmanager delivery, Cosmos; no data quality framework: dbt tests plus `dq_checks` | accepted |
| ADR-016 | Compose profiles as the RAM strategy; `make start` brings up `core` without the replayer | accepted |
| ADR-017 | Stateful windowed job `orders_per_minute` is mandatory | superseded by ADR-024 |
| ADR-018 | `REPLICA IDENTITY FULL` on all `shop` tables | accepted |
| ADR-019 | Incremental snapshots through the signal table `cdc.debezium_signal` | accepted |
| ADR-020 | Silver contracts as JSON Schema; naive timestamps as `timestamp_ntz` (ms) | accepted |
| ADR-021 | Silver upsert: one AvailableNow job, idempotent MERGE guarded by `_last_lsn` | accepted |
| ADR-022 | Bronze keeps `source.sequence`; silver orders by `lsn` until a second writer | accepted |
| ADR-023 | Metric sources: own container-exporter, custom WAL query, JMX agent, StatsD; no Alertmanager | accepted |
| ADR-024 | `orders_per_minute`: Kafka input, own service, distinct count, MERGE that never lowers | accepted |
| ADR-025 | Maintenance: 7 days of snapshots in silver and gold, bronze never expired, orphans weekly | accepted |
| ADR-026 | MinIO and `mc` built from the source of the pinned release tags | accepted |
| ADR-027 | Superset as the BI layer, with an MCP endpoint | accepted |
| ADR-028 | Read-only BI access: catalog `lake_ro` and Trino file-based access control | accepted |
| ADR-029 | Local security model: loopback ports, no authentication, shared keys | accepted |
| ADR-030 | Gold: dbt on Trino, tables per run, one incremental mart | accepted |

## ADR-001 Real data via Olist replay

Context: synthetic generators produce uniform distributions and meaningless dashboards; no
own e-commerce data is available. Decision: load the public Olist dataset (~100k orders,
2016-2018) into PostgreSQL, shift dates to end today, bulk-load 80%, replay 20% on a virtual
clock as real transactions with injectable late, duplicate and schema-change events.
Consequences: realistic seasonality and categories; a replayer service to maintain.

`REPLAY_DATA` (`.env`, `raw` or `sample`, default `raw`) picks the directory under `DATA_DIR` that
`make replay-load` reads: the full download in `data/raw` or the committed 2 000-order slice in
`data/sample`, for a fresh clone and CI smoke. Both come from `Settings`, so `.env` applies without
exporting it into the shell.

## ADR-003 Kafka: KRaft, one broker

Decision: Kafka 4 in KRaft mode, one broker, RF 1, 3 partitions per topic. Retention is 24 h or
2 GiB per partition, whichever comes first (`KAFKA_LOG_RETENTION_BYTES` in compose); Connect's
internal topics have RF 1. Consequences: no broker failover; a consumer down longer than retention
needs an incremental snapshot (ADR-019).

## ADR-004 Object storage

Context: MinIO stopped publishing community images; Docker Hub lost `minio/minio`, while quay.io
still served the release below ([checked](docs/evidence.md#adr-004-image-source-check)).
Decision: keep MinIO on the plain release `RELEASE.2025-09-07T16-13-09Z`, not a hotfix tag, and
administer it with `mc`; the web console on :9001 is used to browse the bucket (OPERATIONS.md,
"MinIO console"). RustFS and Garage stay the documented fallback (both checked, their images pull):
the skill shown is S3-compatible storage, not a vendor. Consequences: the release is frozen, its
known fixes and the risk are in ADR-026, which also replaces the image source. `minio-init`
creates bucket `lakehouse` with `warehouse` and `checkpoints` prefixes.

## ADR-005 Catalog: JDBC first, REST as should-have

Context: Spark and Trino must share one Iceberg catalog. A REST catalog (Lakekeeper) is the 2026
standard and the better interview signal, but one more service with its own bootstrap, and week 1
had to end with a working vertical slice. Decision: start with the JDBC catalog in `postgres-meta`
(Spark `JdbcCatalog`, Trino `iceberg.catalog.type=jdbc`); add Lakekeeper in week 2 with a 3-hour
cap, migrate tables with `register_table`, run it side by side, then cut over. Side by side
(2026-10-08, [evidence](docs/evidence.md#adr-005-catalog-side-by-side-and-cutover)) fixed six
points: (a) new tables get `s3://` paths in the `full-hierarchy` layout with a `{uuid}`, the 9
registered tables stay on `s3a://`, Spark maps `fs.s3.impl` to S3A over HadoopFileIO; (b) soft
delete for 7 days, `push-s3-delete-disabled: false`, protection of every bronze and silver table,
since soft delete does not cover `DROP ... PURGE`; (c) the encryption key, in ADR-029; (d) on
Lakekeeper a drop, `unregister_table` or REST `DELETE` without `purgeRequested=false` deletes files
(OPERATIONS, "What deletes files"); (e) full cutover, side by side is a check, not an end state;
(f) `quay.io/lakekeeper/catalog:v0.13.6` by digest: an image cannot be rolled back after it
migrated the schema. Consequences: zero new services in week 1; the move shows what a catalog
stores.

### Cutover, 2026-10-08

Spark and Trino read and write through Lakekeeper, which runs in `core`; nothing uses the JDBC
catalog. Clients keep their own S3 keys (vended credentials need S3FileIO, a task of its own).

Rollback: free until bronze's first commit through Lakekeeper; since the first maintenance run of
2026-10-29 deleted files the old JDBC snapshots read, only from the copy of `warehouse/` taken
before it ([OPERATIONS.md](OPERATIONS.md#lakekeeper-rest-catalog)). Removed, 2026-11-20: the JDBC
catalog path of the code, its settings and `scripts/lakekeeper/register.sh`. The rows in
`iceberg_catalog` stay as data; a new `postgres-meta` volume no longer creates it.

## ADR-006 Spark 3.5 and Iceberg 1.11 in local mode

Decision: `apache/spark:3.5.9` with `iceberg-spark-runtime-3.5_2.12` 1.11.0 and
`SPARK_MASTER=local[2]`, no standalone cluster. Job code is baked into `lakehouse/spark:dev`, one
local image for bronze, silver, the stateful job, the Lakekeeper bootstrap and maintenance.
Consequences: one JVM per job within its memory limit; a code change needs an image rebuild;
Spark 4 would be a migration of its own.

## ADR-007 Bronze streaming append, silver batch MERGE

Context: Iceberg's Spark streaming sink is append-oriented; MERGE INTO driven directly from a
streaming query is unreliable (Iceberg issues #9730, #10805, #13431). Decision: bronze is an
append-only streaming sink with a 20 s trigger; silver is a separate job with
`Trigger.AvailableNow` scheduled by Airflow every 5 minutes, using `foreachBatch` to run
`MERGE INTO`. Consequences: one continuous JVM plus one short-lived JVM; silver latency is
minutes, not seconds, which is acceptable for analytics; both Spark trigger modes are shown.

On duplicates: bronze is contractually at-least-once. Debezium re-sends events after a hard stop
of Connect (or a restart whose final offset commit does not finish), and those land in bronze as
new Kafka records. Across Spark restarts that keep the checkpoint the Iceberg sink skips an
already committed epoch (it records `spark.sql.streaming.queryId` and `epochId` in the snapshot
summary); the test and the chaos runs:
[evidence](docs/evidence.md#adr-007-duplicates-across-restarts).
The no-duplicates guarantee lives in silver (`MERGE` keyed by primary key with an LSN guard), and
repeats are counted, not assumed away: `dq_checks` sends `lakehouse_dq_lsn_repeats_last_hour`.

## ADR-008 Bronze keeps the payload as JSON text

Context: seven source tables change shape independently, and a schema change must not stop
ingestion. Decision: `lake.bronze.cdc_events` has one fixed schema for all tables. It parses only
what routing and dedup need: `op`, `lsn`, `ts_ms` (Debezium processing time), `source_ts_ms`
(source commit time), plus Kafka coordinates `topic`, `kafka_partition`, `kafka_offset`,
`kafka_ts` and the key. `before` and `after` stay as JSON text. `source_table` comes from the
topic name, not the payload, so an event that does not parse still lands in its table's
partition. `raw` holds the original value only when the envelope did not yield an `op`; silver
sends those rows to quarantine. Partitioned by `(source_table, days(ingest_ts))`, format v2.

Consequences: bronze never fails on content, `ALTER TABLE` in the source is invisible here, and
typing lives in one place (silver, from `contracts/`). The cost is a JSON parse per row in
silver and no column pruning inside `after`.

## ADR-010 Silver layout: `orders` merge-on-read, the rest copy-on-write

Context: every replayed order changes status several times after it is inserted, while the other
tables rarely change a row twice. Copy-on-write MERGE rewrites every data file that holds a
matched row, and the updated orders are spread over all of them.

Decision: `silver.orders` gets `write.merge.mode`, `write.update.mode`, `write.delete.mode` =
`merge-on-read` and `write.delete.granularity` = `file` (Spark's default, spelled out because the
Iceberg docs list `partition`), and is partitioned by `months(order_purchase_timestamp)`. The
other tables stay copy-on-write and unpartitioned. `ensure_table` creates new tables that way and
converges an existing one on the next run with `ALTER TABLE ... SET TBLPROPERTIES` and `ADD
PARTITION FIELD`, which are metadata only; the schema, by contrast, never converges by itself.

Consequences ([measured](docs/evidence.md#adr-010-merge-on-read-against-copy-on-write)): write
amplification drops from about 4.9 KB to about 55 bytes per event. Reads pay: every scan applies
the position deletes, and each MERGE adds small files per touched month. Trino `optimize` folds
them in a `replace` snapshot, which no stream reads, but it conflicts with a merge-on-read MERGE
committing at the same time: the losing commit fails and silver replays the batch on its next
run, so `iceberg_maintenance` must not overlap `silver_upsert`. The partition does not prune the
MERGE itself, whose `on` clause has only the primary key.

## ADR-011 Airflow 3: LocalExecutor, dbt through BashOperator, Spark through DockerOperator

Context: Airflow orchestrates batch only (silver merge, dbt, data quality, maintenance); the bronze
stream is not a DAG. On a 16 GB laptop there is no room for Celery, a triggerer or Cosmos
(ADR-015).

Decision (2026-10-09):

- LocalExecutor; api-server, scheduler and dag-processor run one image, `lakehouse/airflow:dev`
  (`apache/airflow:3.3.2-python3.12`, the Python of the host). Tasks are processes in the
  scheduler container; `[core] parallelism` is 2 within its 900 MB
  ([memory](docs/evidence.md#adr-011-scheduler-memory)).
- dbt through BashOperator: `dbt build` from a venv of its own in the image (`/opt/dbt-venv`,
  versions from `uv.lock`), because dbt next to Airflow fights it over shared dependencies. The
  project is mounted read-only, so target and log paths go to `/tmp`.
- Spark silver through DockerOperator: the scheduler starts `lakehouse/spark:dev` on the network
  `<COMPOSE_PROJECT_NAME>_lake` with the environment compose gives `spark-silver`, through the
  Docker socket (ADR-029). Of the Airflow services only the scheduler joins the socket's group
  (`group_add`, `DOCKER_GID` in `.env`). The alternative, BashOperator with `docker compose run`,
  needs the compose CLI and the repo with its `.env` inside the image.
- No login: SimpleAuthManager with `simple_auth_manager_all_admins` (ADR-029). `.env` holds
  `AIRFLOW_API_SECRET_KEY` (the api-server signs task-log requests to the scheduler with it;
  without a shared value the UI shows no task log) and `DOCKER_GID`.
- Cadence: `silver_upsert` every 5 minutes, and its first task skips the run when bronze has no
  snapshot that silver has not merged, so no JVM starts for nothing and no Asset event wakes dbt;
  `dbt_build` on the Asset `lake.silver`; `dq_checks` every 15 minutes on time. Airflow 3.3 queues
  no Asset event for a paused DAG; `GoldStaleAtRest` covers that.

Consequences: an image of 3.47 GB to build, the socket as the price of DockerOperator,
the dbt version pinned twice (`uv.lock` and `airflow/Dockerfile`).

## ADR-012 No Schema Registry

Decision: JSON envelopes without a registry (`JsonConverter`, `schemas.enable=false`); contracts
live in `contracts/` as JSON Schema. JSON keeps a record readable in any tool (`kafka-ui`, Python,
the bronze text in Trino). Alternatives: Avro or Protobuf with a registry (Apicurio, Karapace):
typed evolution, one more service. Consequences: a type change shows in silver (contracts,
quarantine), not at the producer (ADR-008, ADR-021).

## ADR-013 Spark metrics

Context: Spark stores Kafka offsets in its checkpoint and does not commit to a consumer group,
so `kafka-exporter` reports no lag for it. Decision: a `StreamingQueryListener` in the driver
exposes `spark_streaming_input_rows_total`, `spark_streaming_batch_duration_seconds` and
`spark_streaming_kafka_lag` (latest broker offset minus processed offset, per topic and
partition) via `prometheus_client` on the driver's HTTP port; for stateful queries also the rows
in state, the watermark and a counter of rows the watermark dropped (ADR-024). kafka-exporter was
rejected for the lag: it needs the processed offsets joined by labels in PromQL and keeps growing
while Spark is down, which `SparkNoBatch5m` already catches. Consequences: ~60 lines of Python, a
real "how do you monitor a Spark stream" answer
([details](docs/evidence.md#adr-013-kafka-lag-of-the-spark-stream)).

## ADR-016 Compose profiles; the replayer container only on request

Context: on a 16 GB laptop the services run in profiles (`core`, `query`, `orchestrate`, `obs`,
`bi`, `tools`, `stateful`, `jobs`), never all at once (OPERATIONS.md, "Profiles"). `oltp-replayer`
is in `core`, so `make up PROFILE=core` also started the replayer container, which plays at
`REPLAY_SPEED` (2880, one virtual day per 30 s). The rest of the history is a budget: on
2026-10-09 about 72 virtual days, 36 minutes at that speed.

Decision (2026-10-09): compose stays as it is. `make start` brings up `core` without
`oltp-replayer`, plus `trino`, by naming `spark-bronze kafka-connect trino`; their `depends_on`
pull in the rest of `core`. `make up` refuses any `PROFILE` that contains `core`. Traffic comes
from `make replay-burst SECONDS=<n>`, which plays `n` real seconds on the host and stops; the
container starts only through `make replay-live`.

Alternatives: a profile `replay` for `oltp-replayer`; keeping `make up PROFILE=core` with a
warning (the failure stays one command away). Consequences: `make up PROFILE=core` now fails
with a hint instead of spending the replay; a fresh clone starts with `make bootstrap`.

## ADR-018 REPLICA IDENTITY FULL on the source tables

Context: Debezium fills `before` from what Postgres wrote into the WAL for the old row, which the
table's replica identity governs. Per the Debezium PostgreSQL documentation, with `REPLICA
IDENTITY DEFAULT` "UPDATE and DELETE events contain the previous values for the primary key
columns of a table", with `FULL` they "contain the previous values of all columns in the table".

Decision: `REPLICA IDENTITY FULL` on all seven `shop` tables in `001_schema.sql`. Rationale: one
UPDATE envelope must show what changed. With DEFAULT a status change from `shipped` to
`delivered` has a `before` holding only `order_id`. Soft deletes would survive on DEFAULT, since
they need only the key; late-event ordering and "what did this row look like before" would not.

Consequences: every UPDATE writes the whole old row into the WAL, so WAL volume and slot pressure
grow; cheap at this scale (100k orders, 24 h Kafka retention, one laptop), and slot lag is
monitored (`SlotWalRetainedHigh`). Fallback if WAL becomes the bottleneck: FULL on `orders` only.

## ADR-019 Incremental snapshots through a signal table

Context: on 2026-09-22 the stack had run 26 hours with nothing consuming Kafka. Retention (24 h)
had deleted the initial snapshot and the first part of the replay before bronze existed, so
silver could never match Postgres. Re-running the initial snapshot means dropping the replication
slot and the connector offsets, which is destructive and loses whatever the slot holds.

Decision: give the connector a signaling table and use Debezium incremental snapshots. The table
is `cdc.debezium_signal` (migration 002), in its own schema and added to `shop_publication`
explicitly. `make cdc-snapshot [TABLES=...]` inserts an `execute-snapshot` row; the connector
re-reads the tables in primary-key chunks of 1024 while streaming continues, and resolves
collisions with rows changed during a chunk through open/close watermarks in the same table.
Verified by running it ([evidence](docs/evidence.md#adr-019-incremental-snapshots)): the signal
topic must exist, and snapshot events carry `op = "r"` and a null `lsn`.

Silver takes the newest event per key as the highest LSN, null last; a target row with a null
`_last_lsn` is replaced by any later event. The limit: once silver holds a streamed LSN for a key,
no snapshot read can change that row again, so after an outage that lost events, keys changed
during the gap stay stale until their next change. Comparable snapshot reads would need a
position in bronze (`source.sequence`, ADR-022) in the guard; not done.

Consequences: recovery from "consumer was down longer than retention" is one command with no
blast radius. The connector role needs `insert` on one table in the source database, and every
snapshot writes a pair of watermark rows per chunk there, which nothing cleans up yet. Bronze
receives the snapshotted rows as extra events, which it is allowed to by contract (ADR-007).

## ADR-020 Silver contracts and timestamp types

Context: ADR-008 puts the typing in silver, but the payload in bronze is JSON text whose encoding
follows the connector settings (`decimal.handling.mode=double`, `time.precision.mode=connect`).
Source timestamps are `timestamp without time zone` holding Olist local times.

Decision: one JSON Schema per table in `contracts/silver/`, which states both the wire type and the
silver type of each column plus the primary key. Silver parses `after`/`before` with the wire
types and casts. Timestamps become `timestamp_ntz` (Iceberg `timestamp`, Trino `timestamp(6)`),
converted with integer arithmetic on the epoch milliseconds so the Spark session time zone never
touches them. `smallint` becomes `int` because Iceberg has no smallint. A unit test keeps every
contract in step with `oltp/migrations/001_schema.sql`, and envelope fixtures shaped after the
live topics are validated against both schemas.

Alternatives for decimals on the wire: `precise` (base64 bytes, unreadable in tools) or `string`;
`double` stays because the row fingerprints match at two decimals
([evidence](docs/evidence.md#adr-020-row-fingerprints)).

Consequences: no time zone is invented, and a value reads the same in Spark, Trino and Postgres up
to the millisecond; `connect` precision drops microseconds already in Kafka. `reconcile` compares
live row counts, primary keys, decimal sums and, since 2026-10-30, the `dq_checks` row
fingerprint, which reads timestamps as epoch milliseconds on both sides. A source type change is
a contract change here and an Iceberg type promotion in silver.

## ADR-021 Silver upsert: one AvailableNow job, idempotent MERGE per table

Context: ADR-007 fixes the shape (streaming read of bronze, `foreachBatch`, `MERGE`), not the
details. `foreachBatch` is at-least-once: Spark re-runs a batch whose commit it did not record,
and Iceberg's epoch dedup covers the streaming sink only, not a `MERGE` issued inside the batch.
Spark's MERGE fails when several source rows match one target row, and silently inserts all of
them when they match none.

Decision: one job reads all of bronze and, per table present in the batch, parses with the
contract, sends events it cannot type to `silver.quarantine` (one row per Kafka record, merged
on topic, partition and offset, with the first matching reason), keeps one row per key (highest
LSN, null last, then Debezium time, then Kafka offset), and merges with `when matched and
(t._last_lsn is null or s._last_lsn > t._last_lsn)`. A delete updates only `_is_deleted`,
`_last_lsn`, `_updated_at`. Silver tables are format v2, laid out per ADR-010. Shuffle partitions
are 4, not 200.

Consequences: a replayed batch is a no-op, verified by a test that merges the same batch twice
and by rerunning the job on unchanged bronze. A value that does not fit its column withholds the
whole event, not just that field, so the key keeps its previous state until its next valid change
(deletes are checked only for their key and always apply). Known limits, from Iceberg 1.11:
- The AvailableNow prepare step starts from the snapshot the query first saw
  (apache/iceberg#18000, open). Expiring that bronze snapshot makes every later run fail, so
  `expire_snapshots` on bronze must not run until this is solved, for example with
  `async-micro-batch-planning-enabled` (untested) or a checkpoint reset.
- The same step walks every retained bronze snapshot on each run (apache/iceberg#16940), and
  bronze commits every 20 s while the replayer plays; run time has to be watched.
- LSN is the start of the change's WAL record, not its commit position. Per key it only grows
  with a single writer, which is what the replayer is (checked on 1 561 same-key pairs in Kafka:
  none decreasing). With concurrent writers a re-insert of a key that another transaction just
  deleted can commit later with a lower LSN, and the guard would keep the row deleted. The sound
  order is Debezium's `source.sequence`, which bronze stores since ADR-022; silver does not use it.

## ADR-022 Bronze keeps the commit position (`source.sequence`)

Context: ADR-021 orders changes of one key by `lsn`, the start of the change's WAL record, which
is commit order only with a single writer. Debezium's `source.sequence` is a JSON array in a
string, `[end of the previous transaction's commit record, LSN of this change]`; compared as two
numbers it follows commit order across transactions and WAL order inside one. Incremental
snapshot reads have a null `lsn` but a sequence, the position of the chunk's close watermark,
which would let a snapshot read be compared with streamed changes (ADR-019).

Decision: bronze stores it verbatim as `source_sequence string`, right after `lsn`. Silver keeps
ordering by `lsn`; parsing the pair and switching the MERGE guard is a separate change, due when
a second writer appears or a gap has to be repaired with a snapshot. Bronze adds the column on
start (`ensure_table`), without a rewrite and without touching the checkpoint.

Consequences: rows ingested before 2026-09-26 have a null sequence and are not backfilled (bronze
is append-only). The first element is null for initial snapshot rows and for the first
transaction after one. After a `docker kill` of Connect the first re-sent transaction can carry a
first element that is too small, because the slot is flushed from the last acked record rather
than from the stored offset; a sequence-based guard would have to tolerate that.

## ADR-023 Observability: metric sources

Context: profile `obs` planned cAdvisor for per-container memory, CPU and restarts. On Docker
Desktop 29.8 with the containerd image store, cAdvisor v0.52.1 and v0.55.1 fail to create any
Docker container (`failed to identify the read-write layer ID`; google/cadvisor#3643, closed as
not planned); without its Docker factory it reports raw cgroups by id, every start time equal to
the VM boot (checked 2026-10-19).

Decision:
- `container-exporter` replaces cAdvisor in `obs`: about 200 lines of Python that list the compose
  project's containers through the Docker socket (GET only) at scrape time and export
  `docker_container_*{name,service}`: memory as `docker stats` prints it, limit, CPU seconds,
  start time, `RestartCount`, `OOMKilled`, running and health. A failed Docker call fails the
  scrape. `ContainerRestarting` uses the start time: `docker restart` does not increment
  `RestartCount`.
- Retained WAL of the slot from a custom postgres-exporter query (`lakehouse_slot_retained_bytes`,
  `lakehouse_slot_active`): the built-in collector reports `confirmed_flush_lsn` only for active
  slots, which is exactly when it does not matter.
- Kafka Connect: the JMX exporter agent in an own image layer (`lakehouse/connect:dev`).
- Airflow through its StatsD client and `dq_checks` through DogStatsD gauges into
  statsd-exporter; no Pushgateway.
- No Alertmanager (ADR-015): rule state is read from the UI, `/api/v1/alerts` and the dashboard.

Consequences: one more image to build (`lakehouse/container-exporter:dev`, 128 MB limit, raised
from 64 MB on 2026-11-10: its walk of the Docker API, about 50 MB with swap, kept it swapping) that
holds the Docker socket (ADR-029) and has no host port; metric names differ from cAdvisor's.
Connect, StatsD, the WAL of a burst and the `oltp.message` incident:
[evidence](docs/evidence.md#adr-023-connect-statsd-and-wal).

## ADR-024 Stateful job `orders_per_minute`

Context: the project needs one real stateful Structured Streaming job, with a watermark, state and
a late event shown in SQL. Bronze and silver keep no state.

Decision (2026-10-23):
- **Input is Kafka `oltp.shop.orders`**, own checkpoint `checkpoints/orders_per_minute`,
  `failOnDataLoss`. Bronze as input would add a permanent reader of an Iceberg table whose
  snapshots must not be expired (apache/iceberg#18000), polling 148+ snapshots on every trigger.
- **Own service** `spark-orders-per-minute`, profile `stateful`, the image of `spark-bronze`,
  1792M: an OOM kill of the stateful query does not take CDC ingest with it. The profile does not
  depend on `core` services (`required: false`).
- **Only `op = 'c'`**, one-minute windows over `order_purchase_timestamp`, watermark 5 minutes,
  `update` mode, `size(collect_set(order_id))`. A snapshot read (`r`) comes in table order, not
  time order; `count(*)` would rise on a Debezium resend, and Spark 3.5 cannot chain
  `dropDuplicatesWithinWatermark` and an aggregation in `update` mode.
- **Sink** `lake.silver.orders_per_minute` through `foreachBatch`: `MERGE` that updates only to a
  higher count, so a replayed batch or a fresh checkpoint cannot lower it. No contract file, or
  `silver_upsert` would treat it as a CDC table. Shuffle partitions 2, frozen in the checkpoint.
- **Late events on a lab topic** (`make watermark-demo`) into `lake.demo.orders_per_minute`; the
  live topic gets only real records, so `bronze_offsets_ok` and `reconcile` stay valid.

Consequences: one more service, and one more checkpoint to reset by hand after an outage longer
than Kafka retention. At replay speed 720 five minutes of event time are 0.4 s, so a skew between
topic partitions can drop rows that are not late in the data's own time. Measured facts:
[evidence](docs/evidence.md#adr-024-orders_per_minute-facts).

## ADR-025 Iceberg maintenance policy

Context: silver and gold pile up snapshots (an empty MERGE still commits one to `silver.orders`,
up to 2016 a week; dbt makes one per run); bronze piles up small files and `metadata.json` (122
in MinIO against 101 log entries, 2026-10-23). `expire_snapshots` on bronze breaks the streaming
read of silver (ADR-021). The cleaning procedures are on the blast-radius list.

Decision (2026-10-23):

| Layer | Operation | When | Term |
|---|---|---|---|
| silver | `optimize` (Trino) | daily 03:30 | as before |
| silver.orders | `rewrite_position_delete_files` | daily, after `optimize` | default options |
| silver | `expire_snapshots` | daily, after the rewrite | 7 days, `retain_last` 1 |
| silver | `remove_orphan_files` | weekly, `iceberg_orphans` | older than 7 days |
| gold | `expire_snapshots`, one task per table of `lake.gold` | daily | 7 days |
| gold | `remove_orphan_files` | weekly | older than 7 days |
| bronze | `rewrite_data_files` of past days only | daily, last | whole past days |
| bronze | `remove_orphan_files` in `.../metadata` only | weekly | older than 7 days |
| bronze | `expire_snapshots` | never | refused by the code |

- A Spark job (`maintenance.py`): only Spark has `dry_run`, `location` and
  `rewrite_position_delete_files`; silver `optimize` stays in Trino. Before a session starts the
  job refuses bronze `expire_snapshots` (ADR-021), less than 7 days on silver and gold (Trino's
  own minimum), and bronze orphans outside `metadata` (bronze data cannot be rebuilt after Kafka's
  24 hours); an orphan younger than a week may be a commit in flight; `orphans` is a dry run
  unless `--no-dry-run`; `demo.*` takes any term. Iceberg refuses `older_than` below 24 hours.
- Pools: silver tasks share `lake_writers` with the merge, gold tasks `gold_writers` (1 slot) with
  `dbt_build`, since `CREATE OR REPLACE` and `expire_snapshots` of one table race.
  `write.metadata.delete-after-commit.enabled` is on in silver and bronze; dbt-trino
  cannot set it, so the orphan run cleans gold metadata.
- New DAGs are created paused; orphans delete with `{"dry_run": false}`, the Spark steps of
  `iceberg_maintenance` run with `{"expire_and_compact": true}`.

Consequences: bronze compaction makes a `replace` snapshot, so one empty merge and one `dbt_build`
follow, and frees no space. Time travel deeper than 7 days on silver and gold is gone by design
(chaos 9 rolls a mart back by one snapshot). [Probe and first
runs](docs/evidence.md#adr-025-maintenance-probe-and-first-runs).

## ADR-026 MinIO and mc built from the pinned source

Status: accepted (2026-10-27). Replaces the image source of ADR-004; the rest of ADR-004 (MinIO
as the store, `mc` as the admin tool, the fallbacks) stands.

Context: quay.io stopped serving the MinIO and `mc` images to CI, Docker Hub and `dl.min.io` are
gone, and the upstream Dockerfiles do not build a tag from source. The GitHub repositories are
archived (AGPL-3.0), but the tags resolve
([evidence](docs/evidence.md#adr-026-minio-built-from-source)).

Decision: `docker/minio/Dockerfile` with targets `minio` and `mc`, built by `docker compose` as
`lakehouse/minio:<tag>` and `lakehouse/mc:<tag>`: `git clone --branch <tag>` checked against the
commit SHA written in the Dockerfile, the tag's build flags with explicit `-ldflags`,
`golang:1.24.6-bookworm` and `alpine:3.22` by digest, healthcheck `wget -q --spider` (no `curl`),
`pull_policy: never`. Registry images are pinned by digest; `lakehouse/*` images are built here
and never pulled. No image is published (AGPL), no fork, no change of the S3 layer. A later tag,
RELEASE.2025-10-15T17-29-55Z, fixes CVE-2025-62506 (service account and STS session policies, not
used here); staying on 2025-09-07 is an accepted risk.

Alternatives: a tar of the images in the owner's GHCR (publication); the `pgsty/silo` fork (new
code on a live volume); SeaweedFS, Garage or RustFS (replacing the S3 layer). Each stays open if
this one stops working.

Consequences: the same code and volume, so the swap of a running stack is a recreate of `minio`
and `minio-init`. Rollback is the whole compose block of both services from git (`image:
quay.io/minio/...`, no `build:` and `pull_policy`, healthcheck `curl -sf ...`): the upstream image
has no `wget`, so putting back only `image:` leaves `minio` unhealthy. Keep the old images in the
local store. The build needs the network and takes minutes on a cold cache, which CI caches.

## ADR-027 Superset as the BI layer, with an MCP endpoint

Context: ADR-014 left Superset optional and showed the marts in Grafana. A business reader expects
cross-filters, period comparison and named metrics; an agent needs a programmatic way to query and
build charts. Replaces ADR-014 (2026-11-06).

Decision: Superset 6.1.0 in profile `bi` (base image by digest plus pinned drivers), metadata in
`postgres-meta`, the `Marketplace` dashboard as code in `docker/superset/dashboards/`, imported by
`superset-init` with overwrite: the bundle wins over UI edits, columns and metrics of its datasets
missing from the YAML are deleted, objects outside the bundle stay. It reads only the
`lake_ro.gold` marts as Trino user `superset` (ADR-028), `allow_dml: false`. What the import
cannot carry lives in `superset_config.py`: the theme (a theme import never overwrites), the
relative-time anchor `SUPERSET_DATA_ANCHOR` (first day of the month of the latest order, set by
hand when a replay moves the data into a later month) and `CHART_PLUGINS_EXPERIMENTAL`, without
which the `pop_kpi` tiles fail. `superset-mcp` serves Superset's MCP service on port 5008 bound to
`BIND_IP`; every tool runs as `admin` (`MCP_DEV_USERNAME`), Host and Origin are checked against
DNS rebinding. The UI has a login, MCP has none.

Alternatives: Grafana only (no metric layer, no cross-filters); Metabase or Evidence (another
stack); MCP with JWT auth (`MCP_AUTH_ENABLED`, an identity provider for one user).

Consequences: two long-running services (1280M and 512M); any local process can change Superset
metadata through MCP, not data; UI edits are lost on re-import; the Grafana `Marketplace`
dashboard stays as a light view of the same marts.

## ADR-028 Read-only BI access: catalog `lake_ro` and Trino file-based access control

Context: Trino has no authentication here. Dashboards must not write and must not read silver,
and file-based access control has no privilege for table procedures such as `expire_snapshots`.

Decision (2026-10-29, narrowed to the marts 2026-11-04): `lake_ro` is a twin of `lake` (same
Lakekeeper, warehouse and S3 keys) that differs by one line, `iceberg.security=read_only`.
`rules.json` gives the users `grafana` and `superset` SELECT on `lake_ro.gold.(fct|dim|mart)_*`
only: no other catalog, no procedures, no functions beyond `system.builtin`, no system
information, and of queries only `execute`. Every other user keeps full rights. Rules load on
restart only (no `security.refresh-period`).

Alternatives: Trino authentication (password file, OAuth2) with the same rules; Lakekeeper
authorization (OpenFGA) with vended credentials; separate read-only MinIO keys for `lake_ro`.

Consequences: protects against mistakes, not against a local attacker: the user name is a label.
`lake_ro` still holds the root S3 keys. The dbt views over silver (`stg_*`) are hidden from BI.
Checks: [evidence](docs/evidence.md#trino-access-control).

## ADR-029 Local security model

Context: one user on one laptop, no data worth protecting; every auth system costs memory and
setup.

Decision: every published port is bound to `BIND_IP` (127.0.0.1; compose refuses an empty value).
No login on Kafka, Kafka Connect, Lakekeeper (`allow-all`), Trino, Prometheus, `kafka-ui`
(profile `tools`), the Spark UIs, Airflow (every user is admin) and Superset MCP; Superset UI and
Grafana use generated passwords, the MinIO console the S3 root keys. Secrets live only in `.env`
(git-ignored); `make secrets` replaces every `change_me` with a random value. One MinIO root key
pair is shared by Spark, Trino, Lakekeeper and the three Airflow containers (api-server,
scheduler, dag-processor), one `postgres-meta` superuser (`META_USER`) by Lakekeeper, Airflow and
Superset, and the source database superuser (`OLTP_USER`) by the replayer, postgres-exporter and
Airflow. Lakekeeper encrypts the S3 keys it stores with `LAKEKEEPER_ENCRYPTION_KEY`, not the
database password; the key never changes once a warehouse exists. The Airflow scheduler and
container-exporter hold the Docker socket, root on the host in effect; `:ro` on the socket does
not limit the API (the exporter only reads, by its code). MinIO and Lakekeeper run as root inside
their containers; no container drops capabilities or sets `no-new-privileges`.

Alternatives: Docker secrets; a socket proxy; per-service MinIO users and policies; OIDC
(Keycloak) for Trino, Lakekeeper, Airflow and Superset.

Consequences: any local process, or an escape from a container that holds the socket, owns the
stack. Lakekeeper protection (ADR-005) guards bronze and silver against a mistaken drop, not
against an attacker. Nothing may be exposed beyond loopback as it is.

## ADR-030 Gold: dbt on Trino, tables per run, one incremental mart

Context: gold is derived from silver and can always be rebuilt from it. dbt-trino's default
`on_table_exists: rename` drops a backup table on every run, and on Lakekeeper a drop is a soft
delete that keeps the files for 7 days.

Decision (2026-10-18): staging and intermediate models are views, marts are tables written with
`CREATE OR REPLACE` (`on_table_exists: replace`). `mart_daily_sales` is incremental
`delete+insert` by `purchase_date` with `on_schema_change='fail'`: a run re-selects every
purchase date with an order changed since the mart's watermark, `max(source_updated_at)`. dbt
runs after each silver merge (Asset `lake.silver`), in pool `gold_writers` with the gold
maintenance. Gold is not protected and keeps 7 days of snapshots (ADR-025).

Alternatives: `merge` on date and state (one commit, but a state that lost all its orders of a
date would keep its old row); a full rebuild of `mart_daily_sales` like the other marts.

Consequences: `delete+insert` is two commits, a `delete` and an `append` about 0.3 s apart, so a
reader can see a date missing between them; marts agree with each other per dbt run, not per
query. Known limit: a soft-deleted order or a seller moved to another state leaves its old dates
stale until `--full-refresh`. Recovery is a rebuild from silver.
