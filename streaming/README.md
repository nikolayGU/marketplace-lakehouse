# streaming

Spark image and jobs.

- `Dockerfile`: `apache/spark:3.5.9-java17-python3` + `iceberg-spark-runtime-3.5_2.12:1.11.0` +
  `spark-sql-kafka-0-10` + `hadoop-aws` / `aws-java-sdk-bundle` for S3A + PostgreSQL JDBC for the
  `jdbc` catalog type (the rollback path of the catalog cutover runbook). Jars are downloaded at
  build time with pinned versions and checked against Maven Central's sha1, never fetched at
  runtime. The image's Python is 3.10, so `spark_jobs` avoids 3.11+ syntax.
- `run-job.sh <job>`: the entrypoint, `spark-submit` of `spark_jobs/<job>.py` with
  `SPARK_MASTER` and `SPARK_DRIVER_MEMORY`.
- `spark_jobs/bronze_cdc_ingest.py`: Kafka `oltp.shop.*` -> `lake.bronze.cdc_events`, append,
  20 s trigger, checkpoint `s3a://lakehouse/checkpoints/bronze_cdc_ingest`. Columns: ADR-008, ADR-022.
- `spark_jobs/silver_upsert.py`: Iceberg streaming read from bronze, `Trigger.AvailableNow`,
  `foreachBatch` -> parse with `contracts/silver` -> newest event per key -> `MERGE INTO
  lake.silver.<table>`. `make silver` runs it; the Airflow DAG `silver_upsert` schedules it.
- `spark_jobs/iceberg_demo.py`: `make iceberg-demo`, run in a one-off `spark-silver` container
  from the `lakehouse/spark:dev` image, which `spark-bronze` builds. Rebuilds the sandbox
  `lake.demo.orders` from `silver.orders` (read only) and walks through snapshots, time travel,
  rollback and its undo, compaction and `expire_snapshots`, then prints the same queries for
  Trino. Bronze and silver are never touched. The code is baked into the image, so after a change
  rebuild it: `docker compose --env-file .env -f docker/compose.yaml --profile core build
  spark-bronze`.
- `spark_jobs/contracts.py`: loads `contracts/silver/*.json` (baked into the image at
  `/opt/app/contracts/silver` through the named build context `contracts`).
- `spark_jobs/orders_per_minute.py`: 1-minute window, 5-minute watermark,
  `update` mode, upsert into `silver.orders_per_minute`; makes late-event handling observable.
- `spark_jobs/metrics.py`: `StreamingQueryListener` exposing Prometheus metrics on
  `METRICS_PORT`; last progress time, input rows, batch duration, Kafka lag
  (`spark_streaming_kafka_lag`).
- `spark_jobs/catalog.py`: SparkSession with Iceberg catalog `lake` and S3A pointed at MinIO.
  `CATALOG_TYPE` defaults to `rest` (Lakekeeper, `settings.py`). `jdbc` (JdbcCatalog in
  postgres-meta) is kept only as the rollback path of `docs/runbooks/catalog-cutover.md`, not a
  working mode: its rows point at pre-cutover snapshots.
- `spark_jobs/maintenance.py`: Iceberg maintenance CLI (expire snapshots, remove orphan files,
  rewrite position deletes, compact data files); the rules (bronze never loses a snapshot,
  silver and gold keep a week) are checked before a Spark session starts.
- `spark_jobs/offsets.py`: Kafka offsets and lag out of a streaming progress report, without
  pyspark.
- `spark_jobs/progress.py`: numbers out of a progress report (watermark seconds and the like),
  without pyspark.

Unit tests that build a SparkSession need a JVM and skip without one. The host has no Java;
`make test-spark` runs the Spark test files (`SPARK_TESTS` in the Makefile) inside
`lakehouse/spark:dev` instead (`make test-spark SPARK_IMAGE=lakehouse/spark:ci` in CI); a new
Spark test file has to be added to that list. Inside the image a skipped test fails the run
(`-p no:skipping`).

## orders_per_minute

`spark_jobs/orders_per_minute.py`: distinct new orders (`op = 'c'`) per one-minute window of
`order_purchase_timestamp`, read from Kafka `oltp.shop.orders`, watermark 5 minutes, `update`
mode, MERGE into `lake.silver.orders_per_minute` (a count only rises). Settings `OPM_*` in
`spark_jobs/settings.py`: source topic, target, checkpoint, watermark, trigger (`processing` every
`OPM_TRIGGER_SECONDS`, or `available_now`), starting offsets, shuffle partitions (2, frozen in the
checkpoint on the first run). `make watermark-demo` runs the same code on a lab topic, one
`available_now` run per batch, into `lake.demo.orders_per_minute`.

Two facts the tests pin: Spark drops a late row against the watermark of the *previous* batch, so
the batch that moves the watermark still accepts the late event (one batch of grace); and the batch
frame of `foreachBatch` must be persisted, or every action on it re-runs the aggregation and
inflates the progress counters.
