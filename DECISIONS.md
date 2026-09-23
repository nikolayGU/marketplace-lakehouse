# Decisions

Short ADRs. One entry per decision that someone might question. Status: proposed / accepted /
superseded. Longer reasoning lives in `docs/planning/00-mini-architecture-review.md` (ru).

| ID | Decision | Status |
|---|---|---|
| ADR-001 | Real data via Olist replay, not synthetic generators | accepted |
| ADR-002 | Two PostgreSQL instances: `postgres-oltp` (CDC source) and `postgres-meta` | accepted |
| ADR-003 | Kafka 4 KRaft, single broker, RF=1, 3 partitions per topic, retention 24h | accepted |
| ADR-004 | Object storage: MinIO, last community release pulled from quay.io (Docker Hub repo removed) | accepted |
| ADR-005 | JDBC catalog in `postgres-meta` first; REST catalog (Lakekeeper) as should-have after the vertical slice | accepted |
| ADR-006 | Spark 3.5 + Iceberg 1.11 runtime in `local[2]`, no standalone cluster | accepted |
| ADR-007 | Bronze append-only streaming (at-least-once contract, idempotent epoch commit to be verified); silver via AvailableNow + foreachBatch MERGE is the no-duplicates guarantee | accepted |
| ADR-008 | Bronze keeps payload as JSON string; typed schema applied in silver from contracts | accepted |
| ADR-009 | Soft deletes in silver (`_is_deleted`; Iceberg reserves `_deleted`), filtered in dbt | accepted |
| ADR-010 | `silver.orders` merge-on-read, other silver tables copy-on-write | proposed, measure in week 2 |
| ADR-011 | Airflow 3 LocalExecutor, batch only, BashOperator for dbt (no Cosmos) | accepted |
| ADR-012 | No Schema Registry until week 6; JSON envelopes + JSON Schema contracts | accepted |
| ADR-013 | Spark metrics via custom StreamingQueryListener, because kafka-exporter cannot see Spark offsets | accepted |
| ADR-014 | Superset optional; marts are shown through Grafana + Trino datasource, dbt docs and SQL | accepted |
| ADR-015 | Removed: ClickHouse, k8s, Terraform, Ansible, Loki, Alertmanager delivery, Cosmos | accepted |
| ADR-016 | Compose profiles and the rule "never all profiles at once" as the RAM strategy | accepted |
| ADR-017 | Stateful windowed job `orders_per_minute` (watermark, state, update mode) is mandatory, not optional | accepted |
| ADR-018 | `REPLICA IDENTITY FULL` on all `shop` tables so CDC `before` carries the whole previous row | accepted |
| ADR-019 | Debezium signal table `cdc.debezium_signal` for incremental snapshots, the recovery path when Kafka retention outlives a consumer outage | accepted |
| ADR-020 | Silver contracts as JSON Schema per table; naive source timestamps become `timestamp_ntz` at millisecond precision | proposed, owner to confirm |
| ADR-021 | Silver upsert: one AvailableNow job, newest event per key, MERGE guarded by `_last_lsn`, idempotent on replay | accepted |

## ADR-001 Real data via Olist replay

Context: synthetic generators produce uniform distributions and meaningless dashboards; no
own e-commerce data is available. Decision: load the public Olist dataset (~100k orders,
2016-2018) into PostgreSQL, shift dates to end today, bulk-load 80%, replay 20% on a virtual
clock as real transactions with injectable late, duplicate and schema-change events.
Consequences: realistic seasonality and categories; a replayer service to maintain; dataset
license must be checked before shipping a sample.

## ADR-004 Object storage

Context: MinIO stopped publishing community images and removed the web console. Checked on
2026-09-21: the Docker Hub repository `minio/minio` is gone (the registry denies access and the
Hub API returns 404 for the repository), but `quay.io/minio/minio` still serves the last
community release `RELEASE.2025-09-07T16-13-09Z` (2025-09-07), and quay additionally carries
`.hotfix.*` rebuilds of that same release into 2026.

