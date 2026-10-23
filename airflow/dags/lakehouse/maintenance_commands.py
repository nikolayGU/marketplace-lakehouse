"""Commands the maintenance DAGs hand to the `maintenance` Spark job (streaming/spark_jobs/
maintenance.py). The job checks its own rules; tests/unit/test_dags.py feeds it every command
built here."""

from collections.abc import Mapping, Sequence

from lakehouse.settings import MAINTENANCE_TABLES, RETENTION_DAYS

BRONZE_EVENTS = "lake.bronze.cdc_events"
BRONZE_ORPHAN_SUFFIX = "metadata"

# Rendered by Airflow from the run's params. Only a real `false` (a boolean from the trigger form
# or conf) deletes: a string such as "false" is truthy in Jinja, so it is no reason to.
DRY_RUN_FLAG = "{{ '--no-dry-run' if params.dry_run is sameas false else '--dry-run' }}"


def dry_run_flag(params: Mapping[str, object]) -> str:
    """DRY_RUN_FLAG in Python, for commands a mapped task gets from XCom: Airflow does not render
    those, so the task that builds them resolves the flag from the run's params itself."""
    return "--no-dry-run" if params.get("dry_run") is False else "--dry-run"


def expire_and_compact_enabled(params: Mapping[str, object]) -> bool:
    """iceberg_maintenance runs its Spark steps (expire, position deletes, bronze compaction) only
    for a real `true`: unpausing the DAG is not the owner's ok for the W5-D13 ladder."""
    return params.get("expire_and_compact") is True


def silver_tables() -> list[str]:
    return [f"silver.{table}" for table in MAINTENANCE_TABLES]


def gold_table(name: str) -> str:
    return f"gold.{name}"


def expire_command(tables: Sequence[str]) -> list[str]:
    return ["maintenance", "expire", "--days", str(RETENTION_DAYS), *tables]


def gold_expire_command(name: str) -> list[str]:
    return expire_command([gold_table(name)])


def position_deletes_command(table: str) -> list[str]:
    return ["maintenance", "rewrite-position-deletes", table]


def compact_bronze_command() -> list[str]:
    # Past days only: the stream is still committing to today's partitions.
    return ["maintenance", "rewrite-data", "--before-today", BRONZE_EVENTS]


def orphans_command(tables: Sequence[str], location_suffix: str | None = None) -> list[str]:
    suffix = ["--location-suffix", location_suffix] if location_suffix else []
    return ["maintenance", "orphans", DRY_RUN_FLAG, *suffix, *tables]


def gold_orphans_command(name: str, params: Mapping[str, object]) -> list[str]:
    return ["maintenance", "orphans", dry_run_flag(params), gold_table(name)]
