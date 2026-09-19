# Marketplace Lakehouse (mini)

A small but real data platform that replays two years of real marketplace transactions
(the public Olist dataset) through PostgreSQL and streams every change into an Iceberg
lakehouse. Built to run on a 16 GB laptop, to be broken on purpose, and to be explained
at a Senior Data Engineer interview.

Status: planning. Week 0 of 6.

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
make secrets                 # generates .env from .env.example
make data                    # downloads the Olist dataset into data/raw (Kaggle CLI or manual)
make up PROFILE=core         # postgres x2, kafka, connect, minio, spark-bronze, replayer
make up PROFILE=query        # trino
make replay                  # initial load + start replaying history
make psql                    # source database
make trino                   # trino cli
```

Never start every profile at once on 16 GB. Working combinations are listed in
[OPERATIONS.md](OPERATIONS.md).

| Profile | Services | RAM (limits) |
|---|---|---|
| `core` | postgres-oltp, postgres-meta (JDBC catalog), kafka, kafka-connect, minio, spark-bronze, oltp-replayer | ~7.3 GB |
| `rest` | lakekeeper (REST catalog, should-have) | 0.25 GB |
| `query` | trino | 3.5 GB |
| `orchestrate` | airflow api-server / scheduler / dag-processor | ~1.8 GB |
| `obs` | prometheus, grafana, exporters, cadvisor | ~0.9 GB |
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
scripts/        chaos scenarios, iceberg demos, helpers
tests/          unit tests (parsers, dedup logic, replayer), compose/config tests
docs/           planning (ru), interview notes, images
```

## Failure scenarios

Eight reproducible scenarios (plus two optional), each answered with: what happened, what monitoring shows,
which data is at risk, how the system recovers, and why nothing is lost or duplicated
(or where it can be). Run them with `make chaos-<name>`. See [OPERATIONS.md](OPERATIONS.md).

## Data quality

dbt tests (unique, not_null, relationships, accepted_values, freshness) on gold;
a `dq_checks` DAG reconciles row counts source vs silver vs gold, measures freshness
per table and duplicate ratio in bronze; invalid events land in `silver.quarantine`.

## Testing and CI

`ruff`, `mypy`, `sqlfluff`, `yamllint`, `hadolint`, `pytest tests/unit`, `dbt parse`,
`docker compose config`, `gitleaks`, image build. A manual smoke workflow boots the
`core` profile and checks that bronze receives rows.

## What I learned

Filled in as gates close: [LEARNING.md](LEARNING.md).

## Data

Olist Brazilian E-Commerce public dataset (Kaggle). Check the dataset license before
redistributing; this repository ships only a small sample for tests.
