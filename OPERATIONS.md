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

Both images in `core` (`lakehouse/replayer:dev`, `lakehouse/spark:dev`) are built by
`make up`. To work on one service without the replayer playing, start it by name:

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
| lakekeeper (profile `rest`) | 8181 |
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
make iceberg-demo    # snapshots, time travel, files before/after compaction
```

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

`trino` (profile `query`) reads the same JDBC catalog as Spark:
`docker/trino/etc/catalog/lake.properties` points at `iceberg_catalog` in `postgres-meta` and at
MinIO through the native S3 file system, which accepts the `s3a://` paths Spark writes. The
PostgreSQL driver ships in the image's Iceberg plugin. Heap is `TRINO_XMX`, passed to the
launcher as `-J-Xmx...`; the query memory limits in `config.properties` fit 2g as well.

Start it without the replayer and check it:

```
docker compose --env-file .env -f docker/compose.yaml --profile core --profile query up -d trino
make trino           # trino> select source_table, count(*) from bronze.cdc_events group by 1;
```

Healthy means the image's `health-check` saw `"starting": false` on `/v1/info`, about 40 s
after start. It does not prove the catalog works, because the JDBC connection opens on the
first query: run one. The config is bind-mounted, so after editing `docker/trino/etc` restart
the container (`docker compose ... restart trino`); `up -d` does not notice file changes.

Trino only reads what Spark committed: a bronze micro-batch shows up after its Iceberg commit,
not when Kafka receives the event.

## Failure scenarios

Each scenario is a `make chaos-<name>` target plus a written answer to five questions:
what happened, what monitoring shows, which data is at risk, how the system recovers,
why nothing is lost or duplicated (or where it can be). Filled in as scenarios are run.

| # | Scenario | Target | Status |
|---|---|---|---|
| 1 | Spark bronze killed mid-batch | `chaos-spark-kill` | planned (week 2) |
| 2 | Kafka Connect restart | `chaos-connect-restart` | planned (week 2) |
| 3 | Duplicate events from source | `chaos-duplicates` | planned (week 2) |
| 4 | Late events | `chaos-late` | planned (week 2) |
| 5 | PostgreSQL restart | `chaos-postgres-restart` | planned (week 4) |
| 6 | Connector down for 30 minutes (WAL growth) | `chaos-connect-pause` | planned (week 4) |
| 7 | Corrupted event in topic | `chaos-poison-event` | data half done (W2-T04), alert in week 4 |
| 8 | Kafka down | `chaos-kafka-down` | planned (week 4) |
| 9 (optional) | Airflow task failure (dbt test) | `chaos-break-dbt-test` | planned (week 3) |
| 10 (optional) | Partial processing (Trino memory) | `chaos-trino-memory` | planned (week 3) |

### Template

```
## <n>. <Scenario>

What happened:
What monitoring shows: (metric, alert, time to detect)
Data at risk:
Recovery: (automatic / manual, steps, time to recover)
Why no loss or duplication: (or where it is possible)
Verification SQL:
```

## Runbooks

| Symptom | Runbook |
|---|---|
| Connector status FAILED | `docs/runbooks/connector-failed.md` (week 2) |
| Retained WAL growing | `docs/runbooks/slot-wal-growth.md` (week 4) |
| Spark job no batch for 5 minutes | `docs/runbooks/spark-stalled.md` (week 2) |
| Freshness above 15 minutes | `docs/runbooks/freshness.md` (week 4) |
| Disk full | `docs/runbooks/disk-full.md` (week 4) |
| Reset everything | `make nuke` (asks for confirmation; deletes volumes, checkpoints, data) |

## Backup

Local laptop, nothing irreplaceable: the dataset is re-downloadable, the platform is
re-creatable from the repo. `make nuke && make up && make replay` is the restore procedure and
is itself a test that the repo is complete.
