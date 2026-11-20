"""Run the bronze offsets SQL of scripts/chaos/lib.sh on sqlite3 against crafted partitions."""

import re
import sqlite3
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[2] / "scripts" / "chaos" / "lib.sh"
QUERY_RE = re.compile(r'bronze_offsets_ok\(\) \{.*?trino_value "(.*?)"\)', re.S)

Row = tuple[str, int, int]


def offsets_query() -> str:
    match = QUERY_RE.search(LIB.read_text())
    assert match, "bronze_offsets_ok query not found in lib.sh"
    return match.group(1)


def run_query(rows: list[Row]) -> int:
    con = sqlite3.connect(":memory:")
    try:
        con.execute("attach ':memory:' as bronze")
        con.execute("create table bronze.cdc_events (topic, kafka_partition, kafka_offset)")
        con.executemany("insert into bronze.cdc_events values (?, ?, ?)", rows)
        (bad,) = con.execute(offsets_query()).fetchone()
        return int(bad)
    finally:
        con.close()


def partition(topic: str, part: int, offsets: list[int]) -> list[Row]:
    return [(topic, part, offset) for offset in offsets]


def test_query_is_extracted() -> None:
    query = offsets_query()
    assert "bronze.cdc_events" in query
    assert "count(distinct kafka_offset)" in query


@pytest.mark.parametrize(
    ("name", "rows", "expected"),
    [
        (
            "clean two topics",
            partition("a", 0, [0, 1, 2]) + partition("b", 0, [0, 1]),
            0,
        ),
        ("partition starts above zero", partition("a", 0, [7, 8]), 0),
        ("duplicate offset", partition("a", 0, [0, 1, 1, 2]), 1),
        ("hole", partition("a", 0, [0, 2, 3]), 1),
        (
            "hole in another partition",
            partition("a", 0, [0, 1, 2]) + partition("a", 1, [0, 2]),
            1,
        ),
        (
            "duplicate and hole in different partitions",
            partition("a", 0, [0, 1, 1]) + partition("a", 1, [0, 2]),
            2,
        ),
    ],
)
def test_offsets_query_counts_bad_partitions(name: str, rows: list[Row], expected: int) -> None:
    assert run_query(rows) == expected, name