Decision: keep MinIO, pull it and `mc` from quay.io, pin the plain community release rather than
a hotfix tag, and administer it with `mc` since there is no console. RustFS and Garage stay as
the documented fallback (both were checked and their images pull), but they are not needed: the
skill being demonstrated is "S3-compatible object storage", not a vendor, so a working pinned
image wins over a migration.

Consequences: one non-Docker-Hub registry in `compose.yaml`; the image is frozen at the
2025-09-07 release and will not receive upstream fixes, which is acceptable for a laptop project
with no data worth protecting and a documented fallback. Verified: bucket `lakehouse` with
`warehouse` and `checkpoints` prefixes is created by `minio-init`, and the service reports
healthy on `/minio/health/live`.

## ADR-005 Catalog: JDBC first, REST as should-have

Context: Spark and Trino must share one Iceberg catalog. A REST catalog (Lakekeeper) is the
2026 standard and the better interview signal, but it is one more service with its own
bootstrap, and week 1 must end with a working vertical slice. Decision: start with the JDBC
catalog stored in `postgres-meta` (Spark `JdbcCatalog`, Trino `iceberg.catalog.type=jdbc`;
whether Trino bundles the PostgreSQL driver is checked in W1-T07, otherwise the jar goes into
the image). Add Lakekeeper in week 2 (W2-T09) with a 3-hour cap and migrate tables with
`register_table`; if it does not come up in that time, JDBC stays and this ADR records why.
Consequences: zero new services in week 1; the JDBC to REST migration is itself a learning
exercise about what a catalog actually stores.

Verified on 2026-09-23 (W1-T07): `trinodb/trino:483` ships `postgresql-42.7.13.jar` in
`plugin/iceberg`, so Trino needs no custom image. `iceberg.jdbc-catalog.catalog-name` must be
`lake`, the Spark catalog name, because JdbcCatalog keys every table row by it; with any other
value Trino sees an empty catalog. The native S3 file system (`fs.s3.enabled`; the older
`fs.native-s3.enabled` still works but logs a replacement warning) reads the `s3a://` locations
Spark records in the metadata.

Side effect, found after the fact: Spark's JdbcCatalog creates `iceberg_tables` in the V0 layout,
while Trino defaults to `iceberg.jdbc-catalog.schema-version=V1` and on its first query ran
`ALTER TABLE iceberg_tables ADD COLUMN iceberg_type` in `iceberg_catalog`. The change is
additive, Iceberg detects the column and switches Spark to V1 on its next start, and V1 is what
lets Trino create views, which dbt needs in week 3. Pinning V0 would avoid the DDL but refuse
`CREATE VIEW`, so V1 stays.

## ADR-007 Bronze streaming append, silver batch MERGE

