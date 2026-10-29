# Marketplace Lakehouse (mini)

A small but real data platform that replays two years of real marketplace transactions
(the public Olist dataset) through PostgreSQL and streams every change into an Iceberg
lakehouse. Built to run on a 16 GB laptop, to be broken on purpose, and to be explained
at a Senior Data Engineer interview.

Status: weeks 1-2 of 6 done: CDC into bronze, typed silver with MERGE, the Lakekeeper REST
catalog, failure scenarios 1-4 measured. Week 3 (dbt gold, Airflow) is in progress; observability,
the stateful job and CI for the Spark tests are planned. Current state: [docs/HANDOFF.md](docs/HANDOFF.md) (ru).

## Pipeline

```
oltp_replayer -> PostgreSQL -> Debezium -> Kafka -> Spark Structured Streaming -> Iceberg bronze
                                                                                      |
                                    Airflow 3 (batch only) -> Spark AvailableNow MERGE -> Iceberg silver
                                                                                      |
                                                     Trino <- dbt -> Iceberg gold -> Grafana (Superset optional)
                                                Prometheus + Grafana watch all of it
```

| Layer | What lives there | Written by | Idempotency key |
|---|---|---|---|
| OLTP `shop` | customers, sellers, products, orders, order_items, payments, reviews | replayer | primary key |
| Kafka `oltp.shop.*` | Debezium JSON envelopes, 3 partitions, key = PK | Debezium | offset |
| bronze | raw CDC events, append-only, at-least-once, schema-flexible | Spark streaming | (topic, partition, offset), duplicates measured |
| silver | typed current state, soft deletes, no duplicates | Spark AvailableNow + MERGE | PK + max(lsn) |
| gold | staging -> intermediate -> marts | dbt on Trino | dbt unique_key |

## Why each piece

| Component | Problem it solves | Simpler option rejected |
|---|---|---|
| Debezium | Captures INSERT/UPDATE/DELETE from WAL without touching tables | Polling by `updated_at` misses deletes and intermediate states |
| Kafka | Durable buffer between source and consumers, replay | Direct JDBC reads do not buffer, do not replay |
| Spark Structured Streaming | Kafka -> Iceberg with checkpoints and micro-batches | Kafka Connect Iceberg sink teaches nothing about Spark |
| Iceberg | ACID tables on object storage, snapshots, schema evolution, MERGE | Plain Parquet has no atomic commits, no history |
| Trino | Interactive SQL over the lake, dbt engine | Spark SQL is heavy for interactive use |
| dbt | Tested, documented analytics layer | Hand-written SQL has no tests and no lineage |
| Airflow 3 | Schedules batch steps with retries and asset dependencies | cron has no retries, no visibility |
| Prometheus + Grafana | Lag, freshness, failures | Logs cannot answer "how far behind are we" |

Full reasoning: [ARCHITECTURE.md](ARCHITECTURE.md) and [DECISIONS.md](DECISIONS.md).

## Run

Requirements: Windows 11 with WSL2 + Docker Desktop (or any Linux with Docker), 12 GB for WSL2
(`.wslconfig`), 20 GB disk, Python 3.12 with `uv`.

```bash
make secrets                  # generates .env from .env.example
make hooks                    # installs pre-commit hooks (ruff, yamllint, gitleaks)
make data                     # downloads the Olist dataset into data/raw (Kaggle CLI or manual)
make bootstrap                # core + trino, schema, connector, initial load; ends with "verify ok"
make replay-burst SECONDS=60  # plays about 12 virtual hours of the remaining history, then stops
make verify                   # bronze holds every Kafka record once, silver equals Postgres
make psql                     # source database
make trino                    # trino cli
```

Without a Kaggle account, skip `make data` and set `REPLAY_DATA=sample` in `.env`: the
committed 2 000-order slice in `data/sample`. From a fresh clone on the sample, `make bootstrap`
took 4 minutes with the images built; the first build of the Spark image adds about 80 seconds
with its base image already pulled, mostly 400 MB of jars (2026-10-17).

