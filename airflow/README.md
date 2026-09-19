# airflow

Airflow 3, LocalExecutor, batch only. The bronze stream is not a DAG.

| DAG | Schedule | Does |
|---|---|---|
| `silver_upsert` | every 5 min, `max_active_runs=1` | DockerOperator runs `spark-silver` with `Trigger.AvailableNow` |
| `dbt_build` | on Asset `silver` | `dbt build` (BashOperator), then `dbt docs generate` |
| `dq_checks` | every 15 min | freshness per table, reconciliation source vs silver vs gold, duplicate ratio, quarantine rows; pushes gauges |
| `iceberg_maintenance` | daily | `rewrite_data_files`, `rewrite_position_delete_files`, `expire_snapshots`, `remove_orphan_files` |

`Dockerfile`: `apache/airflow:3.3.2` + `dbt-trino` + `apache-airflow-providers-docker`.
