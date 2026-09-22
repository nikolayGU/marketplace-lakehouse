# streaming

Spark image and jobs.

- `Dockerfile`: `apache/spark:3.5.9-java17-python3` + `iceberg-spark-runtime-3.5_2.12:1.11.0` +
  `spark-sql-kafka-0-10` + `hadoop-aws` / `aws-java-sdk-bundle` for S3A + PostgreSQL JDBC for
  the catalog. Jars are downloaded at build time with pinned versions and checked against Maven
  Central's sha1, never fetched at runtime. The image's Python is 3.10, so `spark_jobs` avoids
  3.11+ syntax.
- `run-job.sh <job>`: the entrypoint, `spark-submit` of `spark_jobs/<job>.py` with
  `SPARK_MASTER` and `SPARK_DRIVER_MEMORY`.
- `spark_jobs/bronze_cdc_ingest.py`: Kafka `oltp.shop.*` -> `lake.bronze.cdc_events`, append,
  20 s trigger, checkpoint `s3a://lakehouse/checkpoints/bronze_cdc_ingest`. Columns: ADR-008.
- `spark_jobs/silver_upsert.py`: Iceberg streaming read from bronze, `Trigger.AvailableNow`,
  `foreachBatch` -> dedup -> quarantine -> `MERGE INTO silver.<table>`. Launched by Airflow.
- `spark_jobs/orders_per_minute.py` (mandatory, week 5): 1-minute window, 5-minute watermark,
  `update` mode, upsert into `silver.orders_per_minute`; makes late-event handling observable.
- `spark_jobs/metrics.py`: `StreamingQueryListener` exposing Prometheus metrics on
  `METRICS_PORT`; last progress time, input rows, batch duration. Kafka lag comes with W4-T02.
- `spark_jobs/catalog.py`: SparkSession with Iceberg catalog `lake` (JdbcCatalog in
  postgres-meta) and S3A pointed at MinIO. `CATALOG_TYPE=rest` is refused until W2-T09.

Unit tests for `to_bronze` need a JVM and skip without one. The host has no Java; run them in
the image:

```
docker run --rm --user root --entrypoint bash -v "$PWD":/repo:ro \
  -e PYTHONPATH=/opt/spark/python:/opt/spark/python/lib/py4j-0.10.9.7-src.zip:/repo/streaming \
  lakehouse/spark:dev -c 'pip install -q pytest && cd /tmp && python3 -m pytest -q \
  -p no:cacheprovider --rootdir=/tmp /repo/tests/unit/test_bronze_cdc_ingest.py'
```
