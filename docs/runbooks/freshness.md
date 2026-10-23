# Silver behind bronze (FreshnessAbove15m)

Symptom: alert `FreshnessAbove15m`: `lakehouse_silver_lag_seconds` above 900. It is the age of the
oldest bronze snapshot that `silver_upsert` has not merged. It is 0 at rest and it is not the age
of the data: `lakehouse_table_freshness_seconds` grows for hours between replay bursts, and
that is no traffic, not a fault. The alert is measured by `dq_checks` every 15 minutes, so it
shows up to 15 minutes after the lag begins.

1. Is `silver_upsert` unpaused and is the scheduler up? In Airflow (`http://127.0.0.1:8090`) or
   `docker compose ps airflow-scheduler`. A paused DAG is the usual cause: the alert is what
   a deliberately paused silver looks like.
2. Last runs: `airflow dags list-runs silver_upsert`. Red: the `merge` task log has the Spark
   error; the other tasks only read.
3. `merge` red because of Trino or MinIO: `make status`, memory of `trino` and `minio`
   (`docker stats --no-stream`).
4. Running but slow: a merge after a long pause reads a large part of bronze; it ends by itself.
   `merge` needs the `lake_writers` pool slot, which `iceberg_maintenance` also uses.
5. Nothing is stuck but the Variable is behind: `airflow variables get silver_upsert_last_bronze_snapshot`
   against `select max_by(snapshot_id, committed_at) from lake.bronze."cdc_events$snapshots"`
   in Trino. A different id means the next run merges.
6. Never run `make silver` by hand while the scheduler is up: two writers on one checkpoint.
   `make silver` refuses; trigger the DAG instead (`airflow dags trigger silver_upsert`).

Reproduce: pause `silver_upsert`, `make replay-burst SECONDS=60`, wait (OPERATIONS.md,
"Observability").
