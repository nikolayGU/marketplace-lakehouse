# Decisions

Short ADRs. One entry per decision that someone might question. Status: proposed / accepted /
superseded. Longer reasoning lives in `docs/planning/00-mini-architecture-review.md` (ru).

| ID | Decision | Status |
|---|---|---|
| ADR-001 | Real data via Olist replay, not synthetic generators | accepted |
| ADR-002 | Two PostgreSQL instances: `postgres-oltp` (CDC source) and `postgres-meta` | accepted |
| ADR-003 | Kafka 4 KRaft, single broker, RF=1, 3 partitions per topic, retention 24h | accepted |
| ADR-004 | Object storage: MinIO, last community release pulled from quay.io (Docker Hub repo removed) | accepted |
| ADR-005 | JDBC catalog in `postgres-meta` first; REST catalog (Lakekeeper) as should-have after the vertical slice | accepted; Spark and Trino switched to Lakekeeper, cutover done 2026-10-08 |
| ADR-006 | Spark 3.5 + Iceberg 1.11 runtime in `local[2]`, no standalone cluster | accepted |
| ADR-007 | Bronze append-only streaming (at-least-once contract, idempotent epoch commit verified 2026-09-26 and 2026-10-07); silver via AvailableNow + foreachBatch MERGE is the no-duplicates guarantee | accepted |
| ADR-008 | Bronze keeps payload as JSON string; typed schema applied in silver from contracts | accepted |
| ADR-009 | Soft deletes in silver (`_is_deleted`; Iceberg reserves `_deleted`), filtered in dbt | accepted |
| ADR-010 | `silver.orders` merge-on-read, partitioned by month; other silver tables copy-on-write | accepted, measured 2026-09-26 |
| ADR-011 | Airflow 3 LocalExecutor, batch only, BashOperator for dbt (no Cosmos), DockerOperator for Spark silver | accepted |
| ADR-012 | No Schema Registry until week 6; JSON envelopes + JSON Schema contracts | accepted |
| ADR-013 | Spark metrics via custom StreamingQueryListener, because kafka-exporter cannot see Spark offsets | accepted |
| ADR-014 | Superset optional; marts are shown through Grafana + Trino datasource, dbt docs and SQL | accepted |
| ADR-015 | Removed: ClickHouse, k8s, Terraform, Ansible, Loki, Alertmanager delivery, Cosmos | accepted |
| ADR-016 | Compose profiles and the rule "never all profiles at once" as the RAM strategy; `core` starts without the replayer container (`make start`) | accepted |
| ADR-017 | Stateful windowed job `orders_per_minute` (watermark, state, update mode) is mandatory, not optional | accepted |
| ADR-018 | `REPLICA IDENTITY FULL` on all `shop` tables so CDC `before` carries the whole previous row | accepted |
| ADR-019 | Debezium signal table `cdc.debezium_signal` for incremental snapshots, the recovery path when Kafka retention outlives a consumer outage | accepted |
| ADR-020 | Silver contracts as JSON Schema per table; naive source timestamps become `timestamp_ntz` at millisecond precision | accepted |
| ADR-021 | Silver upsert: one AvailableNow job, newest event per key, MERGE guarded by `_last_lsn`, idempotent on replay | accepted |
| ADR-022 | Bronze keeps Debezium's `source.sequence` as text; silver keeps ordering by `lsn` until there is a second writer | accepted |
| ADR-023 | Observability sources: own `container-exporter` on the Docker API instead of cAdvisor; retained WAL from a custom postgres-exporter query; JMX agent in an own Connect image layer; StatsD for Airflow and `dq_checks`; no Alertmanager | accepted |
| ADR-024 | Stateful job `orders_per_minute`: reads Kafka, not bronze; own service in profile `stateful`; distinct count under a 5 minute watermark in `update` mode; MERGE that never lowers a count | accepted |

## ADR-001 Real data via Olist replay

Context: synthetic generators produce uniform distributions and meaningless dashboards; no
own e-commerce data is available. Decision: load the public Olist dataset (~100k orders,
2016-2018) into PostgreSQL, shift dates to end today, bulk-load 80%, replay 20% on a virtual
clock as real transactions with injectable late, duplicate and schema-change events.
Consequences: realistic seasonality and categories; a replayer service to maintain; dataset
license must be checked before shipping a sample.

`REPLAY_DATA` (`.env`, `raw` or `sample`, default `raw`) picks the directory under `DATA_DIR` that
`make replay-load` reads: the full download in `data/raw` or the committed 2 000-order slice in
`data/sample`, for a fresh clone and CI smoke. Both come from `Settings`, so `.env` applies without
exporting it into the shell.

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

### Side by side, verified 2026-10-08

W2-T09 runs Lakekeeper next to the JDBC catalog, not instead of it: compose profile `rest`, the
bronze and silver tables registered at their current metadata files, and Spark and Trino still on
JDBC. Six decisions came out of it.

