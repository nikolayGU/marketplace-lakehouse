# Operations

## Profiles and what runs together

| Situation | Command | RAM (limits) |
|---|---|---|
| Daily work on ingestion | `make up PROFILE=core,query` | ~11 GB limits, ~7 GB real |
| Working on dbt / Airflow | `make up PROFILE=core,query,orchestrate` (Trino `Xmx` drops to 2g via `TRINO_XMX`); stop `orchestrate` when not working on batch | ~13 GB limits, ~9 GB real |
| Full pipeline with monitoring | `make up PROFILE=core,query,orchestrate,obs` | ~14 GB limits, ~10 GB real |
| Demo dashboard (optional Superset) | `make down PROFILE=orchestrate && make up PROFILE=bi` | swap orchestrate for bi |
| Debugging Kafka visually | `make up PROFILE=tools` for 15 minutes, then `make down PROFILE=tools` | +0.4 GB |

Never start `orchestrate` and `bi` together. Never start all profiles.

`core` includes Lakekeeper, the Iceberg catalog, since the cutover on 2026-10-08; there is no
`rest` profile any more. Both images in `core` (`lakehouse/replayer:dev`, `lakehouse/spark:dev`)
are built by `make up`. To work on one service without the replayer playing, start it by name
(Spark and Trino bring Lakekeeper up first):

```
docker compose --env-file .env -f docker/compose.yaml --profile core up -d spark-bronze
```

## Ports (all on 127.0.0.1)

| Service | Port |
|---|---|
| postgres-oltp | 5432 |
| postgres-meta | 5433 |
| kafka | 9092 |
| kafka-connect | 8083 |
| minio (S3 API) | 9000 |
| lakekeeper | 8181 |
| spark-bronze UI | 4040 |
| spark-bronze metrics | 4041 |
| spark-silver UI (while `make silver` runs) | 4042 |
| trino | 8080 |
| airflow api-server | 8090 |
| prometheus | 9090 |
| grafana | 3000 |
| superset | 8088 |
| kafka-ui | 8085 |

## Daily commands

First run, source side:

```
make data            # download Olist into data/raw
make migrate         # create schema shop
make replay-load     # shift dates onto today, load the initial share, build the schedule
make replay-start    # play the rest on the virtual clock (REPLAY_SPEED, default 1 day / 30 s)
```

`replay-load` refuses to touch non-empty tables. Starting over means `make replay-reset`, which
empties every `shop` table and drops staging; it asks before doing it.

```
make status          # docker compose ps with health
make logs S=spark-bronze
make psql            # psql into shop
make trino           # trino cli, catalog lake
make kafka-topics    # list topics with partitions
make kafka-groups    # consumer groups and lag (connect only; Spark lag is in Grafana)
make connector-status
make replay-status   # replayer position and virtual clock
make iceberg-demo    # snapshots, time travel, rollback, compaction, expiration
```

`make iceberg-demo` works on `lake.demo.orders` only: every run drops and rebuilds that sandbox
from `silver.orders`, which it only reads, so its rollback and `expire_snapshots` never reach
bronze or silver. It needs `silver.orders` populated (`make silver`) with at least 1 100 live
rows: it copies 1 000 for the first snapshot, then 20 appends of 5. Before the first
`make silver` it fails with table not found.

## Bronze ingest

`spark-bronze` runs `spark_jobs/bronze_cdc_ingest.py`: every `oltp.shop.*` topic into
`lake.bronze.cdc_events`, one micro-batch per `BRONZE_TRIGGER_SECONDS`, checkpoint at
`s3a://lakehouse/checkpoints/bronze_cdc_ingest`. It turns healthy after its first progress event,
which happens on an empty topic too.

- A crash or OOM kill makes Docker restart it (`unless-stopped`), and the job resumes from the
  checkpoint (`Resuming at batch N` in the log). A manual `docker kill` or `docker stop` does not:
  start it with `docker start lakehouse-spark-bronze-1`. Verified on 2026-09-22: resumed at
  batch 6, same `queryId`, no duplicate or missing offsets.
- `startingOffsets=earliest` applies only to a fresh checkpoint. If the job is down longer than
  Kafka retention (24 h), offsets it never read are gone and `failOnDataLoss=true` fails the
  query instead of silently skipping them. Docker then restarts it and it fails the same way,
  so the symptom is a restart loop (`RestartCount` growing, `OffsetOutOfRange` or "data loss" in
  the log). Recovery is a decision, not a restart: see the Kafka gate.
- Unhealthy means no progress or idle event for 120 s: the query is stuck, typically on MinIO
  or `postgres-meta`. The container keeps running; look at `make logs S=spark-bronze`.
- Consumer down longer than retention, or bronze started after the history left Kafka:
  `make cdc-snapshot` (all tables) or `make cdc-snapshot TABLES="shop.orders"` re-reads the
  source into the topics without touching the slot (ADR-019). Done on 2026-09-22 for all seven
  tables after the initial snapshot had expired.
