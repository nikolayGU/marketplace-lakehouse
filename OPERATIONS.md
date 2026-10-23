# Operations

## Profiles and what runs together

| Situation | Command | RAM (limits) |
|---|---|---|
| Daily work on ingestion | `make start` | ~11 GB limits, ~7 GB real |
| Working on dbt / Airflow | `make start && make up PROFILE=orchestrate` (Trino `Xmx` drops to 2g via `TRINO_XMX`); stop `orchestrate` when not working on batch | ~13 GB limits, ~9 GB real |
| Full pipeline with monitoring | `TRINO_XMX=2g make start && make up PROFILE=orchestrate,obs` | 13.6 GB limits, 5.2 GB real at rest (2026-10-19) |
| Demo dashboard (optional Superset) | `make down PROFILE=orchestrate && make up PROFILE=bi` | swap orchestrate for bi |
| Stateful job (`orders_per_minute`) | `make up PROFILE=stateful` on top of `core` | +1.75 GB limit; 495 MiB at rest, 842 MiB while reading 24 h of the topic (2026-10-23) |
| Debugging Kafka visually | `make up PROFILE=tools` for 15 minutes, then `make down PROFILE=tools` | +0.4 GB |

Never start `orchestrate` and `bi` together. Never start all profiles.

`core` includes Lakekeeper, the Iceberg catalog, since the cutover on 2026-10-08; there is no
`rest` profile any more. `make start` brings up `core` without `oltp-replayer`, plus `trino`: it
names `spark-bronze kafka-connect trino`, and their `depends_on` pull in the rest of `core`
(ADR-016). `make up` refuses any `PROFILE` that contains `core`, because that would start the
replayer container, which plays at `REPLAY_SPEED` (2880, one virtual day per 30 s) until stopped.
The rest of the history is a budget for the remaining weeks (D2 in
`docs/planning/07-w3-spec.md`), so traffic comes in bursts from the host:
`make replay-burst SECONDS=<n>` plays `n` real seconds at 720x and stops. `make replay-live`
starts the container on purpose, for a continuous demo; stop it with
`docker compose --env-file .env -f docker/compose.yaml stop oltp-replayer`.

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
| spark-orders-per-minute UI | 4043 |
| trino | 8080 |
| airflow api-server | 8090 |
| prometheus | 9090 |
| grafana | 3000 |
| superset | 8088 |
| kafka-ui | 8085 |

## Daily commands

First run, from a fresh clone:

```
make secrets         # .env with generated passwords; REPLAY_DATA=sample skips the download
make data            # download Olist into data/raw (not needed with REPLAY_DATA=sample)
make bootstrap       # start, migrate, connector, replay-load, verify, protect; safe to re-run
```

`make bootstrap` runs, in order: `make start`; a wait of up to 5 minutes for `spark-bronze`,
`kafka-connect` and `trino` to turn healthy; `make migrate`; `connect/register.sh`;
`make replay-load` unless a replay state exists (`replay state exists, load skipped`);
`make verify`; `scripts/lakekeeper/protect.sh`. None of the steps deletes anything. From a fresh
clone on the sample it took 4 minutes with the images built, a re-run 75 seconds; the first build
of the Spark image adds about 80 seconds with its base image already pulled (2026-10-17).

`make verify` refuses (exit 2) while `airflow-scheduler` runs or a replayer answers on port 8000.
Otherwise it waits up to `VERIFY_WAIT` seconds (default 900) for bronze to catch up with Kafka,
runs one silver merge, and checks that every Kafka offset is in bronze exactly once, that live
silver rows equal Postgres for all seven tables (row count, set of primary keys, sum of every
decimal column; `reconcile`), and that all seven tables reached bronze. The last line is
`verify ok` or `verify failed: <reason>`.

```
make replay-burst SECONDS=60   # about 12 virtual hours at 720x; prints virtual_now before and after
make replay-start              # plays until ctrl-c at REPLAY_SPEED (1 day / 30 s): spends the budget
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

`spark_streaming_kafka_lag{topic,partition}` (21 rows) is messages the broker has past the last
batch; it is 0 at rest and rises only when a backlog is bigger than one trigger
(`BRONZE_MAX_OFFSETS_PER_TRIGGER`). Rows appear after the first batch following a start, so right
after a restart the metric is empty until data arrives (ADR-013).

Check it:

```
curl -s 127.0.0.1:4041/metrics | grep ^spark_streaming   # input rows, last batch, duration, lag
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
`lakehouse/spark:dev` with `pull_policy: never`, so build that image first (`make start` does);
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

## Airflow

Profile `orchestrate`: `airflow-api-server` (UI and REST API on `127.0.0.1:8090`, no login, every
visitor is admin: D12), `airflow-scheduler` (LocalExecutor: tasks run as processes inside this
container) and `airflow-dag-processor`. One image, `lakehouse/airflow:dev` from
`airflow/Dockerfile`: Airflow 3.3.2 on Python 3.12, dbt in `/opt/dbt-venv`. Config is
`docker/airflow/airflow.env`, values from `.env`. Metadata lives in the `airflow` database of
`postgres-meta`; the same instance holds `lakekeeper` and `iceberg_catalog`, which nothing here
touches.

