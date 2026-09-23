"""Envelope fixtures are shaped after records read from the live topics (ids replaced), so these
tests pin what Debezium actually sends to what `contracts/` promises."""

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from spark_jobs.contracts import load_contracts

ROOT = Path(__file__).parents[2]
ENVELOPE = Draft202012Validator(
    json.loads((ROOT / "contracts" / "cdc-envelope.schema.json").read_text())
)
CONTRACTS_DIR = ROOT / "contracts" / "silver"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "envelopes"
FIXTURES = sorted(FIXTURE_DIR.glob("*.json"))


def load(path: Path) -> dict[str, Any]:
    record: dict[str, Any] = json.loads(path.read_text())
    return record


def envelope(name: str) -> dict[str, Any]:
    value: dict[str, Any] = load(FIXTURE_DIR / f"{name}.json")["value"]
    return value


def payload_validator(table: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads((CONTRACTS_DIR / f"{table}.json").read_text()))


def payload(value: dict[str, Any]) -> dict[str, Any]:
    """The row image silver reads: `before` for a delete, `after` otherwise."""
    row: dict[str, Any] = value["before"] if value["op"] == "d" else value["after"]
    return row


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_fixture_is_a_valid_envelope(path: Path) -> None:
    ENVELOPE.validate(load(path)["value"])


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_row_image_matches_the_table_contract(path: Path) -> None:
    value = load(path)["value"]

    payload_validator(value["source"]["table"]).validate(payload(value))


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_kafka_key_is_the_primary_key_in_order(path: Path) -> None:
    record = load(path)
    contract = load_contracts(CONTRACTS_DIR)[record["value"]["source"]["table"]]

    assert tuple(record["key"]) == contract.primary_key
    assert all(record["key"][k] == payload(record["value"])[k] for k in contract.primary_key)


def test_fixtures_cover_every_contract_and_every_op() -> None:
    values = [load(p)["value"] for p in FIXTURES]

    assert {v["source"]["table"] for v in values} == set(load_contracts(CONTRACTS_DIR))
    assert {v["op"] for v in values} == {"c", "u", "d", "r"}


def test_incremental_snapshot_read_has_no_lsn() -> None:
    value = envelope("orders_r_incremental")

    assert (value["op"], value["source"]["snapshot"], value["source"]["lsn"]) == (
        "r",
        "incremental",
        None,
    )
    ENVELOPE.validate(value)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda v: v.pop("op"),
        lambda v: v.update(op="x"),
        lambda v: v.pop("source"),
        lambda v: v["source"].update(lsn="1110641816"),
        lambda v: v["source"].pop("table"),
    ],
    ids=["no-op", "unknown-op", "no-source", "lsn-as-text", "no-table"],
)
def test_broken_envelope_is_rejected(mutate: Any) -> None:
    value = envelope("orders_u")
    mutate(value)

    assert not ENVELOPE.is_valid(value)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda row: row.pop("order_id"),
        lambda row: row.update(order_id=None),
        lambda row: row.update(order_status="lost"),
        lambda row: row.update(order_purchase_timestamp="2026-06-22 06:57:28"),
        lambda row: row.update(order_estimated_delivery_date=None),
    ],
    ids=["no-key", "null-key", "unknown-status", "timestamp-as-text", "null-required"],
)
def test_row_image_that_breaks_the_contract_is_rejected(mutate: Any) -> None:
    row = envelope("orders_u")["after"]
    mutate(row)

    assert not payload_validator("orders").is_valid(row)


def test_column_added_at_the_source_does_not_break_the_contract() -> None:
    """Schema evolution: a new source column reaches bronze before the contract knows it."""
    row = envelope("orders_u")["after"] | {"sales_channel": "app"}

    payload_validator("orders").validate(row)
