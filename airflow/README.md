# airflow

Airflow 3.3.2, LocalExecutor, batch only: the bronze stream is not a DAG (ADR-011). How to run it:
OPERATIONS.md, "Airflow".

| DAG | Schedule | Does |
|---|---|---|
| `silver_upsert` | every 5 min, `max_active_runs=1`, 1 retry | skips without a new bronze snapshot; DockerOperator starts spark-silver (`Trigger.AvailableNow`) in pool `lake_writers`; publishes Asset `lake.silver` |
| `dbt_build` | Asset `lake.silver` | `dbt build` of `lake.gold` (BashOperator, `/opt/dbt-venv`), no retries |
| `dq_checks` | every 15 min | a duplicate key in silver, or silver against Postgres at rest, fails it; repeats, no-ops, quarantine and freshness are logged; counts runs in a row that find gold older than silver at rest (Variable `dq_gold_stale_runs`, metric `lakehouse_dq_gold_stale_runs`, alert `GoldStaleAtRest`) |
| `iceberg_maintenance` | daily | `optimize` of the silver tables through Trino, in pool `lake_writers`; the Spark steps (position deletes, `expire_snapshots`, bronze compaction) only in a run with `{"expire_and_compact": true}` |
| `iceberg_orphans` | weekly (Sunday 04:00), created paused | `remove_orphan_files` of silver, gold and bronze metadata; a dry run unless the run has `{"dry_run": false}`; stays paused (ADR-025) |

- A paused `dbt_build` misses the `lake.silver` event: Airflow queues no Asset event for a paused
  DAG and does not replay it on unpause. Trigger it by hand after unpausing
  (OPERATIONS.md, "Airflow"); `GoldStaleAtRest` fires if that is forgotten.
- `dags/lakehouse/`: settings from the environment, SQL, decisions, clients. It imports no
  airflow, so `tests/unit/test_dags.py` runs it on the host; `.airflowignore` keeps it out of DAG
  parsing.
- `Dockerfile`: `apache/airflow:3.3.2-python3.12`, the docker provider of the image, the clients
  the DAGs import, dbt in `/opt/dbt-venv`.
