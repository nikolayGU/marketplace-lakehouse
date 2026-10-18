"""Connections the tasks open: Trino for the lake, Postgres for the source."""

from contextlib import closing
from typing import Any

import psycopg
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


def trino_value(settings: Settings, query: str) -> Any:
    return trino_rows(settings, query)[0][0]


def postgres_value(settings: Settings, query: str) -> Any:
    conninfo = psycopg.conninfo.make_conninfo(
        host=settings.oltp_host,
        port=settings.oltp_port,
        dbname=settings.oltp_db,
        user=settings.oltp_user,
        password=settings.oltp_password,
    )
    with psycopg.connect(conninfo) as connection, connection.cursor() as cursor:
        cursor.execute(query)
        row = cursor.fetchone()
        if row is None:
            raise ValueError(f"no row from: {query}")
        return row[0]
