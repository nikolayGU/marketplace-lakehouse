"""SEC-02: a published port is bound to BIND_IP, and compose refuses to start without one."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
COMPOSE = REPO / "docker" / "compose.yaml"
ENV_EXAMPLE = REPO / ".env.example"


def _published_ports() -> list[tuple[str, str]]:
    compose: dict[str, Any] = yaml.safe_load(COMPOSE.read_text())
    return [
        (name, str(port))
        for name, service in compose["services"].items()
        for port in service.get("ports", [])
    ]


def _compose_config(env_file: Path, bind_ip: str | None) -> subprocess.CompletedProcess[str]:
    # `config -q` prints nothing on success; without it the output holds every secret of the file.
    env = {k: v for k, v in os.environ.items() if k != "BIND_IP"}
    if bind_ip is not None:
        env["BIND_IP"] = bind_ip
    return subprocess.run(
        [
            *("docker", "compose", "--env-file", str(env_file), "-f", str(COMPOSE)),
            *("--profile", "*", "config", "-q"),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _docker_compose_available() -> bool:
    if shutil.which("docker") is None:
        return False
    probe = subprocess.run(
        ["docker", "compose", "version"], capture_output=True, text=True, check=False
    )
    return probe.returncode == 0


def test_every_published_port_requires_bind_ip() -> None:
    # A bare ${BIND_IP} turns an empty variable into ":8080:8080": every interface.
    ports = _published_ports()

    assert ports
    assert [(name, port) for name, port in ports if not port.startswith("${BIND_IP:?")] == []


def test_env_example_binds_to_loopback() -> None:
    assert "BIND_IP=127.0.0.1" in ENV_EXAMPLE.read_text().splitlines()


@pytest.mark.skipif(not _docker_compose_available(), reason="docker compose is not installed")
def test_compose_refuses_an_empty_or_missing_bind_ip(tmp_path: Path) -> None:
    without_bind_ip = tmp_path / "without-bind-ip.env"
    without_bind_ip.write_text(
        "".join(
            line
            for line in ENV_EXAMPLE.read_text().splitlines(keepends=True)
            if not line.startswith("BIND_IP=")
        )
    )

    # The control: the same file and the same shell with a real address are accepted.
    assert _compose_config(ENV_EXAMPLE, None).returncode == 0
    assert _compose_config(without_bind_ip, "127.0.0.1").returncode == 0

    for env_file, bind_ip in [(ENV_EXAMPLE, ""), (without_bind_ip, None)]:
        refused = _compose_config(env_file, bind_ip)
        assert refused.returncode != 0
        assert "BIND_IP" in refused.stderr


def _services() -> dict[str, Any]:
    compose: dict[str, Any] = yaml.safe_load(COMPOSE.read_text())
    services: dict[str, Any] = compose["services"]
    return services


def test_kafka_advertises_the_host_listener_on_the_published_host_port() -> None:
    # A client on the host bootstraps on the published port, then reconnects to the advertised one.
    kafka = _services()["kafka"]
    advertised = dict(
        item.split("://", 1)
        for item in kafka["environment"]["KAFKA_ADVERTISED_LISTENERS"].split(",")
    )
    advertised_port = advertised["HOST"].rsplit(":", 1)[1]
    listened = dict(
        item.split("://", 1) for item in kafka["environment"]["KAFKA_LISTENERS"].split(",")
    )
    published = [str(p).rsplit(":", 2) for p in kafka["ports"]]

    assert [host_port for _, host_port, _ in published] == [advertised_port]
    assert listened["HOST"].rsplit(":", 1)[1] == published[0][2]


def test_minio_console_has_a_fixed_port_published_to_the_host() -> None:
    minio = _services()["minio"]

    assert "--console-address :9001" in minio["command"]
    assert any(str(p).endswith(":9001:9001") for p in minio["ports"])


ONE_SHOTS = {
    "minio-init",
    "lakekeeper-migrate",
    "lakekeeper-bootstrap",
    "spark-silver",
    "superset-init",
}


def test_every_one_shot_job_of_the_header_exists_and_does_not_restart() -> None:
    services = _services()
    header = "\n".join(
        line for line in COMPOSE.read_text().splitlines()[:10] if line.startswith("#")
    ).replace("\n# ", " ")

    for name in ONE_SHOTS:
        assert name in header, name
        assert services[name].get("restart", "no") == "no", name


def test_superset_init_has_no_healthcheck_and_a_memory_limit() -> None:
    init = _services()["superset-init"]

    assert "healthcheck" not in init
    assert init["deploy"]["resources"]["limits"]["memory"]


def test_superset_stack_waits_for_its_init_and_may_start_without_trino() -> None:
    services = _services()

    for name in ("superset", "superset-mcp"):
        assert services[name]["depends_on"]["superset-init"]["condition"] == (
            "service_completed_successfully"
        )
        assert services[name]["healthcheck"]
        assert services[name]["restart"] == "unless-stopped"
    for name in ("superset", "superset-init"):
        assert services[name]["depends_on"]["trino"]["required"] is False
    assert "superset-mcp" in services and services["superset-mcp"]["profiles"] == ["bi"]


def test_superset_admin_password_is_required_not_defaulted_to_empty() -> None:
    # An empty value would create an admin that nobody can log in as.
    for name in ("superset", "superset-init"):
        value = _services()[name]["environment"]["SUPERSET_ADMIN_PASSWORD"]
        assert value.startswith("${SUPERSET_ADMIN_PASSWORD:?"), name


def test_required_secret_messages_do_not_claim_make_secrets_skips_an_existing_env() -> None:
    assert "skips an existing" not in COMPOSE.read_text()


def test_superset_mcp_checks_host_and_origin_of_every_request() -> None:
    # fastmcp does not by default: a web page could reach the port by DNS rebinding.
    env = _services()["superset-mcp"]["environment"]

    assert env["FASTMCP_HTTP_HOST_ORIGIN_PROTECTION"] == "true"
    assert json.loads(env["FASTMCP_HTTP_ALLOWED_HOSTS"]) == ["127.0.0.1", "localhost", "::1"]
