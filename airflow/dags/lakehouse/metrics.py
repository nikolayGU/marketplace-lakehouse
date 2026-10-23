"""Gauges from dq_checks to statsd-exporter, as DogStatsD lines over UDP (W4-D2).

No airflow import, so the tests run on the host. UDP gives no delivery receipt: a lost packet
shows only as a missing series in Prometheus, and the mapping's TTL removes a series that stops
arriving.
"""

import math
import re
import socket
from collections.abc import Iterable, Mapping
from typing import Any

_UNSAFE_TAG = re.compile(r"[^A-Za-z0-9_.\-/]")


def gauge_line(name: str, value: Any, tags: Mapping[str, str]) -> str | None:
    """`name:value|g|#k:v,k2:v2`, or None when the value must not be sent: missing, not a number,
    not finite, or negative (StatsD reads `-5|g` as "lower the gauge by 5")."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    text = f"{number:.0f}" if number == int(number) else repr(number)
    line = f"{name}:{text}|g"
    if tags:
        line += "|#" + ",".join(f"{k}:{_UNSAFE_TAG.sub('_', v)}" for k, v in tags.items())
    return line


def send(lines: Iterable[str | None], host: str, port: int) -> None:
    """One datagram per line; None lines are skipped. A failure (an unresolvable host while the
    obs profile is down, a closed port) is printed and does not fail the task."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            for line in lines:
                if line is not None:
                    udp.sendto(line.encode(), (host, port))
    except OSError as error:
        print(f"statsd: could not send to {host}:{port}: {error}")
