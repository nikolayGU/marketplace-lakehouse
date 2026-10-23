"""Numbers out of a streaming progress report, without pyspark (W5-T01b)."""

import calendar
import re
from collections.abc import Iterable, Mapping
from typing import Any

_ISO = re.compile(r"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(\.\d+)?Z")


def watermark_seconds(event_time: Mapping[str, str] | None) -> float | None:
    """Unix seconds of `eventTime["watermark"]` (UTC, ISO text), None when the report has none.
    Python 3.10 `fromisoformat` rejects the trailing Z, hence the pattern."""
    text = (event_time or {}).get("watermark")
    match = _ISO.fullmatch(text) if isinstance(text, str) else None
    if match is None:
        return None
    year, month, day, hour, minute, second = (int(g) for g in match.groups()[:6])
    fraction = float(match.group(7) or 0)
    return calendar.timegm((year, month, day, hour, minute, second)) + fraction


def _count(operator: Any, field: str) -> int:
    value = operator.get(field) if isinstance(operator, Mapping) else getattr(operator, field, 0)
    return value if isinstance(value, int) and value > 0 else 0


def state_totals(operators: Iterable[Any] | None) -> tuple[int, int]:
    """(rows held in state, rows the watermark dropped in this batch) over the stateful
    operators of one progress report. Operators come as objects (the listener) or dicts."""
    held = dropped = 0
    for operator in operators or ():
        held += _count(operator, "numRowsTotal")
        dropped += _count(operator, "numRowsDroppedByWatermark")
    return held, dropped
