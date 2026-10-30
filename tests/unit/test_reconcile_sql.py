import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from lakehouse import reconcile as by_value

from scripts.reconcile_sql import queries, value_queries

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "reconcile_sql.py"
CONTRACTS = REPO / "contracts" / "silver"


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


def contracts_copy(tmp_path: Path) -> Path:
    shutil.copytree(CONTRACTS, tmp_path / "silver")
    return tmp_path / "silver"


def add_contract(directory: Path, name: str, source_table: str) -> None:
    orders = json.loads((CONTRACTS / "orders.json").read_text())
    orders["x-source-table"] = source_table
    (directory / f"{name}.json").write_text(json.dumps(orders))


def run_cli_on(directory: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(directory)], capture_output=True, text=True
    )


def test_contracts_directory_of_the_repo_is_the_seven_tables_reconcile_knows() -> None:
    assert sorted(p.stem for p in CONTRACTS.glob("*.json")) == sorted(by_value.TABLES)
    assert run_cli_on(CONTRACTS).returncode == 0


@pytest.mark.parametrize(
    ("change", "said"),
    [
        (lambda d: (d / "payments.json").unlink(), "missing: payments"),
        (lambda d: add_contract(d, "refunds", "shop.refunds"), "unknown: refunds"),
        (lambda d: add_contract(d, "orders_copy", "shop.orders"), "repeated: orders"),
        (lambda d: add_contract(d, "broken", "orders"), "not schema.table"),
    ],
    ids=["missing", "unknown", "duplicate", "source-table-without-schema"],
)
def test_cli_refuses_a_contract_set_that_is_not_the_seven_tables(
    tmp_path: Path, change: Any, said: str
) -> None:
    directory = contracts_copy(tmp_path)
    change(directory)

    result = run_cli_on(directory)

    assert result.returncode == 2
    # One line that says what is wrong and which tables, not a traceback.
    assert len(result.stderr.splitlines()) == 1, result.stderr
    assert said in result.stderr
    assert "Traceback" not in result.stderr
    # Not one line of a partial reconcile: a caller that reads stdout must not see 6 tables.
    assert result.stdout == ""


def test_reconcile_exits_2_before_any_query_when_a_contract_is_missing(tmp_path: Path) -> None:
    # `reconcile` in lib.sh: 6 lines and status 0 was what a deleted contract used to give.
    root = tmp_path / "root"
    (root / "scripts" / "chaos").mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "chaos" / "lib.sh", root / "scripts" / "chaos" / "lib.sh")
    (root / "scripts" / "reconcile_sql.py").symlink_to(SCRIPT)
    shutil.copytree(CONTRACTS, root / "contracts" / "silver")
    (root / "contracts" / "silver" / "payments.json").unlink()
    (root / ".env").write_text("OLTP_USER=user\nOLTP_DB=db\n")
    calls = tmp_path / "calls"
    calls.touch()
    script = (
        f'. "{root}/scripts/chaos/lib.sh"\n'
        'psql_value() { echo "postgres $1" >>"$CALLS"; echo "5 same"; }\n'
        'trino_value() { echo "trino $1" >>"$CALLS"; echo "5 same"; }\n'
        "reconcile\n"
    )

    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env={"PATH": os.environ["PATH"], "CALLS": str(calls)},
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "payments" in result.stderr
    assert result.stdout == ""
    assert calls.read_text() == ""
