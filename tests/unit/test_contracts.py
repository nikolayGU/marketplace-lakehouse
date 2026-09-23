import json
import re
import shutil
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.functions import from_json
from spark_jobs.contracts import load_contracts, parse_contract

ROOT = Path(__file__).parents[2]
CONTRACTS = ROOT / "contracts" / "silver"
SCHEMA_SQL = ROOT / "oltp" / "migrations" / "001_schema.sql"
FIXTURES = ROOT / "tests" / "fixtures" / "envelopes"

COLUMN = re.compile(
    r"(\w+) (varchar\(\d+\)|char\(\d+\)|text|integer|smallint|timestamp|numeric\((\d+), (\d+)\))"
    r"(.*)"
)

needs_java = pytest.mark.skipif(
    shutil.which("java") is None, reason="local SparkSession needs a JVM; CI and the image have one"
)


def source_tables() -> dict[str, dict[str, Any]]:
    """Columns, NOT NULL and primary key of every `shop` table, read from the migration."""
    tables = {}
    sql = SCHEMA_SQL.read_text()
    for name, body in re.findall(r"create table shop\.(\w+) \((.*?)\n\);", sql, re.S):
        columns: list[tuple[str, str, str]] = []
        not_null: set[str] = set()
        primary_key: list[str] = []
        for line in (raw.strip().rstrip(",") for raw in body.splitlines()):
            if line.startswith("primary key"):
                primary_key = [c.strip() for c in line[line.index("(") + 1 : -1].split(",")]
                continue
            match = COLUMN.fullmatch(line)
            if not match:
                continue
            column, pg_type, precision, scale, rest = match.groups()
            if pg_type.startswith("numeric"):
                wire, silver = "number", f"decimal({precision},{scale})"
            elif pg_type in ("integer", "smallint"):
                wire, silver = "integer", "int"
            elif pg_type == "timestamp":
                wire, silver = "integer", "timestamp_ntz"
            else:
                wire, silver = "string", "string"
            columns.append((column, wire, silver))
            if "not null" in rest or "primary key" in rest:
                not_null.add(column)
            if "primary key" in rest:
                primary_key = [column]
        tables[name] = {"columns": columns, "not_null": not_null, "primary_key": primary_key}
    return tables


def test_every_source_table_has_exactly_one_contract() -> None:
    assert {p.stem for p in CONTRACTS.glob("*.json")} == set(source_tables())


@pytest.mark.parametrize("path", sorted(CONTRACTS.glob("*.json")), ids=lambda p: p.stem)
def test_contract_is_valid_json_schema(path: Path) -> None:
    Draft202012Validator.check_schema(json.loads(path.read_text()))


@pytest.mark.parametrize("table", sorted(source_tables()))
def test_contract_matches_the_source_table(table: str) -> None:
    source = source_tables()[table]
    contract = load_contracts(CONTRACTS)[table]

    assert contract.source_table == f"shop.{table}"
    assert [(c.name, c.wire_type, c.silver_type) for c in contract.columns] == source["columns"]
    assert {c.name for c in contract.columns if not c.nullable} == source["not_null"]
    assert list(contract.primary_key) == source["primary_key"]


def minimal(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "x-source-table": "shop.t",
        "x-primary-key": ["id"],
        "required": ["id"],
        "properties": {"id": {"type": "string", "x-silver-type": "string"}},
    }
    doc.update(overrides)
    return doc


def test_nullable_primary_key_is_rejected() -> None:
    nullable_id = {"id": {"type": ["string", "null"], "x-silver-type": "string"}}
    with pytest.raises(ValueError, match="primary key"):
        parse_contract("t", minimal(required=[], properties=nullable_id))


def test_primary_key_outside_the_properties_is_rejected() -> None:
    with pytest.raises(ValueError, match="primary key"):
        parse_contract("t", minimal(**{"x-primary-key": ["other"]}))