(a) Paths of new tables. Lakekeeper gives new tables `s3://` locations in the `full-hierarchy`
layout, `warehouse/<namespace>/<table>-<uuid>/`; the 9 registered tables stay on `s3a://` for
good. Lakekeeper accepts `s3a://` only with `allow-alternative-protocols`, which the vendor advises
solely for registering existing Hadoop tables, and Trino and dbt tables get `s3://` anyway, so Spark
maps `fs.s3.impl` to S3A and pins `io-impl` to HadoopFileIO: the REST client would pick S3FileIO,
and the image has no AWS SDK v2. Both keys sit in the part of `catalog_conf` shared by both catalog
types, so a rollback to JDBC still reads `s3://` tables; for JdbcCatalog HadoopFileIO is the default
already. A soft-deleted table keeps its location taken for 7 days, so the `{uuid}` gives a
re-created table of the same name a fresh path instead of `LocationAlreadyTaken`. The vendor also
advises `{uuid}` in the namespace template, against renames; ours is `{name}`, because `bronze`,
`silver`, `gold` and `demo` are fixed by contract and never renamed, and MinIO then shows
`warehouse/demo/orders-<uuid>/` next to the JDBC sandbox's `warehouse/demo/orders/`. Lakekeeper
compares locations by whole path segments, so a new `silver/orders-<uuid>/` would not collide with
the registered `silver/orders/`.

(b) Delete profile and protection. Soft delete for 7 days: a dropped table can be undropped for a
week before Lakekeeper deletes its location (a drop with `purgeRequested=false` keeps the files).
`push-s3-delete-disabled` is `false` on purpose: its default `true` hands S3FileIO clients
`s3.delete-enabled=false` under soft delete, which would silently turn `expire_snapshots` and
`remove_orphan_files` into no-ops after a move to S3FileIO (HadoopFileIO does not read it). Soft
delete does not cover Spark `DROP ... PURGE`, which deletes the files on the client. Only table
protection stops that, because Lakekeeper refuses the drop with 409 before Spark deletes anything.
Protection goes on every bronze and silver table after the cutover checks, not at registration,
where it would make a repeated `register` fail with 409 and complicate rolling back a failed
cutover. Namespaces stay unprotected: dropping a namespace that holds a protected table is refused
anyway unless forced. Bronze cannot be rebuilt once Kafka's 24 h are gone, which is why this
matters.

(c) Encryption key. Lakekeeper encrypts the warehouse's S3 keys inside its database
(`pgp_sym_encrypt`, aes256) with `LAKEKEEPER_ENCRYPTION_KEY`, a new `.env` variable, instead of
`META_PASSWORD` as in the compose skeleton: a key equal to that database's password protects
nothing when the database leaks, and a password change would silently cut the catalog off from
MinIO. `make secrets` generates it for a fresh `.env`; an existing `.env` gets it from one command
in OPERATIONS rather than from a merge mode in `make_env.py` built for a single clone. Compose
refuses every command without it (`:?`), whatever the profile. The key never changes once a
warehouse exists.

(d) Blast radius. On JDBC, Spark `DROP TABLE` without `PURGE` and Trino `unregister_table` remove
only the catalog row. On Lakekeeper both delete the files: Lakekeeper reads a REST `DELETE` without
`purgeRequested` as a purge, while the Iceberg REST spec defaults it to `false`. `unregister_table`
or a plain REST `DELETE` looks like the safe way to undo a registration, and the registered tables
share their files with the JDBC catalog. Hence a "what deletes files" table in OPERATIONS, and a
matching item in the blast-radius list of `CLAUDE.md`, which the owner reviews with the cutover.

(e) Cutover. Full cutover of Spark and Trino to Lakekeeper, behind two gates: a green side by side
check (below) and the owner's approval of a cutover runbook. Side by side is a check, not an end
state: the REST pointers go stale with bronze's next commit, and a drop through either catalog
hits files both share. W3 then builds gold on the final catalog, with no second migration. The
work is split into two commits at that approval: this one keeps the verified state as a free
rollback point, the cutover gets its own. After the cutover, rollback stays free until bronze's
first commit through Lakekeeper; from then on it is DML on `iceberg_tables` (blast radius).

(f) Version. `quay.io/lakekeeper/catalog:v0.13.6`, pinned by the digest of its multi-arch manifest
list, `sha256:d6829722cac0d00dfc5665b0955766387b93ccadd8b1e70e679b49619bc30ea5`; after the pull
`docker inspect` returned the same RepoDigest. It was the latest release on 2026-10-07 (released
2026-09-22); newer is only `latest-main`, with a breaking authentication change. The pin matters
more than usual: an older image refuses a schema that a newer one migrated, so the image cannot be
rolled back. 0.14 is its own task, with a backup of the `lakekeeper` database first.

