"""The Postgres side of `reconcile` runs against a real Postgres, not only as text (audit b8, b16).

The other reconcile tests compare SQL strings, so a query Postgres rejects, or one that returns a
fingerprint that no longer follows from the rows, passes them. Here the schema `shop` is built by
the migrations of `oltp/migrations` in a database of its own, a few rows go in, and every Postgres
query of `lakehouse.reconcile` and of `scripts/reconcile_sql.py` is executed. The expected values
are computed in Python from the same rows, with their own copy of the canonical text rules.

Needs `RECONCILE_TEST_DSN`: a server on which the role may create a database (CI: the `postgres`
service of `.github/workflows/ci.yml`). Without it the tests that need Postgres are skipped, as in
`make check`. Never point it at the Postgres of the stack (`postgres-oltp`, on a laptop it is
localhost:5432): the tests create and drop a database of their own, but have no business there.
"""

import json
import os
import uuid
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import md5
from pathlib import Path
from typing import Any

import psycopg
import pytest
import yaml  # type: ignore[import-untyped]
from lakehouse import reconcile
from psycopg import sql
from psycopg.conninfo import make_conninfo
from replayer.migrations import apply, migrations_dir, pending

from scripts.reconcile_sql import load_contracts, queries, value_queries

DSN_VARIABLE = "RECONCILE_TEST_DSN"
REPO = Path(__file__).resolve().parents[2]
CONTRACTS = REPO / "contracts" / "silver"
Conn = psycopg.Connection[tuple[Any, ...]]

D = Decimal
T = datetime
DAY = "2017-01-05"

# One list of rows per table, in the column order of `reconcile.TABLES`. Two orders on one day are
# GMV; a canceled and an unavailable one on that day and a canceled one on another are not.
ROWS: dict[str, list[tuple[Any, ...]]] = {
    "customers": [
        ("c1", "u1", "01310", "sao paulo", "SP"),
        ("c2", "u2", "20040", "rio de janeiro", "RJ"),
        # Upper case sorts before lower case bytewise and after it in en_US: only `collate "C"`
        # in the queries puts C3 first.
        ("C3", "u3", "04538", "santos", "SP"),
    ],
    "sellers": [
        ("s1", "13023", "campinas", "SP"),
        ("s2", "30110", "belo horizonte", "MG"),
        ("S3", "80010", "curitiba", "PR"),
    ],
    "products": [
        ("p1", "toys", 40, 287, 1, 225, 16, 10, 14),
        ("p2", None, None, None, None, None, None, None, None),
    ],
    "orders": [
        (
            "o1",
            "c1",
            "delivered",
            T(2017, 1, 5, 10, 0, 0, 123999),
            T(2017, 1, 5, 10, 30),
            None,
            None,
            T(2017, 1, 20),
        ),
        ("o2", "c2", "shipped", T(2017, 1, 5, 12), None, None, None, T(2017, 1, 25)),
        ("o3", "c1", "canceled", T(2017, 1, 5, 13), None, None, None, T(2017, 1, 25)),
        ("o4", "c2", "canceled", T(2017, 2, 1, 9), None, None, None, T(2017, 2, 20)),
        ("o5", "c1", "unavailable", T(2017, 1, 5, 14), None, None, None, T(2017, 1, 25)),
    ],
    "order_items": [
        ("o1", 1, "p1", "s1", T(2017, 1, 9), D("10.50"), D("1.10")),
        ("o1", 2, "p2", "s1", T(2017, 1, 9), D("20.25"), D("2.00")),
        ("o2", 1, "p1", "s1", T(2017, 1, 10), D("5.00"), D("0.50")),
        ("o3", 1, "p1", "s1", T(2017, 1, 10), D("99.00"), D("9.00")),
        ("o4", 1, "p2", "s1", T(2017, 2, 5), D("7.00"), D("1.00")),
        ("o5", 1, "p1", "s1", T(2017, 1, 10), D("50.00"), D("5.00")),
    ],
    "payments": [
        ("o1", 1, "credit_card", 3, D("30.75")),
        ("o1", 2, "voucher", 1, D("5.00")),
        ("o2", 1, "boleto", 1, D("5.50")),
    ],
    # review_id repeats across orders in the source: only the pair is a key.
    "reviews": [
        ("r1", "o1", 5, "great", None, T(2017, 1, 10), T(2017, 1, 11, 8, 15)),
        ("r1", "o2", 4, None, "late, but fine", T(2017, 1, 12), T(2017, 1, 13)),
        ("r2", "o3", 1, "", "never came", T(2017, 1, 14), T(2017, 1, 15)),
    ],
}
GMV = {DAY: D("35.75")}

