"""Runs every panel query of the Grafana dashboards against Prometheus and Trino (W4-T04, W6-T01).

A panel with a typo in a metric name shows "No data" exactly like a metric with no data yet, so
this prints each panel whose query returns nothing and exits 1. A query ending in `or vector(0)`
always returns a row, so for it each metric name must have had a series within the 7 days of
retention instead. An empty panel is idle, not broken (printed as `idle:`, exit code 0), only if
its query ran without error and all of these hold: every metric is a `spark_streaming_*` name
whose type Prometheus knows from its metadata (a counter only with `_total`); the expression names
one Spark query by `query="..."` and has no vector matching (`on`, `ignoring`, `group_*`); that
query has no `spark_streaming_batch_duration_seconds` series (the listener sets it on every
progress event, so none means no batch with data since the start); it reported progress or idle
within the last 300 s (the SparkNoBatch5m threshold); and every selector of the expression had a
series within the retention (7 days), which a typo in a name, label name or label value never had.
After 7 days without a batch with data, or on a fresh Prometheus volume, such panels are `empty`.
A Trino panel (`rawSQL`, datasource trino) runs its SQL on the published Trino port as the
datasource user `grafana`, so the access rules are part of the check: over plain HTTP like
Prometheus, with no `docker compose exec` and no client in the image.
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
# The Trino session user of the Grafana datasource (basicAuthUser in provisioning/datasources/
# trino.yml; a unit test keeps them equal): a panel that works as another user may fail in Grafana.
TRINO_USER = "grafana"
DASHBOARDS = Path(__file__).parents[2] / "observability" / "grafana" / "dashboards"

Query = Callable[[str], list[dict[str, Any]]]
Known = Callable[[str], bool]
Flag = Callable[[str], bool]
BatchAge = Callable[[str], float | None]

IDLE_AFTER = 300.0  # seconds without a batch: same threshold as the SparkNoBatch5m alert
SPARK_PREFIX = "spark_streaming_"
QUERY_LABEL = re.compile(r'\bquery="([^"]+)"')
VECTOR_MATCHING = re.compile(r"\b(on|ignoring|group_left|group_right)\s*\(")

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


def prometheus_get(path: str) -> dict[str, Any]:
    with urllib.request.urlopen(f"{PROMETHEUS}{path}", timeout=10) as response:
        body: dict[str, Any] = json.load(response)
        return body


def metric_known(get: Callable[[str], dict[str, Any]] = prometheus_get) -> Known:
    """Whether Prometheus has metadata for a name; a counter is listed without its `_total`."""

    def types(name: str) -> set[str]:
        data = get("/api/v1/metadata?" + urllib.parse.urlencode({"metric": name}))["data"]
        return {entry["type"] for entry in data.get(name, [])}

    def known(name: str) -> bool:
        if name.endswith("_total") and "counter" in types(name.removesuffix("_total")):
            return True
        own = types(name)
        return bool(own) and "counter" not in own

    return known


def has_batches(query_name: str) -> bool:
    """Whether the query set its batch duration since the current run started."""
    return bool(prometheus_query(f'spark_streaming_batch_duration_seconds{{query="{query_name}"}}'))


def seen_before(selector: str) -> bool:
    """Whether a selector had a series within the retention of Prometheus (7d)."""
    return bool(prometheus_query(f"group(last_over_time({selector}[7d]))"))


def selectors(expr: str, names: set[str]) -> list[str]:
    """Every `name` or `name{...}` of the given metrics as written in the expression."""
    pattern = re.compile(
        r"(?<![\w:])(" + "|".join(map(re.escape, sorted(names))) + r")(\{[^}]*\})?"
    )
    return [match.group(0) for match in pattern.finditer(expr)]


def last_batch_age(query_name: str) -> float | None:
    """Seconds since the Spark query made its last batch, None when it has no series."""
    rows = prometheus_query(
        f'time() - spark_streaming_last_batch_timestamp{{query="{query_name}"}}'
    )
    return float(rows[0]["value"][1]) if rows else None


def is_idle(
    expr: str, known: Known, age: BatchAge, batches: Flag = has_batches, seen: Flag = seen_before
) -> bool:
    """An empty Spark panel of a query that is alive but has had no batch with data."""
    names = metric_names(expr)
    queries = set(QUERY_LABEL.findall(expr))
    if not names or len(queries) != 1 or VECTOR_MATCHING.search(expr):
        return False
    if not all(name.startswith(SPARK_PREFIX) and known(name) for name in names):
        return False
    query_name = next(iter(queries))
    if batches(query_name):
        return False
    seconds = age(query_name)
    if seconds is None or seconds > IDLE_AFTER:
        return False
    return all(seen(selector) for selector in selectors(expr, names))


def trino_query(sql: str, user: str = TRINO_USER) -> list[dict[str, Any]]:
    """Rows of a statement run as `user` (as the plugin does), read page by page along nextUri.

    A Trino error or a statement still running after TRINO_DEADLINE seconds raises OSError.
    """
    deadline = monotonic() + TRINO_DEADLINE
    request = urllib.request.Request(
        f"{TRINO}/v1/statement",
        data=sql.encode(),
        headers={"X-Trino-User": user},
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
        request = urllib.request.Request(page["nextUri"], headers={"X-Trino-User": user})


def panels(dashboard: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Panels of a dashboard, including those inside collapsed rows."""
    for panel in dashboard.get("panels", []):
        yield panel
        yield from panels(panel)


def check(
    paths: Sequence[Path],
    query: Query,
    trino: Query = trino_query,
    known: Known | None = None,
    last_batch_age: BatchAge = last_batch_age,
    has_batches: Flag = has_batches,
    seen_before: Flag = seen_before,
) -> int:
    known = known or metric_known()
    ok = 0
    empty: list[str] = []
    idle: list[str] = []
    for path in paths:
        for panel in panels(json.loads(path.read_text())):
            for target in panel.get("targets", []):
                expr = target.get("expr") or target.get("rawSQL")
                if not expr:
                    continue
                failed = False
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
                    rows, failed = [], True
                if rows:
                    ok += 1
                else:
                    line = f"{path.name}: {panel.get('title', '?')}: {expr}"
                    try:
                        quiet = (
                            "expr" in target
                            and not failed
                            and is_idle(expr, known, last_batch_age, has_batches, seen_before)
                        )
                    except (OSError, ValueError, KeyError, IndexError):
                        quiet = False
                    (idle if quiet else empty).append(line)
    print(f"queries ok: {ok}")
    for line in idle:
        print(f"idle: {line}")
    for line in empty:
        print(f"empty: {line}")
    return 1 if empty else 0


def main(argv: Sequence[str]) -> int:
    paths = [Path(a) for a in argv] or sorted(DASHBOARDS.glob("*.json"))
    return check(paths, prometheus_query)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