- Schema changes of bronze itself are additive and applied on start: a new column goes into
  the DDL at its position and into `ADDED_COLUMNS` (name, type, after), and `ensure_table` adds it
  to the live table there, logging `lacks <column>, adding it`. A column only in the DDL is not
  added, and the streaming sink then refuses the DataFrame: it checks column order. The
  checkpoint is unaffected. `source_sequence` arrived this way on 2026-09-26 (ADR-022); from then
  on every parsed event has one:
  `select count(*) from bronze.cdc_events where op is not null and source_sequence is null
  and ingest_ts > timestamp '2026-09-26 04:13:00'` returns 0.
- Resetting bronze means deleting both the checkpoint prefix and the table, which is on the
  blast-radius list.

Check it:

```
curl -s 127.0.0.1:4041/metrics | grep ^spark_streaming   # input rows, last batch, duration
make logs S=spark-bronze
```

## Silver upsert

`make silver` runs `spark_jobs/silver_upsert.py` once in the `spark-silver` container (profile
`jobs`, needs `core` up): an Iceberg streaming read of `lake.bronze.cdc_events` with
`Trigger.AvailableNow`, checkpoint `s3a://lakehouse/checkpoints/silver_upsert`. It reads every
bronze snapshot committed since the previous run in micro-batches of about 200 000 rows
(`silver_max_rows_per_batch` in `spark_jobs/settings.py`), merges each into the seven
`lake.silver.<table>` tables and exits. Airflow takes over scheduling in week 3.

- Per table and batch: parse `after` (`before` for a delete) with `contracts/silver/<table>.json`,
  send events that cannot become a row to `silver.quarantine`, keep the newest event per primary
  key, `MERGE` guarded by `_last_lsn`.
- Quarantine: one row per Kafka record, keyed by `(topic, kafka_partition, kafka_offset)`, so a
  replayed batch adds nothing. A table without a contract goes there whole as `no_contract`.
  Otherwise `reason` is the first that applies: `unparsed_envelope` (bronze kept it as `raw`),
  `unknown_op`, `null_key`, then, for anything but a delete, `type_mismatch` (a field present in
  the payload that does not fit its column) and `null_required`. A delete needs only its key: it
  flags the row and never writes the other values. `payload` is `raw`, `after`, or `before` for a
  delete. The log says `batch N: <table> events quarantined: {reason: count}` (counts of rejected
  events in the batch, a replay counts them again) or `batch N: <n> <table> events quarantined,
  no contract`. Check: `select source_table, reason, count(*) from silver.quarantine group by 1, 2`.
- Quarantined events are not retried. After a contract fix: a key silver never received (its
  insert was quarantined, or the table had no contract) arrives with its next change or with
  `make cdc-snapshot TABLES=shop.<table>`; a key silver already holds catches up only with its
  next streamed change, because a snapshot read never beats a streamed LSN (ADR-019); a
  quarantined delete is not delivered again by anything and needs a hand fix the owner approves.
- Payload fields the contract does not declare are ignored and logged once per table and batch
  (`payloads carry fields contracts/silver/<table>.json does not declare: [...]`): the source
  gained a column (schema evolution, W2-T07). The row still merges.
- Soft delete: `_is_deleted = true` keeps the last values. Live rows are `where not _is_deleted`.
- Layout (ADR-010): `silver.orders` is merge-on-read and partitioned by month, the other tables
  copy-on-write. An older table converges on the next run (`lake.silver.orders: set ...` and
  `partitioned by ... from now on` in the log), metadata only. Delete files accumulate between
  compactions; `alter table silver.orders execute optimize` in Trino folds them and rewrites old
  files into the current spec. Check: `select content, spec_id, count(*) from
  silver."orders$files" group by 1, 2` (content 1 are delete files).
- `silver_shuffle_partitions` in `spark_jobs/settings.py` (a code default, compose does not pass
  it) is frozen in the checkpoint on the first run: Spark restores the stored value and logs
  `Updating the value of conf 'spark.sql.shuffle.partitions'`. A new value takes effect only
  with a new checkpoint, and deleting the checkpoint prefix is blast radius: the next run then
  re-reads all of bronze (idempotent, but long).
- A rerun with nothing new in bronze does nothing. A crash mid-run replays the unfinished batch,
  and the replay changes nothing that the first attempt already merged.
- The job refuses to start if a silver table and its contract disagree on columns: add the
  column to the contract and `ALTER TABLE ... ADD COLUMN`, in that order.
- Resetting silver means dropping the tables and deleting the checkpoint prefix: blast radius.

First run on 2026-09-23: the whole bronze (518 461 events) in 51 s, 3 batches; live rows equal
`count(*)` in Postgres for all seven tables, 3 order items soft-deleted.

Check it:

```
make silver
make trino   # select count(*) from silver.orders where not _is_deleted;  -- = shop.orders
```

## Query

`trino` (profile `query`) reads the same catalog as Spark, Lakekeeper:
`docker/trino/etc/catalog/lake.properties` points at its REST API and at MinIO through the native
S3 file system, which accepts both the `s3a://` paths of the registered tables and the `s3://`
paths of new ones. Trino uses its own S3 keys, no vended credentials. Heap is `TRINO_XMX`, passed
to the launcher as `-J-Xmx...`; the query memory limits in `config.properties` fit 2g as well.

