import json
import shutil
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from pyspark.sql import Row, SparkSession
from pyspark.sql.types import (
    BinaryType,
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)
from spark_jobs.bronze_cdc_ingest import ENVELOPE, to_bronze

CONTRACT = Path(__file__).parents[2] / "contracts" / "cdc-envelope.schema.json"

# What the Spark Kafka source hands to to_bronze (the columns it reads, not the headers).
KAFKA_SOURCE = StructType(
    [
        StructField("topic", StringType()),
        StructField("partition", IntegerType()),
        StructField("offset", LongType()),
        StructField("timestamp", TimestampType()),
        StructField("key", BinaryType()),
        StructField("value", BinaryType()),
    ]
)

needs_java = pytest.mark.skipif(
    shutil.which("java") is None, reason="local SparkSession needs a JVM; CI and the image have one"
)


def test_envelope_reads_only_fields_the_contract_requires() -> None:
    contract = json.loads(CONTRACT.read_text())
    json_to_spark = {"string": StringType(), "integer": LongType()}

    def spark_type(spec: dict[str, Any]) -> Any:
        kinds = spec["type"] if isinstance(spec["type"], list) else [spec["type"]]
        [kind] = [k for k in kinds if k != "null"]
        return json_to_spark[kind]

    for field in ENVELOPE.fields:
        if field.name in ("before", "after"):
            continue
        spec = contract["properties"][field.name]
        if isinstance(field.dataType, StructType):
            for nested in field.dataType.fields:
                assert nested.name in spec["required"]
                assert spark_type(spec["properties"][nested.name]) == nested.dataType
        else:
            assert field.name in contract["required"]
            if "type" in spec:
                assert spark_type(spec) == field.dataType


@pytest.fixture(scope="module")
def spark() -> Iterator[SparkSession]:
    session = (
        SparkSession.builder.master("local[1]")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "1")
        .getOrCreate()
    )
    yield session
    session.stop()


def envelope(op: str, before: dict[str, Any] | None, after: dict[str, Any] | None) -> bytes:
    event = {
        "op": op,
        "ts_ms": 1_700_000_000_500,
        "before": before,
        "after": after,
        "source": {"lsn": 42, "ts_ms": 1_700_000_000_000, "table": "orders", "schema": "shop"},
    }
    return json.dumps(event).encode()


def kafka_row(value: bytes, key: bytes | None = b'{"order_id":"o1"}', offset: int = 0) -> Row:
    return Row(
        topic="oltp.shop.orders",
        partition=1,
        offset=offset,
        timestamp=datetime(2026, 9, 22, 12, 0),
        key=key,
        value=value,
    )


def bronze(spark: SparkSession, *rows: Row) -> list[Row]:
    return to_bronze(spark.createDataFrame(list(rows), KAFKA_SOURCE)).collect()


@needs_java
def test_update_keeps_before_and_after_as_json_text(spark: SparkSession) -> None:
    value = envelope(
        "u", {"order_id": "o1", "status": "shipped"}, {"order_id": "o1", "status": "delivered"}
    )

    [row] = bronze(spark, kafka_row(value, offset=7))

    assert (row.op, row.lsn, row.ts_ms, row.source_ts_ms) == (
        "u",
        42,
        1_700_000_000_500,
        1_700_000_000_000,
    )
    assert (row.topic, row.kafka_partition, row.kafka_offset) == ("oltp.shop.orders", 1, 7)
    assert row.source_table == "orders"
    assert row.key == '{"order_id":"o1"}'
    assert json.loads(row.before)["status"] == "shipped"
    assert json.loads(row.after)["status"] == "delivered"
    assert row.raw is None
    assert row.ingest_ts is not None


@needs_java
def test_delete_has_no_after(spark: SparkSession) -> None:
    [row] = bronze(spark, kafka_row(envelope("d", {"order_id": "o1"}, None)))

    assert row.op == "d"
    assert row.after is None
    assert json.loads(row.before) == {"order_id": "o1"}


@needs_java
def test_unparseable_value_is_kept_raw_and_routed_by_topic(spark: SparkSession) -> None:
    [row] = bronze(spark, kafka_row(b"not json at all {", key=None))

    assert row.op is None
    assert row.raw == "not json at all {"
    assert row.source_table == "orders"
    assert row.key is None


@needs_java
def test_json_without_op_is_kept_raw(spark: SparkSession) -> None:
    [row] = bronze(spark, kafka_row(b'{"hello": "world"}'))

    assert row.op is None
    assert row.raw == '{"hello": "world"}'


@needs_java
def test_incremental_snapshot_read_has_null_lsn(spark: SparkSession) -> None:
    event = json.loads(envelope("r", None, {"order_id": "o1"}))
    event["source"]["lsn"] = None
    event["source"]["snapshot"] = "incremental"

    [row] = bronze(spark, kafka_row(json.dumps(event).encode()))

    assert (row.op, row.lsn, row.raw) == ("r", None, None)


@needs_java
def test_duplicate_records_both_land(spark: SparkSession) -> None:
    """Bronze is at-least-once by contract: dedup is silver's job, not this one."""
    value = envelope("c", None, {"order_id": "o1"})

    rows = bronze(spark, kafka_row(value, offset=1), kafka_row(value, offset=2))

    assert [r.kafka_offset for r in rows] == [1, 2]
    assert {r.lsn for r in rows} == {42}
