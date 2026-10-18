"""SQL the DAGs run through Trino (catalog lake)."""

LATEST_BRONZE_SNAPSHOT = """
select snapshot_id, committed_at
from lake.bronze."cdc_events$snapshots"
order by committed_at desc
limit 1
"""
