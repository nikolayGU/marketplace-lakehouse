"""Commands the maintenance DAGs hand to the `maintenance` Spark job (streaming/spark_jobs/
maintenance.py). The job checks its own rules; tests/unit/test_dags.py feeds it every command
built here."""

from collections.abc import Sequence

from lakehouse.settings import MAINTENANCE_TABLES, RETENTION_DAYS

BRONZE_EVENTS = "lake.bronze.cdc_events"
BRONZE_ORPHAN_SUFFIX = "metadata"

# Rendered by Airflow from the run's params. Only a real `false` (a boolean from the trigger form
# or conf) deletes: a string such as "false" is truthy in Jinja, so it is no reason to.
DRY_RUN_FLAG = "{{ '--no-dry-run' if params.dry_run is sameas false else '--dry-run' }}"


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
