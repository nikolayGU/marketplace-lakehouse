"""Per-container metrics read from the Docker Engine API at scrape time (ADR-023).

cAdvisor cannot name containers on Docker Desktop with the containerd image store, so this
exporter reports what `docker stats` and `docker inspect` show, labelled by container name.
"""

import json
import urllib.parse
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Protocol

from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, Metric
from prometheus_client.registry import Collector

LABELS = ["name", "service"]


class DockerApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"docker api {status}: {message}")
        self.status = status


class DockerApi(Protocol):
    def get(self, path: str) -> Any: ...


def memory_usage_bytes(stats: dict[str, Any]) -> float | None:
    """Usage minus inactive page cache, the number `docker stats` prints (cgroup v2 and v1)."""
    memory = stats.get("memory_stats", {})
    if "usage" not in memory:
        return None
    detail = memory.get("stats", {})
    inactive = detail.get("inactive_file", detail.get("total_inactive_file", 0))
    return float(memory["usage"] - inactive)


def started_at_seconds(value: str) -> float | None:
    if value.startswith("0001-"):
        return None
    # Docker writes nanoseconds; datetime takes at most microseconds.
    head, _, fraction = value.removesuffix("Z").partition(".")
    stamp = f"{head}.{fraction[:6]}" if fraction else head
    return datetime.fromisoformat(f"{stamp}+00:00").timestamp()


class ContainerCollector(Collector):
    def __init__(self, api: DockerApi, project: str) -> None:
        self.api = api
        query = {
            "all": "true",
            "filters": json.dumps({"label": [f"com.docker.compose.project={project}"]}),
        }
        self.list_path = f"/containers/json?{urllib.parse.urlencode(query)}"

    def collect(self) -> Iterator[Metric]:
        families = {
            "running": GaugeMetricFamily(
                "docker_container_running", "1 when running", labels=LABELS
            ),
            "healthy": GaugeMetricFamily(
                "docker_container_healthy",
                "1 when the healthcheck passes; absent without one",
                labels=LABELS,
            ),
            "started": GaugeMetricFamily(
                "docker_container_start_time_seconds", "Last start, unix seconds", labels=LABELS
            ),
            "restarts": GaugeMetricFamily(
                "docker_container_restart_count",
                "Restarts by the restart policy; `docker restart` changes the start time instead",
                labels=LABELS,
            ),
            "oom": GaugeMetricFamily(
                "docker_container_oom_killed", "1 when the last exit was an OOM kill", labels=LABELS
            ),
            "memory": GaugeMetricFamily(
                "docker_container_memory_usage_bytes",
                "Memory as docker stats shows it",
                labels=LABELS,
            ),
            "limit": GaugeMetricFamily(
                "docker_container_memory_limit_bytes", "Memory limit", labels=LABELS
            ),
            "cpu": CounterMetricFamily(
                "docker_container_cpu_usage_seconds", "CPU time used", labels=LABELS
            ),
        }
        # A failed listing propagates, so the scrape fails (up == 0) instead of showing none.
        containers = self.api.get(self.list_path)
        if not containers:
            # The exporter itself belongs to the project, so the label filter must match.
            raise DockerApiError(
                200, f"no containers for {self.list_path}, check COMPOSE_PROJECT_NAME"
            )
        with ThreadPoolExecutor(max_workers=8) as pool:
            for sample in pool.map(self._read, containers):
                if sample is not None:
                    self._add(families, *sample)
        yield from families.values()

    def _read(
        self, container: dict[str, Any]
    ) -> tuple[list[str], dict[str, Any], dict[str, Any] | None] | None:
        cid = container["Id"]
        labels = [
            container["Names"][0].lstrip("/"),
            container.get("Labels", {}).get("com.docker.compose.service", ""),
        ]
        try:
            inspect = self.api.get(f"/containers/{cid}/json")
            stats = (
                self.api.get(f"/containers/{cid}/stats?stream=false&one-shot=true")
                if container["State"] == "running"
                else None
            )
        except DockerApiError as error:
            # One-off containers (spark-silver runs) can be gone between the listing and here.
            if error.status == 404:
                return None
            raise
        return labels, inspect, stats

    @staticmethod
    def _add(
        families: dict[str, Any],
        labels: list[str],
        inspect: dict[str, Any],
        stats: dict[str, Any] | None,
    ) -> None:
        state = inspect["State"]
        # The listing can be stale by now, and stats of a stopped container come back zeroed.
        running = bool(state.get("Running"))
        families["running"].add_metric(labels, 1.0 if running else 0.0)
        if "Health" in state:
            families["healthy"].add_metric(
                labels, 1.0 if state["Health"]["Status"] == "healthy" else 0.0
            )
        started = started_at_seconds(state.get("StartedAt", "0001-01-01T00:00:00Z"))
        if started is not None:
            families["started"].add_metric(labels, started)
        families["restarts"].add_metric(labels, float(inspect.get("RestartCount", 0)))
        families["oom"].add_metric(labels, 1.0 if state.get("OOMKilled") else 0.0)
        if stats is None or not running:
            return
        memory = memory_usage_bytes(stats)
        if memory is not None:
            families["memory"].add_metric(labels, memory)
            families["limit"].add_metric(labels, float(stats["memory_stats"]["limit"]))
        cpu = stats.get("cpu_stats", {}).get("cpu_usage", {}).get("total_usage")
        if cpu is not None:
            families["cpu"].add_metric(labels, cpu / 1e9)