Before the first start, once per `.env`, from the repo root (each command prints nothing):

```
sed -i "s|^AIRFLOW_FERNET_KEY=.*|AIRFLOW_FERNET_KEY=$(python3 -c 'import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())')|" .env
grep -q '^AIRFLOW_API_SECRET_KEY=' .env || printf 'AIRFLOW_API_SECRET_KEY=%s\n' "$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')" >> .env
grep -q '^DOCKER_GID=' .env || printf 'DOCKER_GID=%s\n' "$(stat -c %g /var/run/docker.sock)" >> .env
```

- Fernet key: a `.env` from `make secrets` before 2026-10-09 holds a 32-character
  `AIRFLOW_FERNET_KEY`, and Airflow accepts only urlsafe base64 of 32 bytes (44 characters).
  Replace it only before Airflow first starts: once Airflow has stored connections or variables,
  a new key makes them unreadable.
- `AIRFLOW_API_SECRET_KEY` signs the api-server's requests for task logs, which the scheduler
  container serves. Without it each process makes up its own, and the UI shows no task log.
- `DOCKER_GID` is the group of `/var/run/docker.sock`; the scheduler joins it (`group_add`) to
  start spark-silver through DockerOperator. Without it: `permission denied` on the socket.

Start, with Trino on a 2 GB heap (RAM, `docs/planning/00-mini-architecture-review.md` §6):

```
TRINO_XMX=2g make start          # recreates trino with -J-Xmx2g
make up PROFILE=orchestrate      # builds lakehouse/airflow:dev on the first run
make airflow-init                # pool lake_writers, 1 slot; safe to re-run
```

While `orchestrate` runs, every `make start` needs `TRINO_XMX=2g` in front: compose takes it from
the shell over `.env`, and without it recreates Trino with the 2500m of `.env`. Stop Airflow with
`make down PROFILE=orchestrate`; the next plain `make start` puts Trino back on 2500m.

Check it:

```
docker compose --env-file .env -f docker/compose.yaml exec airflow-scheduler airflow pools list
docker compose --env-file .env -f docker/compose.yaml exec airflow-scheduler airflow dags list-import-errors
docker compose --env-file .env -f docker/compose.yaml exec airflow-scheduler \
  python -c "import docker; print(docker.from_env().ping())"   # True
```

A new DAG starts paused (`AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION`): unpause it in the UI or
with `airflow dags unpause <dag_id>` in the scheduler container. A trigger of a paused DAG stays
queued. A new DAG file shows up within a minute (`AIRFLOW__DAG_PROCESSOR__REFRESH_INTERVAL=60`).

Measured on 2026-10-18 (`docker stats`, idle, Trino at 2g): airflow-scheduler 386.5 MiB of 600 MiB, airflow-api-server 353.9 MiB of 700 MiB, airflow-dag-processor 202 MiB of 500 MiB, trino 756.3 MiB of 3.5 GiB. Under `dbt build` the scheduler peaked at 579 MiB of the first 600 MiB limit; it is 900 MiB since (D19).

DAGs live in `airflow/dags/`; their shared code is `airflow/dags/lakehouse/`, which
`.airflowignore` keeps out of DAG parsing.

| DAG | Schedule | Does |
|---|---|---|
| `silver_upsert` | every 5 min, `max_active_runs=1`, 1 retry | `bronze_has_new_snapshot` skips the run when bronze has no snapshot silver has not merged; `merge` starts spark-silver (DockerOperator, pool `lake_writers`) and publishes the Asset `lake.silver`; `remember_snapshot` stores the merged snapshot id in the Variable `silver_upsert_last_bronze_snapshot` |
| `dbt_build` | Asset `lake.silver` | `dbt build` of `lake.gold` from `/opt/dbt-venv`, no retries; a manual run takes dbt vars from its conf, `{"dbt_vars": "{...}"}` |
| `dq_checks` | every 15 min | fails on a primary key twice in silver, or on silver differing from Postgres at rest; logs `dq <name>=<value>` lines: delivery repeats and source no-ops of the last hour, new quarantine rows, freshness of each silver table, `dbt source freshness`; sends the same values to Prometheus (see "Observability", `lakehouse_*`), except the quarantine count |
| `iceberg_maintenance` | daily | `optimize` of each silver table through Trino, in pool `lake_writers`; bronze is not touched (D11) |

One silver writer. While `silver_upsert` is unpaused, `make silver` and `make verify` must not
run: two processes on one checkpoint (`make verify` refuses while the scheduler runs). For a
manual merge: `airflow dags pause silver_upsert` in the scheduler container, wait until its
running `merge` ends, `make silver`, then `airflow dags unpause silver_upsert`. The first run from
Airflow continues from the checkpoint of the last `make silver`.

