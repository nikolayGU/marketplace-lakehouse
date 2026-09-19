# Decisions

Short ADRs. One entry per decision that someone might question. Status: proposed / accepted /
superseded. Longer reasoning lives in `docs/planning/00-mini-architecture-review.md` (ru).

| ID | Decision | Status |
|---|---|---|
| ADR-001 | Real data via Olist replay, not synthetic generators | accepted |
| ADR-002 | Two PostgreSQL instances: `postgres-oltp` (CDC source) and `postgres-meta` | accepted |
| ADR-003 | Kafka 4 KRaft, single broker, RF=1, 3 partitions per topic, retention 24h | accepted |
| ADR-004 | Object storage: pin last community MinIO image; fallback RustFS or Garage | proposed |
| ADR-005 | JDBC catalog in `postgres-meta` first; REST catalog (Lakekeeper) as should-have after the vertical slice | accepted |
| ADR-006 | Spark 3.5 + Iceberg 1.11 runtime in `local[2]`, no standalone cluster | accepted |
| ADR-007 | Bronze append-only streaming (at-least-once contract, idempotent epoch commit to be verified); silver via AvailableNow + foreachBatch MERGE is the no-duplicates guarantee | accepted |
| ADR-008 | Bronze keeps payload as JSON string; typed schema applied in silver from contracts | accepted |
| ADR-009 | Soft deletes in silver (`_deleted`), filtered in dbt | accepted |
| ADR-010 | `silver.orders` merge-on-read, other silver tables copy-on-write | proposed, measure in week 2 |
| ADR-011 | Airflow 3 LocalExecutor, batch only, BashOperator for dbt (no Cosmos) | accepted |
| ADR-012 | No Schema Registry until week 6; JSON envelopes + JSON Schema contracts | accepted |
| ADR-013 | Spark metrics via custom StreamingQueryListener, because kafka-exporter cannot see Spark offsets | accepted |
| ADR-014 | Superset optional; marts are shown through Grafana + Trino datasource, dbt docs and SQL | accepted |
| ADR-015 | Removed: ClickHouse, k8s, Terraform, Ansible, Loki, Alertmanager delivery, Cosmos | accepted |
| ADR-016 | Compose profiles and the rule "never all profiles at once" as the RAM strategy | accepted |
| ADR-017 | Stateful windowed job `orders_per_minute` (watermark, state, update mode) is mandatory, not optional | accepted |

## ADR-001 Real data via Olist replay

Context: synthetic generators produce uniform distributions and meaningless dashboards; no
own e-commerce data is available. Decision: load the public Olist dataset (~100k orders,
2016-2018) into PostgreSQL, shift dates to end today, bulk-load 80%, replay 20% on a virtual
clock as real transactions with injectable late, duplicate and schema-change events.
Consequences: realistic seasonality and categories; a replayer service to maintain; dataset
license must be checked before shipping a sample.

## ADR-004 Object storage

Context: MinIO stopped publishing community images to Docker Hub / Quay in October 2025 and
removed the web console earlier. Decision: pin the last community tag if it still pulls and
manage it with `mc`; otherwise switch to RustFS or Garage (both S3-compatible; Spark and Trino
use S3A/S3 either way). The skill being demonstrated is "S3-compatible object storage", not a
vendor. To be closed in week 1 after `docker compose pull`.

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

## ADR-007 Bronze streaming append, silver batch MERGE

Context: Iceberg's Spark streaming sink is append-oriented; MERGE INTO driven directly from a
streaming query is unreliable (Iceberg issues #9730, #10805, #13431). Decision: bronze is an
append-only streaming sink with a 20 s trigger; silver is a separate job with
`Trigger.AvailableNow` scheduled by Airflow every 5 minutes, using `foreachBatch` to run
`MERGE INTO`. Consequences: one continuous JVM plus one short-lived JVM; silver latency is
minutes, not seconds, which is acceptable for analytics; both Spark trigger modes are shown.

On duplicates: bronze is contractually at-least-once. Debezium re-sends events after a restart
and those land in bronze as new Kafka records. For Spark restarts the expectation is that the
Iceberg sink skips an already committed epoch (it records `spark.sql.streaming.queryId` and
`epochId` in the snapshot summary); chaos scenario 1 verifies this experimentally and the
result is recorded here. Either way, the no-duplicates guarantee lives in silver
(`MERGE` keyed by primary key with an LSN guard) and `bronze_duplicate_ratio` is a monitored
metric, not an assumption.

## ADR-013 Spark metrics

Context: Spark stores Kafka offsets in its checkpoint and does not commit to a consumer group,
so `kafka-exporter` reports no lag for it. Decision: a `StreamingQueryListener` in the driver
exposes `spark_streaming_input_rows_total`, `spark_streaming_batch_duration_seconds` and
`spark_streaming_kafka_lag` (latest broker offset minus processed offset) via
`prometheus_client` on the driver's HTTP port. Consequences: ~60 lines of Python, a real
"how do you monitor a Spark stream" answer.
