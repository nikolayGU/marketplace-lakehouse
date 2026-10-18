"""dq_checks: every 15 minutes, check silver against its own keys and against Postgres.

Fails the run: a primary key twice in a silver table; live row counts that differ from Postgres
while nothing is in flight (checks.at_rest). Only logged, as `dq <name>=<value>` lines that W4
exports: the same differences while work is in flight, delivery repeats and source no-ops in the
last hour, new quarantine rows, freshness per silver table, dbt source freshness.
"""

from datetime import UTC, datetime

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import Variable, dag, task
from lakehouse import checks, sql
from lakehouse.clients import postgres_value, trino_rows, trino_value
from lakehouse.settings import (
    LAST_BRONZE_SNAPSHOT,
    SILVER_KEYS,
    SOURCE_TABLES,
    Settings,
    dbt_command,
)

settings = Settings()


@dag(
    schedule="*/15 * * * *",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    tags=["dq"],
)
def dq_checks() -> None:
    @task
    def silver_keys_unique() -> None:
        duplicates = {
            table: int(trino_value(settings, sql.duplicate_keys(table, key)))
            for table, key in SILVER_KEYS.items()
        }
        for table, count in duplicates.items():
            print(f"dq silver_duplicate_keys{{table={table}}}={count}")
        failed = {table: count for table, count in duplicates.items() if count}
        if failed:
            raise ValueError(f"silver holds a primary key more than once: {failed}")

    @task
    def silver_matches_postgres() -> None:
        rows = trino_rows(settings, sql.LATEST_BRONZE_SNAPSHOT)
        latest, committed_at = (int(rows[0][0]), rows[0][1]) if rows else (None, None)
        remembered = Variable.get(LAST_BRONZE_SNAPSHOT, default=None)
        postgres = {t: int(postgres_value(settings, sql.postgres_rows(t))) for t in SOURCE_TABLES}
        silver = {t: int(trino_value(settings, sql.silver_live_rows(t))) for t in SOURCE_TABLES}
        differences = checks.count_differences(postgres, silver)
        resting = checks.at_rest(latest, committed_at, remembered, datetime.now(UTC))
        print(f"dq reconcile_tables_differing={len(differences)} at_rest={resting}")
        for table, (source, lake) in differences.items():
            print(f"{table}: postgres {source}, silver {lake}")
        if differences and resting:
            raise ValueError(f"silver differs from Postgres at rest: {differences}")
        if differences:
            print("in flight: bronze or silver has not caught up yet, no verdict")

    @task
    def report() -> None:
        print(f"dq lsn_repeats_last_hour={trino_value(settings, sql.LSN_REPEATS_LAST_HOUR)}")
        print(f"dq noop_updates_last_hour={trino_value(settings, sql.NOOP_UPDATES_LAST_HOUR)}")
        print(f"dq quarantined_last_hour={trino_value(settings, sql.QUARANTINED_LAST_HOUR)}")
        for table in SILVER_KEYS:
            seconds = trino_value(settings, sql.freshness_seconds(table))
            print(f"dq silver_freshness_seconds{{table={table}}}={seconds}")

    source_freshness = BashOperator(
        task_id="dbt_source_freshness",
        # Exit code 1 is a stale source: no traffic, which is logged, not a failure. 2 is dbt
        # itself failing.
        bash_command=(
            dbt_command("source freshness") + "; rc=$?; "
            'echo "dq dbt_source_freshness_exit_code=$rc"; [ "$rc" -le 1 ]'
        ),
    )

    [silver_keys_unique(), silver_matches_postgres(), report(), source_freshness]


dq_checks()
