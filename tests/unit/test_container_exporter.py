import socketserver
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

import pytest
from container_exporter.client import UnixSocketApi
from container_exporter.collector import (
    ContainerCollector,
    DockerApiError,
    memory_usage_bytes,
    started_at_seconds,
)
from prometheus_client import CollectorRegistry

PROJECT_FILTER = (
    "/containers/json?all=true"
    "&filters=%7B%22label%22%3A+%5B%22com.docker.compose.project%3Dlakehouse%22%5D%7D"
)


class FakeApi:
    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses

    def get(self, path: str) -> Any:
        response = self.responses[path]
        if isinstance(response, Exception):
            raise response
        return response


def listed(cid: str, name: str, state: str) -> dict[str, Any]:
    return {
        "Id": cid,
        "Names": [f"/{name}"],
        "State": state,
        "Labels": {"com.docker.compose.service": name.removeprefix("lakehouse-")[:-2]},
    }


def inspected(
    started: str = "2026-10-18T16:53:13.560015306Z",
    restarts: int = 0,
    oom: bool = False,
    health: str | None = "healthy",
    running: bool = True,
) -> dict[str, Any]:
    state: dict[str, Any] = {"Running": running, "StartedAt": started, "OOMKilled": oom}
    if health is not None:
        state["Health"] = {"Status": health}
    return {"RestartCount": restarts, "State": state}


def stats(usage: int = 1_493_975_040, inactive: int = 3_186_688) -> dict[str, Any]:
    return {
        "memory_stats": {
            "usage": usage,
            "limit": 3_758_096_384,
            "stats": {"inactive_file": inactive},
        },
        "cpu_stats": {"cpu_usage": {"total_usage": 375_531_916_000}},
    }


def scrape(api: FakeApi) -> CollectorRegistry:
    registry = CollectorRegistry()
    registry.register(ContainerCollector(api, "lakehouse"))
    return registry


def value(registry: CollectorRegistry, name: str, container: str) -> float | None:
    return registry.get_sample_value(name, {"name": container, "service": container[10:-2]})


def test_running_container_reports_memory_like_docker_stats() -> None:
    api = FakeApi(
        {
            PROJECT_FILTER: [listed("t1", "lakehouse-trino-1", "running")],
            "/containers/t1/json": inspected(),
            "/containers/t1/stats?stream=false&one-shot=true": stats(),
        }
    )

    registry = scrape(api)

    # docker stats shows usage minus inactive_file: 1.389GiB for trino on 2026-10-19.
    assert (
        value(registry, "docker_container_memory_usage_bytes", "lakehouse-trino-1") == 1_490_788_352
    )
    assert (
        value(registry, "docker_container_memory_limit_bytes", "lakehouse-trino-1") == 3_758_096_384
    )
    assert value(
        registry, "docker_container_cpu_usage_seconds_total", "lakehouse-trino-1"
    ) == pytest.approx(375.531916)
    assert value(registry, "docker_container_running", "lakehouse-trino-1") == 1
    assert value(registry, "docker_container_healthy", "lakehouse-trino-1") == 1
    assert value(
        registry, "docker_container_start_time_seconds", "lakehouse-trino-1"
    ) == pytest.approx(1_792_342_393.560015)


def test_restart_and_oom_are_reported() -> None:
    api = FakeApi(
        {
            PROJECT_FILTER: [listed("k1", "lakehouse-kafka-1", "running")],
            "/containers/k1/json": inspected(restarts=3, oom=True, health="unhealthy"),
            "/containers/k1/stats?stream=false&one-shot=true": stats(),
        }
    )

    registry = scrape(api)

    assert value(registry, "docker_container_restart_count", "lakehouse-kafka-1") == 3
    assert value(registry, "docker_container_oom_killed", "lakehouse-kafka-1") == 1
    assert value(registry, "docker_container_healthy", "lakehouse-kafka-1") == 0


def test_exited_container_has_state_but_no_resource_series() -> None:
    api = FakeApi(
        {
            PROJECT_FILTER: [listed("m1", "lakehouse-minio-init-1", "exited")],
            "/containers/m1/json": inspected(health=None, running=False),
        }
    )

    registry = scrape(api)

    assert value(registry, "docker_container_running", "lakehouse-minio-init-1") == 0
    assert value(registry, "docker_container_memory_usage_bytes", "lakehouse-minio-init-1") is None
    # No healthcheck: no series, rather than a 0 that reads as unhealthy.
    assert value(registry, "docker_container_healthy", "lakehouse-minio-init-1") is None


