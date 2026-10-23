import json
import re
from pathlib import Path
from typing import Any

import pytest
from lakehouse import reconcile
from lakehouse.reconcile import Column

CONTRACTS = Path(__file__).parents[2] / "contracts" / "silver"
MODELS = Path(__file__).parents[2] / "dbt" / "models" / "marts"


def _contract(table: str) -> dict[str, Any]:
    contract: dict[str, Any] = json.loads((CONTRACTS / f"{table}.json").read_text())
    return contract


@pytest.mark.parametrize("table", sorted(reconcile.TABLES))
def test_columns_follow_the_contract(table: str) -> None:
    contract = _contract(table)
    keys, columns = reconcile.TABLES[table]

    assert list(keys) == contract["x-primary-key"]
    declared = [(name, spec["x-silver-type"]) for name, spec in contract["properties"].items()]
    assert [(c.name, c.silver_type) for c in columns] == declared


def test_all_seven_source_tables_are_covered() -> None:
    assert sorted(reconcile.TABLES) == sorted(p.stem for p in CONTRACTS.glob("*.json"))


@pytest.mark.parametrize("gold", sorted(reconcile.GOLD_PAIRS))
def test_gold_columns_exist_in_the_model(gold: str) -> None:
    text = (MODELS / f"{gold}.sql").read_text()
    pair = reconcile.GOLD_PAIRS[gold]

    for column in pair.columns:
        assert re.search(rf"\b{column.gold_name}\b", text), f"{gold} lacks {column.gold_name}"


def test_diff_keys_tells_missing_extra_and_changed_apart() -> None:
    left = {"a": "h1", "b": "h2", "c": "h3", "d": "h4"}
    right = {"b": "h2", "c": "XX", "d": "h4", "e": "h5"}

    only_left, only_right, changed = reconcile.diff_keys(left, right)

    assert (only_left, only_right, changed) == (["a"], ["e"], ["c"])


def test_diff_keys_of_equal_sets_is_empty() -> None:
    assert reconcile.diff_keys({"a": "1"}, {"a": "1"}) == ([], [], [])


def test_classify_names_a_cause_for_each_key() -> None:
    reasons = reconcile.classify(["q", "p", "x"], quarantined={"q"}, in_bronze={"p", "q"})

    assert reasons == {"q": "quarantined", "p": "merge_pending", "x": "unknown"}


def test_gold_at_rest_waits_for_the_newest_silver_row() -> None:
    assert reconcile.gold_at_rest("2026-07-01 10:00:00", "2026-07-01 10:00:00") is True
    assert reconcile.gold_at_rest("2026-07-01 09:59:59", "2026-07-01 10:00:00") is False
    assert reconcile.gold_at_rest(None, "2026-07-01 10:00:00") is False
    assert reconcile.gold_at_rest("2026-07-01 10:00:00", None) is True


def test_a_null_and_an_empty_string_hash_differently() -> None:
    sql = reconcile.row_hash_sql_trino(Column("x", "string"))

    assert r"'\N'" in sql
    assert "coalesce" in sql


def test_decimals_keep_their_contract_scale_on_both_sides() -> None:
    column = Column("price", "decimal(10,2)")

    assert "numeric(38, 2)" in reconcile.row_hash_sql_postgres(column)
    assert "decimal(38, 2)" in reconcile.row_hash_sql_trino(column)


def test_timestamps_compare_as_milliseconds() -> None:
    column = Column("order_purchase_timestamp", "timestamp_ntz")

    assert "epoch" in reconcile.row_hash_sql_postgres(column)
    assert "millisecond" in reconcile.row_hash_sql_trino(column)


def test_queries_only_contain_names_from_the_module() -> None:
    for table in reconcile.TABLES:
        for sql in (
            reconcile.fingerprint_sql_postgres(table),
            reconcile.fingerprint_sql_trino(table),
            reconcile.pairs_sql_postgres(table),
            reconcile.pairs_sql_trino(table),
        ):
            assert ";" not in sql and "--" not in sql
    with pytest.raises(KeyError):
        reconcile.fingerprint_sql_postgres("orders; select 1")


def test_lookup_sql_refuses_a_key_that_is_not_a_plain_identifier() -> None:
    assert reconcile.bronze_lookup_sql("orders", ["ok-1_x"]) is not None
    assert reconcile.bronze_lookup_sql("orders", ["a' or '1'='1"]) is None
    assert reconcile.quarantine_lookup_sql("orders", ["a'b"]) is None


def _pairs(mapping: dict[str, str]):  # type: ignore[no-untyped-def]
    return lambda: mapping


def test_equal_fingerprints_load_nothing() -> None:
    def explode() -> dict[str, str]:
        raise AssertionError("pairs are pulled only when the fingerprints differ")

    verdict = reconcile.compare("source_silver", "orders", "5 abc", "5 abc", explode, explode)

    assert verdict.clean
    assert (verdict.rows_left, verdict.rows_right) == (5, 5)


def test_a_changed_value_at_an_equal_count_is_found() -> None:
    # The case a count and a sum of money cannot see: same rows, one status differs.
    left = {"a": "h1", "b": "h2"}
    right = {"a": "h1", "b": "OTHER"}

    verdict = reconcile.compare(
        "source_silver", "orders", "2 aaa", "2 bbb", _pairs(left), _pairs(right)
    )

    assert not verdict.clean
    assert verdict.changed == ["b"]
    assert (verdict.only_left, verdict.only_right) == ([], [])


def test_missing_keys_get_a_reason() -> None:
    left = {"a": "h1", "b": "h2", "c": "h3"}
    right = {"a": "h1"}

    verdict = reconcile.compare(
        "source_silver",
        "orders",
        "3 aaa",
        "1 bbb",
        _pairs(left),
        _pairs(right),
        explain=lambda keys: reconcile.classify(keys, quarantined={"b"}, in_bronze={"c"}),
    )

    assert verdict.only_left == ["b", "c"]
    assert verdict.reasons == {"b": "quarantined", "c": "merge_pending"}


def test_the_report_lists_at_most_twenty_keys() -> None:
    left = {f"k{i:03d}": "h" for i in range(50)}

    verdict = reconcile.compare("source_silver", "orders", "50 a", "0 b", _pairs(left), _pairs({}))

    assert len(verdict.only_left) == 50
    assert len(verdict.summary().splitlines()) <= 22