Verified on the live stack, with JDBC the live catalog throughout:
- `lakekeeper-migrate` exited 0 and `lakekeeper` turned healthy. The one-shot
  `lakekeeper-bootstrap` printed `warehouse lake created`, a second run `warehouse lake exists`.
  The warehouse came back with the soft profile, the layout and `push-s3-delete-disabled: false`,
  and `/catalog/v1/config?warehouse=lake` returns its id as `defaults.prefix`, with no `io-impl`
  and no `s3.delete-enabled`.
- The Spark image was rebuilt with `catalog_conf`, and bronze, recreated on `CATALOG_TYPE=jdbc`,
  logged `Resuming at batch 120`; its Spark UI listed `io-impl` HadoopFileIO and `fs.s3.impl` S3A.
- With bronze stopped and no silver run, `scripts/lakekeeper/register.sh` registered 9 tables
  (`bronze.cdc_events` and 8 silver tables) and read back the same metadata file from both
  catalogs for each. A temporary read-only Trino catalog on Lakekeeper (not committed, removed
  after the check) then matched `lake` on `count(*)` and the current `main` snapshot id for all 9,
  for example 543 862 rows in `bronze.cdc_events` and 94 113 in `silver.orders`. Bronze was stopped
  twice, about 3 s each (the first comparison script failed on its own SQL and was re-run), and
  resumed at batch 120 both times.
- Decision (a) in the sandbox: the Iceberg demo, run with `CATALOG_TYPE=rest`, created
  `demo.orders` in Lakekeeper under `s3://lakehouse/warehouse/demo/orders-<uuid>/`, wrote and read
  it through S3A, rolled it back, compacted 21 files into 1, and `expire_snapshots` deleted 22 data
  files, 43 manifests and 22 manifest lists. `silver.orders`, the demo's source, kept its snapshot
  and metadata file, and the JDBC `lake.demo.orders` was not touched: `lake.demo` is not
  registered, because the demo starts with `drop ... purge`, which on Lakekeeper would delete the
  JDBC sandbox's files.
- Lakekeeper used 67 MiB after bootstrap and 88 MiB after registration and the demo, of a 256 MiB
  limit.

Consequences until the cutover: Spark and Trino read and write through JDBC only; Lakekeeper's
pointers are stale from bronze's next commit, so the cutover starts by registering again; no table
is protected yet; Lakekeeper also holds the REST-only sandbox `demo.orders`. Lakekeeper runs
without authentication (`allow-all`, it logs a warning), so its port is bound to 127.0.0.1 only.
The cutover is the next step: it runs after the owner approves its runbook, and its own commit
records it here.

### Cutover, 2026-10-08

Spark and Trino read and write through Lakekeeper; nothing reads or writes the JDBC catalog any
more. The cutover followed `docs/runbooks/catalog-cutover.md` on the live stack. Profile `rest`
is gone: `lakekeeper-migrate`, `lakekeeper` and `lakekeeper-bootstrap` are in `core`, and
`spark-bronze`, `spark-silver` and `trino` wait for `lakekeeper-bootstrap`. `CATALOG_TYPE` is
`rest` in `.env.example` and as the code default, and an empty value is refused. Trino's
`lake.properties` is on REST with vended credentials off; the JDBC version is the one in
`5cf0fec`.

Verified on the live stack:
- Bronze stopped with batch 119 committed, then `register.sh` printed `same` for all 9 tables and
  exited 0. Those lines are the rollback point in readable form.
- The switch recreated only `spark-bronze`, and the one-shots `minio-init`, `lakekeeper-migrate`
  and `lakekeeper-bootstrap` exited 0. Trino needed an explicit restart: compose does not see a
  change in a bind-mounted file.
- Before any write through Lakekeeper: bronze turned healthy and logged `Resuming at batch 120`
  and no error, Trino's log showed catalog `lake` on REST, and row count and current `main`
  snapshot of all 9 tables read through Lakekeeper equalled those read through JDBC at the stop.
  `make silver` ran and Lakekeeper's pointers did not move.
- The first commits through Lakekeeper came from one virtual day of replay (`replay_burst 120` at
  speed 720). The pointer of `bronze.cdc_events` moved from `00121-d40d030c-...metadata.json` to
  `00128-01a119cb-...gz.metadata.json`: Lakekeeper commits into an `s3a://` table and writes the
  metadata file itself, gzip-compressed. The JDBC pointers stayed where they were. `make silver`
  merged batch 16, 1275 input rows, through Lakekeeper. `bronze_offsets_report` found 0 duplicates
  and 0 missing in all 21 partitions, and `reconcile` was ok on all 7 tables (orders 94 406,
  order_items 106 994, payments 98 716, reviews 91 600, customers 99 441, products 32 951,
  sellers 3 095).
