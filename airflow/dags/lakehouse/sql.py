"""SQL the DAGs run through Trino (catalog lake) and Postgres (schema shop)."""

LATEST_BRONZE_SNAPSHOT = """
select snapshot_id, committed_at
from lake.bronze."cdc_events$snapshots"
order by committed_at desc
limit 1
"""


def duplicate_keys(table: str, key: tuple[str, ...]) -> str:
    columns = ", ".join(key)
    return f"""
select count(*) from (
    select {columns} from lake.silver.{table} group by {columns} having count(*) > 1
)
"""


def silver_live_rows(table: str) -> str:
    return f"select count(*) from lake.silver.{table} where not _is_deleted"


def postgres_rows(table: str) -> str:
    return f"select count(*) from shop.{table}"


def freshness_seconds(table: str) -> str:
    # quarantine has no _updated_at: its rows carry the time they were quarantined.
    column = "quarantined_at" if table == "quarantine" else "_updated_at"
    return f"select date_diff('second', max({column}), current_timestamp) from lake.silver.{table}"


# Delivery repeats: Debezium sent the same change again (same LSN), as after a Connect kill.
LSN_REPEATS_LAST_HOUR = """
select count(*) from (
    select source_table, key, lsn
    from lake.bronze.cdc_events
    where ingest_ts >= current_timestamp - interval '1' hour and lsn is not null
    group by source_table, key, lsn
    having count(*) > 1
)
"""

# Source repeats: an UPDATE that changed nothing gets a new LSN, so the query above misses it.
NOOP_UPDATES_LAST_HOUR = """
select count(*)
from lake.bronze.cdc_events
where ingest_ts >= current_timestamp - interval '1' hour and op = 'u' and before = after
"""

QUARANTINED_LAST_HOUR = """
select count(*)
from lake.silver.quarantine
where quarantined_at >= current_timestamp - interval '1' hour
"""


def optimize(table: str) -> str:
    return f"alter table lake.silver.{table} execute optimize"
