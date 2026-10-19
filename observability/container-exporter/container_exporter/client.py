"""Read-only Docker Engine API client over the unix socket, standard library only."""

import http.client
import json
import socket
from typing import Any

from container_exporter.collector import DockerApiError


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self.socket_path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


class UnixSocketApi:
    def __init__(self, socket_path: str, timeout: float = 5.0) -> None:
        self.socket_path = socket_path
        self.timeout = timeout

    def get(self, path: str) -> Any:
        # One connection per request: the collector reads containers from several threads.
        connection = _UnixConnection(self.socket_path, self.timeout)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            body = response.read()
        finally:
            connection.close()
        if response.status != 200:
            raise DockerApiError(response.status, body.decode(errors="replace").strip())
        return json.loads(body)