- `protect.sh` protected all 9 tables; a second run printed `already protected` for each.
- Lakekeeper used 90.95 MiB of its 256 MiB limit, and the `lakekeeper` database is 12 MB.

What changes with Lakekeeper as the live catalog:
- Drops. Lakekeeper's reading of a `DELETE` without `purgeRequested` as a purge, against the REST
  spec's default `false` (d), now applies to every engine: any `DROP TABLE` from Spark, Trino or
  dbt deletes files. Soft delete keeps them 7 days, except after Spark `DROP ... PURGE`, and
  protection makes Lakekeeper refuse the drop with 409 on the 9 bronze and silver tables; `demo`
  and the coming `gold` stay unprotected. The blast-radius list in `CLAUDE.md` now names these
  drops, `unregister_table`, a REST `DELETE`, removing protection, `force=true`, a new delete
  profile, and deleting a warehouse or a namespace recursively.
- Two schemes for good (a): the 9 registered tables on `s3a://`, every table Lakekeeper creates on
  `s3://`. Bronze and silver commits now exercise the first, the side by side sandbox proved the
  second.
- File IO. Clients keep their own S3 keys: Spark through HadoopFileIO and S3A, Trino through its
  native S3 file system with vended credentials off. Vended credentials are the next step and need
  S3FileIO, because HadoopFileIO in Iceberg 1.11 does not implement `SupportsStorageCredentials`
  and ignores any credential the catalog hands out. S3FileIO needs AWS SDK v2 in the Spark image,
  and from then on `push-s3-delete-disabled: false` (b) is what keeps `expire_snapshots` and
  `remove_orphan_files` working. A task of its own.
- The key from (c), which never rotates, now sits on every commit, not only on Lakekeeper's own
  deletes: Lakekeeper writes each new metadata file with the S3 credential it keeps encrypted
  under `LAKEKEEPER_ENCRYPTION_KEY`, and it has no other S3 keys.
- No authentication. Lakekeeper still runs `allow-all`, now as the catalog of every table. The
  port stays on 127.0.0.1 and protection covers the tables that cannot be rebuilt: enough for a
  one-user laptop, not for anything shared.
- Idempotent commits. Idempotency keys are on by default in Lakekeeper and kept 30 minutes.
  #1952, one of the two fixes that moved the pin from 0.13.1 to 0.13.6, advertises
  `idempotency-key-lifetime` at the top level of `/v1/config`, the only place the Iceberg 1.11
  client looks. With it the client sends an `Idempotency-Key` on every commit, so a commit retried
  after a timeout gets the first attempt's answer instead of conflicting with its own change.
  Whether the live config response carries the field was not checked.
- The digest pin (f) holds, and with Lakekeeper in `core` an image change touches the critical
  path: 0.14 waits for its own task and a backup of the `lakekeeper` database.

Rollback: the free one ended with bronze's first commit through Lakekeeper. The JDBC rows in
`iceberg_catalog` keep the pre-cutover pointers as the rollback point until the end of week 3;
going back is DML on `iceberg_tables`, which only the owner runs (runbook, "Rollback"). Outside
that procedure no Spark job runs with `CATALOG_TYPE=jdbc` and Trino does not get the JDBC
`lake.properties` back: the two histories would fork, and maintenance on one side would delete
files the other still reads. `register.sh` refuses now that `CATALOG_TYPE` is `rest`.

## ADR-007 Bronze streaming append, silver batch MERGE

