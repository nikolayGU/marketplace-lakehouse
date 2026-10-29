"""Decisions the DAGs make, as plain functions over what the tasks read."""

import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, TypedDict

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


class CdcState(TypedDict):
    """What one dq_checks run leaves for the next: the base the next run compares with."""

    writes: int
    flush: str | None
    stalled: bool


def load_cdc_state(raw: str | None) -> CdcState | None:
    """The state a run stored, or None when there is none or it cannot be read (then the next
    run only remembers a base, it never reads a stall out of garbage)."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    writes, flush, stalled = data.get("writes"), data.get("flush"), data.get("stalled")
    if not isinstance(writes, int) or isinstance(writes, bool):
        return None
    if not (flush is None or isinstance(flush, str)) or not isinstance(stalled, bool):
        return None
    return {"writes": writes, "flush": flush, "stalled": stalled}


def cdc_state(
    writes_now: int, flush_now: str | None, remembered: CdcState | None
) -> tuple[bool, CdcState]:
    """Whether CDC stands, and the state to remember. It stands when the source wrote since the
    last run and the slot confirmed nothing; it keeps standing, whatever the source does, until
    the slot moves. Strict where unsure: no slot (CDC is dead and a difference must show red), a
    counter that fell (statistics were reset), or no earlier run mean not stalled."""

    def state(stalled: bool) -> tuple[bool, CdcState]:
        return stalled, {"writes": writes_now, "flush": flush_now, "stalled": stalled}

    if flush_now is None or remembered is None:
        return state(False)
    if flush_now != remembered["flush"] or writes_now < remembered["writes"]:
        return state(False)
    if writes_now > remembered["writes"]:
        return state(True)
    return state(remembered["stalled"])


def count_outcome(differences: bool, resting: bool, stalled: bool) -> str:
    """How a count comparison ends: ok when silver matches Postgres, red when it differs at rest
    and CDC is not stalled, in_flight otherwise: work on its way into silver, or a CDC that
    stands, where the difference is no verdict yet."""
    if not differences:
        return "ok"
    if resting and not stalled:
        return "red"
    return "in_flight"


def skip_source_values(resting: bool, stalled: bool) -> bool:
    """The source-silver value pairs wait: work in flight, or a CDC that stands (an UPDATE moves
    no count, so a stall can hide behind equal counts)."""
    return not resting or stalled


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