`reconcile_values` compares by value what `reconcile` compares by count, key set and sums: a row
fingerprint is the md5 of the canonical text of every column (null as `\N`, decimals at the contract
scale, timestamps as epoch milliseconds), built the same in Postgres and Trino; a table is the row
count plus the md5 of its sorted `key=fingerprint` pairs. Pairs: each of the seven source tables
against silver (live rows), and `fct_orders`, `fct_order_items` (soft-deleted rows included, with
their flag), `dim_products`, `dim_sellers` against silver; `dim_customers` only by row count (its
grain is `customer_unique_id`). Only at rest (`checks.at_rest`; the silver-gold pairs also wait until
`fct_orders.updated_at` has caught up with silver); otherwise the task is green, prints `in flight, no
verdict` and sets `lakehouse_dq_reconcile_in_flight` to 1. Red means a value differs at rest: the log
lists the first 20 keys of each kind of difference and, for a key silver lacks, why (`quarantined`,
`merge_pending`, `unknown`). Measured 2026-10-23: 7 source-silver and 5 silver-gold verdicts in 7 s
inside the task (25 s through the Trino CLI), 0 differing, 19 `reconcile_rows` series; right after a
20 s burst the task said `in flight`. The negative path (a changed value at an equal count, a missing
key and its reason) is covered by unit tests, since a live difference would have to be written to
the source, and from there it goes to silver.

A red `dq_checks` means one of two things. `silver_keys_unique`: silver holds a primary key
twice, which MERGE must never produce; read the last `silver_upsert` log and the quarantine.
`silver_matches_postgres`: counts differ although bronze has been quiet for 5 minutes and silver
merged its latest snapshot, so a change never reached silver; `make verify` (with the scheduler
stopped) shows the offsets and the counts. Differences with `at_rest=False` are normal during a
replay burst. A stale `dbt source freshness` (exit code 1) is logged, not failed: no traffic is not
a broken pipeline.

Host sleep pauses the Docker VM. A task in flight at that moment fails on wake: Trino has
abandoned its query (`ABANDONED_QUERY`), the scheduler fails task instances without a heartbeat,
and the task's API token has expired (`Invalid auth token`). Before reading a red run as a
pipeline failure, look for `Heartbeat recovered after <n> seconds` just before it in
`docker logs lakehouse-airflow-scheduler-1`. Keep Windows sleep off while the stack runs
(`powercfg /change standby-timeout-ac 0`, the same for `hibernate-timeout-ac`).

## Observability

`make up PROFILE=obs` on top of `core` (and usually `orchestrate`); it starts nothing from
`core`. Prometheus on http://127.0.0.1:9090, Grafana on http://127.0.0.1:3000 (`admin`, password
`GRAFANA_ADMIN_PASSWORD` from `.env`). Exporters have no host ports; Prometheus reaches them on
the `lake` network.