@pytest.mark.parametrize(
    "spec",
    [
        {"type": "boolean", "x-silver-type": "string"},
        {"type": ["string", "integer"], "x-silver-type": "string"},
        {"type": "string", "x-silver-type": "varchar(32)"},
    ],
)
def test_unsupported_types_are_rejected(spec: dict[str, Any]) -> None:
    doc = minimal()
    doc["properties"]["extra"] = spec
    with pytest.raises(ValueError, match="unsupported"):
        parse_contract("t", doc)


@pytest.mark.parametrize(
    ("spec", "required"),
    [
        ({"type": ["string", "null"], "x-silver-type": "string"}, ["id", "extra"]),
        ({"type": "string", "x-silver-type": "string"}, ["id"]),
    ],
    ids=["required-but-nullable", "not-null-but-optional"],
)
def test_nullability_must_agree(spec: dict[str, Any], required: list[str]) -> None:
    doc = minimal(required=required)
    doc["properties"]["extra"] = spec
    with pytest.raises(ValueError, match="disagree"):
        parse_contract("t", doc)


def test_empty_directory_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no contracts"):
        load_contracts(tmp_path)


@pytest.fixture(scope="module")
def spark() -> Iterator[SparkSession]:
    # Not UTC on purpose: the timestamp conversion must not depend on the session time zone.
    session = (
        SparkSession.builder.master("local[1]")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "1")
        .config("spark.sql.session.timeZone", "America/Sao_Paulo")
        .getOrCreate()
    )
    yield session
    session.stop()


def typed_frame(spark: SparkSession, table: str, *payloads: str) -> DataFrame:
    contract = load_contracts(CONTRACTS)[table]
    df = spark.createDataFrame([(p,) for p in payloads], "payload string")
    parsed = df.select(from_json("payload", contract.wire_schema).alias("p"))
    return parsed.select(*contract.typed("p"))


def typed_rows(spark: SparkSession, table: str, *payloads: str) -> list[Any]:
    return typed_frame(spark, table, *payloads).collect()


def fixture_payload(name: str) -> dict[str, Any]:
    value = json.loads((FIXTURES / f"{name}.json").read_text())["value"]
    payload: dict[str, Any] = value["after"] or value["before"]
    return payload


@needs_java
def test_wire_values_become_silver_types(spark: SparkSession) -> None:
    [order] = typed_rows(spark, "orders", json.dumps(fixture_payload("orders_c")))
    [item] = typed_rows(spark, "order_items", json.dumps(fixture_payload("order_items_d")))

    types = {c.name: c.silver_type for c in load_contracts(CONTRACTS)["orders"].columns}
    df = typed_frame(spark, "orders", json.dumps(fixture_payload("orders_c")))
    assert {f.name: f.dataType.simpleString() for f in df.schema.fields} == types
    # 1782111448898 ms after the epoch, read as a wall clock with no zone.
    assert order.order_purchase_timestamp == datetime(2026, 6, 22, 6, 57, 28, 898000)
    assert order.order_approved_at is None
    assert order.order_status == "created"
    assert (item.order_item_id, item.price, item.freight_value) == (
        1,
        Decimal("99.90"),
        Decimal("39.98"),
    )


@needs_java
def test_value_of_the_wrong_type_comes_out_null(spark: SparkSession) -> None:
    payload = fixture_payload("order_items_d") | {"price": "ninety-nine"}

    [item] = typed_rows(spark, "order_items", json.dumps(payload))

    # from_json keeps the fields that did parse; silver has to catch the null itself.
    assert item.price is None
    assert (item.order_id, item.freight_value) == ("order-1", Decimal("39.98"))


@needs_java
def test_numbers_out_of_range_come_out_null(spark: SparkSession) -> None:
    item = fixture_payload("order_items_d") | {
        "order_item_id": 2**40,
        "shipping_limit_date": 10**17,
        "price": 1e12,
    }

    [row] = typed_rows(spark, "order_items", json.dumps(item))

    assert (row.order_item_id, row.shipping_limit_date, row.price) == (None, None, None)


@needs_java
def test_unparseable_payload_gives_a_null_primary_key(spark: SparkSession) -> None:
    [row] = typed_rows(spark, "orders", "{not json")

    assert row.order_id is None
