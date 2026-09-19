# Architecture

## Goal

Replay real marketplace history through an OLTP database, capture every change with CDC,
land it in an Iceberg lakehouse, and serve tested analytics, on one 16 GB laptop, with
operations, observability and failure recovery treated as first-class.

## Data flow

1. `oltp_replayer` loads the Olist dataset into PostgreSQL schema `shop` with all timestamps
   shifted so the last day of the dataset is "today". 80% of history is bulk-loaded; the
   remaining 20% is replayed on a virtual clock (`REPLAY_SPEED`, e.g. one day per 30 s) as real
   INSERT / UPDATE / DELETE statements: order created, approved, shipped, delivered, canceled,
   review added or removed. Knobs inject late updates, duplicate updates and a schema change.
2. Debezium (Kafka Connect, PostgreSQL connector, `snapshot.mode=initial`) reads the WAL through
   a logical replication slot and produces one topic per table, `oltp.shop.<table>`, keyed by
   primary key, 3 partitions. Delivery is at-least-once.
3. Spark Structured Streaming job `bronze_cdc_ingest` subscribes to `oltp.shop.*`, runs a
   micro-batch every 20 s and appends raw envelopes to `bronze.cdc_events` (Iceberg). The
   payload stays a JSON string, so schema changes upstream never break bronze. Checkpoint in
   object storage; Iceberg commits are atomic per batch.
4. Spark job `silver_upsert` runs every 5 minutes from Airflow with `Trigger.AvailableNow`.
   It reads bronze incrementally (Iceberg streaming source), parses payloads against contracts,
   deduplicates by `(table, key, lsn)`, sends unparsable rows to `silver.quarantine`, and
   `MERGE INTO silver.<table>` with `WHEN MATCHED AND source.lsn > target._last_lsn`. Deletes are
   soft (`_deleted = true`). Late events never overwrite newer state. Re-running a batch yields
   the same result. Bronze itself is an at-least-once journal: duplicates there are allowed and
   measured, silver is where the no-duplicates guarantee lives.
5. Spark job `orders_per_minute` (mandatory, week 5) keeps a 1-minute window with a 5-minute
   watermark in `update` mode, upserting into `silver.orders_per_minute`. It exists to make
   watermark, state and late-event behaviour observable rather than theoretical.
6. dbt on Trino builds `stg_*` views, `int_*` models and marts (`fct_orders`, `fct_order_items`,
   `dim_*`, `mart_daily_sales` incremental merge, `mart_seller_performance`, `mart_delivery_sla`)
   hourly, triggered by the silver asset. Tests and docs run with it.
7. `dq_checks` reconciles counts source vs silver vs gold, measures freshness and duplicate
   ratio, and exports gauges to Prometheus. `iceberg_maintenance` compacts files, rewrites
   position deletes, expires snapshots and removes orphans.
8. Prometheus scrapes Kafka, Connect, PostgreSQL (slot lag, retained WAL), the Spark driver
   (custom `StreamingQueryListener` metrics: input rows, batch duration, Kafka lag), Airflow
   (StatsD) and cAdvisor. Grafana shows "Pipeline health" and "Infra". Six alert rules.
9. Grafana with a Trino datasource shows a few gold-level charts; Superset is optional.

## Where exactly-once comes from

No single component is exactly-once. Debezium and Kafka are at-least-once; Spark can re-run a
micro-batch after a crash. The end result is still correct because the sinks that matter are
idempotent: silver applies changes by primary key with an LSN guard, so a replayed or
duplicated event is a no-op; dbt incremental models merge on a unique key. Bronze is treated as
at-least-once by contract; whether the Iceberg sink really skips an already committed epoch
after a crash is verified by chaos scenario 1, not assumed.

## What is deliberately absent

Multi-broker Kafka, Spark cluster, Schema Registry (stretch), Superset (optional), ClickHouse,
Kubernetes, Terraform, Ansible, Loki, managed cloud. Each is either already known to the author or does not close a
skill gap this project targets. See DECISIONS.md.

## Resource model

Compose profiles let the platform run in pieces: `core` always, `query` almost always,
`orchestrate` only while batch work is being developed or demoed, `obs` from week 4, `rest`
once the REST catalog is adopted, `bi` only if there is time left. Every container has a memory
limit, a real healthcheck, `restart: unless-stopped`, log rotation, and ports bound to
`127.0.0.1` only. WSL2 is capped at 12 GB.

## Diagram

See README.md for the ASCII flow. A rendered diagram goes to `docs/img/architecture.svg`
once the vertical slice runs.
