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
- Resetting bronze means deleting both the checkpoint prefix and the table, which is on the
  blast-radius list.

Check it:

```
curl -s 127.0.0.1:4041/metrics | grep ^spark_streaming   # input rows, last batch, duration
make logs S=spark-bronze
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
| 7 | Corrupted event in topic | `chaos-poison-event` | planned (week 4) |
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