Start it without the replayer and check it:

```
docker compose --env-file .env -f docker/compose.yaml --profile core --profile query up -d trino
make trino           # trino> select source_table, count(*) from bronze.cdc_events group by 1;
```

Healthy means the image's `health-check` saw `"starting": false` on `/v1/info`, about 40 s
after start. It does not prove the catalog works: run one query. The config is bind-mounted, so
after editing `docker/trino/etc` restart the container (`docker compose ... restart trino`);
`up -d` does not notice file changes.

Trino only reads what Spark committed: a bronze micro-batch shows up after its Iceberg commit,
not when Kafka receives the event.

## Lakekeeper (REST catalog)

Lakekeeper v0.13.6 is the Iceberg catalog of Spark and Trino since the cutover on 2026-10-08
(ADR-005; procedure and rollback in `docs/runbooks/catalog-cutover.md`). Its services are in
profile `core`: `lakekeeper-migrate` (one-shot schema migration of the `lakekeeper` database in
`postgres-meta`, 128 MiB), `lakekeeper` (the API on `127.0.0.1:8181`, 256 MiB limit) and
`lakekeeper-bootstrap` (one-shot, 128 MiB). `spark-bronze`, `spark-silver` and `trino` wait for
`lakekeeper-bootstrap`, so every `up` of them runs the one-shots again (`minio-init`,
`lakekeeper-migrate`, `lakekeeper-bootstrap`), all idempotent. Without `lakekeeper` Spark cannot
commit and Trino cannot load a table. The API has no authentication (allow-all), which is why the
port stays on 127.0.0.1.

`make silver` and `make iceberg-demo` run `spark-silver` with `--no-deps`: they never start
Lakekeeper, so it must already be running (`make status`; `make lakekeeper-bootstrap` starts it).

