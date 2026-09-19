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