# Order of insertion that satisfies the foreign keys.
LOAD_ORDER = ("customers", "sellers", "products", "orders", "order_items", "payments", "reviews")


def _text(value: Any, silver_type: str) -> str:
    """The canonical text of one value, written again here and not taken from reconcile.py."""
    if value is None:
        return "\\N"
    if silver_type == "timestamp_ntz":
        return str((value - T(1970, 1, 1)) // timedelta(milliseconds=1))
    if silver_type.startswith("decimal"):
        scale = int(silver_type.split(",")[1].rstrip(") "))
        return f"{value:.{scale}f}"
    return str(value)


def _pairs(table: str) -> list[tuple[str, str]]:
    keys, columns = reconcile.TABLES[table]
    names = [c.name for c in columns]
    pairs = []
    for row in ROWS[table]:
        cells = [_text(v, c.silver_type) for v, c in zip(row, columns, strict=True)]
        key = ":".join(str(row[names.index(k)]) for k in keys)
        pairs.append((key, md5(chr(31).join(cells).encode()).hexdigest()))
    return sorted(pairs, key=lambda pair: pair[0].encode())


def _fingerprint(pairs: list[tuple[str, str]]) -> str:
    joined = ",".join(f"{k}={h}" for k, h in pairs)
    return f"{len(pairs)} {md5(joined.encode()).hexdigest()}"


def _dsn() -> str:
    dsn = os.environ.get(DSN_VARIABLE)
    if not dsn:
        pytest.skip(f"{DSN_VARIABLE} is not set: no Postgres to run the reconcile queries on")
    return dsn


def _require_a_collation_that_is_not_bytewise(connection: Conn) -> None:
    """In a database whose default collation is bytewise, `collate "C"` would prove nothing."""
    row = connection.execute(
        "select datcollate from pg_database where datname = current_database()"
    )
    collation = row.fetchone()
    ordered = connection.execute("select array_agg(k order by k) from (values ('S3'), ('s1')) v(k)")
    first = ordered.fetchone()
    assert collation is not None and first is not None
    assert first[0] == ["s1", "S3"], (
        f"the default collation {collation[0]!r} of the test database sorts S3 before s1, like "
        '"C": the key order the queries ask for cannot be told from the default'
    )


@pytest.fixture(scope="module")
def conn() -> Iterator[Conn]:
    """A connection to a database created for this module, with `shop` built by the migrations."""
    admin_dsn = _dsn()
    name = f"reconcile_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
    try:
        with psycopg.connect(make_conninfo(admin_dsn, dbname=name)) as connection:
            # What oltp/init does on the first start; migration 002 adds a table to the publication.
            connection.execute("create schema shop")
            connection.execute("create publication shop_publication for tables in schema shop")
            connection.commit()
            _require_a_collation_that_is_not_bytewise(connection)
            for path in pending(connection, migrations_dir()):
                apply(connection, path)
            for table in LOAD_ORDER:
                columns = [c.name for c in reconcile.TABLES[table][1]]
                statement = sql.SQL("insert into shop.{} ({}) values ({})").format(
                    sql.Identifier(table),
                    sql.SQL(", ").join(map(sql.Identifier, columns)),
                    sql.SQL(", ").join(sql.Placeholder() * len(columns)),
                )
                with connection.cursor() as cursor:
                    cursor.executemany(statement, ROWS[table])
            connection.commit()
            yield connection
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(
                sql.SQL("drop database if exists {} with (force)").format(sql.Identifier(name))
            )


@pytest.fixture(autouse=True)
def _rollback(request: pytest.FixtureRequest) -> Iterator[None]:
    yield
    if "conn" in request.fixturenames:
        request.getfixturevalue("conn").rollback()


def _value(conn: Conn, query: str) -> str:
    row = conn.execute(query).fetchone()
    assert row is not None
    return str(row[0])


def _rows(conn: Conn, query: str) -> list[tuple[Any, ...]]:
    return conn.execute(query).fetchall()


def test_the_seed_covers_every_table_reconcile_knows() -> None:
    assert set(ROWS) == set(reconcile.TABLES) == set(LOAD_ORDER)


@pytest.mark.parametrize("table", LOAD_ORDER)
def test_the_fingerprint_follows_from_the_rows(conn: Conn, table: str) -> None:
    got = _value(conn, reconcile.fingerprint_sql_postgres(table))

    assert got == _fingerprint(_pairs(table))
    assert _value(conn, reconcile.fingerprint_sql_postgres(table)) == got


@pytest.mark.parametrize("table", LOAD_ORDER)
def test_the_pairs_are_the_row_hashes_in_bytewise_key_order(conn: Conn, table: str) -> None:
    got = _rows(conn, reconcile.pairs_sql_postgres(table))

    assert got == _pairs(table)


def _contract(table: str) -> dict[str, Any]:
    contract: dict[str, Any] = json.loads((CONTRACTS / f"{table}.json").read_text())
    return contract


@pytest.mark.parametrize("table", LOAD_ORDER)
def test_the_script_queries_run_and_count_keys_and_sums(conn: Conn, table: str) -> None:
    contract = next(c for c in load_contracts(CONTRACTS) if c["x-source-table"] == f"shop.{table}")
    name, counts, _ = queries(contract)
    values, _ = value_queries(contract)
    keys = sorted(":".join(map(str, key)) for key in _key_values(table))
    decimals = [
        i for i, c in enumerate(reconcile.TABLES[table][1]) if c.silver_type.startswith("decimal")
    ]
    sums = [sum(row[i] for row in ROWS[table]) for i in decimals]
    expected = [str(len(keys)), md5(",".join(keys).encode()).hexdigest()]
    expected += [f"{total:.2f}" for total in sums]

    assert name == table
    assert _value(conn, counts) == " ".join(expected)
    assert _value(conn, values) == _fingerprint(_pairs(table))


def _key_values(table: str) -> list[tuple[Any, ...]]:
    keys, columns = reconcile.TABLES[table]
    names = [c.name for c in columns]
    return [tuple(row[names.index(k)] for k in keys) for row in ROWS[table]]


def test_the_sums_are_the_ones_the_rows_add_up_to() -> None:
    # The oracle above must not be trivially empty for the tables that carry money.
    assert sum(row[5] for row in ROWS["order_items"]) == D("191.75")
    assert sum(row[4] for row in ROWS["payments"]) == D("41.25")


def test_gmv_counts_the_days_of_orders_that_are_not_canceled(conn: Conn) -> None:
    pairs = [(day, f"{gmv:.2f}") for day, gmv in GMV.items()]

    assert _rows(conn, reconcile.gmv_pairs_sql_postgres()) == pairs
    assert _value(conn, reconcile.gmv_fingerprint_sql_postgres()) == _fingerprint(pairs)


# Each non-key column to a value of its own, valid under the checks and foreign keys of its table.
CHANGES: dict[str, Callable[[str], str]] = {
    "string": lambda c: f"left(md5(coalesce({c}, 'x')), 2)",
    "int": lambda c: f"coalesce({c}, 0) + 1",
    "decimal": lambda c: f"coalesce({c}, 0) + 0.01",
    "timestamp_ntz": lambda c: f"coalesce({c}, timestamp '2017-03-01') + interval '1 millisecond'",
}
SPECIFIC_VALUES = {
    ("orders", "order_status"): "'approved'",
    ("orders", "customer_id"): "'c2'",
    ("order_items", "product_id"): "'p2'",
    ("order_items", "seller_id"): "'s2'",
    ("payments", "payment_type"): "'debit_card'",
    ("reviews", "review_score"): "2",
}


def _non_key_columns() -> list[tuple[str, str, str]]:
    return [
        (table, column.name, column.silver_type)
        for table in LOAD_ORDER
        for column in reconcile.TABLES[table][1]
        if column.name not in reconcile.TABLES[table][0]
    ]


@pytest.mark.parametrize(
    ("table", "column", "silver_type"),
    _non_key_columns(),
    ids=[f"{t}.{c}" for t, c, _ in _non_key_columns()],
)
def test_a_changed_value_changes_the_fingerprint(
    conn: Conn, table: str, column: str, silver_type: str
) -> None:
    kind = "decimal" if silver_type.startswith("decimal") else silver_type
    new = SPECIFIC_VALUES.get((table, column)) or CHANGES[kind](column)
    before = _value(conn, reconcile.fingerprint_sql_postgres(table))

    try:
        conn.execute(f"update shop.{table} set {column} = {new}")
        after = _value(conn, reconcile.fingerprint_sql_postgres(table))
    finally:
        conn.rollback()

    assert after != before
    assert _value(conn, reconcile.fingerprint_sql_postgres(table)) == before


def test_a_changed_price_moves_the_gmv_of_its_day(conn: Conn) -> None:
    before = _value(conn, reconcile.gmv_fingerprint_sql_postgres())

    try:
        conn.execute("update shop.order_items set price = price + 1 where order_id = 'o1'")
        after = _value(conn, reconcile.gmv_fingerprint_sql_postgres())
        pairs = _rows(conn, reconcile.gmv_pairs_sql_postgres())
    finally:
        conn.rollback()

    assert after != before
    assert pairs == [(DAY, "37.75")]


def test_a_deleted_row_changes_the_count_and_the_key_set(conn: Conn) -> None:
    before = _value(conn, reconcile.fingerprint_sql_postgres("payments"))

    try:
        conn.execute("delete from shop.payments where order_id = 'o1' and payment_sequential = 2")
        after = _value(conn, reconcile.fingerprint_sql_postgres("payments"))
    finally:
        conn.rollback()

    assert before.split()[0] == "3"
    assert after.split()[0] == "2"
    assert after.split()[1] != before.split()[1]


def test_ci_runs_this_module_on_the_image_the_source_database_runs() -> None:
    ci = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text())
    compose = yaml.safe_load((REPO / "docker" / "compose.yaml").read_text())
    job = ci["jobs"]["lint-and-test"]
    steps = [s for s in job["steps"] if "test_reconcile_postgres.py" in s.get("run", "")]

    assert job["services"]["postgres"]["image"] == compose["services"]["postgres-oltp"]["image"]
    assert len(steps) == 1
    step = steps[0]
    # Exactly this command: `|| true`, `-k`, `--deselect` or a changed path each run less or hide
    # a failure. A step or a job that may fail, or runs only on a condition, can end green with
    # nothing run.
    assert step["run"].strip() == "uv run pytest tests/unit/test_reconcile_postgres.py -q"
    for where, spec in (("step", step), ("job", job)):
        assert "continue-on-error" not in spec, f"the {where} may fail without failing the job"
        assert "if" not in spec, f"the {where} runs only on a condition"
    # A skip would be a green job that ran nothing.
    assert step["env"]["FAIL_ON_SKIP"] == "1"
    assert step["env"][DSN_VARIABLE].startswith("postgresql://")
