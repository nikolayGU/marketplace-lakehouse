# Operations

- [Profiles and what runs together](#profiles-and-what-runs-together)
- [Ports](#ports-all-on-127001)
- [Daily commands](#daily-commands)
- [Bronze ingest](#bronze-ingest)
- [Silver upsert](#silver-upsert)
- [Query](#query): [Access control](#access-control)
- [Lakekeeper (REST catalog)](#lakekeeper-rest-catalog)
- [MinIO console](#minio-console)
- [Superset (profile `bi`)](#superset-profile-bi)
- [Airflow](#airflow)
- [Observability](#observability): [SLIs](#slis-and-thresholds), [Alerts](#alerts), [Dashboards](#dashboards)
- [Stateful job](#stateful-job)
- [Maintenance](#maintenance)
- [CI](#ci): [Pinned images and actions](#pinned-images-and-actions)
- [Failure scenarios](#failure-scenarios)
- [Runbooks](#runbooks)
- [Backup](#backup)

## Profiles and what runs together

| Situation | Command | RAM (limits) |
|---|---|---|
| Daily work on ingestion | `make start` | ~11 GB limits, ~7 GB real |
| Working on dbt / Airflow | `make start && make up PROFILE=orchestrate`; stop `orchestrate` when not working on batch | ~13 GB limits, ~9 GB real |
| Full pipeline with monitoring | `make start && make up PROFILE=orchestrate,obs` | 14.2 GB limits (14496 MiB on 2026-11-10: `core` without `oltp-replayer` 7680, `trino` 3584, `orchestrate` 2100, `obs` 1132; sum of `deploy` limits, one-shot jobs not counted), 5.2 GB real at rest (2026-10-19, before the Trino plugin) |
| Demo dashboard ([Superset](#superset-profile-bi) and its MCP endpoint) | `make down PROFILE=orchestrate && make up PROFILE=bi` | swap orchestrate for bi; ~1.8 GB of limits (superset 1280M, superset-mcp 512M), 1024M while `superset-init` runs; needs `SUPERSET_ADMIN_PASSWORD` in `.env` |
| Stateful job (`orders_per_minute`) | `make up PROFILE=stateful` on top of `core` | +1.75 GB limit; 495 MiB at rest, 842 MiB while reading 24 h of the topic (2026-10-23) |
| Debugging Kafka visually | `make up PROFILE=tools` for 15 minutes, then `make down PROFILE=tools` | +0.4 GB |

All profiles except `tools` ran together on 2026-11-10: 20 containers, 6.0 GiB in `docker stats` at
rest. The largest sum over the 7 days before was 8.33 GiB, on 2026-11-06 at 16:20:30 UTC during the
live end-to-end run to gold and Superset (Prometheus, `sum(docker_container_memory_usage_bytes)`
at the 15 s scrape step; a 1 m step misses it). No OOM; WSL sees 11.7 GiB. Conditions: `TRINO_XMX=2g`,
no `tools`, no parallel `make test-spark` (1.1 to 1.2 GiB, no limit), no image builds and no
`make dags-check` meanwhile. `tools` and a second stack do not run together with it.

`TRINO_XMX=2g` is the default of `.env.example`; an existing `.env` keeps its value, set
`TRINO_XMX=2g` there. `docker stats` and RSS do not see swap: a container may swap up to its own
limit. Read `memory.stat`, `memory.swap.current` and `memory.events` in the container's cgroup, and
take the peaks of a sum in Prometheus with a 15 s subquery step.

`core` includes Lakekeeper, the Iceberg catalog. `make start` brings up `core` without `oltp-replayer`, plus `trino`: it
names `spark-bronze kafka-connect trino`, and their `depends_on` pull in the rest of `core`
(ADR-016). `make up` refuses any `PROFILE` that contains `core`, because that would start the
replayer container, which plays at `REPLAY_SPEED` (2880, one virtual day per 30 s) until stopped.
`postgres-meta` (the Lakekeeper, Airflow and Superset databases) belongs to `core` only: the other
profiles depend on it with `required: false`, so `make up PROFILE=orchestrate|bi|query` expects
`make start` first, and `make down PROFILE=orchestrate|bi` leaves the catalog database running.
The replay budget is limited, so traffic comes in bursts from the host:
`make replay-burst SECONDS=<n>` plays `n` real seconds at 720x and stops. `make replay-live`
starts the container on purpose, for a continuous demo; stop it with
`docker compose --env-file .env -f docker/compose.yaml stop oltp-replayer`.

## Ports (all on 127.0.0.1)

| Service | Profile | Port |
|---|---|---|
| postgres-oltp | `core` | 5432 |
| postgres-meta | `core` | 5433 |
| kafka | `core` | 9092 (host listener, see below) |
| kafka-connect | `core` | 8083 |
| minio S3 API | `core` | 9000 (a browser is redirected to the console) |
| minio web console | `core` | 9001 |
| lakekeeper (API and UI at `/ui/`) | `core` | 8181 |
| spark-bronze UI | `core` | 4040 |
| spark-bronze metrics | `core` | 4041 |
| oltp-replayer `/metrics`, `/status` | `core`, only through `make replay-live` | 8000 |
| spark-silver UI (while `make silver` runs) | `jobs` | 4042 |
| spark-orders-per-minute UI | `stateful` | 4043 |
| trino | `query` | 8080 |
| airflow api-server | `orchestrate` | 8090 |
| prometheus | `obs` | 9090 |
| grafana | `obs` | 3000 |
| superset | `bi` | 8088 |
| superset-mcp | `bi` | 5008 |
| kafka-ui | `tools` | 8085 |

Every profile except `core` is started on purpose with `make up PROFILE=<name>`, and `jobs`
only runs when a make target starts its container, so most rows above answer nothing by default.
`BIND_IP` in `.env` is `127.0.0.1`. From the host, Kafka clients use the bootstrap `127.0.0.1:9092`:
the broker advertises `localhost:9092` on its `HOST` listener. Containers use `kafka:9092`.

## Daily commands

First run:

```
make secrets         # .env with generated passwords; on an existing .env it only appends missing keys; REPLAY_DATA=sample skips the download
make data            # download Olist into data/raw (not needed with REPLAY_DATA=sample)
make bootstrap       # start, migrate, connector, replay-load, verify, protect; safe to re-run
```

`make bootstrap` runs: `make start`; a wait of up to 5 minutes for `spark-bronze`, `kafka-connect`
and `trino` to turn healthy; `make migrate`; `connect/register.sh`; `make replay-load` unless a
replay state exists (`replay state exists, load skipped`); `make verify`;
`scripts/lakekeeper/protect.sh`. None of the steps deletes anything.
On the sample it took 4 minutes with the images built, a re-run 75 seconds; the first build of the Spark image adds about 80 seconds with its base image already pulled (2026-10-17).

`make verify` refuses (exit 2) while `airflow-scheduler` runs, while a replayer answers on port
8000, and when Trino does not answer `select 1`, its catalog `lake` does not answer `show schemas`
(Lakekeeper down) or MinIO does not answer (MinIO down). Otherwise it waits up to `VERIFY_WAIT`
seconds (default 900) for bronze to catch up with Kafka, runs one silver merge, and checks that no
Kafka offset is in bronze twice and none is missing between the lowest and the highest offset of
each partition, that bronze reached Kafka's end offsets, that live silver rows equal Postgres for
all seven tables (row count, set of primary keys, sum of every decimal column and the row
fingerprint of every column; `reconcile`), and that all seven tables reached bronze. The last line
is `verify ok` or `verify failed: <reason>`.

Both `verify` targets run three probes after the replayer check (and the scheduler check of
`make verify`), each in at most `TRINO_PROBE_WAIT` (a number from 1, default 20) + 2 seconds,
instead of waiting `VERIFY_WAIT` and blaming Kafka: `select 1` to Trino, `show schemas` in catalog
`lake`, and `curl` of `$S3_ENDPOINT/minio/health/live` run inside the trino container. The third is
not a table query on purpose: Trino caches table metadata, so `$manifests` answered with MinIO
down. It shows that MinIO answers, not that the credentials or the files are right. Exit 2 with:

- `verify failed: Trino does not answer within N s: <reason>` (hangs) or `verify failed: Trino
  probe failed: <reason>` (error, a stopped container);
- `verify failed: Trino answers, but catalog lake does not answer within N s` or `... catalog lake
  fails (Lakekeeper?): <reason>`; with `TRINO_PROBE_WAIT` below about 10 a stopped Lakekeeper reads
  as `does not answer within N s`;
- `verify failed: Trino and catalog lake answer, but the object store (MinIO) does not answer
  within N s` or `... but the object store (MinIO) fails: <reason>`; a stopped MinIO leaves the
  Docker DNS (`curl: (6) Could not resolve host: minio`), a paused one would read as `does not
  answer` (not measured).

Measured refusals: [evidence](docs/evidence.md#probe-minio-stopped). Ctrl+C ends either target with
`verify interrupted` and exit 130; a kill (TERM) ends the script at once, but a running merge container goes on.

```
make replay-burst SECONDS=60   # about 12 virtual hours at 720x; prints virtual_now before and after
make replay-start              # plays until ctrl-c at REPLAY_SPEED (1 day / 30 s): spends the budget
```

`replay-load` refuses to touch non-empty tables. Starting over means `make replay-reset`, which
empties every `shop` table and drops staging; it asks first. The emptying is a `TRUNCATE`, and
Debezium 3.5 skips truncate events by default (`skipped.operations=t`): bronze and silver keep every row, and the next
`make reconcile` is red on row counts. A real start over is the lake too, which today means
`make nuke && make bootstrap` (blast radius, owner's ok).

```
make status          # docker compose ps with health
make logs S=spark-bronze
make psql            # psql into shop
make trino           # trino cli, catalog lake
make kafka-topics    # list topics with partitions
make kafka-groups    # classic consumer groups and lag; Spark keeps offsets in its checkpoint (lag is in Grafana)
make connector-status
make replay-status   # replayer position and virtual clock
make iceberg-demo    # snapshots, time travel, rollback, compaction, expiration
```

`make iceberg-demo` works on `lake.demo.orders` only: it rebuilds that sandbox from `silver.orders`
(read only), so its rollback and `expire_snapshots` never reach bronze or silver. It needs
`silver.orders` with at least 1 100 live rows (`make silver` first).

## Bronze ingest

`spark-bronze` runs `spark_jobs/bronze_cdc_ingest.py`: every `oltp.shop.*` topic into
`lake.bronze.cdc_events`, one micro-batch per `BRONZE_TRIGGER_SECONDS`, checkpoint at
`s3a://lakehouse/checkpoints/bronze_cdc_ingest`. It turns healthy after its first progress event,
which happens on an empty topic too.

- A crash or OOM kill makes Docker restart it (`unless-stopped`), and the job resumes from the
  checkpoint (`Resuming at batch N` in the log). A manual `docker kill` or `docker stop` does not:
  start it with `docker start lakehouse-spark-bronze-1`.
- `startingOffsets=earliest` applies only to a fresh checkpoint. If the job is down longer than
  Kafka retention (24 h), `failOnDataLoss=true` fails the query instead of skipping offsets, and
  Docker restarts it into the same failure: a restart loop (`RestartCount` growing, `OffsetOutOfRange`
  or "data loss" in the log). Recovery is a decision, not a restart: see the Kafka gate.
- Unhealthy means no progress or idle event for 120 s: the query is stuck, typically on MinIO
  or `postgres-meta`. The container keeps running; read `make logs S=spark-bronze`.
- Consumer down longer than retention, or bronze started after the history left Kafka:
  `make cdc-snapshot` (all tables) or `make cdc-snapshot TABLES="shop.orders"` re-reads the
  source into the topics without touching the slot (ADR-019).
- Schema changes of bronze itself are additive and applied on start: a new column goes into
  the DDL at its position and into `ADDED_COLUMNS` (name, type, after), and `ensure_table` adds it
  to the live table there, logging `lacks <column>, adding it`. A column only in the DDL is not
  added, and the streaming sink then refuses the DataFrame (column order). The checkpoint is unaffected. `source_sequence` arrived this way (ADR-022).
- Resetting bronze means deleting the checkpoint prefix and the table: blast radius.

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
`lake.silver.<table>` tables and exits.

- Per table and batch: parse `after` (`before` for a delete) with `contracts/silver/<table>.json`,
  send events that cannot become a row to `silver.quarantine`, keep the newest event per primary
  key, `MERGE` guarded by `_last_lsn`.
- Quarantine: one row per Kafka record, keyed by `(topic, kafka_partition, kafka_offset)`, so a
  replayed batch adds nothing. A table without a contract goes there whole as `no_contract`.
  Otherwise `reason` is the first that applies: `unparsed_envelope` (bronze kept it as `raw`),
  `unknown_op`, `null_key`, then, for anything but a delete, `type_mismatch` (a field that does not
  fit its column) and `null_required`. A delete needs only its key: it flags the row and never
  writes the other values. The log says `batch N: <table> events quarantined: {reason: count}` (a
  replay counts them again) or `batch N: <n> <table> events quarantined, no contract`. Check: `select source_table, reason, count(*) from silver.quarantine group by 1, 2`.
- Quarantined events are not retried. After a contract fix a key silver never received arrives with
  its next change or with `make cdc-snapshot TABLES=shop.<table>`; a key silver already holds
  catches up only with its next streamed change (a snapshot never beats a streamed LSN, ADR-019); a
  quarantined delete needs a hand fix the owner approves.
- Payload fields the contract does not declare are ignored and logged once per table and batch
  (`payloads carry fields contracts/silver/<table>.json does not declare: [...]`): the source
  gained a column. The row still merges. Proven by the Spark unit tests
  (`tests/unit/test_silver_upsert.py`), not live: migration
  `oltp/migrations/evolution/003_orders_sales_channel.sql` has not run on the stack (the contract
  change is the owner's Modify gate).
- Soft delete: `_is_deleted = true` keeps the last values. Live rows are `where not _is_deleted`.
- Layout (ADR-010): `silver.orders` is merge-on-read and partitioned by month, the other tables
  copy-on-write. An older table converges on the next run (metadata only). Delete files accumulate
  between compactions; `alter table silver.orders execute optimize` in Trino folds them. Check: `select content, spec_id, count(*) from
  silver."orders$files" group by 1, 2` (content 1 are delete files).
- `silver_shuffle_partitions` in `spark_jobs/settings.py` is frozen in the checkpoint on the first
  run (Spark logs `Updating the value of conf 'spark.sql.shuffle.partitions'`). A new value takes
  effect only with a new checkpoint, and deleting the checkpoint prefix is blast radius: the next
  run then re-reads all of bronze (idempotent, but long).
- A rerun with nothing new in bronze does nothing. A crash mid-run replays the unfinished batch,
  and the replay changes nothing that the first attempt already merged.
- The job refuses to start if a silver table and its contract disagree on columns: add the
  column to the contract and `ALTER TABLE ... ADD COLUMN`, in that order.
- Losing the silver checkpoint is checked by the unit test
  `test_a_lost_checkpoint_rereads_bronze_and_silver_keeps_its_values`, not live (owner's decision, 2026-11-04): a new checkpoint re-reads all of bronze, and silver keeps the same values, with no
  duplicates and no losses; `_updated_at` changes only for rows without an LSN (`_last_lsn is null`).
- Resetting silver means dropping the tables and deleting the checkpoint prefix: blast radius.

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

Healthy means `/v1/info` says `"starting": false`; run one query to prove the catalog. The config is bind-mounted, so
after editing `docker/trino/etc` (catalogs, `access-control.properties`, `rules.json`) restart the
container (`docker compose ... restart trino`); `up -d` does not notice file changes.

Trino only reads what Spark committed: a micro-batch shows up after its Iceberg commit.

### Access control

Trino has file-based access control (Trino 483): `docker/trino/etc/access-control.properties`
(`access-control.name=file`) points at `docker/trino/etc/rules.json`. Rules go top down, the first
match applies, no match is a deny
(https://trino.io/docs/483/security/file-system-access-control.html).

File-based rules do not cover table procedures ("all are effectively allowed" in the
documentation), so `ALTER TABLE ... EXECUTE expire_snapshots | remove_orphan_files | optimize`
passes whatever the rules say, and the first two delete files. `grafana` therefore does not read
`lake` at all. It reads `lake_ro` (`docker/trino/etc/catalog/lake_ro.properties`): the same
Lakekeeper, warehouse and S3 keys, plus `iceberg.security=read_only`, which denies DDL, DML and
procedures for every user on that catalog
(https://trino.io/docs/483/connector/iceberg.html#security). `lake_ro` and `lake` are two names for
the same tables: nothing is copied.

| User | Can |
|---|---|
| `grafana` (Grafana), `superset` (Superset) | `select` on the `lake_ro.gold` tables `fct_*`, `dim_*` and `mart_*` only (not the dbt views `stg_*` and `int_*`, which read silver with the owner's rights, nor the seed `category_translation`); `lake_ro` is read-only twice (rules and connector); catalogs `lake` and `system` and every other: none; no schema ownership, no procedures, no other users' queries, no system information |
| everyone else (`dbt`, `airflow`, `trino` of the CLI and `make` targets, any new name) | `lake` as before access control: all table privileges, schema ownership, procedures, query management, system information; `lake_ro` is read-only for them too, they have no use for it |

Both files are read when `trino` starts, so a change needs a restart of the container
(`docker compose ... restart trino`, which interrupts running queries and needs an "ok"); there is
no `security.refresh-period` on purpose. A malformed `rules.json` is expected to stop Trino at startup (see `docker logs`; by the documentation, not tried).
`tests/unit/test_trino_access.py` checks the files against the model of the documentation (first
match, no match is a deny) and that `lake_ro.properties` equals `lake.properties` plus
`iceberg.security=read_only`. It does not run Trino: the checks below do.

Check it after a restart (Trino up; the iceberg metadata tables follow their table):

```
T="docker compose --env-file .env -f docker/compose.yaml exec -T trino trino"
$T --user grafana --execute "select count(*) from lake_ro.gold.fct_orders"        # passes
$T --user grafana --execute "select count(*) from lake_ro.silver.orders"          # Access Denied
$T --user grafana --execute "select count(*) from lake_ro.gold.stg_reviews"       # Access Denied (dbt view over silver)
$T --user grafana --execute "select count(*) from lake.gold.fct_orders"           # Access Denied (catalog)
$T --user grafana --execute "alter table lake_ro.gold.category_translation execute optimize" # Access Denied
$T --user dbt --execute "alter table lake_ro.gold.category_translation execute optimize"     # Access Denied (read_only)
```

Residual risk. Trino has no authentication, the user name is only a label. Two ways around the
rules remain: (1) a Grafana admin creates a new Trino datasource in the UI with user `dbt`
(`editable: false` protects only the provisioned datasource, not Grafana from new ones);
(2) any client that reaches port 8080 (the host, bound to `BIND_IP`, or any container in the
`lake` network) can pass `--user dbt` and get all rights on `lake`. What stands in the way: the
Grafana admin password and the ports bound to `BIND_IP`. The rules do not protect against a person
with an admin login, a shell or network access; that needs authentication and a separate decision.

## Lakekeeper (REST catalog)

Lakekeeper v0.13.6 is the Iceberg catalog of Spark and Trino (ADR-005). Its services are in profile
`core`: `lakekeeper-migrate` (one-shot schema migration of the `lakekeeper` database in
`postgres-meta`, 128 MiB), `lakekeeper` (the API on `127.0.0.1:8181`, 256 MiB limit) and
`lakekeeper-bootstrap` (one-shot, 128 MiB). `spark-bronze`, `spark-silver` and `trino` wait for
`lakekeeper-bootstrap`, so every `up` of them runs the idempotent one-shots again (`minio-init`,
`lakekeeper-migrate`, `lakekeeper-bootstrap`). Without `lakekeeper` Spark cannot commit and Trino
cannot load a table. The API has no authentication (allow-all), which is why the port stays on
127.0.0.1. The same port serves the catalog UI, http://127.0.0.1:8181/ui/
(HTTP 200): the warehouse `lake`, its namespaces and tables; it needs no login either.

`make silver` and `make iceberg-demo` run `spark-silver` with `--no-deps`: they never start
Lakekeeper, so it must already be running (`make status`; `make lakekeeper-bootstrap` starts it).

```
make lakekeeper-bootstrap   # starts lakekeeper (migration first) if needed, creates warehouse lake
curl -s '127.0.0.1:8181/catalog/v1/config?warehouse=lake'   # defaults.prefix is the warehouse id
docker stats --no-stream lakehouse-lakekeeper-1
```

`make lakekeeper-bootstrap` is safe to re-run (`warehouse lake exists`, nothing changes). It runs
in `lakehouse/spark:dev` with `pull_policy: never`, so build that image first (`make start` does);
otherwise compose stops with `No such image`.

Encryption key. `LAKEKEEPER_ENCRYPTION_KEY` encrypts the warehouse's S3 keys inside the
`lakekeeper` database. `make secrets` generates every secret of a new `.env` and on an existing one
only appends the keys that are missing; without this key every compose command fails (`required
variable LAKEKEEPER_ENCRYPTION_KEY is missing a value`), so run `make secrets` once on an existing
`.env`. Never change the key once the warehouse exists: Lakekeeper could no longer decrypt its S3
keys, and every commit depends on them. Sending the credential again
(`POST /management/v1/warehouse/{id}/storage-credential`) should repair that; it is untested.

Spark and Trino reach the catalog only through Lakekeeper. The `iceberg_catalog` database in
`postgres-meta` of an existing volume holds old rows that nothing reads. A copy of `warehouse/` from
before the first maintenance run is on `/mnt/d/lakehouse-backup/warehouse-20261029`.

What deletes files. Lakekeeper reads a REST `DELETE` without `purgeRequested` as a purge (the
Iceberg REST spec defaults it to `false`), and warehouse `lake` soft-deletes for 7 days: the table
disappears from the catalog at once, Lakekeeper deletes its whole location 7 days later, and until
then it can be undropped (below).

| Action | Lakekeeper (soft delete, 7 days) |
|---|---|
| Spark `DROP TABLE` | `DELETE` without `purgeRequested`: location deleted after 7 days |
| Spark `DROP TABLE ... PURGE` | the same drop, then Spark deletes the files itself, at once; undrop brings back no data |
| Trino `DROP TABLE` (dbt drops through it) | `DELETE ?purgeRequested=true`: location deleted after 7 days |
| Trino `CALL system.unregister_table` | `DELETE` without `purgeRequested`: location deleted after 7 days |
| REST `DELETE .../tables/<t>` | location deleted after 7 days |
| REST `DELETE .../tables/<t>?purgeRequested=false` | files stay; the table is hidden at once and leaves the catalog after 7 days |

`force=true` on a REST `DELETE` skips both the 7 days and table protection: the table leaves the
catalog at once and, unless `purgeRequested=false`, its whole location is deleted at once too.
All of it is on the blast-radius list.

Protection. `scripts/lakekeeper/protect.sh` set `protected` on all 9 bronze and silver tables.
Lakekeeper then answers a drop of any of them with 409 before anything is deleted, Spark
`DROP ... PURGE` included; commits are not affected. Run it again when a new bronze or silver table
appears or a table is re-registered (it comes back unprotected); it only sets the flag and reads it
back. `demo` and `gold` stay unprotected. Removing protection is on the blast-radius list: the
owner does it by hand. The flag lives under the warehouse id and the table's Iceberg `table-uuid`:

```
lk=http://127.0.0.1:8181; json() { python3 -c "import json, sys; print(json.load(sys.stdin)$1)"; }
wid=$(curl -s "$lk/catalog/v1/config?warehouse=lake" | json '["defaults"]["prefix"]')
tid=$(curl -s "$lk/catalog/v1/$wid/namespaces/silver/tables/orders?snapshots=refs" |
  json '["metadata"]["table-uuid"]')
curl -s "$lk/management/v1/warehouse/$wid/table/$tid/protection"   # {"protected":true,...}
# POST {"protected": true} to the same URL sets it (protect.sh does);
# {"protected": false} removes it: owner only
```

Undrop (not tried on this stack): a dropped table can be brought back within 7 days unless
`DROP ... PURGE` deleted its files; `lk` and `wid` as above:

```
curl -s "$lk/management/v1/warehouse/$wid/deleted-tabulars"   # id, name, expiration-date
curl -sS -X POST -H 'Content-Type: application/json' \
  -d '{"targets": [{"type": "table", "id": "<id from the list>"}]}' \
  "$lk/management/v1/warehouse/$wid/deleted-tabulars/undrop"   # 204 on success
```

## MinIO console

The console of MinIO is on http://127.0.0.1:9001 (service `minio` in `docker/compose.yaml`), profile `core`.
Log in with `S3_ACCESS_KEY` and `S3_SECRET_KEY` from `.env`. The bucket named by `S3_BUCKET` holds
the Iceberg data and metadata files of bronze, silver and gold. Look, do not delete: a file removed by hand breaks its table.

## Superset (profile `bi`)

Optional BI over the gold marts, with an MCP endpoint. `make up PROFILE=bi` on top of
`core` and `query` (swap `orchestrate` for `bi` to stay lean); three services, all built from
`docker/superset/Dockerfile` (Superset 6.1.0 plus the drivers `psycopg2-binary`, `trino` and
`fastmcp`, pinned by `constraints.txt`):

| Service | Port | Limit | Does |
|---|---|---|---|
| `superset-init` | none | 1024M | one-shot: `superset db upgrade`, creates `admin`, `superset init`, imports the bundle `docker/superset/dashboards/` (`docker/superset/init.sh`); skips the import with a warning when Trino is not reachable |
| `superset` | 8088 | 1280M | UI and REST API, metadata in the database `superset` of `postgres-meta`; waits for `superset-init` |
| `superset-mcp` | 5008 | 512M | the MCP server built into Superset 6.1 (`superset mcp run`), endpoint `http://127.0.0.1:5008/mcp`; waits for `superset-init` |

The admin password is `SUPERSET_ADMIN_PASSWORD` in `.env`. Compose requires it, so after updating
the repository run `make secrets` once: it appends the keys of `.env.example` that `.env` lacks and
never changes an existing one. Without it every compose command, whatever the profile, stops.

The bundle holds the database `Lakehouse (Trino lake_ro)` (`trino://superset@trino:8080/lake_ro`),
4 datasets, 13 charts and the dashboard `Marketplace` (v2, Harbor palette).

Import order. `superset-init` runs `docker/superset/import_bundle.py` (datasets, charts, dashboard,
`overwrite=True`): a UI edit of a bundled object is replaced by the next import, and an import
error fails `superset-init`. To import again, recreate the one-shot (Trino must be up):

```
docker compose --env-file .env -f docker/compose.yaml --profile bi up -d --force-recreate --no-deps superset-init
```

Relative time: `superset_config.py` sets the relative start and end from `SUPERSET_DATA_ANCHOR`
(default `2026-07-01`, the first day of the month of the latest order), so "Last quarter" counts
from the data, not from today. After a replay moves the data end into a later month, set it in
`.env` and recreate `superset` and `superset-mcp`; this changes the stand, so ask first.

Restart `superset` after editing `superset_config.py` (`make up` does not recreate it).

Dashboard notes:
- The KPI tiles are `pop_kpi` charts, which the 6.1.0 frontend registers only with
  `CHART_PLUGINS_EXPERIMENTAL` in `FEATURE_FLAGS` (`superset_config.py`). Without it every tile shows
  "Item with key pop_kpi is not registered".
- "No filter" in the Period filter breaks the KPI tiles: pick a period such as "Last quarter".
- The Harbor palette and the theme tokens are in `docker/superset/superset_config.py`.

Check that the charts answer, from the host (reads only; the password comes from the container
environment):

```
docker exec lakehouse-superset-1 python /app/check.py
```

It logs in through the REST API and runs every chart of the dashboard; it exits 1 for a failing or
empty chart. Last run: [evidence](docs/evidence.md#superset-dashboard-v2).

Freshness. `silver_upsert` merges every 5 minutes and `dbt_build` runs on its Asset. Superset caches
chart data and metadata for 300 s (`CACHE_DEFAULT_TIMEOUT` in `superset_config.py`), so a chart can lag
by that much. "Data through" is the date of the last purchase, not the build time.

Data boundary. Superset queries Trino as the user `superset`, which has the rights of `grafana`:
`select` on the `fct_*`, `dim_*` and `mart_*` tables of `lake_ro.gold` and nothing else
(`docker/trino/etc/rules.json`, rule `grafana|superset`). The database is imported with
`allow_dml: false`. Trino has no authentication, so the user name is a label
([Access control](#access-control)).

MCP and its limits. Any MCP client can connect to `http://127.0.0.1:5008/mcp` (client settings are not kept in
the repository). Example for Claude Code: `claude mcp add --transport http --scope local superset http://127.0.0.1:5008/mcp`.
- Every tool runs as the Superset user `admin` (`MCP_DEV_USERNAME` in `superset_config.py`), with no
  login on the endpoint: the local single-user mode, like Airflow without a login. A client can
  create and change charts, dashboards and saved queries; the data it reads stays inside the ACL above.
- The port is bound to `BIND_IP`; `FASTMCP_HTTP_HOST_ORIGIN_PROTECTION` and
  `FASTMCP_HTTP_ALLOWED_HOSTS` check Host and Origin (421, 403), against DNS rebinding.
- A deployment reachable from outside the machine must turn on `MCP_AUTH_ENABLED` with a JWT
  provider and drop `MCP_DEV_USERNAME` (see the comment next to it in `superset_config.py`); this
  repository does not configure that.

## Airflow

Profile `orchestrate`: `airflow-api-server` (UI and REST API on `127.0.0.1:8090`, no login, every
visitor is admin, ADR-011), `airflow-scheduler` (LocalExecutor: tasks run as processes inside this
container) and `airflow-dag-processor`. One image, `lakehouse/airflow:dev` from
`airflow/Dockerfile`: Airflow 3.3.2 on Python 3.12, dbt in `/opt/dbt-venv`. Config is
`docker/airflow/airflow.env`, values from `.env`. Metadata lives in the `airflow` database of
`postgres-meta`; the same instance holds `lakekeeper` and, on a volume that has it,
`iceberg_catalog` (old rows, unread), which nothing here touches.

Before the first start, once per `.env`: `make secrets`. It generates `AIRFLOW_FERNET_KEY` and
`AIRFLOW_API_SECRET_KEY` for a new `.env`, and on an existing one appends the keys that are missing.
It leaves `DOCKER_GID` empty, so set it if it is empty (the command prints nothing):

```
sed -i "s/^DOCKER_GID=$/DOCKER_GID=$(stat -c %g /var/run/docker.sock)/" .env
```

- `AIRFLOW_API_SECRET_KEY` signs the api-server's requests for task logs; without it the UI shows no task log.
- `DOCKER_GID` is the group of `/var/run/docker.sock`, which the scheduler joins to start
  spark-silver through DockerOperator. Without it: `permission denied` on the socket.

Start (the Trino heap is `TRINO_XMX`, see Profiles):

```
make start
make up PROFILE=orchestrate      # builds lakehouse/airflow:dev on the first run
make airflow-init                # pools lake_writers and gold_writers, 1 slot each; safe to re-run
```

Stop Airflow with `make down PROFILE=orchestrate`.

Check it:

```
docker compose --env-file .env -f docker/compose.yaml exec airflow-scheduler airflow pools list
docker compose --env-file .env -f docker/compose.yaml exec airflow-scheduler airflow dags list-import-errors
docker compose --env-file .env -f docker/compose.yaml exec airflow-scheduler \
  python -c "import docker; print(docker.from_env().ping())"   # True
```

A new DAG starts paused: unpause it in the UI or with `airflow dags unpause <dag_id>` in the
scheduler container; a trigger of a paused DAG stays queued. A new DAG file shows up within a minute.

DAGs live in `airflow/dags/`; their shared code is `airflow/dags/lakehouse/`, which
`.airflowignore` keeps out of DAG parsing.

| DAG | Schedule | Does |
|---|---|---|
| `silver_upsert` | every 5 min, `max_active_runs=1`, 1 retry; each task 10 min, the run 30 min | `bronze_has_new_snapshot` skips the run when silver has merged every bronze snapshot; `merge` starts spark-silver (DockerOperator, pool `lake_writers`) and publishes the Asset `lake.silver`; `remember_snapshot` stores the merged snapshot id in the Variable `silver_upsert_last_bronze_snapshot` |
| `dbt_build` | Asset `lake.silver`; the task 15 min, the run 20 min | `dbt build` of `lake.gold` from `/opt/dbt-venv`, no retries; a manual run takes dbt vars from its conf, `{"dbt_vars": "{...}"}` |
| `dq_checks` | every 15 min; each task 10 min, the run 14 min | `cdc_progress` reads the CDC position; `silver_keys_unique` fails on a primary key twice in silver; `silver_matches_postgres` fails when silver differs from Postgres at rest; `reconcile_values` compares values source-silver and silver-gold and GMV against the source, fails on a difference at rest, on a failed gold snapshot check (`dq gold_stale_failed=1`) and on a failed GMV step or CDC re-read; `dbt_source_freshness` fails when its query fails, not when the source is stale; `report` logs `dq <name>=<value>` lines and sends them to Prometheus (see "Observability", `lakehouse_*`), except the quarantine count |
| `iceberg_maintenance` | daily; each task 60 min, the run 4 h | `optimize` of each silver table through Trino, in pool `lake_writers`; the Spark steps (position deletes, `expire_snapshots` of silver and gold, compaction of past bronze days) only in a run with `{"expire_and_compact": true}`, see "Maintenance" |
| `iceberg_orphans` | weekly; each task 60 min, the run 4 h | `remove_orphan_files` of silver, gold and bronze metadata; a dry run unless the run has `{"dry_run": false}` |

One silver writer. While `silver_upsert` is unpaused, `make silver` and `make verify` must not
run: two processes on one checkpoint (`make verify` refuses while the scheduler runs). For a
manual merge: `airflow dags pause silver_upsert` in the scheduler container, wait until its
running `merge` ends, `make silver`, then `airflow dags unpause silver_upsert`. The first run from
Airflow continues from the checkpoint of the last `make silver`.

A paused `dbt_build` loses Asset events. Airflow 3.3 queues no Asset event for a DAG that is paused
(`airflow/assets/manager.py:354` in the Airflow image) and does not replay it on unpause: on
2026-11-06 the `lake.silver` event of 12:11:49 UTC created no run, and gold stayed behind silver.
So after you unpause `dbt_build`, trigger it once by hand (`airflow dags trigger dbt_build`),
unless a silver merge with events will follow. `make chaos-silver-kill` does this itself after it
lifts its own pause (`cleanup` in `scripts/chaos/silver-kill.sh`). If it is forgotten, `dq_checks` counts
the runs that find the stand at rest and gold older than silver (Variable `dq_gold_stale_runs`) and
`GoldStaleAtRest` fires after two in a row (see "Alerts").

The checks of `dq_checks` have known windows; no fix is decided. (1) A write to the source between `cdc_progress` and the first position read
in `reconcile_values` (about 7 to 8 s) shows neither as a standing CDC nor as a shift. (2) A merge
that commits silver in the middle of `dbt_build` while gold is committed later from the old silver
leaves the gate open until the next build. (3) Kafka down for less than 20 minutes while the slot
moved earlier in the same 15 minutes: the first run at rest is red, a true signal through a check
written for another cause ([scenario 8](docs/failure-scenarios.md#8-kafka-down-for-6-minutes)). A CDC position that shifts
during the check reads as `in flight`, not as red.

Separately, `dbt_build` and the silver merge do not exclude each other: a build longer than about 4
minutes can meet a merge and fail on a relationships test; the next build fixes it.

Timeouts. Every task has an `execution_timeout` and every DAG a `dagrun_timeout`; all attempts of a
task fit in its run (`make dags-check` and `tests/unit/test_dags.py` check it). The Spark tasks
remove their container with force, so a task that times out stops its Spark job; the failure reads
`Process timed out` followed by `NotFound: No such container` (`on_kill` stops a container the
timeout already removed).
The merge container has a fixed name, `lakehouse-silver-merge`: a second merge fails with 409
while it exists, and `make silver` refuses too. After a killed scheduler or worker it can stay
behind and every merge fails with `name "/lakehouse-silver-merge" is already in use`. Check `docker ps -a --filter 'name=^/lakehouse-silver-merge$' --format '{{.Status}}'`:
`Up` is a live writer, wait for it; `Exited` is a leftover, `docker rm lakehouse-silver-merge`
with the owner's ok (never `rm -f` on an `Up` one). The name is global to the Docker host: a
second stack of this repo would collide on it. Not proven live: a timeout on a real merge, and what
`dagrun_timeout` does to a running container (SIGTERM, then SIGKILL after 5 s; if the JVM is slower,
the container stays and the next merge fails with the 409).

`reconcile_values` (value comparison source-silver and silver-gold, GMV against the source) and
what a red `dq_checks` task means: [dq-checks runbook](docs/runbooks/dq-checks.md#a-red-dq_checks-task).
A red run after host sleep: step 2 of [airflow-dag-failed](docs/runbooks/airflow-dag-failed.md).

## Observability

`make up PROFILE=obs` on top of `core` (and usually `orchestrate`). Prometheus on
http://127.0.0.1:9090, Grafana on http://127.0.0.1:3000 (`admin`, password `GRAFANA_ADMIN_PASSWORD`
from `.env`). Exporters have no host ports.

| Job | Target | What it gives |
|---|---|---|
| `prometheus` | `localhost:9090` | Prometheus itself, `prometheus_tsdb_head_series` |
| `kafka-connect` | `kafka-connect:9404` | JMX agent in the Connect JVM (`docker/connect/`): `kafka_connect_connector_task_status{connector,task,status}`, `debezium_postgres_streaming_*` (-1 and 0 until the first event after a start), `jvm_*` |
| `spark-bronze` | `spark-bronze:4041` | bronze listener: rows, batch duration, last batch time, `spark_streaming_kafka_lag{query,topic,partition}` (ADR-013) |
| `kafka-exporter` | `kafka-exporter:9308` | brokers, topic and partition offsets (not Spark's lag: ADR-013) |
| `postgres-exporter` | `postgres-exporter:9187` | `pg_*`, plus `lakehouse_slot_retained_bytes` and `lakehouse_slot_active` per slot from `observability/postgres-exporter/queries.yaml` |
| `statsd-exporter` | `statsd-exporter:9102` | StatsD of Airflow (`AIRFLOW__METRICS__STATSD_*` in `docker/airflow/airflow.env`): `airflow_dagrun_failed_seconds{dag_id}`, `airflow_ti_finish_total{dag_id,task_id,state}`, `airflow_task_duration_seconds{dag_id,task_id}` by `observability/statsd/mapping.yml`; `dq_checks` gauges (`lakehouse_*`, [series](observability/README.md#series)) |
| `container-exporter` | `container-exporter:9105` | `docker_container_*{name,service}`: memory as `docker stats`, limit, CPU, start time, restarts, OOM kill, health (ADR-023) |

The series `dq_checks` sends (`lakehouse_*`, DogStatsD over UDP, a 45 minute TTL):
[observability/README.md](observability/README.md#series). They come every 15 minutes, so an alert
on them can lag by that long. The quarantine count stays in the log (its metric and alert are the
owner's decision). UDP gives no receipt: the check is the series in Prometheus.

Check it:

```bash
curl -s 127.0.0.1:9090/api/v1/targets | python3 -c 'import json,sys; t=json.load(sys.stdin)["data"]["activeTargets"]; print(sorted((x["labels"]["job"], x["health"]) for x in t))'
curl -s 127.0.0.1:9090/api/v1/query --data-urlencode 'query=lakehouse_slot_retained_bytes'
curl -s 127.0.0.1:3000/api/health
```

Mounts, the reload of Prometheus, the Connect volume and the other notes on the profile:
[observability/README.md](observability/README.md#notes).

### SLIs and thresholds

| SLI | Metric | Threshold and alert |
|---|---|---|
| Bronze freshness against Kafka | `spark_streaming_kafka_lag`, `time() - spark_streaming_last_batch_timestamp` | 300 s without a batch: `SparkNoBatch5m`; no alert on lag, it is 0 at rest |
| Silver freshness against bronze | `lakehouse_silver_lag_seconds` | 900 s: `FreshnessAbove15m`; 900 s plus up to 15 minutes until the next `dq_checks` (1561 s measured) |
| Gold freshness against silver | `lakehouse_dq_gold_stale_runs`, `lakehouse_dq_gold_not_compared_runs` | 2 runs at rest: `GoldStaleAtRest`; 24 runs: `SilverGoldNotCompared`; no gauge for the age of gold |
| Table freshness | `lakehouse_table_freshness_seconds` | no alert: no traffic between replay bursts is not a fault |
| CDC | `kafka_connect_connector_task_status`, `lakehouse_dq_cdc_stalled` | task not `running` for 1m: `ConnectorNotRunning`; stalled 20 minutes: `CdcStalledSourceWrites` |
| Replication slot | `lakehouse_slot_retained_bytes`, `lakehouse_slot_active` | 64 MiB inactive or 512 MiB any, 5m: `SlotWalRetainedHigh`; 64 MiB for an hour on an active slot: `SlotWalHeldIdle`; a healthy slot holds about 25 MB |

These are targets for a laptop, not SLOs with an error budget.

### Alerts

13 alerts in 16 rules in `observability/prometheus/alerts.yml` (`SparkNoBatch5m`, `FreshnessAbove15m`
and `DqChecksStale` have two each), tested by `make alerts-test`; live proof and time to fire:
[evidence](docs/evidence.md#alerts-and-time-to-fire). No Alertmanager (ADR-023): read them in the
Prometheus UI (`/alerts`), `curl 127.0.0.1:9090/api/v1/alerts` or the "Firing alerts" panel. After
editing the file: `docker exec lakehouse-prometheus-1 kill -HUP 1`, never `docker kill -s HUP`
([why](observability/README.md#notes)).

Nothing watches the watcher: when Prometheus itself is down, no rule is evaluated, Grafana has no
alerting set up (`provisioning/alerting` is empty) and nothing is delivered anywhere. After a host
sleep or a Docker restart run `make report`: it lists project containers that are down although
their restart policy is `unless-stopped`.

| Alert | Expression | `for` | Why this threshold |
|---|---|---|---|
| `ConnectorNotRunning` | `absent(kafka_connect_connector_task_status{connector="shop-connector",status="running"} == 1)` | 1m | a task not `running` is no CDC; `absent` covers a Connect that is down |
| `SlotWalRetainedHigh` | slot over 64 MiB and inactive, or over 512 MiB | 5m | an idle healthy slot holds about 25 MB; an inactive one grows without bound (`max_slot_wal_keep_size = -1`) |
| `SparkNoBatch5m` | `time() - last_batch_timestamp > 300`, and `absent(...)` for the dead driver | 1m / 5m | idle events keep the timestamp moving, so only a stuck or dead query trips it |
| `FreshnessAbove15m` | `last_over_time(lakehouse_silver_lag_seconds[1h]) > 900` | 0 | age of the oldest bronze snapshot silver has not merged; table freshness does not alert |
| `AirflowDagFailed` | `increase(airflow_dagrun_failed_seconds_count[30m]) > 0` or a series new within 30 minutes while the `statsd-exporter` target was up 30 minutes earlier | 0 | second half: first failure after statsd-exporter started, ignoring old counters after a scrape gap; misses a first failure in the 30 minutes after Prometheus starts |
| `ContainerRestarting` | `changes(docker_container_start_time_seconds{name=~".+-[0-9]+", service!~"<one-shot services>"}[15m]) > 0` | 0 | `docker restart` moves the start time, `RestartCount` does not; the silver merge container is not counted |
| `FreshnessAbove15m`, `cause="unknown"` | `absent(lakehouse_silver_lag_seconds)` | 15m | `dq_checks` sends no lag it cannot tell, and statsd-exporter drops a gauge after 45 minutes |
| `DqChecksStale` | `time() - last_over_time(lakehouse_dq_last_run_timestamp_seconds[1h]) > 1800` (`cause="stale"`), `absent(...)` (`cause="gone"`) | 0 / 15m | `dq_checks` runs every 15 minutes; a paused DAG, a stopped scheduler or a failing `report` stops every `lakehouse_dq_*` gauge |
| `CdcStalledSourceWrites` | `min_over_time(lakehouse_dq_cdc_stalled[20m]) == 1 and count_over_time(...[20m]) >= 70` | 0 | the source wrote and the slot confirmed nothing for two `dq_checks` runs in a row |
| `ScrapeTargetDown` | `up{job!="spark-orders-per-minute"} == 0` | 2m | an exporter that is down silences its own alerts (ADR-023); the stateful job runs only with `PROFILE=stateful` |
| `SlotWalHeldIdle` | `min_over_time(lakehouse_slot_retained_bytes[1h])` over 64 MiB, slot active, now at most 512 MiB | 0 | an active slot moves only when the source writes (about 24 MB held after a day idle), so a whole hour above 64 MiB means no traffic reached it |
| `SparkRestartLoop` | `changes(docker_container_start_time_seconds{service="spark-bronze", name=~".+-spark-bronze-[0-9]+"}[10m]) > 2` | 0 | a driver that dies before its first batch keeps both `SparkNoBatch5m` rules inside their window; one planned restart stays under the threshold |
| `GoldStaleAtRest` | `last_over_time(lakehouse_dq_gold_stale_runs[1h]) >= 2`, severity `warn` | 0 | gold is older than silver by Iceberg snapshots while the stand is at rest: `dbt_build` paused or red, or its Asset event lost for a paused DAG (see "Airflow"); two runs because one can be the build on its way. Silent under a continuous replay (never at rest): `SilverGoldNotCompared` speaks after 6 hours |
| `SilverGoldNotCompared` | `last_over_time(lakehouse_dq_gold_not_compared_runs[1h]) >= 24` | 0 | `dq_checks` compares silver and gold only at rest and skips silently when the stand never is (a continuous replay); 24 runs are 6 hours of `dq_checks` working |

Limits worth knowing:

- `absent()` alerts also fire when the source is off (obs up, core down).
- A crash-looping Spark driver (Kafka stopped) dies before its first batch, so `SparkNoBatch5m`
  stays quiet; `SparkRestartLoop` catches it on the third restart within 10 minutes (51 s on the
  stored chaos 8 data, not shown live).
- `SlotWalHeldIdle` is late by design (a full hour); when the slot goes over 512 MiB or inactive it
  goes out at once while `SlotWalRetainedHigh` waits its `for: 5m`: up to 5 minutes with no alert.
- CDC "stands" when the write counter of schema `shop` (`pg_stat_user_tables`) grew since the
  previous `dq_checks` run and `confirmed_flush_lsn` of `shop_slot` did not move, until the slot
  moves. The source-silver comparisons are then `in flight, no verdict`, the silver-gold pairs still
  run, and `CdcStalledSourceWrites` fires after about 20 minutes (live in chaos 6, 2026-10-29).
- A difference at rest is red when the source is silent, the slot does not exist, after a reset
  of the statistics and on the first run; if the counter cannot be read, `cdc_progress` fails and
  the checks that need it end `upstream_failed`.

### Dashboards

Grafana provisions `observability/grafana/dashboards/*.json` (classic JSON, edits in the UI are
not saved: change the file). `uv run python scripts/obs/check_dashboards.py` runs every panel query
against Prometheus (or, for a Trino panel, its SQL against Trino on `127.0.0.1:8080`, which needs the
`query` profile) and lists the empty ones, since a typo and a missing metric both read "No data".
A Spark panel that ran fine but is empty is `idle:` (exit 0) only under conditions that are in
[observability/README.md](observability/README.md#dashboard-check); anything else is `empty`, exit 1.

| Dashboard / panel | Query (metric) | Source |
|---|---|---|
| Pipeline health: bronze lag, rows, batch duration, last batch | `spark_streaming_*` | bronze listener (ADR-013); `SparkNoBatch5m` |
| connector status, behind source | `kafka_connect_connector_task_status`, `debezium_postgres_streaming_MilliSecondsBehindSource` | Connect JMX; `ConnectorNotRunning` |
| WAL retained, slot active | `lakehouse_slot_*` | postgres-exporter; `SlotWalRetainedHigh` |
| silver lag, table freshness, DQ | `lakehouse_silver_lag_seconds`, `lakehouse_table_freshness_seconds`, `lakehouse_dq_*` | `dq_checks` via StatsD; `FreshnessAbove15m` |
| Airflow tasks and runs | `airflow_*` | StatsD; `AirflowDagFailed` |
| firing alerts | `ALERTS{alertstate="firing"}` | Prometheus |
| Infra: memory, CPU, restarts, OOM, health | `docker_container_*` | container-exporter (ADR-023); `ContainerRestarting` |
| Marketplace: sales, GMV, delivery SLA, cancellations | SQL on `lake_ro.gold.fct_orders`, `mart_daily_sales`, `fct_order_items` | Trino plugin `trino-datasource@1.4.1` |

The Marketplace dashboard needs the Trino plugin: `GF_PLUGINS_PREINSTALL_SYNC=trino-datasource@1.4.1`
installs it into the `grafana` volume before Grafana starts. The first start needs internet, and a
failed install halts Grafana as a whole; once the version is in the volume, a restart works offline.
Panels name `lake_ro.gold.<table>` and convert Trino's decimal string to a number. Check: `uv run python scripts/obs/check_dashboards.py observability/grafana/dashboards/marketplace.json`
prints `queries ok: 4`; it runs as the user `grafana`, so it also fails on a panel the rules deny.

Order counts and cancellations come from `fct_orders`: `mart_daily_sales` counts an order in each
of its states, so `sum(orders_count)` overstates. GMV is summed from the mart; the category panel
applies the same definition, so its categories add up to `sum(gmv)`.

Risk: the plugin runs any SQL the panel or Explore sends, as Trino user `grafana`; what that user may
do and the residual risk are in [Access control](#access-control). Freshness panels step every 15
minutes (the cadence of `dq_checks`); that is not a bug.

## Stateful job

`spark-orders-per-minute` (profile `stateful`, ADR-024): distinct new orders per minute of
`order_purchase_timestamp`, watermark 5 minutes, from Kafka `oltp.shop.orders` into
`lake.silver.orders_per_minute` (Trino: `silver.orders_per_minute`).

- Start: `make up PROFILE=stateful` (the image is built with `core`; nothing from `core` restarts).
  Stop: `make down PROFILE=stateful`. UI `127.0.0.1:4043`, metrics `:4041` inside the network
  (Prometheus job `spark-orders-per-minute`).
- It reads from the beginning of the topic on the first start (Kafka keeps 24 h).
- Metrics (the query label is `orders_per_minute`): `spark_streaming_state_rows` (windows held),
  `spark_streaming_watermark_timestamp_seconds` (event time of the data, not the clock),
  `spark_streaming_late_rows_dropped_total` (rows behind the watermark, counted once the batch after
  the one that moved the watermark has run), plus the batch metrics of bronze.
- Reset (blast radius, needs the owner's "ok"): a MERGE never lowers a count, so deleting
  `checkpoints/orders_per_minute` and starting again recomputes from Kafka; windows older than
  Kafka's retention keep their counts. Needed after more than 24 h down (`failOnDataLoss`).
- After a start or restart the state and watermark series are absent until the first batch with
  data, so `check_dashboards.py` lists those two panels as `idle` (not empty) on a quiet system, for
  at most the 7 days of Prometheus retention since the last batch with data.
- Live check of 2026-10-23 (per-minute counts against `silver.orders`, `make watermark-live`, memory):
  the Stateful job row of [README](README.md).
- Demos: `make watermark-demo` (lab topic, own table `demo.orders_per_minute`, needs only `core`)
  and `make watermark-live` (needs the service; re-sends the oldest real order, which the watermark
  must drop once, and the newest, which it must count once; `lsn_repeats_last_hour` grows by 2,
  silver absorbs both by LSN).

## Maintenance

Policy and reasons: ADR-025. `iceberg_maintenance` (daily 03:30) and `iceberg_orphans` (weekly,
Sunday 04:00) are created paused and unpaused one rung at a time (the ladder in ADR-025); do not
unpause them to "see what happens": `expire_snapshots` and `remove_orphan_files` delete files, and
the lake has no regular backup (see Backup). Since 2026-10-29 `iceberg_maintenance` is unpaused and `iceberg_orphans` is still
paused. `iceberg_maintenance` existed before its Spark steps, so "created paused" does not hold
them back: they run only in a run with `{"expire_and_compact": true}` (a scheduled run does
`optimize` only), and turning them on daily is a change of the param's default with its own "ok".
After unpausing, `iceberg_orphans` starts a run at once: its last due date is in the past. Rebuild the Spark image
first (`docker compose ... --profile core build spark-bronze`): DAG files are live when saved, the
job `maintenance.py` only after the image.

By hand, from the repo root (nothing runs by itself):

```
C="docker compose --env-file .env -f docker/compose.yaml --profile core run --rm --no-deps spark-silver"
$C maintenance orphans silver.sellers                       # dry run: counts, does not delete
$C maintenance expire --days 7 silver.sellers               # deletes snapshots older than a week
$C maintenance rewrite-position-deletes silver.orders       # not proven live, see "Not proven yet"
$C maintenance rewrite-data --before-today lake.bronze.cdc_events
```

Each call prints one JSON line (`dry_run`, the table, candidates or removed files). A refusal
(`expire` on bronze, a term under 7 days on silver or gold, `orphans` on bronze without
`--location-suffix metadata`, a suffix other than `metadata` or `data`, `--retain-last` under 1)
exits 1 before a Spark session starts. To read a result: for `expire`, compare `select count(*) from silver.<t>."$snapshots"` before and after, and that
`select count(*)` of the table did not move; for `orphans`, the dry run lists what the real run
would remove.

First live run (2026-10-29) with times and file counts, and the check that the procedure lists a
table directory, not a string prefix: [evidence](docs/evidence.md#first-live-run-2026-10-29) and
[orphans next to `orders_per_minute`](docs/evidence.md#orphans-next-to-orders_per_minute-2026-10-30).

### Not proven yet

- `rewrite-position-deletes silver.orders` (ADR-025, failed on 2026-10-23) did not run live: the
  scheduled run of 2026-10-29 skipped `rewrite_position_deletes`.
- `iceberg_orphans` stays paused. Whether it runs weekly is the owner's decision.
- 13 directories `gold/mart_daily_sales__dbt_tmp-*` are left outside every table location. The
  orphans procedure does not touch them.

## CI

`.github/workflows/ci.yml`, on every pull request and push to main; a newer push to the same
branch cancels the older pull request run.

| Job | What it does |
|---|---|
| `lint-and-test` | Temurin 17, `uv sync --locked`, ruff, `bash -n` on shell scripts, mypy, yamllint, sqlfluff, `dbt parse`, `pytest tests/unit`, compose config, gitleaks |
| `hadolint` | one run per Dockerfile (a test compares the matrix with `find`), fails on warning and above; accepted findings sit in the Dockerfile as `# hadolint ignore=` with the reason |
| `alerts-test` | `make alerts-test` (promtool, pinned Prometheus image) |
| `spark-tests` | builds `lakehouse/spark:ci` and runs `make test-spark SPARK_IMAGE=lakehouse/spark:ci`; `FAIL_ON_SKIP=1` (`tests/unit/conftest.py`) turns any skip into a failure |
| `airflow-image` | builds `lakehouse/airflow:ci` (scope `airflow`), imports Airflow, trino, psycopg and pydantic-settings, runs `dbt --version` in its venv, and `make dags-check`: every DAG file imports in the image, offline, with `docker/airflow/airflow.env`; every task has an `execution_timeout` whose attempts fit in the DAG's `dagrun_timeout`, every DockerOperator removes its container with force, and the merge has its fixed name |
| `minio-images` | builds `lakehouse/minio:ci` and `lakehouse/mc:ci` from `docker/minio/Dockerfile` and runs `bash scripts/check-minio-images.sh`: the release and commit each binary prints, `sh` and `wget` in both images, a throwaway MinIO healthy on the compose healthcheck, `create-bucket.sh` twice |

Every job here and the smoke job run on `ubuntu-24.04`, so a new Ubuntu release and its default
Java reach CI only with a commit, though GitHub still updates the image under the label
(`Version:` in the job log) (on `ubuntu-26.04`, Java 25, the SparkSession tests fail with
`getSubject is not supported`). `setup-uv` installs uv 0.12.17; nothing ties it to the uv on
the host, so a host upgrade needs the same `version` change in both workflows.
`actions/checkout` leaves no git credentials behind (`persist-credentials: false`).

`.github/workflows/smoke.yml` (on demand and weekly, Monday 03:00 UTC while the repository is active:
GitHub pauses scheduled workflows after 60 days without activity; 45 minutes at most) walks the path
from a clean clone on the committed sample: `make secrets` with `REPLAY_DATA=sample`, `make
bootstrap`, a 60 s `make replay-burst`, `make verify`, a second `make bootstrap` (must say
`replay state exists, load skipped` and end `verify ok`). It builds the Spark, Connect, MinIO and mc
images from scratch, so it is cold every time. Run it: `gh workflow run smoke.yml --ref main`, then
`gh run watch <id> --exit-status`. On failure it uploads `smoke-logs` (container state and the last
200 log lines of every service). Red on 2026-10-23 and 2026-10-26: the MinIO images were gone from
quay.io and Docker Hub (built from source since ADR-026); first green run 2026-10-29 (40907438614).

Repeat locally: `make test-spark`, `make dags-check`. `make test-spark` pins `pytest` and
`jsonschema` to the versions in `uv.lock` (`tests/unit/test_makefile.py` compares them). Runs:
`gh run list --workflow ci`.

### Pinned images and actions

Every registry image and every `FROM` is `name:tag@sha256:<digest>`, every third-party action
`owner/repo@<commit sha> # vX.Y.Z`; `tests/unit/test_pinning.py` fails on a tag alone. How to change
a version and what is not covered: [docs/supply-chain.md](docs/supply-chain.md).

Under the containerd image store the `.Image` of a container is the digest of the index and changes
with every build, even from cache. To see which image a container runs, compare
`docker inspect -f '{{json .ImageManifestDescriptor}}' <container>` with `docker image ls --tree`.

## Failure scenarios

Each scenario is a `make chaos-<name>` target plus a written answer to five questions; the text of
every scenario is in [docs/failure-scenarios.md](docs/failure-scenarios.md). `bronze_offsets_ok` in
`scripts/chaos/lib.sh` looks for gaps only between the first and the last offset of a partition.

| # | Scenario | Target | Date |
|---|---|---|---|
| 1 | [Spark bronze killed mid-batch](docs/failure-scenarios.md#1-spark-bronze-killed-mid-batch) | `chaos-spark-kill` | 2026-10-07 (re-run) |
| 2a | [Kafka Connect restart](docs/failure-scenarios.md#2a-kafka-connect-restart) | `chaos-connect-restart` | 2026-10-07 (re-run) |
| 2b | [Kafka Connect killed](docs/failure-scenarios.md#2b-kafka-connect-killed) | `MODE=kill make chaos-connect-restart` | 2026-10-07 (re-run) |
| 3 | [Duplicate events from source](docs/failure-scenarios.md#3-duplicate-events-from-the-source) | `chaos-duplicates` | 2026-10-07 |
| 4 | [Late events](docs/failure-scenarios.md#4-late-events) | `chaos-late` | 2026-10-07 |
| 5 | [PostgreSQL restart](docs/failure-scenarios.md#5-postgresql-restart) | `chaos-postgres-restart` | 2026-10-23 |
| 6 | [Connector down for 30 minutes (WAL growth)](docs/failure-scenarios.md#6-connector-stopped-for-30-minutes-wal-growth) | `chaos-connect-pause` | 2026-10-23 |
| 7 | [Corrupted event in topic](docs/failure-scenarios.md#7-corrupted-event-in-topic) | `chaos-poison-event` | 2026-10-23 (re-run through the Airflow merge) |
| 8 | [Kafka down](docs/failure-scenarios.md#8-kafka-down-for-6-minutes) | `chaos-kafka-down` | 2026-10-23 |
| 9 | [Airflow task failure (dbt test)](docs/failure-scenarios.md#9-airflow-task-failure-dbt-test) | `chaos-break-dbt-test` | 2026-10-18 |
| 10b | [Silver merge killed between two tables](docs/failure-scenarios.md#10b-silver-merge-killed-between-two-tables) | `chaos-silver-kill` | 2026-11-06 |

## Runbooks

| Alert | Runbook |
|---|---|
| `ConnectorNotRunning`, `CdcStalledSourceWrites` | `docs/runbooks/connector-failed.md` |
| `SlotWalRetainedHigh`, `SlotWalHeldIdle` | `docs/runbooks/slot-wal-growth.md` |
| `SparkNoBatch5m`, `SparkRestartLoop` | `docs/runbooks/spark-stalled.md` |
| `FreshnessAbove15m` | `docs/runbooks/freshness.md` |
| `DqChecksStale`, `SilverGoldNotCompared`, `GoldStaleAtRest` | `docs/runbooks/dq-checks.md` |
| `ScrapeTargetDown`, `ContainerRestarting` | `docs/runbooks/containers.md` |
| `AirflowDagFailed` | `docs/runbooks/airflow-dag-failed.md` |
| Disk full | `docs/runbooks/disk-full.md` |
| Reset everything | `make nuke` (asks for confirmation; deletes volumes, checkpoints, data) |

## Backup

Local laptop, nothing irreplaceable: the dataset is re-downloadable, the platform is re-creatable. `make nuke && make bootstrap` is the restore procedure and is itself
a test that the repo is complete. There is no regular backup; the one-off copy of `warehouse/`
taken before the first maintenance run is on `/mnt/d/lakehouse-backup/warehouse-20261029`.

No RPO or RTO is defined. A rebuild loses the replay position, the Airflow history, Grafana state
outside the provisioned dashboards, and any CDC still in Kafka (24 h retention). What each piece of state has:

| State | Copy | Restore tested |
|---|---|---|
| Postgres `shop` | none; `make bootstrap` and the replay rebuild it | the rebuild of the initial state, by every clean-clone run (smoke); the current state: no |
| `postgres-meta`: the `lakekeeper` catalog, Airflow | none | no |
| MinIO `warehouse/` | the one-off file copy of 2026-10-29 on `/mnt/d` | no; files alone do not restore the catalog pointers in `lakekeeper` |
| Spark checkpoints (`checkpoints/` in MinIO) | none | no |
| `.env` | none in the repo, by design | no |

`.env` is the one piece the repo cannot regenerate: `LAKEKEEPER_ENCRYPTION_KEY` encrypts the S3
keys inside the `lakekeeper` database, so a lost `.env` leaves an intact warehouse whose catalog
cannot be read. Keep a copy of `.env` outside the repo (owner's step, never committed).

Not proven live: losing a Spark checkpoint (silver only by the unit test
`test_a_lost_checkpoint_rereads_bronze_and_silver_keeps_its_values`, see the silver section),
MinIO or Lakekeeper down while a job writes, a full disk, and a restore from the copy above. A
checkpoint restores only together with the catalog it was written against. Anonymous volumes left
by recreated containers (`docker volume ls -q -f dangling=true`) take a few MB; removing them is
the owner's call.
