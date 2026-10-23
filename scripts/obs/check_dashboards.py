"""Runs every panel query of the Grafana dashboards against Prometheus (W4-T04).

A panel with a typo in a metric name shows "No data" exactly like a metric with no data yet, so
this prints each panel whose query returns nothing and exits 1. Usage:
    uv run python scripts/obs/check_dashboards.py [dashboard.json ...]
"""

import json
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

PROMETHEUS = "http://127.0.0.1:9090"
DASHBOARDS = Path(__file__).parents[2] / "observability" / "grafana" / "dashboards"

Query = Callable[[str], list[dict[str, Any]]]


def prometheus_query(expr: str) -> list[dict[str, Any]]:
    url = f"{PROMETHEUS}/api/v1/query?" + urllib.parse.urlencode({"query": expr})
    with urllib.request.urlopen(url, timeout=10) as response:
        result: list[dict[str, Any]] = json.load(response)["data"]["result"]
        return result


def panels(dashboard: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Panels of a dashboard, including those inside collapsed rows."""
    for panel in dashboard.get("panels", []):
        yield panel
        yield from panels(panel)


def check(paths: Sequence[Path], query: Query) -> int:
    ok, empty = 0, []
    for path in paths:
        for panel in panels(json.loads(path.read_text())):
            for target in panel.get("targets", []):
                expr = target.get("expr")
                if not expr:
                    continue
                try:
                    rows = query(expr)
                except OSError as error:
                    print(f"query failed for {expr}: {error}")
                    rows = []
                if rows:
                    ok += 1
                else:
                    empty.append(f"{path.name}: {panel.get('title', '?')}: {expr}")
    print(f"panels ok: {ok}")
    for line in empty:
        print(f"empty: {line}")
    return 1 if empty else 0


def main(argv: Sequence[str]) -> int:
    paths = [Path(a) for a in argv] or sorted(DASHBOARDS.glob("*.json"))
    return check(paths, prometheus_query)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
