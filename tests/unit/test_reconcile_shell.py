"""`reconcile` in scripts/chaos/lib.sh, run for real with Postgres and Trino replaced by two
functions that answer from the environment. The SQL is the one scripts/reconcile_sql.py generates
from the real contracts, so a query that goes to the wrong side or a column that is read from the
wrong place shows up here, not only on a live stack."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from lakehouse import reconcile as by_value

REPO = Path(__file__).resolve().parents[2]
TABLES = sorted(by_value.TABLES)

# The stubs shadow the functions lib.sh defines. A fingerprint query is the one that pairs keys
# with row hashes (`k || '=' || h`); the other query of a table is count, keys and sums.
STUBS = r"""
answer() {
  local side=$1 sql=$2 table kind=basic
  printf '%s\t%s\n' "$side" "$sql" >>"$CALLS"
  [[ $sql =~ (shop|silver)\.([a-z_]+) ]] || return 1
  table=${BASH_REMATCH[2]}
  [[ $sql == *"k || '=' || h"* ]] && kind=values
  if [ "$kind" = values ]; then
    [ "$FAIL_VALUES" = "$side" ] && return 1
    [ "$EMPTY_VALUES" = "$side" ] && return 0
    if [ "$side" = trino ] && [ "$table" = "$DIFFERENT_VALUES" ]; then
      echo "5 changed"
    else
      echo "5 same"
    fi
  else
    [ "$EMPTY_BASIC" = "$side" ] && return 0
    echo "5 keys 1.00"
  fi
}
psql_value() { answer postgres "$1"; }
trino_value() { answer trino "$1"; }
"""


def run_reconcile(tmp_path: Path, **env: str) -> subprocess.CompletedProcess[str]:
    root = tmp_path / "root"
    (root / "scripts" / "chaos").mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "chaos" / "lib.sh", root / "scripts" / "chaos" / "lib.sh")
    (root / "scripts" / "reconcile_sql.py").symlink_to(REPO / "scripts" / "reconcile_sql.py")
    (root / "contracts").symlink_to(REPO / "contracts")
    (root / ".env").write_text("OLTP_USER=user\nOLTP_DB=db\n")
    calls = tmp_path / "calls"
    calls.touch()
    script = f'. "{root}/scripts/chaos/lib.sh"\n{STUBS}\nreconcile\n'
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ["PATH"],
            "CALLS": str(calls),
            "DIFFERENT_VALUES": "",
            "FAIL_VALUES": "",
            "EMPTY_VALUES": "",
            "EMPTY_BASIC": "",
            **env,
        },
    )


def lines_by_table(result: subprocess.CompletedProcess[str]) -> dict[str, str]:
    return {line.split()[0]: line for line in result.stdout.splitlines()}


def test_equal_fingerprints_say_values_ok_for_every_table(tmp_path: Path) -> None:
    result = run_reconcile(tmp_path)

    assert result.returncode == 0, result.stderr
    lines = lines_by_table(result)
    assert sorted(lines) == TABLES
    assert all(line.endswith("values ok") for line in lines.values()), result.stdout


def test_changed_value_under_equal_counts_and_keys_is_a_difference(tmp_path: Path) -> None:
    # A changed order_status keeps the row count and every key: only the fingerprint sees it.
    result = run_reconcile(tmp_path, DIFFERENT_VALUES="orders")

    assert result.returncode == 1, result.stderr
    lines = lines_by_table(result)
    assert "rows ok   keys ok" in lines["orders"]
    assert lines["orders"].endswith("values DIFF")
    assert all(lines[t].endswith("values ok") for t in TABLES if t != "orders")


def test_every_fingerprint_query_goes_to_its_own_side(tmp_path: Path) -> None:
    run_reconcile(tmp_path)

    calls = [line.split("\t", 1) for line in (tmp_path / "calls").read_text().splitlines()]
    for side, build in (
        ("postgres", by_value.fingerprint_sql_postgres),
        ("trino", by_value.fingerprint_sql_trino),
    ):
        sent = {sql for who, sql in calls if who == side}
        assert {build(t) for t in TABLES} <= sent


@pytest.mark.parametrize("side", ["postgres", "trino"])
def test_failed_fingerprint_query_is_exit_2_not_ok(tmp_path: Path, side: str) -> None:
    result = run_reconcile(tmp_path, FAIL_VALUES=side)

    assert result.returncode == 2
    assert "values ok" not in result.stdout


@pytest.mark.parametrize("side", ["postgres", "trino"])
def test_empty_fingerprint_is_exit_2_not_two_equal_nothings(tmp_path: Path, side: str) -> None:
    result = run_reconcile(tmp_path, EMPTY_VALUES=side)

    assert result.returncode == 2
    assert "values ok" not in result.stdout


@pytest.mark.parametrize("side", ["postgres", "trino"])
def test_empty_count_query_is_exit_2_and_names_the_table(tmp_path: Path, side: str) -> None:
    result = run_reconcile(tmp_path, EMPTY_BASIC=side)

    assert result.returncode == 2
    assert "returned nothing" in result.stderr
    assert "rows ok" not in result.stdout
