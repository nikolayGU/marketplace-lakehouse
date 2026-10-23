"""Decisions the DAGs make, as plain functions over what the tasks read."""

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

# Bronze commits every 20 s while Kafka has events; five quiet minutes mean the source stopped.
QUIET = timedelta(minutes=5)


def new_bronze_snapshot(latest: int | None, remembered: str | None) -> int | None:
    """Bronze's latest snapshot when silver has not merged it yet, else None."""
    if latest is None or str(latest) == remembered:
        return None
    return latest


def at_rest(
    latest: int | None,
    committed_at: datetime | None,
    remembered: str | None,
    now: datetime,
) -> bool:
    """Nothing is on its way into silver: bronze has been quiet for QUIET and silver_upsert has
    merged its latest snapshot. Only then may silver and Postgres be compared."""
    if latest is None:
        return True
    if committed_at is None or now - committed_at < QUIET:
        return False
    return str(latest) == remembered


def silver_lag_seconds(
    latest: int | None, remembered: str | None, oldest_unmerged_age: int | None
) -> int | None:
    """How long the oldest bronze snapshot silver has not merged has waited, 0 when silver has
    merged the latest one. None when it cannot be told: no Variable yet, or the remembered
    snapshot is not in bronze's history (then "nothing newer" would read as a false 0)."""
    if latest is None:
        return 0
    if remembered is None:
        return None
    if str(latest) == remembered:
        return 0
    return oldest_unmerged_age


def count_differences(
    postgres: Mapping[str, int], silver: Mapping[str, int]
) -> dict[str, tuple[int, int]]:
    """Tables whose live row counts differ, as {table: (postgres, silver)}."""
    return {t: (n, silver.get(t, 0)) for t, n in postgres.items() if silver.get(t, 0) != n}


def freshness_query_failures(sources: Mapping[str, Any]) -> list[str]:
    """Sources whose freshness query failed, from dbt's target/sources.json. dbt exits 1 for a
    stale source too; that one (status warn or error) is no traffic, not a broken check."""
    results = sources.get("results", [])
    return [r["unique_id"] for r in results if r.get("status") == "runtime error"]