MinIO and its `mc` client are built from the source of their last community tags on the first
start (no registry serves the images any more, ADR-026): it needs the network for GitHub and the
Go module proxy. The first build on a laptop (2026-10-27, `--build-arg GOFLAGS=-p=2`, an earlier
revision of the same Dockerfile) took about 4 minutes for MinIO and under half a minute for `mc`
after it; the cold time on a CI runner is not measured. On a host short of memory build them first:
`docker compose --env-file .env -f docker/compose.yaml build --build-arg GOFLAGS=-p=2 minio minio-init`.

`make start` brings up `core` and `query` without the replayer container, which would play the
rest of the history at full speed; `make up` refuses any `PROFILE` that contains `core`
(ADR-016). Never start every profile at once on 16 GB. Working combinations are listed in
[OPERATIONS.md](OPERATIONS.md).

| Profile | Services | RAM (limits) |
|---|---|---|
| `core` | postgres-oltp, postgres-meta (Lakekeeper's database), kafka, kafka-connect, minio, lakekeeper (Iceberg REST catalog), spark-bronze; oltp-replayer only through `make replay-live` | ~7.5 GB |
| `query` | trino | 3.5 GB |
| `orchestrate` | airflow api-server / scheduler / dag-processor | ~1.8 GB |
| `obs` | prometheus, grafana, exporters, container-exporter | ~0.8 GB |
| `bi` | superset (optional) | 1.2 GB |
| `tools` | kafka-ui | 0.4 GB |

## Repository

```
oltp/           schema migrations, oltp_replayer (Olist loader + change replayer)
connect/        Debezium connector config and registration script
streaming/      Spark image, bronze_cdc_ingest, silver_upsert, orders_per_minute, metrics listener
contracts/      JSON Schema for CDC envelope and silver tables
dbt/            dbt project (staging, intermediate, marts, seeds, tests)
airflow/        DAGs and Airflow image
observability/  prometheus config, alert rules, grafana provisioning
docker/         compose.yaml and per-service configs
scripts/        chaos scenarios, helpers
tests/          unit tests (parsers, dedup logic, MERGE, quarantine, replayer, Makefile)
docs/           planning (ru), interview notes, images
```

## Failure scenarios

Eight reproducible scenarios (plus two optional), each answered with: what happened, what monitoring shows,
which data is at risk, how the system recovers, and why nothing is lost or duplicated
(or where it can be). Run them with `make chaos-<name>`. See [OPERATIONS.md](OPERATIONS.md).

## Data quality

Now: invalid events land in `silver.quarantine`, and `make verify` checks that bronze holds
every Kafka offset exactly once and that silver's live rows match Postgres per table by row count,
set of primary keys and sums of decimal columns. Planned (weeks 3 and 5): dbt tests on gold and a
`dq_checks` DAG for freshness and duplicate ratios.

## Testing and CI

CI (`.github/workflows/ci.yml`) has five jobs: `lint-and-test` (`uv sync --locked`, `ruff`,
`mypy`, `sqlfluff`, `yamllint`, `dbt parse`, `pytest tests/unit`, `docker compose config`,
`gitleaks`), `hadolint` on the six Dockerfiles, `spark-tests` (builds `lakehouse/spark:ci` and runs
`make test-spark` in it, where the Iceberg jar exists and a skipped test is a failure),
`airflow-image` (builds the Airflow image and imports what the DAGs need) and `minio-images`
(builds MinIO and `mc` from source and runs them, ADR-026). `smoke.yml` (on demand and every Monday
03:00 UTC; green on 2026-10-29, run 40907438614) walks the clean-clone path on the sample.

## What I learned

Filled in as gates close: [LEARNING.md](LEARNING.md).

## Data

Olist Brazilian E-Commerce public dataset (Kaggle). Check the dataset license before
redistributing; this repository ships only a small sample for tests.
