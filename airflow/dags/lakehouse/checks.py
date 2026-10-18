"""Decisions the DAGs make, as plain functions over what the tasks read."""


def new_bronze_snapshot(latest: int | None, remembered: str | None) -> int | None:
    """Bronze's latest snapshot when silver has not merged it yet, else None."""
    if latest is None or str(latest) == remembered:
        return None
    return latest
