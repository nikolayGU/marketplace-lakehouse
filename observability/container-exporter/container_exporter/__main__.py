"""Serve container metrics on EXPORTER_PORT until the container stops."""

import threading

from prometheus_client import CollectorRegistry, start_http_server
from pydantic_settings import BaseSettings

from container_exporter.client import UnixSocketApi
from container_exporter.collector import ContainerCollector


class Settings(BaseSettings):
    docker_socket: str = "/var/run/docker.sock"
    exporter_port: int = 9105
    compose_project_name: str = "lakehouse"


def main() -> None:
    settings = Settings()
    # A registry of its own: the default one would call Docker on register and add process metrics.
    registry = CollectorRegistry()
    registry.register(
        ContainerCollector(UnixSocketApi(settings.docker_socket), settings.compose_project_name)
    )
    start_http_server(settings.exporter_port, registry=registry)
    print(
        f"container-exporter on :{settings.exporter_port}, project {settings.compose_project_name}",
        flush=True,
    )
    threading.Event().wait()


if __name__ == "__main__":
    main()