Context: Iceberg's Spark streaming sink is append-oriented; MERGE INTO driven directly from a
streaming query is unreliable (Iceberg issues #9730, #10805, #13431). Decision: bronze is an
append-only streaming sink with a 20 s trigger; silver is a separate job with
`Trigger.AvailableNow` scheduled by Airflow every 5 minutes, using `foreachBatch` to run
`MERGE INTO`. Consequences: one continuous JVM plus one short-lived JVM; silver latency is
minutes, not seconds, which is acceptable for analytics; both Spark trigger modes are shown.

On duplicates: bronze is contractually at-least-once. Debezium re-sends events after a hard stop
of Connect (or a restart whose final offset commit does not finish), and those land in bronze as
new Kafka records. For Spark restarts the expectation is that the
Iceberg sink skips an already committed epoch (it records `spark.sql.streaming.queryId` and
`epochId` in the snapshot summary); chaos scenario 1 verifies this experimentally and the
result is recorded here. Either way, the no-duplicates guarantee lives in silver
(`MERGE` keyed by primary key with an LSN guard) and `bronze_duplicate_ratio` is a monitored
metric, not an assumption.

Verified on 2026-09-26, re-run on 2026-10-07 with a script that asserts the result. Iceberg 1.11
`SparkWrite` skips an epoch when the last snapshot of the same query id already carries an equal
or higher `epochId`. `tests/unit/test_iceberg_sink.py` reproduces the crash window by deleting
`commits/N` of a checkpoint: Spark re-runs batch N, the re-run adds no rows and no snapshot, and a
new checkpoint (new query id) appends every file again. On the live stack `make chaos-spark-kill`
killed the driver during batch 80 on 2026-10-07 (batch 47 on 2026-09-26), both times before the
write stage; after `docker start` Spark replayed the batch, and the script found every Kafka
offset in bronze exactly once, with no gaps, and no epoch committed twice.
So bronze is exactly once across Spark restarts that keep the checkpoint, and at-least-once
across Debezium re-sends and checkpoint loss.

In the runs measured so far Debezium re-sent events only after a hard stop. A `docker restart` of
Connect (SIGTERM) waits up to `offset.flush.timeout.ms` (5 s) for producer acks, stores the offset
of the last acked record and flushes that offset's commit LSN to the slot; on resume Debezium drops
what Postgres re-sends up to the stored offset. The shutdown took about 1.3 s and gave 0 repeats
on 2026-10-07 (about 2 s and 0 repeats on 2026-09-26). That holds only while the stop fits
Docker's 10 s stop timeout (no `stop_grace_period`) and the final commit fits 5 s; records still
unacked then, or a timed-out commit, are sent again as after a kill. A `docker kill` skips the
final commit, and everything since the last offset flush (at most `offset.flush.interval.ms`,
60 s) arrives again with the same LSN: 253 events for a kill about 9 s after the flush on
2026-10-07 (11 events about 2 s after it on 2026-09-26), and silver live row counts still matched
Postgres both times. A Postgres restart (chaos 5) is not measured yet.

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

Context: every replayed order changes status several times after it is inserted, while
customers, sellers, products, items, payments and reviews rarely change a row twice. Copy-on-write
MERGE rewrites every data file that holds a matched row, and the updated orders are spread over
all of them.

Decision: `silver.orders` gets `write.merge.mode`, `write.update.mode`, `write.delete.mode` =
`merge-on-read` and `write.delete.granularity` = `file` (Spark's default, spelled out because the
Iceberg docs list `partition`), and is partitioned by `months(order_purchase_timestamp)`. The
other tables stay copy-on-write and unpartitioned. `ensure_table` creates new tables that way and
converges an existing one on the next run with `ALTER TABLE ... SET TBLPROPERTIES` and `ADD
PARTITION FIELD`, which are metadata only; the schema, by contrast, never converges by itself.

Measured on 2026-09-26 on the live table (91 k orders), one replay burst each:

| | copy-on-write | merge-on-read |
|---|---|---|
| orders events in the batch | 1 174 | 1 405 |
| data files rewritten | 4 of 4 | 0 |
| rows written | 90 950 | 1 115 new rows + 842 position deletes |
| bytes written (`added-files-size`) | 5 735 311 | 77 891 (70 316 data + 7 575 deletes) |
| orders step, between log lines | 4.2 s | 2.9 s, of which the MERGE statement 2.1 s |

Write amplification drops from about 4.9 KB to about 55 bytes per event. The cost moves to
reads: every scan applies the position deletes (one delete file per touched data file with
`file` granularity), and each MERGE adds small files per touched month. `ALTER TABLE
silver.orders EXECUTE optimize` in Trino folds the deletes and rewrites files of the old
unpartitioned spec into the monthly one: on 2026-09-26 it turned 6 data files and 4 delete
files into 22 files, one per month, with the row count unchanged. That is a `replace` snapshot,
which no stream reads, so no data is at risk. It does conflict with a merge-on-read MERGE that
commits at the same time: the MERGE's position deletes point at files optimize removed, the losing
commit fails, and silver replays the batch on its next run. `iceberg_maintenance` therefore must
not overlap `silver_upsert`.
The partition does not prune the MERGE itself, whose `on` clause has only the primary key.

## ADR-011 Airflow 3: LocalExecutor, dbt through BashOperator, Spark through DockerOperator

Context: Airflow orchestrates batch only (silver merge, dbt, data quality, maintenance); the bronze
stream is not a DAG. On a 16 GB laptop there is no room for Celery, a triggerer or Cosmos
(ADR-015).

Decision (2026-10-09, D9 and D12 of the week 3 spec):

- LocalExecutor; api-server, scheduler and dag-processor run one image, `lakehouse/airflow:dev`
  (`apache/airflow:3.3.2-python3.12`, the Python of the host). Tasks are processes in the
  scheduler container; `[core] parallelism` is 2 within its 900 MB. The first limit, 600 MB,
  left too little room: `dbt build` alone peaked the scheduler at 579 MiB (D19, 2026-10-18).
- dbt through BashOperator: `dbt build` from a venv of its own in the image (`/opt/dbt-venv`,
  versions from `uv.lock`), because dbt next to Airflow fights it over shared dependencies. The
  project is mounted read-only, so target and log paths go to `/tmp`.
- Spark silver through DockerOperator: the scheduler starts `lakehouse/spark:dev` on the network
  `<COMPOSE_PROJECT_NAME>_lake` with the environment compose gives `spark-silver`, through the
  Docker socket. The socket is root on the host in effect; accepted for a single-user laptop with
  every port on 127.0.0.1. Only the scheduler joins the socket's group (`group_add`, `DOCKER_GID`
  in `.env`). The alternative, BashOperator with `docker compose run`, needs the compose CLI and
  the repo with its `.env` inside the image.
