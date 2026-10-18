"""Connections the tasks open: Trino for the lake."""

from contextlib import closing
from typing import Any

import trino

from lakehouse.settings import Settings


def trino_rows(settings: Settings, query: str) -> list[list[Any]]:
    connection = trino.dbapi.Connection(
        host=settings.trino_host, port=settings.trino_port, user="airflow", catalog="lake"
    )
    with closing(connection):
        cursor = connection.cursor()
        cursor.execute(query)
        rows: list[list[Any]] = cursor.fetchall()
        return rows
