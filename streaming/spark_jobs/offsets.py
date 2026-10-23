"""Kafka offsets from a Structured Streaming progress, without pyspark (W4-T02)."""

import json
from typing import Any


def _parse(offsets: str | None) -> dict[str, dict[int, int]]:
    """`{"topic": {"0": 123}}` as text; `None`, `"null"`, broken JSON and entries of another shape
    mean nothing known for them."""
    if not offsets:
        return {}
    try:
        parsed: Any = json.loads(offsets)
    except ValueError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    known: dict[str, dict[int, int]] = {}
    for topic, partitions in parsed.items():
        if isinstance(partitions, dict):
            known[topic] = {
                int(partition): offset
                for partition, offset in partitions.items()
                if partition.isdigit() and type(offset) is int
            }
    return known


def kafka_lag(end_offset: str | None, latest_offset: str | None) -> dict[tuple[str, int], int]:
    """Messages the source still has past the last batch, per (topic, partition).

    A partition missing from `end_offset` is counted from 0. Rows never go negative. Without
    `latest_offset` (the first batch reports `null`) there is nothing to compare, so no rows.
    """
    ended = _parse(end_offset)
    lag: dict[tuple[str, int], int] = {}
    for topic, partitions in _parse(latest_offset).items():
        for partition, latest in partitions.items():
            read = ended.get(topic, {}).get(partition, 0)
            lag[(topic, partition)] = max(latest - read, 0)
    return lag