| Job | Target | What it gives |
|---|---|---|
| `prometheus` | `localhost:9090` | Prometheus itself, `prometheus_tsdb_head_series` |
| `kafka-connect` | `kafka-connect:9404` | JMX agent in the Connect JVM (`docker/connect/`): `kafka_connect_connector_status`, `kafka_connect_connector_task_status{connector,task,status}` (1 for the current status), `debezium_postgres_streaming_*` (`Connected`, `MilliSecondsSinceLastEvent`, `MilliSecondsBehindSource`, `TotalNumberOfEventsSeen`; -1 and 0 until the first event after a start), `jvm_*` |
| `spark-bronze` | `spark-bronze:4041` | bronze listener: rows, batch duration, last batch time, `spark_streaming_kafka_lag{query,topic,partition}` (ADR-013) |
| `kafka-exporter` | `kafka-exporter:9308` | brokers, topic and partition offsets (not Spark's lag: ADR-013) |
| `postgres-exporter` | `postgres-exporter:9187` | `pg_*`, plus `lakehouse_slot_retained_bytes` and `lakehouse_slot_active` per slot from `observability/postgres-exporter/queries.yaml` |
| `statsd-exporter` | `statsd-exporter:9102` | StatsD of Airflow (`AIRFLOW__METRICS__STATSD_*` in `docker/airflow/airflow.env`): `airflow_dagrun_success_seconds{dag_id}`, `airflow_dagrun_failed_seconds{dag_id}`, `airflow_ti_finish_total{dag_id,task_id,state}`, `airflow_task_duration_seconds{dag_id,task_id}` by `observability/statsd/mapping.yml`; unmapped names pass through with underscores. `dq_checks` gauges (`lakehouse_*`, below) |
| `container-exporter` | `container-exporter:9105` | `docker_container_*{name,service}`: memory as `docker stats`, limit, CPU, start time, restarts, OOM kill, health (ADR-023) |

`dq_checks` sends DogStatsD gauges over UDP to `statsd-exporter:9125` (`lakehouse/metrics.py`,
`STATSD_HOST` and `STATSD_PORT` default to that); tags become labels, and the mapping gives every
`lakehouse.*` series a TTL of 45 minutes (three cadences), so a series disappears when `dq_checks`
stops instead of showing its last value for ever.

| Series | Labels | Meaning |
|---|---|---|
| `lakehouse_table_freshness_seconds` | `layer` (`silver`, `bronze`), `table` | seconds since the newest `_updated_at` (silver, 7 tables) or `ingest_ts` (bronze, per `source_table`); grows for hours between replay bursts, which is "no traffic", not a fault |
| `lakehouse_silver_lag_seconds` | none | seconds the oldest bronze snapshot silver has not merged has waited; 0 at rest. It is not freshness. Not sent while the Variable `silver_upsert_last_bronze_snapshot` is missing or names a snapshot bronze no longer has |
| `lakehouse_dq_silver_duplicate_keys` | `table` | primary keys twice in a silver table (8 incl. quarantine) |
| `lakehouse_dq_reconcile_tables_differing` | `at_rest` | tables whose live row count differs from Postgres |
| `lakehouse_dq_lsn_repeats_last_hour`, `lakehouse_dq_noop_updates_last_hour` | none | delivery repeats and no-op updates of the last hour |
| `lakehouse_dq_dbt_source_freshness_exit_code` | none | 0, or 1 for a stale source |
| `lakehouse_dq_last_run_timestamp_seconds` | none | Unix time of the last `report` task |

`reconcile_values` (W5-T04) adds the series of the value reconciliation:

| Series | Labels | Meaning |
|---|---|---|
| `lakehouse_dq_reconcile_rows` | `layer` (`source`, `silver`, `gold`), `table` | rows compared (19 series: 7 + 7 + 5) |
| `lakehouse_dq_reconcile_values_differing` | `pair` (`source_silver`, `silver_gold`), `table` | keys on both sides whose row fingerprints differ |
| `lakehouse_dq_reconcile_keys_missing` | `pair`, `table`, `side` | keys the other side lacks; `side="right"` is a key the source (or silver) has and silver (or gold) lacks |
| `lakehouse_dq_reconcile_in_flight` | none | 1 while work is in flight and no verdict was made |
| `lakehouse_dq_reconcile_verdict_timestamp_seconds` | none | Unix time of the last verdict |

Values come at the cadence of `dq_checks` (15 minutes), so an alert on them can lag by that long.
A negative value is never sent (StatsD would read it as a decrement). The quarantine count stays
in the log: its metric and alert are the owner's Modify gate (W4-D8). UDP gives no receipt: the
check is the series in Prometheus. With `obs` down the tasks print `statsd: could not send` and
stay green (checked 2026-10-23).

Check it:

```bash
curl -s 127.0.0.1:9090/api/v1/targets | python3 -c 'import json,sys; t=json.load(sys.stdin)["data"]["activeTargets"]; print(sorted((x["labels"]["job"], x["health"]) for x in t))'
curl -s 127.0.0.1:9090/api/v1/query --data-urlencode 'query=lakehouse_slot_retained_bytes'
curl -s 127.0.0.1:3000/api/health
```

- Their `depends_on` on `core` services is `required: false`, so `make up PROFILE=obs` stays a
  valid project without `core`. The healthchecks of `kafka-exporter` and `postgres-exporter` look
  for `kafka_brokers` above 0 and `pg_up 1`, since `/metrics` answers 200 with the broker or the
  database down; without `core` both should stay unhealthy (not run live: `core` was up).
- `observability/prometheus` is mounted read-only as a directory. After editing rules or scrape
  configs: `docker kill -s HUP lakehouse-prometheus-1`.
- Kafka Connect: `/kafka/config` is an anonymous volume of the Debezium image, and a recreated
  container keeps the old one. A file the image layer adds there is hidden, so `metrics.yaml` is
  bind-mounted; without it the agent stops the JVM and Connect restarts in a loop (2026-10-19,
  ten minutes of no CDC).
- Airflow sends StatsD over UDP: without `obs` the packets are lost and Airflow keeps running
  (scheduler healthy in 66 s with `obs` down, no `gaierror`, 2026-10-19).
- Grafana provisioning is mounted whole over the image's directory, so `provisioning/alerting`
  and `provisioning/plugins` exist in the repo empty: without them Grafana logs errors.
- Every file compose mounts must exist before the first start: a missing file becomes a
  root-owned directory on the host. `find observability -type d -name '*.y*ml'` must print nothing.
- `container-exporter` holds the Docker socket (root on the host in effect) and only sends GET.
  It joins the socket's group `DOCKER_GID` from `.env`, as the scheduler does; a wrong group
  shows as `up == 0` with a permission error in its log. An empty container list fails the
  scrape too: it means `COMPOSE_PROJECT_NAME` does not match the stack.
  `docker_container_restart_count` counts restarts by the restart policy only; `docker restart`
  shows as a new `docker_container_start_time_seconds`.
### Alerts

Six alerts in `observability/prometheus/alerts.yml`, tested by `make alerts-test` (promtool, ten
cases, failure cases first) and each shown firing in its own scenario. No Alertmanager (ADR-023):
read them in the Prometheus UI (`/alerts`), `curl 127.0.0.1:9090/api/v1/alerts` or the "Firing
alerts" panel. After editing the file: `docker kill -s HUP lakehouse-prometheus-1`.

| Alert | Expression | `for` | Why this threshold | Shown in | Time to fire (2026-10-23) |
|---|---|---|---|---|---|
| `ConnectorNotRunning` | `absent(kafka_connect_connector_task_status{connector="shop-connector",status="running"} == 1)` | 1m | a task that is not `running` is no CDC; `absent` also covers a Connect that is down | scenario 6 | 95 s after `PUT /stop` |
| `SlotWalRetainedHigh` | slot over 64 MiB and inactive, or over 512 MiB | 5m | an idle healthy slot holds about 25 MB; an inactive one grows without bound (`max_slot_wal_keep_size = -1`) | scenario 6 | 326 s after the stop (80 MB held) |
| `SparkNoBatch5m` | `time() - last_batch_timestamp > 300`, and `absent(...)` for the dead driver | 0 / 5m | idle events keep the timestamp moving, so only a stuck or dead query trips it | stop `spark-bronze` | 315 s after the stop (`cause="gone"`) |
| `FreshnessAbove15m` | `lakehouse_silver_lag_seconds > 900` | 0 | age of the oldest bronze snapshot silver has not merged; table freshness grows between bursts and does not alert | pause `silver_upsert`, burst | 1561 s after bronze caught up (900 s plus up to 15 min until the next `dq_checks`) |
| `AirflowDagFailed` | `increase(airflow_dagrun_failed_seconds_count[30m]) > 0` or a series new within 30 minutes | 0 | the second half catches the first failure after statsd-exporter started | scenario 9 | 17 s after the red run ended |
| `ContainerRestarting` | `changes(docker_container_start_time_seconds{...}[15m]) > 0`, one-shot containers excluded | 0 | `docker restart` moves the start time; `RestartCount` follows only the restart policy | scenarios 5 and 8 | 15 s after the restart |

Limits worth knowing: `absent()` alerts also burn when the source is off (obs up, core down); a
crash-looping Spark driver (Kafka stopped, 15 restarts) does not trip `SparkNoBatch5m`, the restart
series and `ContainerRestarting` show it; `dq_checks` itself goes red with "differs at rest" when the
source writes and nothing arrives (Kafka or connector down), which raises `AirflowDagFailed`. The
`lakehouse_*` gauges arrive every 15 minutes, so alerts on them lag by that much.

### Dashboards

Grafana provisions `observability/grafana/dashboards/*.json` (classic JSON, edits in the UI are
not saved: change the file). `uv run python scripts/obs/check_dashboards.py` runs every panel query
against Prometheus and lists the empty ones, since a typo and a missing metric both read "No data".

| Dashboard / panel | Query (metric) | Source |
|---|---|---|
| Pipeline health: bronze Kafka lag | `spark_streaming_kafka_lag` | bronze listener (ADR-013) |
| rows per second, batch duration | `spark_streaming_input_rows_total`, `spark_streaming_batch_duration_seconds` | bronze listener |
| seconds since the last bronze batch | `time() - spark_streaming_last_batch_timestamp` | bronze listener; alert `SparkNoBatch5m` |
| connector task status, behind source | `kafka_connect_connector_task_status`, `debezium_postgres_streaming_MilliSecondsBehindSource` | JMX agent in Connect; alert `ConnectorNotRunning` |
| WAL retained, slot active | `lakehouse_slot_retained_bytes`, `lakehouse_slot_active` | custom query of postgres-exporter; alert `SlotWalRetainedHigh` |
| silver lag, table freshness | `lakehouse_silver_lag_seconds`, `lakehouse_table_freshness_seconds` | `dq_checks` via StatsD; alert `FreshnessAbove15m` |
| DQ | `lakehouse_dq_*` | `dq_checks` via StatsD |
| task durations, failed tasks and runs | `airflow_task_duration_seconds`, `airflow_ti_finish_total`, `airflow_dagrun_failed_seconds_count` | Airflow StatsD; alert `AirflowDagFailed` |
| firing alerts | `ALERTS{alertstate="firing"}` | Prometheus |
| Infra: memory, CPU, start time, restarts, OOM, health | `docker_container_*` | container-exporter (ADR-023); alert `ContainerRestarting` |

Freshness panels step every 15 minutes (the cadence of `dq_checks`); that is not a bug.

- At rest on 2026-10-19 with `core+query+orchestrate+obs`: 2921 head series; Prometheus 142 MiB
  of 300 MiB, Grafana 123 of 256, container-exporter 29 of 64, other exporters 8-10 of 64.

## Stateful job

`spark-orders-per-minute` (profile `stateful`, ADR-024): distinct new orders per minute of
`order_purchase_timestamp`, watermark 5 minutes, from Kafka `oltp.shop.orders` into
`lake.silver.orders_per_minute` (Trino: `silver.orders_per_minute`).

- Start: `make up PROFILE=stateful` (the image is built with `core`; nothing from `core` restarts).
  Stop: `make down PROFILE=stateful`. UI `127.0.0.1:4043`, metrics `:4041` inside the network
  (Prometheus job `spark-orders-per-minute`).
- It reads from the beginning of the topic on the first start, so the table fills up to the data
  Kafka still holds (24 h of retention).
- Metrics (the query label is `orders_per_minute`): `spark_streaming_state_rows` (windows held),
  `spark_streaming_watermark_timestamp_seconds` (event time of the data: a date in the replay's
  past, not the clock), `spark_streaming_late_rows_dropped_total`, plus the batch metrics of
  bronze. Read `late_rows_dropped` as: rows behind the watermark in that batch, counted once the
  batch after the one that moved the watermark has run.
- Reset (the checkpoint is on the blast-radius list, so with the owner's "ok"): the table is derived
  and a MERGE never lowers a count, so deleting `checkpoints/orders_per_minute` and starting again
  recomputes from Kafka without undoing anything; windows older than Kafka's retention keep their
  old counts. Needed when the service was down longer than 24 h (`failOnDataLoss`).
- After a start or restart the state and watermark series are absent until the first batch with
  data (an idle trigger carries no state), so `check_dashboards.py` lists those two panels as empty
  on a quiet system.
- Live check (2026-10-23, 60 s burst, 12 virtual hours): per minute, `silver.orders_per_minute`
  against `count(*)` of `silver.orders` from the burst's start: 164 windows, 0 differing, 194
  orders each side; `spark_streaming_late_rows_dropped_total` 0, so no partition skew beat the
  watermark at 720x. After `restart` the job resumed from its checkpoint and the same comparison
  gave 0 again. `make watermark-live`: the oldest order of the last 12 hours was dropped once
  (`dropped 0 -> 1`), the newest was counted once (`1 -> 1`), the sum of orders stayed 819.
  Memory of all containers with the profile: 8.2 GiB (below the 10 GiB stop rule, W4-D5).
- Demos: `make watermark-demo` (lab topic, three `availableNow` runs, own table
  `demo.orders_per_minute`, needs only the `core` stack) and `make watermark-live` (needs the
  service; re-sends the oldest real order, which the watermark must drop once, and the newest, which
  it must count once; `lsn_repeats_last_hour` grows by 2, silver absorbs both by LSN).

## Maintenance

Policy and reasons: ADR-025. `iceberg_maintenance` (daily 03:30) and `iceberg_orphans` (weekly,
Sunday 04:00) are created paused and unpaused one rung at a time (the ladder in ADR-025); do not
unpause them to "see what happens": `expire_snapshots` and `remove_orphan_files` delete files, and the
lake has no backup. Rebuild the Spark image first (`docker compose ... --profile core build
spark-bronze`): the DAG files are live as soon as they are saved, the job `maintenance.py` only after
the image.

By hand, from the repo root (nothing runs by itself; `--entrypoint` skips `run-job.sh` only for
probes, the job form is):

```
C="docker compose --env-file .env -f docker/compose.yaml --profile core run --rm --no-deps spark-silver"
$C maintenance orphans silver.sellers                       # dry run: counts, does not delete
$C maintenance expire --days 7 silver.sellers               # deletes snapshots older than a week
$C maintenance rewrite-position-deletes silver.orders
$C maintenance rewrite-data --before-today lake.bronze.cdc_events
```

Each call prints one JSON line (`dry_run`, the table, candidates or removed files). A refusal
(`expire` on bronze, a term under 7 days on silver or gold, `orphans` on bronze without
`--location-suffix metadata`) exits 1 before a Spark session starts. To read a result: for
`expire`, compare `select count(*) from silver.<t>."$snapshots"` before and after, and that
`select count(*)` of the table did not move; for `orphans`, the dry run lists what the real run
would remove.

## CI

`.github/workflows/ci.yml`, on every pull request and push to main; a newer push to the same
branch cancels the older pull request run.

| Job | What it does |
|---|---|
| `lint-and-test` | `uv sync --locked`, ruff, mypy, yamllint, sqlfluff, `dbt parse`, `pytest tests/unit`, compose config, gitleaks |
| `hadolint` | one run per Dockerfile (matrix, a test compares it with `find`), fails on warning and above; accepted findings sit in the Dockerfile as `# hadolint ignore=` with the reason |
| `spark-tests` | builds `lakehouse/spark:ci` (layer cache `type=gha`, scope `spark`) and runs `make test-spark SPARK_IMAGE=lakehouse/spark:ci`; `-p no:skipping` makes a skip a failure |
| `airflow-image` | builds `lakehouse/airflow:ci` (scope `airflow`), imports Airflow, trino, psycopg and pydantic-settings, runs `dbt --version` in its venv |

`.github/workflows/smoke.yml` (on demand and Mondays 03:00 UTC, 45 minutes at most) walks the path
from a clean clone on the committed sample: `make secrets` with `REPLAY_DATA=sample`, `make
bootstrap`, a 60 s `make replay-burst`, `make verify`, a second `make bootstrap` (must say
`replay state exists, load skipped` and end `verify ok`). It builds the Spark and Connect images from
scratch, so it is cold every time. Run it: `gh workflow run smoke.yml --ref main`, then
`gh run watch <id> --exit-status`. On failure it uploads `smoke-logs` (container state and the last
200 log lines of every service). Not run on GitHub yet; the runner size and the free disk it prints
in its first steps belong here after the first run.

Repeat locally: `make test-spark` (132 passed, no skipped, 2026-10-23, ~80 s with a warm image).
`make test-spark` pins `pytest` and `jsonschema` to the versions in `uv.lock`
(`tests/unit/test_makefile.py` compares them). Not run on GitHub yet: first push, then
`gh run list --workflow ci`.

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
| 5 | PostgreSQL restart | `chaos-postgres-restart` | done 2026-10-23 |
| 6 | Connector down for 30 minutes (WAL growth) | `chaos-connect-pause` | done 2026-10-23 |
| 7 | Corrupted event in topic | `chaos-poison-event` | done 2026-10-23 (re-run through the Airflow merge); alert is the owner's Modify gate |
| 8 | Kafka down | `chaos-kafka-down` | done 2026-10-23 |
| 9 | Airflow task failure (dbt test) | `chaos-break-dbt-test` | done 2026-10-18 |
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
with the driver, so since W4 Prometheus scrapes it, the scrape
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
restarted by the policy). A kill shorter than the `for: 1m` of `ConnectorNotRunning` does not trip
it; `ContainerRestarting` fires for `kafka-connect` (the start time moves, checked 2026-10-23
for Postgres and Kafka in scenarios 5 and 8). In bronze, repeated `(source_table,
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

### 5. PostgreSQL restart

```
make chaos-postgres-restart   # core + obs up, no replay running
```

What happened (2026-10-23): `docker compose restart postgres-oltp` with the connector streaming
and bronze caught up; the slot `shop_slot` stood at `0/5A7E0660`, walsender pid 16292. Postgres was
`healthy` 13 s later and the connector streamed from a new walsender 13 s later too, by itself:
the Debezium task retried and was never `FAILED`. The script then played a 30 s replay burst
(after the restart: the host replayer writes to Postgres and would die with it); bronze caught up 28 s
after the burst.
What monitoring shows: `ContainerRestarting` for `postgres-oltp` firing 15 s after the restart
(16:53:20 restart, 16:53:35 firing). The connector panel stays green; the restart is too short for
`ConnectorNotRunning` (`for: 1m`), and nothing else notices. If the task does not come back, the
script stops with the name of `docs/runbooks/connector-failed.md` and does not restart the task
itself, so the run shows the system's own answer.
Data at risk: none. The slot and its WAL survive a restart of Postgres, and the connector resumes
from `confirmed_flush_lsn`; events it had sent but not yet confirmed can be sent again with the same
LSN, and silver absorbs them (scenario 2b).
Recovery: automatic, 13 s.
Why no loss or duplication: the slot is durable in Postgres, offsets are in `connect-offsets`, bronze
keeps one row per Kafka offset (`bronze_offsets_ok`), silver merges by key and LSN.
Verification: the script ends with `bronze_offsets_ok`, `merge_silver` (the `silver_upsert` DAG while
the scheduler runs) and `reconcile`: 7 of 7 tables ok.

### 6. Connector stopped for 30 minutes (WAL growth)

```
make chaos-connect-pause   # HOLD=1800 s by default; core + obs up, no replay running
```

What happened (2026-10-23): `PUT /connectors/shop-connector/stop` at 18:21:55 (not `pause`: a paused
task keeps its walsender and the slot stays active, W4-D11). The slot turned inactive 4 s later; a
30 s burst and padding took it from 11 MB to 80.9 MB; the connector was resumed 1812 s after the
stop, bronze had caught up 19 s later, `reconcile` 7 of 7, every offset once. A short rerun (hold
60 s, 19:14) did the same with 83.9 MB held; after the resume and a 15 s burst the connector had
confirmed everything (28 kB unconfirmed) and `restart_lsn` retained 3.9 MB.
What monitoring shows: `ConnectorNotRunning` 95 s after the stop (75 s in the rerun) and
`SlotWalRetainedHigh` 326 s after it (`for: 5m` plus the scrape; both runs). `dq_checks` also goes
red with "differs at rest": bronze is quiet because nothing arrives, while the source writes.
Data at risk: none while the slot lives; Postgres keeps every WAL file it has not confirmed
(`max_slot_wal_keep_size = -1`), so the disk of the VM is the limit, and nothing but this alert
watches it (runbook `docs/runbooks/slot-wal-growth.md`). Replay alone writes ~1.1 MB of WAL per
virtual hour; the 64 MiB threshold is reached in about 2.5 virtual days of events.
Recovery: automatic once the connector runs (`resume`), minutes. A script killed mid-hold resumes
the connector from a trap: the STOPPED state survives a Connect restart.
Why no loss or duplication: the slot, `connect-offsets` and the Kafka offsets in bronze; checked
by `bronze_offsets_ok` and `reconcile`.
How the WAL is added, and what not to do: replay is too slow, so the script adds a transaction
and `pg_switch_wal()` per round (one 16 MB segment each; Debezium forwards nothing of it). The first
run used `pg_logical_emit_message` with 4 MB records instead, and that stopped CDC: Debezium decodes
logical messages and publishes them to `oltp.message`, a topic that does not exist (topic
auto-creation is off), and then hit the 1 MB `max.request.size` of the Connect producer. CDC stood
from about 18:52 to 19:00 with no loss; fixed by creating `oltp.message` (max message 8 MB,
retention 1 hour) and `CONNECT_PRODUCER_MAX_REQUEST_SIZE=8388608` in `docker/compose.yaml`, and the
connector drained 66 MB in seconds. `pg_replication_slot_advance` would have skipped the records and
was not used. The topic and the setting stay as a guard; do not use logical messages for padding.

### 7. Corrupted event in topic

```
make chaos-poison-event   # core up; with the Airflow scheduler running the merge is the silver_upsert DAG
```

What happened: one record that is not a Debezium envelope (`not json at all {poison-<ts>`) is
produced into `oltp.shop.orders`. Bronze keeps it as raw text (`raw` set, `op` null). The next
`silver_upsert` run routes it to `silver.quarantine` (`reason = unparsed_envelope`, topic, partition,
offset and payload kept) and carries on with the rest of the batch; a second run does not
quarantine it again.
What monitoring shows: the number of quarantined rows in the last hour is a line of the
`dq_checks` log (`dq quarantined_last_hour=<n>`, task `report`). It is deliberately not exported
to Prometheus and has no alert: `quarantine_rows_total` and its alert are the owner's Modify gate
(W4-D8, `02-learning-gates.md`). The `lakehouse_dq_*` series cover duplicates, repeats and
reconciliation, not quarantine. Detection today is manual: `select reason, count(*) from
silver.quarantine group by 1`.
Data at risk: none. The record stays in bronze and in quarantine with its payload.
Recovery: nothing to recover; a human reads the payload and decides.
Why no loss or duplication: bronze is append-only and keeps the raw value; the quarantine key is
(topic, partition, offset), so a rerun merges onto the same row.
Verification: the script ends with one quarantine row for its marker after the first merge and
still one after the second.

### 8. Kafka down for 6 minutes

```
make chaos-kafka-down   # KAFKA_DOWN=360 by default; core + obs up, no replay running
```

What happened (2026-10-23): a 120 s replay burst started; 33 s into it `kafka` was stopped at
17:09:09 and kept down for 360 s, then started. Kafka was `healthy` 20 s after the start, the
connector `RUNNING` 20 s after (Connect had kept running and retried), bronze caught up 25 s
after. Spark did not wait: with the container stopped, the name `kafka` no longer resolves on the
compose network, the Kafka source fails with `No resolvable bootstrap urls given in
bootstrap.servers`, the query ends with an error and Docker restarts the driver about every 20 s
from 17:10:24 until Kafka was back at 17:15:10: 15 restarts (`RestartCount` 15). Each restart
resumed from the checkpoint.
What monitoring shows: `ContainerRestarting` for `kafka` and for `spark-bronze`, and
`ConnectorNotRunning`. `SparkNoBatch5m` did **not** fire: the restart loop keeps bringing the
series back before its `for: 5m` is over, so the restart counter and `ContainerRestarting` are
the signal for a crash-looping driver, not the last-batch age. A `dq_checks` run at 17:15 failed
with `silver differs from Postgres at rest`: bronze had been quiet for more than the 5 minutes that
count as "at rest", because the source could not deliver, while Postgres kept writing; that red run
raised `AirflowDagFailed`. It is a true signal (the pipeline is not delivering), through a check
that was written for another cause.
Data at risk: none while the outage is shorter than Kafka retention (24 h) and the slot lives.
Connect holds what it cannot produce, Postgres keeps the WAL. Longer than 24 h: scenario "Bronze
ingest" (`failOnDataLoss=true`).
Recovery: automatic, 25 s after Kafka returned.
Why no loss or duplication: offsets are per topic partition in Kafka and in the checkpoint; the 21
partitions hold no duplicate and no missing offset after the outage (`bronze_offsets_report`),
silver equals Postgres (7 of 7 ok).

### 9. Airflow task failure (dbt test)

```
make chaos-break-dbt-test   # orchestrate up, dbt_build unpaused, no replay running
```

What happened: `dbt_build` ran with the conf `{"dbt_vars": "{chaos_break_test: true}"}`. The
singular test `assert_chaos_break_test` on `fct_orders` returned every order under that switch and
failed.
What monitoring shows: `dbt_build` red in the Airflow UI; the task log names the test
(`Failure in test assert_chaos_break_test`). Alert `AirflowDagFailed` fired 17 s after the red run
ended (2026-10-23: run ended 16:39:47, the counter appeared at the 16:39:50 scrape, the alert at
16:40:05; 15 s evaluation plus the scrape). Seen in the UI when the run ends, 16 s after the trigger.
Data at risk: none. `fct_orders` was rebuilt before its test ran; every model after it was skipped,
so the marts kept their previous snapshot (`mart_daily_sales`: 9 snapshots before
and after).
Recovery: manual. Remove the cause (here the switch) and trigger `dbt_build`; the next silver merge
triggers it too. The run without the switch was green.
Why no loss or duplication: `dbt build` skips the children of a failed test, and a mart is either
replaced atomically (`CREATE OR REPLACE`) or not touched.
Verification SQL:

```
select committed_at, operation from gold."mart_daily_sales$snapshots"
order by committed_at desc limit 3;
```

## Runbooks

| Symptom | Runbook |
|---|---|
| Connector status FAILED | `docs/runbooks/connector-failed.md` |
| Retained WAL growing | `docs/runbooks/slot-wal-growth.md` |
| Spark job no batch for 5 minutes | `docs/runbooks/spark-stalled.md` |
| Freshness above 15 minutes | `docs/runbooks/freshness.md` |
| Disk full | `docs/runbooks/disk-full.md` (week 4) |
| Catalog cutover to Lakekeeper, or its rollback (owner only) | `docs/runbooks/catalog-cutover.md` |
| Reset everything | `make nuke` (asks for confirmation; deletes volumes, checkpoints, data) |

## Backup

Local laptop, nothing irreplaceable: the dataset is re-downloadable, the platform is
re-creatable from the repo. `make nuke && make bootstrap` is the restore procedure and is itself
a test that the repo is complete.
