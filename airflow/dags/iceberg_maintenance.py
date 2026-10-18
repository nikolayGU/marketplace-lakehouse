"""iceberg_maintenance: daily optimize of every silver table through Trino (D11).

Compaction of small files, and folding the delete files of merge-on-read silver.orders. In the
pool lake_writers with silver_upsert's merge: two commits to silver.orders at once and the loser
fails (ADR-010). Bronze, expire_snapshots and remove_orphan_files are week 5 (ADR-021).
"""

from datetime import datetime

from airflow.sdk import dag, task
from lakehouse import sql
from lakehouse.clients import trino_rows
from lakehouse.settings import LAKE_WRITERS_POOL, SILVER_KEYS, Settings

settings = Settings()


@dag(
    schedule="@daily",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    tags=["maintenance"],
)
def iceberg_maintenance() -> None:
    @task(pool=LAKE_WRITERS_POOL)
    def optimize(table: str) -> None:
        for row in trino_rows(settings, sql.optimize(table)):
            print(f"{table}: {row}")

    optimize.expand(table=list(SILVER_KEYS))


iceberg_maintenance()