Context: Iceberg's Spark streaming sink is append-oriented; MERGE INTO driven directly from a
streaming query is unreliable (Iceberg issues #9730, #10805, #13431). Decision: bronze is an
append-only streaming sink with a 20 s trigger; silver is a separate job with
`Trigger.AvailableNow` scheduled by Airflow every 5 minutes, using `foreachBatch` to run
`MERGE INTO`. Consequences: one continuous JVM plus one short-lived JVM; silver latency is
minutes, not seconds, which is acceptable for analytics; both Spark trigger modes are shown.

On duplicates: bronze is contractually at-least-once. Debezium re-sends events after a restart
and those land in bronze as new Kafka records. For Spark restarts the expectation is that the
Iceberg sink skips an already committed epoch (it records `spark.sql.streaming.queryId` and
`epochId` in the snapshot summary); chaos scenario 1 verifies this experimentally and the
result is recorded here. Either way, the no-duplicates guarantee lives in silver
(`MERGE` keyed by primary key with an LSN guard) and `bronze_duplicate_ratio` is a monitored
metric, not an assumption.

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

## ADR-013 Spark metrics

Context: Spark stores Kafka offsets in its checkpoint and does not commit to a consumer group,
so `kafka-exporter` reports no lag for it. Decision: a `StreamingQueryListener` in the driver
exposes `spark_streaming_input_rows_total`, `spark_streaming_batch_duration_seconds` and
`spark_streaming_kafka_lag` (latest broker offset minus processed offset) via
`prometheus_client` on the driver's HTTP port. Consequences: ~60 lines of Python, a real
"how do you monitor a Spark stream" answer.

## ADR-018 REPLICA IDENTITY FULL on the source tables

Context: Debezium fills the `before` field of an event from whatever Postgres wrote into the
WAL for the old row, and that is governed by the table's replica identity. The Debezium
PostgreSQL documentation is explicit: with `REPLICA IDENTITY DEFAULT`, "UPDATE and DELETE events
contain the previous values for the primary key columns of a table", while with
`REPLICA IDENTITY FULL` they "contain the previous values of all columns in the table".

Decision: set `REPLICA IDENTITY FULL` on all seven `shop` tables in `001_schema.sql`.

Rationale: half the point of this project is being able to open one UPDATE envelope and say what
changed, which the Kafka gate asks for directly. With DEFAULT, a status change from `shipped` to
`delivered` produces a `before` holding only `order_id`, and the question cannot be answered from
the event at all. Soft deletes in silver would survive on DEFAULT, since they only need the key,
but late-event ordering and any "what did this row look like before" query would not.

Consequences: every UPDATE writes the whole old row into the WAL, so WAL volume and replication
slot pressure grow. At this scale (100k orders, 24 h Kafka retention, one laptop) that is cheap,
and slot lag is monitored anyway (`SlotWalRetainedHigh`, W4-T05). If WAL growth ever becomes the
bottleneck, the fallback is FULL on `orders` alone and DEFAULT elsewhere.

## ADR-019 Incremental snapshots through a signal table

Context: on 2026-09-22 the stack had run 26 hours with nothing consuming Kafka. Retention (24 h)
had deleted the initial snapshot and the first part of the replay before bronze existed, so
bronze could only ever see changes from that day on, and silver could never match Postgres.
Re-running the initial snapshot means dropping the replication slot and the connector offsets,
which is destructive and also loses whatever the slot holds.

Decision: give the connector a signaling table and use Debezium incremental snapshots. The table
is `cdc.debezium_signal` (migration 002), in its own schema and added to `shop_publication`
explicitly. `make cdc-snapshot [TABLES=...]` inserts an `execute-snapshot` row; the connector
re-reads the tables in primary-key chunks of 1024 while streaming continues, and resolves
collisions with rows changed during a chunk through open/close watermarks it writes into the
same table.

Verified by running it, not by the docs, which say neither:
- Debezium publishes the signal table like any captured table, watermarks included, to
  `oltp.cdc.debezium_signal`. With broker auto-creation off the producer blocked and the whole
  change stream stalled until the topic existed; `register.sh` now creates it. The separate
  schema keeps those rows out of bronze.
- Incremental snapshot events carry `op = "r"`, `source.snapshot = "incremental"` and
  `source.lsn = null`. The envelope contract now allows a null `lsn`, and silver's LSN guard
  (W2-T02) must treat null as older than any streamed change, otherwise a snapshot row either
  never lands or overwrites a newer state.

Silver (W2-T02) implements that as: inside a batch the newest event per key is the highest LSN,
null last; a target row with a null `_last_lsn` is replaced by any later event. The limit, which
the owner should weigh before relying on this path for a real gap: once silver holds a streamed
LSN for a key, no snapshot read can change that row again. After an outage that lost events,
keys changed during the gap stay stale until their next change. Making snapshot reads
comparable would need a position in bronze (the envelope's `source.sequence` carries one for
incremental reads), which is a bronze contract change and is not done.

Consequences: recovery from "consumer was down longer than retention" is one command with no
blast radius. The connector role needs `insert` on one table in the source database, and every
snapshot writes a pair of watermark rows per chunk there, which nothing cleans up yet. Bronze
receives the snapshotted rows as extra events, which it is allowed to by contract (ADR-007).

## ADR-020 Silver contracts and timestamp types

Context: silver needs typed tables, and ADR-008 puts the typing there, but the payload in bronze is
JSON text whose encoding follows the connector settings (`decimal.handling.mode=double`,
`time.precision.mode=connect`). Source timestamps are `timestamp without time zone` holding Olist
local times.

Decision: one JSON Schema per table in `contracts/silver/`, which states both the wire type and the
silver type of each column plus the primary key. Silver parses `after`/`before` with the wire
types and casts. Timestamps become `timestamp_ntz` (Iceberg `timestamp`, Trino `timestamp(6)`),
converted with integer arithmetic on the epoch milliseconds so the Spark session time zone never
touches them. `smallint` becomes `int` because Iceberg has no smallint. A unit test keeps every
contract in step with `oltp/migrations/001_schema.sql`, and envelope fixtures shaped after the
live topics are validated against both schemas.

Consequences: no time zone is invented, and a value reads the same in Spark, Trino and Postgres
up to the millisecond. The microseconds are gone already in Kafka, because `connect` precision is
milliseconds, so a silver timestamp can differ from Postgres by less than 1 ms; reconciliation
compares counts and keys, not timestamps. Changing a column type in the source is a contract
change here and an Iceberg type promotion in silver.

## ADR-021 Silver upsert: one AvailableNow job, idempotent MERGE per table

Context: ADR-007 fixes the shape (streaming read of bronze, `foreachBatch`, `MERGE`), not the
details. `foreachBatch` is at-least-once: Spark re-runs a batch whose commit it did not record,
and Iceberg's epoch dedup covers the streaming sink only, not a `MERGE` issued inside the batch.
Spark's MERGE fails when several source rows match one target row, and silently inserts all of
them when they match none.

Decision: one job reads all of bronze and, per table present in the batch, parses with the
contract, drops invalid events, keeps one row per key (highest LSN, null last, then Debezium time,
then Kafka offset), and merges with `when matched and (t._last_lsn is null or s._last_lsn >
t._last_lsn)`. A delete updates only `_is_deleted`, `_last_lsn`, `_updated_at`. Silver tables are
format v2, copy-on-write for now (layout is W2-T03, ADR-010). Shuffle partitions are 4, not 200.
The soft-delete column is `_is_deleted` because Iceberg reserves `_deleted` for a metadata column
and refuses a table that uses it.

Consequences: a replayed batch is a no-op, verified by a test that merges the same batch twice
and by rerunning the job on unchanged bronze. Two known limits, both from Iceberg 1.11:
- The AvailableNow prepare step starts from the snapshot the query first saw
  (apache/iceberg#18000, open). Expiring that bronze snapshot makes every later run fail, so
  `expire_snapshots` on bronze (W5-T05) must not run until this is solved, for example with
  `async-micro-batch-planning-enabled` (untested) or a checkpoint reset.
- The same step walks every retained bronze snapshot on each run (apache/iceberg#16940), and
  bronze commits every 20 s while the replayer plays; run time has to be watched.
- LSN is the start of the change's WAL record, not its commit position. Per key it only grows
  with a single writer, which is what the replayer is (checked on 1 561 same-key pairs in Kafka:
  none decreasing). With concurrent writers a re-insert of a key that another transaction just
  deleted can commit later with a lower LSN, and the guard would keep the row deleted. The sound
  order is Debezium's `source.sequence` (`[last commit LSN, LSN]`), which bronze does not store;
  adding it is a bronze contract change for the owner to decide.
