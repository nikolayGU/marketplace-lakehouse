"""iceberg_orphans: weekly search for orphan files, a dry run unless told otherwise (W5-D13).

remove_orphan_files deletes files no snapshot references. A wrong `older_than` deletes files of
a commit in flight, and on bronze that cannot be undone, so: the job refuses less than 7 days,
bronze only in its metadata directory (never data, ADR-021), and the DAG deletes only when the
run's conf has {"dry_run": false}. The DAG is created paused (AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_
CREATION): the owner reads the dry-run list before unpausing it.
"""

from datetime import datetime, timedelta

from airflow.providers.docker.operators.docker import DockerOperator
from airflow.sdk import dag, task
from lakehouse import sql
from lakehouse.clients import trino_rows
from lakehouse.maintenance_commands import (
    BRONZE_EVENTS,
    BRONZE_ORPHAN_SUFFIX,
    gold_orphans_command,
    orphans_command,
    silver_tables,
)
from lakehouse.settings import GOLD_WRITERS_POOL, LAKE_WRITERS_POOL, Settings
from lakehouse.spark_task import spark_job_kwargs

settings = Settings()


@dag(
    schedule="0 4 * * 0",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    params={"dry_run": True},
    tags=["maintenance"],
)
def iceberg_orphans() -> None:
    @task
    def gold_orphan_commands(params: dict[str, object] | None = None) -> list[list[str]]:
        # Airflow does not render templates in values a mapped task gets from XCom, so the dry
        # run flag is resolved here from the run's params, not left to DRY_RUN_FLAG.
        names = [str(row[0]) for row in trino_rows(settings, sql.GOLD_BASE_TABLES)]
        print(f"gold base tables: {names}")
        return [gold_orphans_command(name, params or {}) for name in names]

    orphans_silver = DockerOperator(
        task_id="orphans_silver",
        command=orphans_command(silver_tables()),
        **spark_job_kwargs(LAKE_WRITERS_POOL),
    )
    DockerOperator.partial(
        task_id="orphans_gold",
        retries=2,
        retry_delay=timedelta(minutes=5),
        **spark_job_kwargs(GOLD_WRITERS_POOL),
    ).expand(command=gold_orphan_commands())
    orphans_bronze_metadata = DockerOperator(
        task_id="orphans_bronze_metadata",
        command=orphans_command([BRONZE_EVENTS], location_suffix=BRONZE_ORPHAN_SUFFIX),
        **spark_job_kwargs(LAKE_WRITERS_POOL),
    )
    # orphans_gold depends on nothing above: its own pool, its own tables.
    # One after another, so a failed list stops before the next table's delete.
    orphans_silver >> orphans_bronze_metadata


iceberg_orphans()
