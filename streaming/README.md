# streaming

Spark image and jobs.

- `Dockerfile`: `apache/spark:3.5.9` + `iceberg-spark-runtime-3.5_2.12:1.11.0` +
  `spark-sql-kafka-0-10` + `hadoop-aws` / `aws-java-sdk-bundle` for S3A. Jars are downloaded at
  build time with pinned versions, never at runtime.
- `jobs/bronze_cdc_ingest.py`: Kafka `oltp.shop.*` -> `bronze.cdc_events`, append, 20 s trigger,
  checkpoint `s3a://lakehouse/checkpoints/bronze`.
- `jobs/silver_upsert.py`: Iceberg streaming read from bronze, `Trigger.AvailableNow`,
  `foreachBatch` -> dedup -> quarantine -> `MERGE INTO silver.<table>`. Launched by Airflow.
- `jobs/orders_per_minute.py` (mandatory, week 5): 1-minute window, 5-minute watermark,
  `update` mode, upsert into `silver.orders_per_minute`; makes late-event handling observable.
- `metrics.py`: `StreamingQueryListener` exposing Prometheus metrics on `METRICS_PORT`.
- `catalog.py`: SparkSession builder; `CATALOG_TYPE=jdbc|rest` selects JdbcCatalog in
  postgres-meta or the Lakekeeper REST catalog. S3A settings from env.
