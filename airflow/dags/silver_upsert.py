"""silver_upsert: every 5 minutes, merge what bronze committed into silver (D10, ADR-021).

The merge is spark-silver, the same container as `make silver`, started by DockerOperator. A run
without a new bronze snapshot skips the merge and publishes no Asset event, so dbt_build sleeps.
"""

import os
from datetime import datetime, timedelta

from airflow.providers.docker.operators.docker import DockerOperator
from airflow.sdk import Asset, Variable, dag, task
from lakehouse import checks, sql
from lakehouse.clients import trino_rows
from lakehouse.settings import (
    LAKE_WRITERS_POOL,
    LAST_BRONZE_SNAPSHOT,
    SILVER_ASSET_NAME,
    Settings,
    spark_silver_environment,
)

settings = Settings()
public_env, private_env = spark_silver_environment(os.environ)


@dag(
    schedule="*/5 * * * *",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=1)},
    tags=["silver"],
)
def silver_upsert() -> None:
    @task.short_circuit
    def bronze_has_new_snapshot() -> int | bool:
        rows = trino_rows(settings, sql.LATEST_BRONZE_SNAPSHOT)
        latest = int(rows[0][0]) if rows else None
        remembered = Variable.get(LAST_BRONZE_SNAPSHOT, default=None)
        new = checks.new_bronze_snapshot(latest, remembered)
        print(f"bronze latest snapshot {latest}, silver merged {remembered}")
        return new if new is not None else False

    merge = DockerOperator(
        task_id="merge",
        image=settings.spark_image,
        command=["silver_upsert"],
        network_mode=settings.lake_network,
        environment=public_env,
        private_environment=private_env,
        mem_limit="2g",
        # Airflow runs in a container: a host temp dir to mount does not exist.
        mount_tmp_dir=False,
        auto_remove="success",
        pool=LAKE_WRITERS_POOL,
        outlets=[Asset(SILVER_ASSET_NAME)],
        do_xcom_push=False,
    )

    @task
    def remember_snapshot(snapshot_id: int) -> None:
        # The id read before the merge, not bronze's current one: whatever bronze committed
        # during the merge is the next run's work.
        Variable.set(LAST_BRONZE_SNAPSHOT, str(snapshot_id))

    snapshot = bronze_has_new_snapshot()
    snapshot >> merge >> remember_snapshot(snapshot)


silver_upsert()
