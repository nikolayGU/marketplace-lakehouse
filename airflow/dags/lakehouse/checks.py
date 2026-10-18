"""Decisions the DAGs make, as plain functions over what the tasks read."""

from collections.abc import Mapping
from datetime import datetime, timedelta

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


def count_differences(
    postgres: Mapping[str, int], silver: Mapping[str, int]
) -> dict[str, tuple[int, int]]:
    """Tables whose live row counts differ, as {table: (postgres, silver)}."""
    return {t: (n, silver.get(t, 0)) for t, n in postgres.items() if silver.get(t, 0) != n}
