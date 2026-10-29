"""SQL the DAGs run through Trino (catalog lake) and Postgres (schema shop)."""

from lakehouse.settings import SHOP_SLOT

LATEST_BRONZE_SNAPSHOT = """
select snapshot_id, committed_at
from lake.bronze."cdc_events$snapshots"
order by committed_at desc
limit 1
"""


# One row: rows written to schema shop since the statistics were last reset (only a write moves
# it; pg_current_wal_lsn grows without one), and the position the slot has confirmed, as text
# (NULL when the slot does not exist).
CDC_PROGRESS = f"""
select
  (select coalesce(sum(n_tup_ins + n_tup_upd + n_tup_del), 0)
   from pg_stat_user_tables where schemaname = 'shop'),
  (select confirmed_flush_lsn::text
   from pg_replication_slots where slot_name = '{SHOP_SLOT}')
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


def oldest_unmerged_snapshot_age(remembered: str) -> str | None:
    """Seconds since the oldest bronze snapshot committed after the one silver merged last.
    None for an id that is not a plain number: it goes into the text of the query."""
    if not remembered.isdigit():
        return None
    snapshots = 'lake.bronze."cdc_events$snapshots"'
    return f"""
select date_diff('second', min(committed_at), current_timestamp)
from {snapshots}
where committed_at > (select committed_at from {snapshots} where snapshot_id = {remembered})
"""


BRONZE_FRESHNESS = """
select source_table, date_diff('second', max(ingest_ts), current_timestamp)
from lake.bronze.cdc_events
group by source_table
"""


def optimize(table: str) -> str:
    return f"alter table lake.silver.{table} execute optimize"


# The gold tables dbt materialized as tables (views have no snapshots to expire).
GOLD_BASE_TABLES = """
select table_name
from lake.information_schema.tables
where table_schema = 'gold' and table_type = 'BASE TABLE'
order by table_name
"""
