"""iceberg_maintenance: daily upkeep of the lake's Iceberg tables (D11 W3, W5-D11, W5-D12).

Silver: optimize through Trino, then the Spark job `maintenance` folds the position deletes of
silver.orders and expires snapshots older than a week. Gold: expire_snapshots, one task per table
of lake.gold, in the pool gold_writers with dbt_build. Bronze: compaction of past days only;
bronze snapshots are never expired (ADR-021). Silver tasks share the pool lake_writers with
silver_upsert's merge: two commits to one table at once and the loser fails (ADR-010).
Orphan files are the weekly iceberg_orphans.

Only optimize runs by default. The Spark steps wait for {"expire_and_compact": true} in the run's
conf: the DAG existed before them, so "created paused" does not hold them back, and unpausing it
is not the owner's ok for the W5-D13 ladder.
"""

from datetime import datetime, timedelta

from airflow.providers.docker.operators.docker import DockerOperator
from airflow.sdk import dag, task
from lakehouse import sql
from lakehouse.clients import trino_rows
from lakehouse.maintenance_commands import (
    compact_bronze_command,
    expire_and_compact_enabled,
    expire_command,
    gold_expire_command,
    position_deletes_command,
    silver_tables,
)
from lakehouse.settings import GOLD_WRITERS_POOL, LAKE_WRITERS_POOL, SILVER_KEYS, Settings
from lakehouse.spark_task import spark_job_kwargs

settings = Settings()


@dag(
    schedule="30 3 * * *",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=4),
    default_args={"execution_timeout": timedelta(minutes=60)},
    params={"expire_and_compact": False},
    tags=["maintenance"],
)
def iceberg_maintenance() -> None:
    @task.short_circuit
    def expire_and_compact(params: dict[str, object] | None = None) -> bool:
        enabled = expire_and_compact_enabled(params or {})
        print(
            f"expire_and_compact={enabled}: the Spark steps {'run' if enabled else 'are skipped'}"
        )
        return enabled

    @task(pool=LAKE_WRITERS_POOL)
    def optimize(table: str) -> None:
        for row in trino_rows(settings, sql.optimize(table)):
            print(f"{table}: {row}")

    @task
    def gold_expire_commands() -> list[list[str]]:
        names = [str(row[0]) for row in trino_rows(settings, sql.GOLD_BASE_TABLES)]
        print(f"gold base tables: {names}")
        return [gold_expire_command(name) for name in names]

    rewrite_position_deletes = DockerOperator(
        task_id="rewrite_position_deletes",
        command=position_deletes_command("silver.orders"),
        **spark_job_kwargs(LAKE_WRITERS_POOL),
    )
    expire_silver = DockerOperator(
        task_id="expire_silver",
        command=expire_command(silver_tables()),
        **spark_job_kwargs(LAKE_WRITERS_POOL),
    )
    # A mapped task per table: one table's lost commit race does not fail the others.
    DockerOperator.partial(
        task_id="expire_gold",
        retries=2,
        retry_delay=timedelta(minutes=5),
        **spark_job_kwargs(GOLD_WRITERS_POOL),
    ).expand(command=(gold_commands := gold_expire_commands()))
    compact_bronze = DockerOperator(
        task_id="compact_bronze",
        command=compact_bronze_command(),
        **spark_job_kwargs(LAKE_WRITERS_POOL),
    )

    optimized = optimize.expand(table=list(SILVER_KEYS))
    switch = expire_and_compact()
    # expire_gold waits for the switch only: its own pool, its own tables.
    switch >> [rewrite_position_deletes, gold_commands]
    optimized >> rewrite_position_deletes >> expire_silver >> compact_bronze


iceberg_maintenance()