Measured on 2026-10-08 right after the cutover: `lakekeeper` 91 MiB of its 256 MiB, the
`lakekeeper` database 12 MB (commands in the runbook's step 6). Bronze commits every 20 s and each
commit now writes `postgres-meta` too: compare both a day later.

```
make lakekeeper-bootstrap   # starts lakekeeper (migration first) if needed, creates warehouse lake
curl -s '127.0.0.1:8181/catalog/v1/config?warehouse=lake'   # defaults.prefix is the warehouse id
docker stats --no-stream lakehouse-lakekeeper-1
```

`make lakekeeper-bootstrap` is safe to re-run: the second time it prints `warehouse lake exists`
and changes nothing, since it never updates an existing warehouse. It runs in
`lakehouse/spark:dev` with `pull_policy: never`, so build that image first (`make up` does);
otherwise compose stops with `No such image`.

Encryption key. `LAKEKEEPER_ENCRYPTION_KEY` encrypts the warehouse's S3 keys inside the
`lakekeeper` database. `make secrets` generates it only for a new `.env`; it never touches an
existing one, and without the key every compose command fails, `make lint` and `make up`
included, whatever the profile (`required variable LAKEKEEPER_ENCRYPTION_KEY is missing a
value`). Add it to an existing `.env` once, from the repo root; the command prints nothing:

```
grep -q '^LAKEKEEPER_ENCRYPTION_KEY=' .env || printf 'LAKEKEEPER_ENCRYPTION_KEY=%s\n' "$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')" >> .env
```

Never change the key once the warehouse exists: Lakekeeper could no longer decrypt its S3 keys,
and it writes every new metadata file with them, so commits depend on the key. Sending the
credential again (`POST /management/v1/warehouse/{id}/storage-credential`) should repair that; it
is untested.

Airflow Fernet key. A `.env` from `make secrets` before the fix holds a 32-character
`AIRFLOW_FERNET_KEY`, and Airflow accepts only urlsafe base64 of 32 bytes (44 characters).
`make secrets` never rewrites an existing `.env`, so replace that one line from the repo root
before Airflow first starts; the command prints nothing. Once Airflow has stored connections or
variables, a new key makes them unreadable.

```
sed -i "s|^AIRFLOW_FERNET_KEY=.*|AIRFLOW_FERNET_KEY=$(python3 -c 'import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())')|" .env
```

After the cutover. Never start a Spark job with `CATALOG_TYPE=jdbc` (in `.env`, as
`-e CATALOG_TYPE=jdbc` or exported in a shell), and never give Trino the JDBC `lake.properties`
back, except through the runbook's rollback. The JDBC rows in `iceberg_catalog` still point at
the pre-cutover snapshots, kept as the rollback point until the end of week 3: a job on them would
commit on top of an old snapshot, the two catalogs would fork, and `expire_snapshots` or
`remove_orphan_files` on one side would delete files the other still reads. Compose takes
`CATALOG_TYPE` from the shell over `.env`, so never source `.env` in a shell that runs compose.

Registration was the cutover's first step and is not repeated. `scripts/lakekeeper/register.sh`
refuses while `CATALOG_TYPE` in `.env` or in the shell is anything but `jdbc`, and a protected
table would refuse the overwrite with 409 anyway. Do not work around either: registering again
puts the stale JDBC pointers over the live ones. A new cutover after a rollback starts at the
runbook's step 1.

What deletes files. Lakekeeper reads a REST `DELETE` without `purgeRequested` as a purge (the
Iceberg REST spec defaults it to `false`), and warehouse `lake` soft-deletes for 7 days: the table
disappears from the catalog at once, Lakekeeper deletes its whole location 7 days later, and until
then it can be undropped (below). The location of a registered table is also the JDBC table's
directory, so the right column destroys the rollback point too.

| Action | JDBC catalog | Lakekeeper (soft delete, 7 days) |
|---|---|---|
| Spark `DROP TABLE` | removes the catalog row; files stay | `DELETE` without `purgeRequested`: location deleted after 7 days |
| Spark `DROP TABLE ... PURGE` | Spark deletes every file the table references, at once | the same drop, then Spark deletes the files itself, at once; undrop brings back no data |
| Trino `DROP TABLE` (dbt drops through it) | Trino deletes the table's files and its directory, at once | `DELETE ?purgeRequested=true`: location deleted after 7 days |
| Trino `CALL system.unregister_table` | removes the catalog row; files stay | `DELETE` without `purgeRequested`: location deleted after 7 days |
| REST `DELETE .../tables/<t>` | no REST API | location deleted after 7 days |
| REST `DELETE .../tables/<t>?purgeRequested=false` | no REST API | files stay; the table is hidden at once and leaves the catalog after 7 days |

`force=true` on a REST `DELETE` skips both the 7 days and table protection: the table leaves the
catalog at once and, unless `purgeRequested=false`, its whole location is deleted at once too.
Since the cutover the right column is what every engine does; the left one applies again only
after a rollback. All of it is on the blast-radius list.

Protection. `scripts/lakekeeper/protect.sh` set `protected` on all 9 bronze and silver tables at
the cutover. Lakekeeper then answers a drop of any of them with 409 before anything is deleted,
Spark `DROP ... PURGE` included; commits are not affected. Run it again when a new bronze or
silver table appears and after any registration, since a re-registered table comes back
unprotected; it only ever sets the flag and reads it back. `demo` and `gold` stay unprotected.
Removing protection is on the blast-radius list: the owner does it by hand, nothing else does. The
flag lives under the warehouse id and the table's Iceberg `table-uuid`:

```
lk=http://127.0.0.1:8181; json() { python3 -c "import json, sys; print(json.load(sys.stdin)$1)"; }
wid=$(curl -s "$lk/catalog/v1/config?warehouse=lake" | json '["defaults"]["prefix"]')
tid=$(curl -s "$lk/catalog/v1/$wid/namespaces/silver/tables/orders?snapshots=refs" |
  json '["metadata"]["table-uuid"]')
curl -s "$lk/management/v1/warehouse/$wid/table/$tid/protection"   # {"protected":true,...}
# POST {"protected": true} to the same URL sets it (protect.sh does);
# {"protected": false} removes it: owner only
```

Undrop. A dropped table stays in Lakekeeper's list of deleted tables for 7 days and can be
brought back with its files, unless Spark `DROP ... PURGE` already deleted them. Not tried on this
stack yet; `lk` and `wid` as above:

```
curl -s "$lk/management/v1/warehouse/$wid/deleted-tabulars"   # id, name, expiration-date
curl -sS -X POST -H 'Content-Type: application/json' \
  -d '{"targets": [{"type": "table", "id": "<id from the list>"}]}' \
  "$lk/management/v1/warehouse/$wid/deleted-tabulars/undrop"   # 204 on success
```

## Failure scenarios

Each scenario is a `make chaos-<name>` target plus a written answer to five questions:
what happened, what monitoring shows, which data is at risk, how the system recovers,
why nothing is lost or duplicated (or where it can be). Filled in as scenarios are run.

| # | Scenario | Target | Status |
|---|---|---|---|
| 1 | Spark bronze killed mid-batch | `chaos-spark-kill` | done 2026-10-07 (re-run) |
| 2a | Kafka Connect restart | `chaos-connect-restart` | done 2026-10-07 (re-run) |
| 2b | Kafka Connect killed | `MODE=kill make chaos-connect-restart` | done 2026-10-07 (re-run) |
| 3 | Duplicate events from source | `chaos-duplicates` | done 2026-10-07 UTC |
| 4 | Late events | `chaos-late` | done 2026-10-07 UTC |
| 5 | PostgreSQL restart | `chaos-postgres-restart` | planned (week 4) |
| 6 | Connector down for 30 minutes (WAL growth) | `chaos-connect-pause` | planned (week 4) |
| 7 | Corrupted event in topic | `chaos-poison-event` | data half done (W2-T04), alert in week 4 |
| 8 | Kafka down | `chaos-kafka-down` | planned (week 4) |
| 9 (optional) | Airflow task failure (dbt test) | `chaos-break-dbt-test` | planned (week 3) |
| 10 (optional) | Partial processing (Trino memory) | `chaos-trino-memory` | planned (week 3) |

### Template

```
### <n>. <Scenario>

What happened:
What monitoring shows: (metric, alert, time to detect)
Data at risk:
Recovery: (automatic / manual, steps, time to recover)
Why no loss or duplication: (or where it is possible)
Verification SQL:
```

Every scenario prints its own verification; the helpers it uses (`bronze_offsets_report`,
`bronze_caught_up`, ...) live in `scripts/chaos/lib.sh`. The file sets `set -euo pipefail` and
exports `.env`, so run a helper from the repo root in a child shell, not sourced into your own:
`bash -c '. scripts/chaos/lib.sh && bronze_offsets_report'`. A scenario that plays a replay
burst on the host stops before it touches anything, its script exiting 2, while another replayer
answers on `127.0.0.1:8000` (the `oltp-replayer` container or `make replay-start`): the burst
could not bind the port, and that replayer would keep playing at its own `REPLAY_SPEED`.

### 1. Spark bronze killed mid-batch

`make chaos-spark-kill` plays about 30 virtual hours (150 s at 720x, `CHAOS_REPLAY_SPEED`), waits
until the Spark UI reports a running job, `docker kill`s `spark-bronze` and starts it 5 s later.
It then reads `Resuming at batch N` from the new log: equal committed and available offsets mean
the kill landed between batches, and the script exits 1 as inconclusive; otherwise it prints
`Spark replayed batch N`. After the replayer burst ends and bronze catches up with Kafka it fails
on any duplicate or missing offset and on any epoch one query committed twice.

What happened: the driver JVM died with a micro-batch in flight. Spark had written `offsets/N` to
the checkpoint but not `commits/N`, and Iceberg had no snapshot for epoch N. On 2026-10-07 the
kill came 4 s after `offsets/80` was written, while the first stage of batch 80 (ShuffleMapStage
0) was still reading Kafka: the write stage (ResultStage 1) was never submitted, so no data file
reached MinIO.
What monitoring shows: the container exits and stays down until it is started again (`docker
kill` counts as a manual stop, the restart policy does not apply). The `:4041` endpoint goes away
with the driver, so once Prometheus scrapes it (W4-T01, not running on 2026-10-07) the scrape
fails (`up` = 0) and Prometheus marks `spark_streaming_last_batch_timestamp` stale: Grafana shows
no data, not an old timestamp.
`SparkNoBatch5m` (week 4) written as `time() - spark_streaming_last_batch_timestamp > 300` alone
would never fire here, so it also needs `absent(spark_streaming_last_batch_timestamp)`, for 5
minutes. After `docker start` the log says `Resuming at batch N`.
Data at risk: the batch in flight, 158 records in batch 80 on 2026-10-07 (`added-records` of its
snapshot). None is lost: Kafka keeps the records within retention, and bronze only misses the
batch until it is replayed.
Recovery: automatic after the container starts: Spark replays batch N from `offsets/N`. On
2026-10-07 the kill landed at 18:09:44 during batch 80 and the container started at 18:09:49; the
query logged `Resuming at batch 80` at 18:10:03, the replayed batch 80 committed at 18:10:12, 28 s
after the kill, with the same query id, and batch 81 followed. The container reported healthy at
18:10:17, about 28 s after the start (the script polls every 3 s). The first run, on 2026-09-26,
landed the same way (batch 47, 1 s after `offsets/47`, before the write stage) and also committed
the replayed batch 28 s after the kill.
Why no loss or duplication: the offsets come from the checkpoint, so nothing is skipped; a
replayed batch that Iceberg already committed is skipped by epoch (`Skipping epoch N`), because
the sink stores `spark.sql.streaming.queryId` and `epochId` in every snapshot summary. Both live
kills landed before the write stage, so no skip was needed and no `Skipping epoch` line appeared;
the commit-window case is reproduced deterministically by `tests/unit/test_iceberg_sink.py`. On
2026-10-07 the script ended with `ok`: no duplicate or missing offset in any of the 21 topic
partitions and no epoch committed twice. A kill during the write stage leaves the files already
written in MinIO as orphans until `remove_orphan_files` (week 5); neither run left any, since the
write stage never started.
Verification SQL (0 in both columns for every topic partition):

```
select topic, kafka_partition, count(*) - count(distinct kafka_offset) as duplicates,
       max(kafka_offset) - min(kafka_offset) + 1 - count(distinct kafka_offset) as missing
from bronze.cdc_events group by 1, 2 order by 1, 2;
```

### 2a. Kafka Connect restart

`make chaos-connect-restart` plays about 36 virtual hours (180 s at 720x) and 90 s into it runs
`docker restart lakehouse-kafka-connect-1`. It waits until the connector reports RUNNING and
`shop_slot` streams to a new walsender, lets the burst end and bronze catch up, and exits 1 as
inconclusive unless CDC events were produced both in the minute before the restart and after it.
Then it prints the events repeated with the same LSN, runs silver and compares live row counts
with Postgres (`reconcile`, which fails on any difference).

What happened: the worker got SIGTERM. On the way down it waited for the producer's acks and stored
the offset of the last acked record in `connect-offsets` (`Committing offsets for 1305 acknowledged
messages` on 2026-10-07); Debezium flushed that offset's last commit LSN to the replication slot,
which is behind the stored change LSN (offset `lsn=0/4F7298D0`, `lastCommitLsn=0/4F7221F8`, and
Postgres logged `Streaming transactions committing after 0/4F7221F8`). After the restart Postgres
re-sent the transactions committing after the slot position, and Debezium dropped everything up to
the stored offset (`identified as already processed`, then `switching off the filtering` at
`0/4F72B4D0`).
What monitoring shows: `make connector-status` is briefly unavailable, then RUNNING; the
Connect log shows `Committing offsets for N acknowledged messages` just before `Stopping down
connector`. Bronze stops growing for the restart and catches up afterwards.
Data at risk: none. The replayer kept writing; Postgres kept the WAL for the slot.
Recovery: automatic, about 32 s on 2026-10-07 (SIGTERM at 18:14:19, `Kafka Connect stopped` at
18:14:20.4, `Processing messages` at 18:14:50.7); about 40 s on 2026-09-26.
Why no loss or duplication: the final offset commit covered every record Kafka had acked, and on
resume Debezium filters whatever Postgres re-sends up to that offset, so nothing reached Kafka
twice. That holds while the stop fits Docker's 10 s stop timeout and the final commit fits
`offset.flush.timeout.ms` (5 s); otherwise expect repeats as in 2b. On 2026-10-07, with 1429 CDC
events produced in the minute before the restart and 1593 after it, 0 events repeated with the
same LSN, and live row counts of all seven silver tables matched Postgres; the 2026-09-26 run also
gave 0.

### 2b. Kafka Connect killed

`MODE=kill make chaos-connect-restart` does the same with `docker kill` and, 5 s later, `docker
start`. It also exits 1 as inconclusive when the kill repeated no event, which means it came
right after an offset flush.

What happened: no shutdown hook ran. Connect stores source offsets every 60 s
(`offset.flush.interval.ms`), so on restart it resumes from the last stored offset: Postgres
re-sends from the slot's last confirmed position, Debezium skips up to the stored offset, and every
event emitted after the stored offset is sent a second time with the same LSN.
What monitoring shows: the container is gone until someone starts it (a manual kill is not
restarted by the policy); `ConnectorNotRunning` (week 4). In bronze, repeated `(source_table,
key, lsn)`: the second copy arrives after the restart, the first can be up to 60 s older than the
kill.
Data at risk: none lost. Repeats only.
Recovery: `docker start lakehouse-kafka-connect-1`; the connector resumes by itself (on 2026-10-07
`Processing messages` at 18:20:30.0, 26 s after the start at 18:20:03.6).
Why no loss or duplication: nothing is lost because both positions are behind what reached
Kafka. The repeats land in bronze, which is at-least-once by contract, and silver's MERGE keeps
one row per key and ignores an equal LSN (ADR-021). On 2026-10-07 the kill came about 9 s after
the last offset flush (`Committing offsets for 728 acknowledged messages` at 18:19:49.2 in the
Connect log, walsender connection reset at 18:19:57.9 in the postgres-oltp log): 253 events
arrived twice (orders 173 on 152 keys, order_items 40, payments 39, reviews 1), their first copies
produced between 18:19:48.8 (not covered by that flush) and 18:19:57.4, and live row counts of all
seven silver tables still matched Postgres. On 2026-09-26 a kill about 2 s after the flush
repeated 11 events: the count follows the time since the last flush, up to 60 s of changes.
Verification SQL (the first copy can be in bronze up to 60 s before the kill, so the window starts
90 s before it; `make chaos-connect-restart` uses the run start instead, and on 2026-10-07 both
gave the same 253 events):

```
select source_table, count(distinct key) as keys_repeated, count(*) as events_repeated,
       sum(copies - 1) as extra_events
from (select source_table, key, lsn, count(*) as copies from bronze.cdc_events
      where ingest_ts >= timestamp '<kill time, UTC>' - interval '90' second and lsn is not null
      group by 1, 2, 3 having count(*) > 1)
group by 1;
```

### 3. Duplicate events from the source

`make chaos-duplicates` stops before it touches anything while another replayer answers on `:8000`
(the script exits 2, make prints `Error 2`; a failed check prints `Error 1`), waits until bronze has
caught up with Kafka so that the window holds only this run, prints the window start, and plays
about one virtual day (120 s at 720x) with `REPLAY_DUPLICATE_RATIO=0.1`. Once bronze has caught up
again it prints, per table, the UPDATEs, the no-op UPDATEs (`before = after`) with their share of
status UPDATEs, and the changes that arrived twice with the same LSN. It fails when orders got no
no-op UPDATE (the burst proved nothing) or when any change arrived twice with the same LSN (a
delivery repeat mixed in). Then it runs silver and fails unless silver holds, for every order whose
last event is a repeat, that repeat's LSN and status, and unless live row counts match Postgres.

What happened: the replayer picks `REPLAY_DUPLICATE_RATIO` of the orders (md5 of
`duplicate:<order_id>`) and runs every status UPDATE of a picked order twice, with the same values,
in one transaction. Postgres writes a second tuple version, so Debezium emits a second event with a
new LSN and `before` = `after`: a real change that changes nothing. On 2026-10-07 (UTC) the burst
moved the virtual clock from 2026-07-08 10:06 to 2026-07-09 10:03 (`make replay-status`), and bronze
took 2267 CDC events in the window (opened 2026-10-07 20:31:07 UTC).
What monitoring shows: the replayer counts the repeats (`replayer_events_total{kind="duplicate"}` on
its `/metrics`, `:8000` while the burst runs); nothing downstream reacts, by design.
`bronze_duplicate_ratio` by `(source_table, key, lsn)`, a planned `dq_checks` metric (W3-T05),
measures delivery repeats (chaos 2b) only: a source repeat is a new WAL record with a new LSN, so it
never counts there and shows instead as `op = 'u'` with `before = after`. Until the metric exists
the same check is `lsn_duplicates_since` in `scripts/chaos/lib.sh`.
Data at risk: none in silver. Bronze grows by the repeats (95 of the 2267 events in that run), and a
consumer that counts bronze events as business changes (status changes per day, say) counts each
repeat as one more: filter `before = after` out or read silver.
Recovery: nothing to recover; the next silver run absorbs the repeats. In that run the whole script
(burst, both catch-ups, silver, checks) took 3 min 11 s.
Why no loss or duplication: the repeat commits in the same transaction as its original, so a silver
batch usually holds both: `latest_per_key` keeps the repeat (higher LSN, same values) and MERGE
writes the row once. Only if a batch boundary splits the pair does MERGE rewrite the row with
identical values and a newer `_last_lsn` (one more row version in merge-on-read `silver.orders`, no
data change). Either way silver ends equal to Postgres. In that run orders had 1344 events and 1067
UPDATEs: 972 status changes and 95 no-op repeats, 9.8% of status UPDATEs, on 90 of the 926 orders
updated (85 with one repeat, 5 with two, one per status change); order_items (309 events), payments
(288) and reviews (326) had no UPDATE. 0 changes arrived twice with the same LSN, silver held the
repeat's LSN and status for all 90 orders whose last event is a repeat, and live row counts of all
seven silver tables matched Postgres (orders 93 860). The share is close to 10% because 90 picked of
926 is close to the expected 92.6: the ratio picks orders, not UPDATEs. The first run (burst on
2026-09-26, silver and `reconcile` ok on 2026-10-05 after the laptop slept) predates the asserts and
printed 18 no-op of 325 orders events, 5.5% of all orders events, a denominator the script no longer
uses; on status UPDATEs that is 18 of 120, 15.0%, on 16 of 114 orders: the fewer orders a burst
updates, the further the share can drift from the ratio.
Verification SQL (window start from the script's `window:` line; add an upper bound when later runs
followed, `ingest_ts < timestamp '2026-10-07 20:33:25'` for the numbers above, since bronze caught
up at 20:33:24):

```
select source_table, count(*) as events, count_if(op = 'u') as updates,
       count_if(op = 'u' and before = after) as no_op_updates,
       cast(100.0 * count_if(op = 'u' and before = after)
            / nullif(count_if(op = 'u' and before <> after), 0) as decimal(5, 1))
         as pct_of_status_updates,
       count(distinct key) filter (where op = 'u') as keys_updated,
       count(distinct key) filter (where op = 'u' and before = after) as keys_repeated
from bronze.cdc_events
where ingest_ts >= timestamp '<window start, UTC>'
group by 1 order by 1;
```

### 4. Late events

`make chaos-late` stops before it touches anything while another replayer answers on `:8000` (the
script exits 2), and before the burst when `shop-connector` or its task is not RUNNING or
`spark-bronze` is not healthy, naming the runbook (the script exits 1); `make` itself exits 2 on any
failure and shows the script's status as `Error 2` or `Error 1`. It prints the window start, plays
about one virtual day (120 s at 720x), waits until bronze has caught up and runs silver. It then
picks an order whose oldest change in the window (insert or update) has a newer one by LSN, and
fails unless silver already holds a higher `_last_lsn` for that order: at an equal one the row would
read the same afterwards and prove nothing, and with no row, a null or a lower one, MERGE would take
the re-sent change and the script would fail for the wrong reason. It reads that change back from
Kafka by partition and offset, produces it again with the same key, waits until bronze holds one
more copy of that LSN and runs silver again. It fails unless that run merged orders events (a run
that never read the record would also leave the row as it was) and unless silver's `order_status`
and `_last_lsn` for the order match before and after.

What happened: an older change of an order reached bronze after silver had applied a newer one.
Debezium does this after a kill (2b): everything sent since the last offset flush comes again with
the same LSN, behind newer changes that silver may already hold; a graceful restart (2a) re-sends
nothing. The script produces the record by hand, so the run does not depend on where a kill lands.
On 2026-10-07 (UTC) the burst moved the virtual clock from 2026-07-09 10:03 to 2026-07-10 10:00
(`make replay-status`), and bronze took 1180 events in the window (opened 2026-10-07 20:56:27 UTC),
the re-sent record included. Of the 350 orders the burst changed, 180 had more than one change, so
the pick is rarely short of candidates. It picked order `008819c6d5f6da6fa5cd9d50ca927cf4`: its
insert (`op = 'c'`, `created`, LSN 1401450968) and its update to `approved` (LSN 1401679552) came in
one bronze batch, and the first silver run left the row at `approved` with `_last_lsn` 1401679552.
The script re-sent the insert at 20:59:17 UTC.
What monitoring shows: nothing reacts, by design. Bronze takes one more record, and the second
silver run logs an orders merge (`batch N: <k> events merged into lake.silver.orders`) while the row
stays. The repeat check by `(source_table, key, lsn)` (`lsn_duplicates_since`, later the duplicate
ratio in `dq_checks`, W3-T05) counts the re-sent record as one delivery repeat, as in 2b. In that
run bronze took the record in at 20:59:20 UTC, and the second silver run logged
`batch 15: 1 events merged into lake.silver.orders in 2.4 s`. The count is the orders events the
silver batch read from bronze (before quarantine and before keeping one row per key), not rows MERGE
changed: the snapshot that run committed has `changed-partition-count` 0, no `added-records` and the
same `total-records` (98812) as the first run's. `lsn_duplicates_since` over the window reported
orders with 1 key repeated and 1 extra event.
Data at risk: none in silver. Bronze keeps the re-sent record for good, at a new offset with the
old LSN: a consumer that reads bronze in offset or ingest order rather than by LSN sees the order
go back to its older status.
Recovery: nothing to recover; the MERGE guard drops the event. In that run the whole script (burst,
catch-up, both silver runs, checks) took 3 min 12.6 s.
Why no loss or duplication: silver keeps one row per key, and MERGE updates a matched row only when
`t._last_lsn is null or s._last_lsn > t._last_lsn` (ADR-021; a null marks a row from an incremental
snapshot read). The re-sent change has a lower LSN than the row, so the row and its `_last_lsn`
stay; an equal LSN (a plain repeat, 2b) is skipped the same way. In that run bronze held LSN
1401450968 twice in partition 1, both `created` with the same key and `after`: offset 74825,
ingested at 20:57:40 UTC, and the re-sent copy at offset 74855, at 20:59:20 UTC. Silver read
`approved` with `_last_lsn` 1401679552 before and after, and the row's `_updated_at`, 20:59:03 UTC,
is from the first silver run, before the re-send.

Two meanings of "late". This scenario is late arrival: a change reaches the lake out of LSN order,
which here only a delivery repeat produces, and silver guards against it. `REPLAY_LATE_RATIO` with
`REPLAY_LATE_DELAY_SECONDS` is the other meaning: for that share of orders (md5 of
`late:<order_id>`) the replayer pushes the `delivered` update back by the delay in virtual time. The
change is late in event time for the windowed job (W5-T01, watermark), but it commits later, reaches
Kafka in order with a higher LSN, and gives silver nothing to guard against.
Verification SQL (order and stale LSN from the script's `re-sending` line):

```
select kafka_partition, kafka_offset, lsn,
       json_extract_scalar(after, '$.order_status') as status, ingest_ts
from bronze.cdc_events where lsn = <stale lsn> and source_table = 'orders';

select order_status, _last_lsn, _updated_at from silver.orders where order_id = '<order id>';

-- right after the script: the second silver run's snapshot changes no partition, adds no record
select committed_at, summary['changed-partition-count'] as changed_partitions,
       element_at(summary, 'added-records') as added_records,
       summary['total-records'] as total_records
from silver."orders$snapshots" order by committed_at desc limit 2;
```

## Runbooks

| Symptom | Runbook |
|---|---|
| Connector status FAILED | `docs/runbooks/connector-failed.md` |
| Retained WAL growing | `docs/runbooks/slot-wal-growth.md` (week 4) |
| Spark job no batch for 5 minutes | `docs/runbooks/spark-stalled.md` |
| Freshness above 15 minutes | `docs/runbooks/freshness.md` (week 4) |
| Disk full | `docs/runbooks/disk-full.md` (week 4) |
| Catalog cutover to Lakekeeper, or its rollback (owner only) | `docs/runbooks/catalog-cutover.md` |
| Reset everything | `make nuke` (asks for confirmation; deletes volumes, checkpoints, data) |

## Backup

Local laptop, nothing irreplaceable: the dataset is re-downloadable, the platform is
re-creatable from the repo. `make nuke && make up && make replay` is the restore procedure and
is itself a test that the repo is complete.