- No login (D12): SimpleAuthManager with `simple_auth_manager_all_admins`. Any process on the
  laptop can drive the DAGs, which is acceptable here. `AIRFLOW_ADMIN_PASSWORD` is gone from
  `.env.example`.
- `.env` gains `AIRFLOW_API_SECRET_KEY` (the api-server signs task-log requests to the scheduler
  with it; without a shared value the UI shows no task log) and `DOCKER_GID`.
- Cadence (D10): `silver_upsert` every 5 minutes, and its first task skips the run when bronze
  has no snapshot that silver has not merged, so no JVM starts for nothing and no Asset event
  wakes dbt; `dbt_build` on the Asset `lake.silver`; `dq_checks` every 15 minutes on time (moving
  it onto the Asset is the owner's Modify gate).
- Maintenance in week 3 (D11): only `optimize` of the silver tables, in the pool `lake_writers`
  (1 slot) together with the silver merge, since two commits to `silver.orders` at once fail one
  of them (ADR-010). `expire_snapshots` and `remove_orphan_files` wait for the policy of week 5
  (ADR-021).

Consequences: an image of 3.47 GB to build, the socket as the price of DockerOperator,
the dbt version pinned twice (`uv.lock` and `airflow/Dockerfile`).

## ADR-013 Spark metrics

Context: Spark stores Kafka offsets in its checkpoint and does not commit to a consumer group,
so `kafka-exporter` reports no lag for it. Decision: a `StreamingQueryListener` in the driver
exposes `spark_streaming_input_rows_total`, `spark_streaming_batch_duration_seconds` and
`spark_streaming_kafka_lag` (latest broker offset minus processed offset) via
`prometheus_client` on the driver's HTTP port. Consequences: ~60 lines of Python, a real
"how do you monitor a Spark stream" answer. For stateful queries the listener also exports the
rows in state, the watermark (Unix seconds of event time) and a counter of rows the watermark
dropped (W5-T01b, ADR-024).

W4-T02 (2026-10-23): the lag is `spark_streaming_kafka_lag{query,topic,partition}`, one row per
topic and partition (21 for bronze), computed from the last progress as `latestOffset` minus
`endOffset` (`spark_jobs/offsets.py`; a partition missing from `endOffset` counts from 0, the
value is never negative, a `null` `latestOffset` gives no rows). `latestOffset` is the broker's
end at planning time, not the end limited by `maxOffsetsPerTrigger` (the Kafka source reports it
through `reportLatestOffset`). An idle event means no new data, so it sets every known row of the
query to 0; otherwise the last value would hang on the dashboard. Rows appear with the first
progress after a start. kafka-exporter was rejected for the lag: it needs the processed offsets
joined by labels in PromQL, and it keeps growing when Spark is down, which `SparkNoBatch5m`
already catches. The lag is above 0 only while a backlog exceeds one trigger
(`BRONZE_MAX_OFFSETS_PER_TRIGGER`, 20000 rows); a 60 s replay burst (579 events, 890 bronze rows)
stays at 0, so the above-zero path is covered by unit tests, not yet by a live backlog.

## ADR-016 Compose profiles; the replayer container only on request

Context: on a 16 GB laptop the services run in profiles (`core`, `query`, `orchestrate`, `obs`,
`bi`, `tools`), never all at once (OPERATIONS.md, "Profiles"). `oltp-replayer` is in `core`, so
`make up PROFILE=core` also started the replayer container, which plays at `REPLAY_SPEED` (2880,
one virtual day per 30 s). From week 3 the rest of the history is a budget for weeks 3-6 (D2 in
`docs/planning/07-w3-spec.md`): on 2026-10-09 about 72 virtual days, 36 minutes at that speed.

Decision (2026-10-09, D1 of the week 3 spec): compose stays as it is. `make start` brings up
`core` without `oltp-replayer`, plus `trino`, by naming `spark-bronze kafka-connect trino`; their
`depends_on` pull in the rest of `core`. `make up` refuses any `PROFILE` that contains `core`.
Traffic comes from `make replay-burst SECONDS=<n>`, which plays `n` real seconds on the host and
stops; the container starts only through `make replay-live`.

Alternatives: a profile `replay` for `oltp-replayer` (one line of compose, but a change of
infrastructure); keeping `make up PROFILE=core` with a warning (the failure stays one command
away).

Consequences: `make up PROFILE=core` from older notes now fails with a hint instead of spending
the replay; a fresh clone starts with `make bootstrap`.

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
(`reconcile` in `scripts/chaos/lib.sh`) compares live row counts, the set of primary keys and the
sums of decimal columns, not timestamps. Changing a column type in the source is a contract
change here and an Iceberg type promotion in silver.

W5-T04: `dq_checks` compares values through a row fingerprint at millisecond precision for
timestamps and at the contract scale for decimals; the fingerprints from Postgres and Trino were
equal on all seven tables on 2026-10-23, which confirms the wire (doubles) and the casts lose
nothing at two decimals.

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
(t._last_lsn is null or s._last_lsn > t._last_lsn)`. A delete updates only `_is_deleted`, `_last_lsn`, `_updated_at`. Silver tables are
format v2, laid out per ADR-010 (`orders` merge-on-read, partitioned by month; the rest
copy-on-write). Shuffle partitions are 4, not 200.
The soft-delete column is `_is_deleted` because Iceberg reserves `_deleted` for a metadata column
and refuses a table that uses it.

Consequences: a replayed batch is a no-op, verified by a test that merges the same batch twice
and by rerunning the job on unchanged bronze. A value that does not fit its column withholds the
whole event, not just that field, so the key keeps its previous state until its next valid change
(deletes are checked only for their key and always apply). Two known limits, both from Iceberg 1.11:
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
  order is Debezium's `source.sequence` (`[end of the previous transaction's commit, LSN]`),
  which bronze stores since ADR-022; silver does not use it yet.

## ADR-022 Bronze keeps the commit position (`source.sequence`)

Context: ADR-021 orders changes of one key by `lsn`, the start of the change's WAL record. That
is commit order only with a single writer. Debezium's `source.sequence` is a JSON array in a
string, `[end of the previous transaction's commit record, LSN of this change]`; compared as two
numbers it follows commit order across transactions and WAL order inside one. Incremental
snapshot reads have a null `lsn` but a sequence, the position of the chunk's close watermark,
which is what would let a snapshot read be compared with streamed changes (ADR-019).

Decision: bronze stores it verbatim as `source_sequence string`, right after `lsn`. Silver keeps
ordering by `lsn` for now; parsing the pair and switching the MERGE guard is a separate change,
due when a second writer appears or a gap has to be repaired with a snapshot. Bronze adds the
column on start (`ensure_table`), without a rewrite and without touching the checkpoint.

Consequences: rows ingested before 2026-09-26 have a null sequence. Bronze is append-only, so
they are not backfilled; most of them have also left Kafka (24 h retention). The first element is null for initial snapshot rows and for
the first transaction after one. After a `docker kill` of Connect the first re-sent transaction
can carry a first element that is too small, because the slot is flushed from the last acked
record rather than from the stored offset; a sequence-based guard would have to tolerate that.

## ADR-023 Observability: metric sources

Context: profile `obs` planned cAdvisor for per-container memory, CPU and restarts (Infra
dashboard, `ContainerRestarting`). On Docker Desktop 29.8 with the containerd image store,
cAdvisor v0.52.1 and v0.55.1 fail to create any Docker container (`failed to identify the
read-write layer ID`; upstream google/cadvisor#3643, closed as not planned), so no series carries
a container name. With its Docker factory disabled, cAdvisor reports raw cgroups by 64-character
id only, and every `container_start_time_seconds` equals the VM boot time (checked 2026-10-19).

Decision: `container-exporter` replaces cAdvisor in `obs`. About 200 lines of Python on the
standard library, `prometheus_client` and `pydantic-settings`; at scrape time it lists the
compose project's containers through the Docker socket (GET only) and exports
`docker_container_*{name,service}`: memory as `docker stats` prints it (usage minus inactive file
cache), memory limit, CPU seconds, start time, `RestartCount`, `OOMKilled`, running and health. A
failed Docker call fails the scrape (`up == 0`) rather than returning an empty page.
`ContainerRestarting` uses the start time: `docker restart` and compose restarts do not increment
`RestartCount`, only the restart policy does.

Retained WAL of the replication slot comes from a custom postgres-exporter query
(`lakehouse_slot_retained_bytes`, `lakehouse_slot_active`): the built-in slot collector reports
`confirmed_flush_lsn` only for active slots, which is exactly when it does not matter.

Consequences: one more image to build (`lakehouse/container-exporter:dev`, 64 MB limit, ~30 MB
used). The container holds the Docker socket, root on the host in effect, like the Airflow
scheduler (ADR-011); it has no host port. Metric names differ from cAdvisor's, so community
dashboards for cAdvisor do not apply as is.

Kafka Connect (W4-D1): the Debezium image's entrypoint loads the JMX exporter agent when
`ENABLE_JMX_EXPORTER=true`, but ships no jar. An own layer (`docker/connect/Dockerfile`, image
`lakehouse/connect:dev`) adds `jmx_prometheus_javaagent-1.6.0.jar` from the GitHub release with
the release's sha256; Maven Central stops at 1.0.1. A bind-mounted jar was rejected: a missing
file becomes a root-owned directory and the JVM of a `core` service does not start. The rules
file is bind-mounted, because `/kafka/config` is an anonymous volume that a recreated container
keeps. Connector and task status are string attributes and become a `status` label.

Airflow and `dq_checks` (W4-D2): Airflow's own StatsD client, mapped to labelled names by
statsd-exporter; `dq_checks` sends DogStatsD gauges with tags to the same exporter. UDP loses
packets silently while `obs` is down; the `dq_checks` gauges get a TTL in the mapping (W4-T03),
so their series disappear instead of freezing. Airflow's own counters have no TTL.
A Pushgateway would be one more service for the same job.

WAL of a replay burst (W4-T02, 2026-10-23): 60 s of `make replay-burst` (579 events, 11 h 54 min
of virtual time) wrote 13 589 336 bytes (`0/59AEAC70` to `0/5A7E07C8`), so a 64 MiB threshold
needs about five such bursts with an inactive slot (chaos 6 must run longer than one burst).

No Alertmanager (W4-D6): ADR-015 dropped alert delivery. Rules live in Prometheus; their state is
read from the UI, `/api/v1/alerts` and the dashboard.

## ADR-024 Stateful job `orders_per_minute`

Context: the roadmap asks for one real stateful Structured Streaming job, with a watermark, state
and a late event shown in SQL (W5-T01, spec `docs/planning/10-w5-spec.md`, decisions W5-D1 to D5).
Bronze and silver keep no state.

Decision (2026-10-23):
- **Input is Kafka `oltp.shop.orders`**, own checkpoint `checkpoints/orders_per_minute`, `failOnDataLoss`.
  Bronze as input would add a permanent reader of an Iceberg table whose snapshots must not be
  expired (apache/iceberg#18000), polling a history of 148+ snapshots on every trigger.
- **Own service** `spark-orders-per-minute`, profile `stateful`, the image of `spark-bronze`, 1792M.
  A failure or OOM kill of the stateful query does not take CDC ingest with it. The profile does
  not depend on `core` services (`required: false`).
- **Only `op = 'c'`**, window of one minute over `order_purchase_timestamp`, watermark 5 minutes,
  `update` mode, aggregate `size(collect_set(order_id))`. A snapshot read (`r`) comes in table
  order, not time order. `count(*)` would rise on a Debezium resend (253 repeats in chaos 2b), and
  Spark 3.5 cannot chain `dropDuplicatesWithinWatermark` and an aggregation in `update` mode.
- **Sink** `lake.silver.orders_per_minute` through `foreachBatch`: `MERGE`, update only when the
  new count is higher, so a replayed batch or a rerun on a fresh checkpoint cannot lower what is
  there. No file in `contracts/silver/`, otherwise `silver_upsert` would treat it as a CDC table.
  `spark.sql.shuffle.partitions` 2: it is frozen in the checkpoint, and the default 200 means
  hundreds of small state files per batch on S3A.
- **Late events are shown on a lab topic** (`make watermark-demo`): the same code, one
  `availableNow` run per batch on one checkpoint, into `lake.demo.orders_per_minute`. The live
  topic only receives real records (`make watermark-live` re-publishes real inserts), so
  `bronze_offsets_ok` and `reconcile` stay valid. `REPLAY_LATE_RATIO` moves UPDATEs, which this job
  does not read.

Facts measured on 2026-10-23 (Spark 3.5.9):
- Spark drops a late row against the watermark of the **previous** batch. The batch that moves the
  watermark still accepts the late event; the next one drops it. The demo therefore uses three
  runs: orders, an order inside the watermark, then the late order and a resend.
- `collect_set` works in a streaming aggregation in `update` mode.
- The `foreachBatch` frame must be persisted. On the Kafka source of the first demo, every action
  on it re-ran the aggregation and inflated the counters (dropped 3 for one late row, state rows 8
  for 3 windows); persisted, the demo reports `dropped=1`, `state_rows=3`, then 2.
- `numRowsDroppedByWatermark` counts rows dropped in that batch; the listener adds it to a counter
  (`spark_streaming_late_rows_dropped_total`).

Consequences: one more service (495 MiB at rest, 842 MiB while reading the topic from the start), one more checkpoint to
reset by hand if the job is down longer than Kafka retention (24 h; the table is derived and the
count is protected by the MERGE). The watermark is in event time; at a replay speed of 720x five
minutes are 0.4 s of real time, so a partition skew between topic partitions can drop rows that
are not late in the data's own time. Measured after a 60 s burst (12 virtual hours): 164 windows equal
to `count(*)` of `silver.orders` per minute, 0 rows dropped.
