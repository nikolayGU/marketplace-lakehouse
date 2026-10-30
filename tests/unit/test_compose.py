"""SEC-02: a published port is bound to BIND_IP, and compose refuses to start without one."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

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
