import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from lakehouse import reconcile as by_value

from scripts.reconcile_sql import queries, value_queries

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "reconcile_sql.py"


def contract(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "x-source-table": "shop.order_items",
        "x-primary-key": ["order_id", "order_item_id"],
        "properties": {
            "order_id": {"x-silver-type": "string"},
            "order_item_id": {"x-silver-type": "int"},
            "price": {"x-silver-type": "decimal(10,2)"},
            "freight_value": {"x-silver-type": "decimal(10,2)"},
            "shipping_limit_date": {"x-silver-type": "timestamp_ntz"},
        },
    }
    return base | overrides


def test_both_sides_hash_the_same_composite_key_and_sum_every_decimal_column() -> None:
    table, postgres, trino = queries(contract())

    assert table == "order_items"
    assert "concat_ws(':', order_id::text, order_item_id::text) as k" in postgres
    assert "concat_ws(':', cast(order_id as varchar), cast(order_item_id as varchar)) as k" in trino
    assert 'order by k collate "C"' in postgres
    for column in ("price", "freight_value"):
        assert f"cast(coalesce(sum({column}), 0) as numeric(38, 2))" in postgres
        assert f"cast(cast(coalesce(sum({column}), 0) as decimal(38, 2)) as varchar)" in trino
    assert "shipping_limit_date" not in postgres + trino


def test_postgres_reads_every_row_and_silver_only_live_rows() -> None:
    _, postgres, trino = queries(contract())

    assert "from shop.order_items" in postgres
    assert "_is_deleted" not in postgres
    assert "from silver.order_items where not _is_deleted" in trino


def test_sum_keeps_the_contract_scale() -> None:
    properties = {"id": {"x-silver-type": "string"}, "rate": {"x-silver-type": "decimal(12, 4)"}}
    _, postgres, trino = queries(contract(**{"x-primary-key": ["id"], "properties": properties}))

    assert "as numeric(38, 4))" in postgres
    assert "as decimal(38, 4))" in trino


def test_table_without_decimal_columns_compares_count_and_keys_only() -> None:
    properties = {"seller_id": {"x-silver-type": "string"}, "city": {"x-silver-type": "string"}}
    _, postgres, trino = queries(
        contract(**{"x-primary-key": ["seller_id"], "properties": properties})
    )

    assert "sum(" not in postgres + trino
    assert postgres.startswith("with src as (select seller_id::text as k from")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"x-primary-key": []}, "no x-primary-key"),
        ({"x-primary-key": ["missing"]}, "not a property"),
        ({"x-source-table": "order_items"}, "schema.table"),
    ],
)
def test_contract_that_cannot_be_reconciled_fails_loudly(
    overrides: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        queries(contract(**overrides))


def run_cli(*flags: str) -> list[list[str]]:
    result = subprocess.run(
        [sys.executable, *flags, str(SCRIPT), str(REPO / "contracts" / "silver")],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.split("\t") for line in result.stdout.splitlines()]


def test_cli_prints_one_tab_separated_line_per_silver_contract() -> None:
    lines = run_cli()

    assert [line[0] for line in lines] == [
        "customers",
        "order_items",
        "orders",
        "payments",
        "products",
        "reviews",
        "sellers",
    ]
    assert all(len(line) == 5 for line in lines)


def test_cli_value_queries_are_the_ones_the_dag_builds() -> None:
    # One implementation of the row fingerprint: dq_checks and `make reconcile` run the same SQL.
    for table, _, _, postgres, trino in run_cli():
        assert postgres == by_value.fingerprint_sql_postgres(table)
        assert trino == by_value.fingerprint_sql_trino(table)


def test_cli_runs_on_the_bare_interpreter_lib_sh_uses() -> None:
    # `python3` in lib.sh has no packages: no site, no environment, only the standard library.
    assert run_cli("-I", "-S") == run_cli()


def test_value_queries_cover_every_column_of_a_table_without_decimals() -> None:
    # `orders` has no decimal column: before the fingerprint a changed status went unnoticed.
    postgres, trino = value_queries(
        contract(**{"x-source-table": "shop.orders", "x-primary-key": ["order_id"]})
    )

    for query in (postgres, trino):
        assert "order_status" in query
    assert postgres == by_value.fingerprint_sql_postgres("orders")
    assert trino == by_value.fingerprint_sql_trino("orders")


def test_table_the_fingerprint_does_not_know_fails_loudly() -> None:
    with pytest.raises(ValueError, match="no columns for 'refunds'"):
        value_queries(contract(**{"x-source-table": "shop.refunds"}))
