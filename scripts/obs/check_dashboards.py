"""Runs every panel query of the Grafana dashboards against Prometheus and Trino (W4-T04, W6-T01).

A panel with a typo in a metric name shows "No data" exactly like a metric with no data yet, so
this prints each panel whose query returns nothing and exits 1. A query ending in `or vector(0)`
always returns a row, so for it each metric name must have had a series within the 7 days of
retention instead. A Trino panel (`rawSQL`, datasource trino) runs its SQL on the published Trino
port: over plain HTTP like Prometheus, with no `docker compose exec` and no client in the image.
Usage:
    uv run python scripts/obs/check_dashboards.py [dashboard.json ...]
"""

import json
import re
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from time import monotonic
from typing import Any

PROMETHEUS = "http://127.0.0.1:9090"
TRINO_DEADLINE = 120.0  # seconds for one statement, all pages together
TRINO = "http://127.0.0.1:8080"  # compose publishes it on ${BIND_IP}, 127.0.0.1 in .env.example
DASHBOARDS = Path(__file__).parents[2] / "observability" / "grafana" / "dashboards"

Query = Callable[[str], list[dict[str, Any]]]

# Words of PromQL that are not metric names; ALERTS exists only while an alert fires.
NOT_METRICS = {"by", "without", "on", "ignoring", "group_left", "group_right", "bool", "offset"}
NOT_METRICS |= {"or", "and", "unless", "ALERTS", "ALERTS_FOR_STATE"}
GROUPING = re.compile(r"\b(by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)")
NAME = re.compile(r"(?<![\w:])[a-zA-Z_:][\w:]*(?![\w:]*\s*\()")


def metric_names(expr: str) -> set[str]:
    """The metric names of a query: no functions, label names, label values or keywords."""
    bare = re.sub(r'"[^"]*"|\{[^}]*\}|\[[^\]]*\]', " ", expr)
    bare = GROUPING.sub(" ", bare)
    return {name for name in NAME.findall(bare) if name not in NOT_METRICS}


def prometheus_query(expr: str) -> list[dict[str, Any]]:
    url = f"{PROMETHEUS}/api/v1/query?" + urllib.parse.urlencode({"query": expr})
    with urllib.request.urlopen(url, timeout=10) as response:
        result: list[dict[str, Any]] = json.load(response)["data"]["result"]
        return result


def trino_query(sql: str) -> list[dict[str, Any]]:
    """Rows of a statement, read page by page along nextUri.

    A Trino error or a statement still running after TRINO_DEADLINE seconds raises OSError.
    """
    deadline = monotonic() + TRINO_DEADLINE
    request = urllib.request.Request(
        f"{TRINO}/v1/statement",
        data=sql.encode(),
        headers={"X-Trino-User": "dashboard-check", "X-Trino-Catalog": "lake"},
        method="POST",
    )
    rows: list[dict[str, Any]] = []
    while True:
        if monotonic() > deadline:
            raise OSError(f"Trino statement not finished in {TRINO_DEADLINE:.0f} s")
        with urllib.request.urlopen(request, timeout=30) as response:
            page = json.loads(response.read())
        if "error" in page:
            raise OSError(page["error"].get("message", "Trino query failed"))
        rows.extend({"row": row} for row in page.get("data", []))
        if "nextUri" not in page:
            return rows
        request = urllib.request.Request(
            page["nextUri"], headers={"X-Trino-User": "dashboard-check"}
        )


def panels(dashboard: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Panels of a dashboard, including those inside collapsed rows."""
    for panel in dashboard.get("panels", []):
        yield panel
        yield from panels(panel)


def check(paths: Sequence[Path], query: Query, trino: Query = trino_query) -> int:
    ok, empty = 0, []
    for path in paths:
        for panel in panels(json.loads(path.read_text())):
            for target in panel.get("targets", []):
                expr = target.get("expr") or target.get("rawSQL")
                if not expr:
                    continue
                try:
                    rows = trino(expr) if "rawSQL" in target else query(expr)
                    # A counter of failures appears with the first failure: a name had a series
                    # within the retention (7d) or it is a typo.
                    if (
                        "expr" in target
                        and "or vector(" in expr
                        and any(
                            not query(f"group(last_over_time({name}[7d]))")
                            for name in sorted(metric_names(expr))
                        )
                    ):
                        rows = []
                except (OSError, ValueError) as error:
                    print(f"query failed for {expr}: {error}")
                    rows = []
                if rows:
                    ok += 1
                else:
                    empty.append(f"{path.name}: {panel.get('title', '?')}: {expr}")
    print(f"queries ok: {ok}")
    for line in empty:
        print(f"empty: {line}")
    return 1 if empty else 0


def main(argv: Sequence[str]) -> int:
    paths = [Path(a) for a in argv] or sorted(DASHBOARDS.glob("*.json"))
    return check(paths, prometheus_query)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