def test_container_removed_between_list_and_inspect_is_skipped() -> None:
    api = FakeApi(
        {
            PROJECT_FILTER: [
                listed("gone", "lakehouse-spark-silver-run-1", "running"),
                listed("t1", "lakehouse-trino-1", "running"),
            ],
            "/containers/gone/json": DockerApiError(404, "No such container"),
            "/containers/t1/json": inspected(),
            "/containers/t1/stats?stream=false&one-shot=true": stats(),
        }
    )

    registry = scrape(api)

    assert value(registry, "docker_container_running", "lakehouse-spark-silver-run-1") is None
    assert value(registry, "docker_container_running", "lakehouse-trino-1") == 1


def test_container_removed_between_inspect_and_stats_is_skipped() -> None:
    api = FakeApi(
        {
            PROJECT_FILTER: [listed("gone", "lakehouse-spark-silver-run-1", "running")],
            "/containers/gone/json": inspected(),
            "/containers/gone/stats?stream=false&one-shot=true": DockerApiError(404, "No such"),
        }
    )

    registry = scrape(api)

    assert value(registry, "docker_container_running", "lakehouse-spark-silver-run-1") is None


def test_container_stopped_after_listing_is_reported_by_inspect() -> None:
    # Stats of a stopped container answer 200 with zeroed fields; inspect has the truth.
    zeroed = {"memory_stats": {}, "cpu_stats": {"cpu_usage": {"total_usage": 0}}}
    api = FakeApi(
        {
            PROJECT_FILTER: [listed("k1", "lakehouse-kafka-1", "running")],
            "/containers/k1/json": inspected(running=False),
            "/containers/k1/stats?stream=false&one-shot=true": zeroed,
        }
    )

    registry = scrape(api)

    assert value(registry, "docker_container_running", "lakehouse-kafka-1") == 0
    assert value(registry, "docker_container_cpu_usage_seconds_total", "lakehouse-kafka-1") is None


def test_per_container_error_other_than_404_fails_the_scrape() -> None:
    api = FakeApi(
        {
            PROJECT_FILTER: [listed("t1", "lakehouse-trino-1", "running")],
            "/containers/t1/json": inspected(),
            "/containers/t1/stats?stream=false&one-shot=true": TimeoutError("timed out"),
        }
    )

    with pytest.raises(TimeoutError):
        value(scrape(api), "docker_container_running", "lakehouse-trino-1")


def test_empty_listing_fails_the_scrape() -> None:
    # The exporter is a container of the project itself: an empty list means a wrong
    # COMPOSE_PROJECT_NAME, not a stack without containers.
    registry = scrape(FakeApi({PROJECT_FILTER: []}))

    with pytest.raises(DockerApiError, match="COMPOSE_PROJECT_NAME"):
        value(registry, "docker_container_running", "lakehouse-trino-1")


def test_docker_api_down_fails_the_scrape() -> None:
    # An empty but successful scrape would look like "no containers"; a failed one sets up == 0.
    registry = scrape(FakeApi({PROJECT_FILTER: DockerApiError(500, "daemon unavailable")}))

    with pytest.raises(DockerApiError):
        value(registry, "docker_container_running", "lakehouse-trino-1")


def test_memory_usage_without_inactive_file_falls_back_to_usage() -> None:
    assert memory_usage_bytes({"memory_stats": {"usage": 100, "stats": {}}}) == 100
    assert (
        memory_usage_bytes({"memory_stats": {"usage": 100, "stats": {"total_inactive_file": 30}}})
        == 70
    )


def test_memory_usage_of_a_container_that_just_stopped_is_none() -> None:
    assert memory_usage_bytes({"memory_stats": {}}) is None


def test_never_started_container_has_no_start_time() -> None:
    assert started_at_seconds("0001-01-01T00:00:00Z") is None


def test_start_time_keeps_microseconds_of_nanosecond_timestamps() -> None:
    assert started_at_seconds("2026-10-18T16:53:13.560015306Z") == pytest.approx(
        1_792_342_393.560015
    )
    assert started_at_seconds("2026-10-18T16:53:13Z") == 1_792_342_393


class FakeDockerHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/containers/json":
            body, status = b'[{"Id": "t1"}]', 200
        else:
            body, status = b'{"message": "No such container: x"}', 404
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def address_string(self) -> str:
        return "unix"

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture
def docker_socket(tmp_path: Path) -> Iterator[str]:
    path = str(tmp_path / "docker.sock")
    server = socketserver.ThreadingUnixStreamServer(path, FakeDockerHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield path
    server.shutdown()
    server.server_close()


def test_socket_api_returns_parsed_json(docker_socket: str) -> None:
    assert UnixSocketApi(docker_socket).get("/containers/json") == [{"Id": "t1"}]


def test_socket_api_raises_with_status_on_error(docker_socket: str) -> None:
    with pytest.raises(DockerApiError) as error:
        UnixSocketApi(docker_socket).get("/containers/x/json")

    assert error.value.status == 404
    assert "No such container" in str(error.value)


def test_socket_api_without_socket_raises_os_error(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        UnixSocketApi(str(tmp_path / "missing.sock")).get("/containers/json")
