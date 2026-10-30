import ast
import importlib.util
import json
import sys
import types
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jinja2
import pytest
import yaml  # type: ignore[import-untyped]
from lakehouse import checks, reconcile, sql
from lakehouse.maintenance_commands import (
    DRY_RUN_FLAG,
    compact_bronze_command,
    dry_run_flag,
    expire_and_compact_enabled,
    expire_command,
    gold_expire_command,
    gold_orphans_command,
    orphans_command,
    position_deletes_command,
    silver_tables,
)
from lakehouse.settings import (
    CDC_STATE_SEEN,
    GOLD_NOT_COMPARED_RUNS,
    GOLD_WRITERS_POOL,
    LAST_BRONZE_SNAPSHOT,
    MAINTENANCE_TABLES,
    RETENTION_DAYS,
    SHOP_SLOT,
    SILVER_KEYS,
    SOURCE_TABLES,
    SPARK_SILVER_ENV,
    SPARK_SILVER_SECRETS,
    dbt_command,
    spark_silver_environment,
)
from lakehouse.spark_task import spark_job_kwargs
from spark_jobs import maintenance

REPO = Path(__file__).resolve().parents[2]


def spark_silver_compose_env() -> dict[str, str]:
    compose = yaml.safe_load((REPO / "docker" / "compose.yaml").read_text())
    return dict(compose["services"]["spark-silver"]["environment"])


def airflow_env() -> dict[str, str]:
    pairs = {}
    for line in (REPO / "docker" / "airflow" / "airflow.env").read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.startswith("#"):
            pairs[key] = value
    return pairs


def test_dag_passes_every_key_compose_gives_spark_silver() -> None:
    # A key compose adds to spark-silver and the DAG forgets: Airflow's silver run would differ
    # from make silver, or go to another catalog.
    assert set(SPARK_SILVER_ENV) == set(spark_silver_compose_env())


def test_airflow_env_carries_spark_silver_values_unchanged() -> None:
    compose_env = spark_silver_compose_env()
    passed = airflow_env()

    assert {key: passed.get(key) for key in compose_env} == compose_env


def test_secrets_go_to_private_environment_only() -> None:
    environ = {key: f"value of {key}" for key in SPARK_SILVER_ENV}

    public, private = spark_silver_environment(environ)

    assert set(private) == set(SPARK_SILVER_SECRETS)
    assert set(public) | set(private) == set(SPARK_SILVER_ENV)
    assert not set(public) & set(private)


def test_missing_key_fails_at_parse_time() -> None:
    environ = {key: "x" for key in SPARK_SILVER_ENV if key != "S3_SECRET_KEY"}

    with pytest.raises(KeyError, match="S3_SECRET_KEY"):
        spark_silver_environment(environ)


def test_silver_keys_are_the_primary_keys_of_the_contracts() -> None:
    contracts = {
        path.stem: json.loads(path.read_text())["x-primary-key"]
        for path in (REPO / "contracts" / "silver").glob("*.json")
    }

    assert {t: list(k) for t, k in SILVER_KEYS.items() if t != "quarantine"} == contracts


@pytest.mark.parametrize(
    ("latest", "remembered", "expected"),
    [
        (42, None, 42),  # silver_upsert never ran
        (42, "41", 42),  # bronze committed since
        (42, "42", None),  # nothing new: skip
        (None, None, None),  # bronze empty
    ],
)
def test_new_bronze_snapshot(
    latest: int | None, remembered: str | None, expected: int | None
) -> None:
    assert checks.new_bronze_snapshot(latest, remembered) == expected


NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("latest", "committed_ago", "remembered", "expected"),
    [
        (42, timedelta(minutes=6), "42", True),  # quiet and merged
        (42, timedelta(minutes=4), "42", False),  # bronze still moving
        (42, timedelta(minutes=6), "41", False),  # silver behind bronze
        (42, timedelta(minutes=6), None, False),  # silver_upsert never ran
        (None, None, None, True),  # empty bronze: nothing in flight
    ],
)
def test_at_rest(
    latest: int | None,
    committed_ago: timedelta | None,
    remembered: str | None,
    expected: bool,
) -> None:
    committed_at = NOW - committed_ago if committed_ago is not None else None

    assert checks.at_rest(latest, committed_at, remembered, NOW) is expected


def state(writes: int, flush: str | None, stalled: bool = False) -> checks.CdcState:
    return {"writes": writes, "flush": flush, "stalled": stalled}


@pytest.mark.parametrize(
    ("writes_now", "flush_now", "remembered", "stalled", "kept"),
    [
        # First run: nothing to compare with, the base is remembered.
        (10, "0/10", None, False, state(10, "0/10")),
        # Writes grew and the slot did not move: CDC stands.
        (15, "0/10", state(10, "0/10"), True, state(15, "0/10", True)),
        # Nothing changed after that: the stall holds until the slot moves (chaos 6, no writes
        # during the hold).
        (15, "0/10", state(15, "0/10", True), True, state(15, "0/10", True)),
        # The writes keep coming while it stands.
        (22, "0/10", state(15, "0/10", True), True, state(22, "0/10", True)),
        # The slot moved: CDC is alive, the base is the current pair.
        (15, "0/20", state(15, "0/10", True), False, state(15, "0/20")),
        (22, "0/20", state(10, "0/10"), False, state(22, "0/20")),
        # Nothing changed and it was not standing: still not.
        (10, "0/10", state(10, "0/10"), False, state(10, "0/10")),
        # Statistics were reset (crash): the counter fell, no verdict on a stall.
        (3, "0/10", state(10, "0/10", True), False, state(3, "0/10")),
        # No slot: CDC is dead, the strict verdict stays, the base still moves.
        (15, None, state(10, "0/10"), False, state(15, None)),
        (15, None, None, False, state(15, None)),
        (15, None, state(10, None), False, state(15, None)),
        # The slot appeared after a run without one: it moved from nothing.
        (15, "0/10", state(10, None), False, state(15, "0/10")),
    ],
)
def test_cdc_state(
    writes_now: int,
    flush_now: str | None,
    remembered: checks.CdcState | None,
    stalled: bool,
    kept: checks.CdcState,
) -> None:
    assert checks.cdc_state(writes_now, flush_now, remembered) == (stalled, kept)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("not json", None),
        ("[1, 2]", None),
        ('{"writes": "x", "flush": null, "stalled": false}', None),
        ('{"writes": 5}', None),
        ('{"writes": 5, "flush": "0/1", "stalled": true}', state(5, "0/1", True)),
        ('{"writes": 5, "flush": null, "stalled": false}', state(5, None)),
    ],
)
def test_load_cdc_state_ignores_what_it_cannot_read(
    raw: str | None, expected: checks.CdcState | None
) -> None:
    assert checks.load_cdc_state(raw) == expected


@pytest.mark.parametrize(
    ("differences", "resting", "stalled", "expected"),
    [
        (True, True, False, "red"),  # silent source, silver differs at rest: the check holds
        (True, True, True, "in_flight"),  # the source writes, nothing arrives
        (True, False, False, "in_flight"),  # bronze or silver still moving
        (True, False, True, "in_flight"),
        (False, True, False, "ok"),
        (False, True, True, "ok"),
        (False, False, False, "ok"),
        (False, False, True, "ok"),
    ],
)
def test_count_outcome(differences: bool, resting: bool, stalled: bool, expected: str) -> None:
    assert checks.count_outcome(differences, resting, stalled) == expected


@pytest.mark.parametrize(
    ("resting", "stalled", "expected"),
    [(True, False, False), (True, True, True), (False, False, True), (False, True, True)],
)
def test_skip_source_values(resting: bool, stalled: bool, expected: bool) -> None:
    assert checks.skip_source_values(resting, stalled) is expected


def test_shop_slot_is_the_slot_the_connector_creates() -> None:
    connector = json.loads((REPO / "connect" / "shop-connector.json").read_text())

    assert connector["config"]["slot.name"] == SHOP_SLOT
    assert f"'{SHOP_SLOT}'" in sql.CDC_PROGRESS


class Ref:
    """What calling a stubbed task returns: the output of that task, by name."""

    def __init__(self, name: str) -> None:
        self.name = name


class DqChecks:
    """dq_checks.py loaded with Airflow's decorators stubbed (Airflow is not installed on the
    host): the task bodies are plain functions, the wiring is recorded, and every outside call
    (Postgres, Trino, Variable, statsd) is replaced."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.bodies: dict[str, Callable[..., Any]] = {}
        self.wiring: dict[str, list[tuple[Any, ...]]] = {}
        self.variables: dict[str, str] = {}
        self.sent: list[tuple[str, object, dict[str, str]]] = []
        self.queries: list[str] = []
        self.postgres_counts: dict[str, int] = {}
        self.cdc: tuple[int | None, str | None] | None = (10, "0/10")
        self.bronze: list[list[Any]] = [[5, datetime(2026, 10, 1, tzinfo=UTC)]]
        self.gold_differs = False
        self.gmv_differs = False
        self.gold_updated = "2026-10-01 00:00:00"
        self.mart_updated: str | None = "2026-10-01 00:00:00"
        self.trino_fails_on: str | None = None
        variables = self.variables

        class Variable:
            @staticmethod
            def get(key: str, default: Any = None) -> Any:
                return variables.get(key, default)

            @staticmethod
            def set(key: str, value: str) -> None:
                variables[key] = value

        def task(body: Callable[..., Any]) -> Callable[..., Ref]:
            self.bodies[body.__name__] = body

            def call(*args: Any) -> Ref:
                self.wiring.setdefault(body.__name__, []).append(args)
                return Ref(body.__name__)

            return call

        def dag(**_: Any) -> Callable[[Callable[[], None]], Callable[[], None]]:
            return lambda body: body

        sdk = types.ModuleType("airflow.sdk")
        sdk.Variable = Variable  # type: ignore[attr-defined]
        sdk.dag = dag  # type: ignore[attr-defined]
        sdk.task = task  # type: ignore[attr-defined]
        package = types.ModuleType("airflow")
        package.sdk = sdk  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "airflow", package)
        monkeypatch.setitem(sys.modules, "airflow.sdk", sdk)
        spec = importlib.util.spec_from_file_location(
            "dq_checks_under_test", REPO / "airflow" / "dags" / "dq_checks.py"
        )
        assert spec is not None and spec.loader is not None
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        monkeypatch.setattr(self.module, "postgres_value", self.postgres_value)
        monkeypatch.setattr(self.module, "postgres_rows", self.postgres_rows)
        monkeypatch.setattr(self.module, "trino_value", self.trino_value)
        monkeypatch.setattr(self.module, "trino_rows", self.trino_rows)
        monkeypatch.setattr(self.module, "export", lambda *gauges: self.sent.extend(gauges))

    def run(self, name: str, *args: Any) -> Any:
        return self.bodies[name](*args)

    def postgres_value(self, _settings: object, query: str) -> Any:
        self.queries.append(query)
        if query == reconcile.gmv_fingerprint_sql_postgres():
            return "596 gmv"
        for table in SOURCE_TABLES:
            if query == sql.postgres_rows(table):
                return self.postgres_counts.get(table, 10)
        return "10 fp"

    def postgres_rows(self, _settings: object, query: str) -> list[tuple[Any, ...]]:
        self.queries.append(query)
        if query == sql.CDC_PROGRESS:
            return [] if self.cdc is None else [self.cdc]
        if query == reconcile.gmv_pairs_sql_postgres():
            return [("2026-07-17", "20585.00")]
        return []

    def trino_rows(self, _settings: object, query: str) -> list[list[Any]]:
        self.queries.append(query)
        if query == sql.LATEST_BRONZE_SNAPSHOT:
            return self.bronze
        if query == reconcile.gmv_pairs_sql_trino():
            return [["2026-07-17", "20585.01" if self.gmv_differs else "20585.00"]]
        for gold in reconcile.GOLD_PAIRS:
            if query == reconcile.gold_pairs_sql_trino(gold, "gold") and self.gold_differs:
                return [["key", "changed"]]
            if query == reconcile.gold_pairs_sql_trino(gold, "silver"):
                return [["key", "original"]]
        return []

    def trino_value(self, _settings: object, query: str) -> Any:
        self.queries.append(query)
        if query == self.trino_fails_on:
            raise RuntimeError("trino is down")
        if query == reconcile.gmv_fingerprint_sql_trino():
            return "596 other" if self.gmv_differs else "596 gmv"
        for table in SOURCE_TABLES:
            if query == sql.silver_live_rows(table):
                return 10
        if self.gold_differs and query in {
            reconcile.gold_sql_trino(g) for g in reconcile.GOLD_PAIRS
        }:
            return "10 other"
        if query in (reconcile.SILVER_CUSTOMERS_WITH_ORDERS, reconcile.GOLD_CUSTOMERS):
            return 4
        if query == reconcile.GOLD_UPDATED:
            return self.gold_updated
        if query == reconcile.MART_UPDATED:
            return self.mart_updated
        if query == reconcile.SILVER_UPDATED:
            return "2026-10-01 00:00:00"
        return "10 fp"

    def at_rest(self) -> None:
        self.variables[LAST_BRONZE_SNAPSHOT] = "5"

    def queried_source_values(self) -> bool:
        return any(query == reconcile.fingerprint_sql_postgres("orders") for query in self.queries)

    def queried_gold_values(self) -> bool:
        gold = next(iter(reconcile.GOLD_PAIRS))
        return reconcile.gold_sql_trino(gold) in self.queries

    def queried_gmv(self) -> bool:
        return {
            reconcile.gmv_fingerprint_sql_postgres(),
            reconcile.gmv_fingerprint_sql_trino(),
        } <= set(self.queries)

    def gauge(self, name: str) -> object:
        return next(value for sent, value, _ in self.sent if sent == name)


@pytest.fixture
def dq(monkeypatch: pytest.MonkeyPatch) -> DqChecks:
    return DqChecks(monkeypatch)


def test_dq_checks_hands_the_cdc_verdict_to_both_checks_that_use_it(dq: DqChecks) -> None:
    assert dq.wiring["silver_matches_postgres"][0][0].name == "cdc_progress"
    assert dq.wiring["reconcile_values"][0][0].name == "cdc_progress"
    assert dq.wiring["cdc_progress"] == [()]


def test_cdc_progress_remembers_the_pair_and_sends_the_gauge_every_run(dq: DqChecks) -> None:
    assert dq.run("cdc_progress") is False
    assert dq.gauge("lakehouse.dq.cdc_stalled") == 0
    assert json.loads(dq.variables[CDC_STATE_SEEN]) == state(10, "0/10")


def test_cdc_progress_holds_the_stall_when_nothing_changes(dq: DqChecks) -> None:
    dq.variables[CDC_STATE_SEEN] = json.dumps(state(10, "0/10"))
    dq.cdc = (15, "0/10")
    assert dq.run("cdc_progress") is True
    dq.sent.clear()

    assert dq.run("cdc_progress") is True  # no writes since: still stalled (chaos 6 hold)
    assert dq.gauge("lakehouse.dq.cdc_stalled") == 1

    dq.cdc = (15, "0/30")
    assert dq.run("cdc_progress") is False
    assert json.loads(dq.variables[CDC_STATE_SEEN]) == state(15, "0/30")


def test_cdc_progress_fails_when_the_write_counter_cannot_be_read(dq: DqChecks) -> None:
    dq.cdc = None

    with pytest.raises(RuntimeError, match="write counter"):
        dq.run("cdc_progress")
    assert CDC_STATE_SEEN not in dq.variables


def test_cdc_progress_without_a_slot_is_not_a_stall(dq: DqChecks) -> None:
    dq.variables[CDC_STATE_SEEN] = json.dumps(state(10, "0/10"))
    dq.cdc = (15, None)

    assert dq.run("cdc_progress") is False
    assert dq.gauge("lakehouse.dq.cdc_stalled") == 0


def test_counts_differ_at_rest_with_a_silent_source_is_red(dq: DqChecks) -> None:
    dq.at_rest()
    dq.postgres_counts = {"orders": 12}

    with pytest.raises(ValueError, match="differs from Postgres at rest"):
        dq.run("silver_matches_postgres", False)


def test_counts_differ_at_rest_with_a_stalled_cdc_is_no_verdict(
    dq: DqChecks, capsys: pytest.CaptureFixture[str]
) -> None:
    dq.at_rest()
    dq.postgres_counts = {"orders": 12}

    dq.run("silver_matches_postgres", True)

    assert "in flight" in capsys.readouterr().out


def test_counts_differ_while_bronze_is_moving_is_no_verdict(dq: DqChecks) -> None:
    dq.variables[LAST_BRONZE_SNAPSHOT] = "4"
    dq.postgres_counts = {"orders": 12}

    dq.run("silver_matches_postgres", False)


def test_source_values_are_compared_at_rest_with_a_live_cdc(dq: DqChecks) -> None:
    dq.at_rest()

    dq.run("reconcile_values", False)

    assert dq.queried_source_values()
    assert dq.queried_gold_values()
    assert dq.gauge("lakehouse.dq.reconcile_in_flight") == 0


def test_only_updates_at_a_stalled_cdc_raise_the_gauge_and_skip_only_the_source_pairs(
    dq: DqChecks,
) -> None:
    # An UPDATE moves no row count: silver and Postgres agree on counts, only the values differ.
    dq.at_rest()
    dq.variables[CDC_STATE_SEEN] = json.dumps(state(10, "0/10"))
    dq.cdc = (15, "0/10")

    stalled = dq.run("cdc_progress")
    dq.run("silver_matches_postgres", stalled)
    dq.run("reconcile_values", stalled)

    assert dq.gauge("lakehouse.dq.cdc_stalled") == 1
    assert not dq.queried_source_values()
    assert dq.queried_gold_values()
    assert dq.gauge("lakehouse.dq.reconcile_in_flight") == 1


def test_a_gold_difference_is_still_red_at_a_stalled_cdc(dq: DqChecks) -> None:
    dq.at_rest()
    dq.gold_differs = True

    with pytest.raises(ValueError, match="values differ at rest"):
        dq.run("reconcile_values", True)


def test_gmv_by_day_is_compared_with_the_source_at_rest(dq: DqChecks) -> None:
    dq.at_rest()

    dq.run("reconcile_values", False)

    assert dq.queried_gmv()
    assert dq.gauge("lakehouse.dq.reconcile_gmv_compared") == 1
    assert (
        "lakehouse.dq.reconcile_values_differing",
        0,
        {"pair": "source_gold", "table": "mart_daily_sales_gmv"},
    ) in dq.sent


def test_a_day_whose_gmv_differs_from_the_source_is_red_and_named(dq: DqChecks) -> None:
    # What a mutation in int_daily_sales looks like from here: gold says 20585.01 for a day
    # where Postgres says 20585.00, and every other check of the mart still agrees with itself.
    dq.at_rest()
    dq.gmv_differs = True

    with pytest.raises(ValueError) as failure:
        dq.run("reconcile_values", False)

    message = str(failure.value)
    assert "source_gold" in message
    assert "mart_daily_sales_gmv" in message
    assert "2026-07-17" in message
    assert dq.gauge("lakehouse.dq.reconcile_gmv_compared") == 1
    assert (
        "lakehouse.dq.reconcile_values_differing",
        1,
        {"pair": "source_gold", "table": "mart_daily_sales_gmv"},
    ) in dq.sent


def test_gmv_is_not_compared_at_a_stalled_cdc(dq: DqChecks) -> None:
    # The source has writes silver has not seen: the source-gold pair has no verdict either.
    dq.at_rest()
    dq.gmv_differs = True

    dq.run("reconcile_values", True)

    assert not dq.queried_gmv()
    assert dq.queried_gold_values()
    assert dq.gauge("lakehouse.dq.reconcile_gmv_compared") == 0


def test_gmv_is_not_compared_while_gold_is_behind_silver(dq: DqChecks) -> None:
    dq.at_rest()
    dq.gmv_differs = True
    dq.gold_updated = "2026-09-30 00:00:00"

    dq.run("reconcile_values", False)

    assert not dq.queried_gmv()
    assert dq.gauge("lakehouse.dq.reconcile_gmv_compared") == 0


@pytest.mark.parametrize("mart_updated", ["2026-09-30 23:59:59", None], ids=["older", "empty"])
def test_gmv_is_not_compared_while_the_mart_is_behind_fct_orders(
    dq: DqChecks, capsys: pytest.CaptureFixture[str], mart_updated: str | None
) -> None:
    # dbt builds fct_orders first and delete+inserts the mart's changed days after: in between
    # (and while the days are deleted) gold and the source differ for a reason that is not an error.
    dq.at_rest()
    dq.gmv_differs = True
    dq.mart_updated = mart_updated
    dq.variables[GOLD_NOT_COMPARED_RUNS] = "23"

    dq.run("reconcile_values", False)

    assert not dq.queried_gmv()
    assert dq.queried_gold_values()
    assert "mart_daily_sales has not caught up with fct_orders: GMV not compared" in (
        capsys.readouterr().out
    )
    # Gold was compared, the mart's lag is not the silver-gold alert's business.
    assert dq.gauge("lakehouse.dq.reconcile_gold_compared") == 1
    assert dq.gauge("lakehouse.dq.reconcile_gmv_compared") == 0
    assert dq.variables[GOLD_NOT_COMPARED_RUNS] == "0"


def test_gmv_is_compared_when_the_mart_is_as_new_as_fct_orders(dq: DqChecks) -> None:
    dq.at_rest()
    dq.gmv_differs = True
    dq.mart_updated = dq.gold_updated

    with pytest.raises(ValueError, match="mart_daily_sales_gmv"):
        dq.run("reconcile_values", False)

    assert dq.queried_gmv()


def test_gmv_is_not_compared_while_bronze_is_moving(dq: DqChecks) -> None:
    dq.variables[LAST_BRONZE_SNAPSHOT] = "4"
    dq.gmv_differs = True

    dq.run("reconcile_values", False)

    assert not dq.queried_gmv()
    assert dq.gauge("lakehouse.dq.reconcile_gmv_compared") == 0


def test_the_gmv_verdict_comes_after_the_silver_gold_verdicts(dq: DqChecks) -> None:
    dq.at_rest()
    dq.gold_differs = True
    dq.gmv_differs = True

    with pytest.raises(ValueError) as failure:
        dq.run("reconcile_values", False)

    message = str(failure.value)
    assert 0 <= message.index("silver_gold") < message.index("source_gold")


def test_nothing_is_compared_while_bronze_is_moving(dq: DqChecks) -> None:
    dq.variables[LAST_BRONZE_SNAPSHOT] = "4"

    dq.run("reconcile_values", False)

    assert not dq.queried_source_values()
    assert not dq.queried_gold_values()
    assert dq.gauge("lakehouse.dq.reconcile_in_flight") == 1


def test_a_run_without_a_verdict_counts_one_more_run_without_gold(dq: DqChecks) -> None:
    # SilverGoldNotCompared reads these gauges. They come in every run, also in the early return:
    # a series that only came when gold was reached would vanish at the statsd TTL during a
    # continuous replay and the alert would stay quiet.
    dq.variables[LAST_BRONZE_SNAPSHOT] = "4"
    dq.variables[GOLD_NOT_COMPARED_RUNS] = "3"

    dq.run("reconcile_values", False)

    assert dq.gauge("lakehouse.dq.reconcile_in_flight") == 1
    assert dq.gauge("lakehouse.dq.reconcile_gold_compared") == 0
    assert dq.gauge("lakehouse.dq.reconcile_gmv_compared") == 0
    assert dq.gauge("lakehouse.dq.gold_not_compared_runs") == 4
    assert dq.variables[GOLD_NOT_COMPARED_RUNS] == "4"


def test_gold_behind_silver_counts_one_more_run_without_gold(dq: DqChecks) -> None:
    dq.at_rest()
    dq.gold_updated = "2026-09-30 00:00:00"
    dq.variables[GOLD_NOT_COMPARED_RUNS] = "3"

    dq.run("reconcile_values", False)

    assert not dq.queried_gold_values()
    assert dq.gauge("lakehouse.dq.reconcile_gold_compared") == 0
    assert dq.gauge("lakehouse.dq.gold_not_compared_runs") == 4
    assert dq.variables[GOLD_NOT_COMPARED_RUNS] == "4"


def test_a_run_that_compared_gold_resets_the_count(dq: DqChecks) -> None:
    dq.at_rest()
    dq.variables[GOLD_NOT_COMPARED_RUNS] = "23"

    dq.run("reconcile_values", False)

    assert dq.gauge("lakehouse.dq.reconcile_gold_compared") == 1
    assert dq.gauge("lakehouse.dq.gold_not_compared_runs") == 0
    assert dq.variables[GOLD_NOT_COMPARED_RUNS] == "0"


def test_a_stalled_cdc_still_compares_gold_and_resets_the_count(dq: DqChecks) -> None:
    dq.at_rest()
    dq.variables[GOLD_NOT_COMPARED_RUNS] = "23"

    dq.run("reconcile_values", True)

    assert dq.queried_gold_values()
    assert dq.gauge("lakehouse.dq.reconcile_in_flight") == 1
    assert dq.gauge("lakehouse.dq.reconcile_gold_compared") == 1
    assert dq.gauge("lakehouse.dq.gold_not_compared_runs") == 0
    assert dq.variables[GOLD_NOT_COMPARED_RUNS] == "0"


@pytest.mark.parametrize("remembered", [None, "", "garbage", "-5"])
def test_a_count_that_is_missing_or_unreadable_starts_from_zero(
    dq: DqChecks, remembered: str | None
) -> None:
    dq.variables[LAST_BRONZE_SNAPSHOT] = "4"
    if remembered is not None:
        dq.variables[GOLD_NOT_COMPARED_RUNS] = remembered

    dq.run("reconcile_values", False)

    assert dq.gauge("lakehouse.dq.gold_not_compared_runs") == 1
    assert dq.variables[GOLD_NOT_COMPARED_RUNS] == "1"


@pytest.mark.parametrize(
    "failing_query",
    [
        reconcile.GOLD_UPDATED,  # before gold is known to be at rest
        reconcile.gold_sql_trino(next(iter(reconcile.GOLD_PAIRS))),  # inside the pair comparison
        reconcile.GOLD_CUSTOMERS,  # after the pairs
        reconcile.MART_UPDATED,  # after the silver-gold verdicts, before the mart is at rest
        reconcile.gmv_fingerprint_sql_trino(),  # the source-gold pair, the last gold query
    ],
    ids=["gold_updated", "first_gold_pair", "gold_customers", "mart_updated", "gmv"],
)
def test_a_comparison_that_fails_does_not_reset_the_count(dq: DqChecks, failing_query: str) -> None:
    dq.at_rest()
    dq.variables[GOLD_NOT_COMPARED_RUNS] = "23"

    dq.trino_fails_on = failing_query

    with pytest.raises(RuntimeError, match="trino is down"):
        dq.run("reconcile_values", False)

    assert dq.variables[GOLD_NOT_COMPARED_RUNS] == "23"


def test_count_differences_lists_only_tables_that_differ() -> None:
    postgres = {"orders": 10, "payments": 7}
    silver = {"orders": 10, "payments": 6}

    assert checks.count_differences(postgres, silver) == {"payments": (7, 6)}


def test_freshness_query_failures_are_told_apart_from_stale_sources() -> None:
    # dbt exits 1 both for a stale source and for a freshness query that failed: only the
    # status in target/sources.json tells them apart.
    sources = {
        "results": [
            {"unique_id": "source.marketplace.silver.orders", "status": "pass"},
            {"unique_id": "source.marketplace.silver.order_items", "status": "warn"},
            {"unique_id": "source.marketplace.silver.payments", "status": "error"},
            {"unique_id": "source.marketplace.silver.reviews", "status": "runtime error"},
        ]
    }

    assert checks.freshness_query_failures(sources) == ["source.marketplace.silver.reviews"]


def test_freshness_runs_in_a_target_path_of_its_own() -> None:
    # dq_checks and dbt_build run dbt at the same time in one container.
    command = dbt_command("source freshness", target_path="/tmp/dbt/freshness")

    assert "--target-path /tmp/dbt/freshness" in command
    assert "/tmp/dbt/target" not in command


def test_freshness_reads_the_time_column_each_table_has() -> None:
    # quarantine has no _updated_at: dq_checks' report failed on it with COLUMN_NOT_FOUND.
    assert "max(quarantined_at)" in sql.freshness_seconds("quarantine")
    assert "max(_updated_at)" in sql.freshness_seconds("orders")


def test_dbt_writes_only_to_tmp() -> None:
    # The project is mounted read-only into Airflow.
    command = dbt_command("build")

    assert "--project-dir /opt/dbt" in command
    assert "--target-path /tmp/dbt/target" in command
    assert "--log-path /tmp/dbt/logs" in command


# Maintenance (W5-T05a).


def dag_keywords(dag_file: str, call: str) -> dict[str, ast.expr]:
    """Keyword arguments of the first call to `call(...)` in a DAG file; Airflow is not on the
    host, so the file is read, not imported."""
    tree = ast.parse((REPO / "airflow" / "dags" / dag_file).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == call:
            return {k.arg: k.value for k in node.keywords if k.arg}
    raise AssertionError(f"{dag_file} has no call to {call}")


def test_the_gold_pool_has_one_slot_and_dbt_build_takes_it() -> None:
    # expire_snapshots and CREATE OR REPLACE of one gold table would race for the commit.
    pool = dag_keywords("dbt_build.py", "BashOperator")["pool"]

    assert GOLD_WRITERS_POOL == "gold_writers"
    assert isinstance(pool, ast.Name) and pool.id == "GOLD_WRITERS_POOL"
    assert "pools set gold_writers 1" in (REPO / "Makefile").read_text()


def test_maintenance_covers_every_silver_table_and_orders_per_minute() -> None:
    assert (*SILVER_KEYS, "orders_per_minute") == MAINTENANCE_TABLES
    assert RETENTION_DAYS == 7


def test_gold_tables_come_from_base_tables_only() -> None:
    # Views have no snapshots to expire.
    assert "table_schema = 'gold'" in sql.GOLD_BASE_TABLES
    assert "table_type = 'BASE TABLE'" in sql.GOLD_BASE_TABLES
    assert "lake.information_schema.tables" in sql.GOLD_BASE_TABLES


def template_flag(**params: object) -> str:
    return jinja2.Environment().from_string(DRY_RUN_FLAG).render(params=params)


def test_a_scheduled_orphans_run_is_a_dry_run() -> None:
    assert template_flag(dry_run=True) == dry_run_flag({"dry_run": True}) == "--dry-run"


@pytest.mark.parametrize("value", ["false", "False", 0, None, ""])
def test_only_a_real_false_turns_the_dry_run_off(value: object) -> None:
    # A string "false" from a hand-typed conf is truthy in Jinja: it must not delete anything.
    assert template_flag(dry_run=value) == dry_run_flag({"dry_run": value}) == "--dry-run"


def test_false_in_the_conf_turns_the_dry_run_off() -> None:
    assert template_flag(dry_run=False) == dry_run_flag({"dry_run": False}) == "--no-dry-run"


@pytest.mark.parametrize("dry_run", [True, False])
def test_mapped_gold_orphans_commands_carry_no_template(dry_run: bool) -> None:
    # Airflow does not render values a mapped task gets from XCom: the flag is resolved in the
    # task that builds the commands, from the run's params.
    command = gold_orphans_command("orders_daily", {"dry_run": dry_run})

    assert not any("{{" in part for part in command)
    assert assert_accepted_by_the_job(command) == ["lake.gold.orders_daily"]
    assert maintenance.parse_args(command[1:]).dry_run is dry_run


def test_the_gold_orphans_task_builds_commands_from_the_params() -> None:
    source = (REPO / "airflow" / "dags" / "iceberg_orphans.py").read_text()

    assert "gold_orphans_command(name, params or {})" in source
    assert "orphans_command([gold_table" not in source


def test_orphans_dag_is_a_weekly_dry_run_by_default() -> None:
    dag = dag_keywords("iceberg_orphans.py", "dag")

    assert ast.literal_eval(dag["params"]) == {"dry_run": True}
    assert ast.literal_eval(dag["schedule"]) == "0 4 * * 0"
    assert ast.literal_eval(dag["max_active_runs"]) == 1


def test_maintenance_expires_and_compacts_only_when_asked() -> None:
    # Unpausing the existing DAG must not start the W5-D13 ladder: expire and compaction wait
    # for a run with {"expire_and_compact": true} or for a code change of the default.
    dag = dag_keywords("iceberg_maintenance.py", "dag")

    assert ast.literal_eval(dag["params"]) == {"expire_and_compact": False}


@pytest.mark.parametrize(
    ("params", "enabled"),
    [({"expire_and_compact": True}, True), ({"expire_and_compact": "true"}, False), ({}, False)],
)
def test_only_a_real_true_enables_expire_and_compaction(
    params: dict[str, object], enabled: bool
) -> None:
    assert expire_and_compact_enabled(params) is enabled


def test_every_spark_step_of_maintenance_waits_for_the_switch() -> None:
    source = (REPO / "airflow" / "dags" / "iceberg_maintenance.py").read_text()

    assert "switch >> [rewrite_position_deletes, gold_commands]" in source


def test_airflow_env_pauses_new_dags() -> None:
    # iceberg_orphans relies on it: it never runs before the owner unpauses it.
    assert airflow_env()["AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION"] == "True"


def rendered(command: list[str], **params: object) -> list[str]:
    env = jinja2.Environment()
    return [env.from_string(part).render(params=params) for part in command]


def assert_accepted_by_the_job(command: list[str]) -> list[str]:
    """What the DAG passes, the job accepts: its rules are in code, not in the DAG."""
    assert command[0] == "maintenance"
    return maintenance.validate(maintenance.parse_args(command[1:]))


def test_silver_commands_pass_the_rules_of_the_job() -> None:
    expire = assert_accepted_by_the_job(rendered(expire_command(silver_tables())))
    deletes = assert_accepted_by_the_job(position_deletes_command("silver.orders"))

    assert "lake.silver.orders_per_minute" in expire
    assert len(expire) == len(MAINTENANCE_TABLES)
    assert deletes == ["lake.silver.orders"]
    assert maintenance.parse_args(expire_command(silver_tables())[1:]).days == 7


def test_gold_expire_takes_one_table_per_command() -> None:
    command = gold_expire_command("orders_daily")

    assert assert_accepted_by_the_job(command) == ["lake.gold.orders_daily"]


def test_bronze_is_compacted_up_to_yesterday_and_never_expired() -> None:
    command = compact_bronze_command()

    assert assert_accepted_by_the_job(command) == ["lake.bronze.cdc_events"]
    assert "--before-today" in command
    assert "expire" not in command


@pytest.mark.parametrize("dry_run", [True, False])
def test_orphans_commands_pass_the_rules_of_the_job(dry_run: bool) -> None:
    for command in (
        orphans_command(silver_tables()),
        orphans_command(["lake.bronze.cdc_events"], location_suffix="metadata"),
    ):
        assert_accepted_by_the_job(rendered(command, dry_run=dry_run))


def test_bronze_orphans_always_go_to_the_metadata_location() -> None:
    command = orphans_command(["lake.bronze.cdc_events"], location_suffix="metadata")

    assert command[command.index("--location-suffix") + 1] == "metadata"
    with pytest.raises(maintenance.PolicyError, match="ADR-021"):
        assert_accepted_by_the_job(rendered(orphans_command(["lake.bronze.cdc_events"])))


# Timeouts and one writer of the silver checkpoint (REL-03, DATA-09). Airflow is not on the host,
# so the DAG files are read; `make dags-check` repeats the timeout checks on the loaded DAGs.

DAG_FILES = sorted(path.name for path in (REPO / "airflow" / "dags").glob("*.py"))


def duration(node: ast.expr) -> timedelta:
    """The value of a `timedelta(minutes=..)` written in a DAG file."""
    assert isinstance(node, ast.Call), ast.unparse(node)
    assert getattr(node.func, "id", None) == "timedelta" and not node.args, ast.unparse(node)
    return timedelta(**{k.arg: ast.literal_eval(k.value) for k in node.keywords if k.arg})


def default_arg(dag: dict[str, ast.expr], name: str) -> ast.expr | None:
    default_args = dag.get("default_args")
    if not isinstance(default_args, ast.Dict):
        return None
    for key, value in zip(default_args.keys, default_args.values, strict=True):
        if isinstance(key, ast.Constant) and key.value == name:
            return value
    return None


@pytest.mark.parametrize("dag_file", DAG_FILES)
def test_every_dag_ends_a_run_that_hangs(dag_file: str) -> None:
    # A hung run holds its pool slot, and max_active_runs=1 queues every later run behind it.
    dag = dag_keywords(dag_file, "dag")

    assert "dagrun_timeout" in dag, f"{dag_file}: dag(...) has no dagrun_timeout"
    assert duration(dag["dagrun_timeout"]) > timedelta(0)


@pytest.mark.parametrize("dag_file", DAG_FILES)
def test_every_task_has_an_execution_timeout_within_the_dagrun_timeout(dag_file: str) -> None:
    dag = dag_keywords(dag_file, "dag")
    assert "dagrun_timeout" in dag, f"{dag_file}: dag(...) has no dagrun_timeout"
    limit = duration(dag["dagrun_timeout"])

    default = default_arg(dag, "execution_timeout")
    assert default is not None, f"{dag_file}: default_args has no execution_timeout"
    tree = ast.parse((REPO / "airflow" / "dags" / dag_file).read_text())
    # A task may set its own, but not a longer one than the run lives.
    own = [
        duration(keyword.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "execution_timeout"
    ]
    for timeout in (duration(default), *own):
        assert timedelta(0) < timeout <= limit, f"{dag_file}: {timeout} against {limit}"


# What Airflow uses for a task that sets neither (airflow.sdk.bases.operator, DEFAULT_RETRIES and
# DEFAULT_RETRY_DELAY; docker/airflow/airflow.env does not change them).
NO_RETRIES = 0
AIRFLOW_DEFAULT_RETRY_DELAY = timedelta(minutes=5)


def task_setting(name: str, node: ast.expr) -> Any:
    return ast.literal_eval(node) if name == "retries" else duration(node)


@pytest.mark.parametrize("dag_file", DAG_FILES)
def test_every_task_ends_all_its_attempts_before_the_dagrun_timeout(dag_file: str) -> None:
    # A hung attempt that the dagrun_timeout ends gets SIGTERM, and on_kill races a SIGKILL a few
    # seconds later: the container may survive. A hung task must end by its own execution_timeout
    # on each attempt, so all attempts and the waits between them fit in the run.
    dag = dag_keywords(dag_file, "dag")
    assert "dagrun_timeout" in dag, f"{dag_file}: dag(...) has no dagrun_timeout"
    limit = duration(dag["dagrun_timeout"])
    base: dict[str, Any] = {
        "retries": NO_RETRIES,
        "retry_delay": AIRFLOW_DEFAULT_RETRY_DELAY,
        "execution_timeout": None,
    }
    defaults = {
        name: task_setting(name, value)
        for name in base
        if (value := default_arg(dag, name)) is not None
    }
    # The default_args alone, then every call that sets one of the three itself, as the mapped
    # `.partial(retries=2, ...)` of the maintenance DAGs.
    settings: list[tuple[str, dict[str, Any]]] = [("default_args", {**base, **defaults})]
    tree = ast.parse((REPO / "airflow" / "dags" / dag_file).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            own = {k.arg: task_setting(k.arg, k.value) for k in node.keywords if k.arg in base}
            if own:
                settings.append((f"line {node.lineno}", {**base, **defaults, **own}))

    for where, task in settings:
        retries, timeout, delay = task["retries"], task["execution_timeout"], task["retry_delay"]
        assert timeout is not None, f"{dag_file} {where}: no execution_timeout"
        needed = (retries + 1) * timeout + retries * delay
        assert needed < limit, (
            f"{dag_file} {where}: {retries + 1} attempts of {timeout} and {retries} waits of "
            f"{delay} take {needed}, dagrun_timeout is {limit}"
        )


def docker_operator_calls(dag_file: str) -> list[ast.Call]:
    """`DockerOperator(...)` and `DockerOperator.partial(...)` calls of a DAG file."""
    tree = ast.parse((REPO / "airflow" / "dags" / dag_file).read_text())
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "partial":
            func = func.value
        if isinstance(func, ast.Name) and func.id == "DockerOperator":
            calls.append(node)
    return calls


def removes_container_with_force(call: ast.Call) -> bool:
    for keyword in call.keywords:
        if keyword.arg == "auto_remove":
            return isinstance(keyword.value, ast.Constant) and keyword.value.value == "force"
    # spark_job_kwargs sets "force" itself; an auto_remove given to it would override that.
    return any(
        keyword.arg is None
        and isinstance(keyword.value, ast.Call)
        and getattr(keyword.value.func, "id", None) == "spark_job_kwargs"
        and not any(inner.arg == "auto_remove" for inner in keyword.value.keywords)
        for keyword in call.keywords
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('DockerOperator(task_id="a", auto_remove="force")', True),
        ('DockerOperator(task_id="a", auto_remove="success")', False),
        ('DockerOperator(task_id="a")', False),
        ('DockerOperator(task_id="a", **spark_job_kwargs(POOL))', True),
        ('DockerOperator(task_id="a", **spark_job_kwargs(POOL, retries=2))', True),
        # **extra comes last in spark_job_kwargs and overrides its "force".
        ('DockerOperator(task_id="a", **spark_job_kwargs(POOL, auto_remove="success"))', False),
        ('DockerOperator(task_id="a", **spark_job_kwargs(POOL, auto_remove="force"))', False),
        (
            'DockerOperator.partial(task_id="a", **spark_job_kwargs(POOL, auto_remove="never"))',
            False,
        ),
    ],
)
def test_the_force_check_catches_what_overrides_it(source: str, expected: bool) -> None:
    call = ast.parse(source).body[0]
    assert isinstance(call, ast.Expr) and isinstance(call.value, ast.Call)

    assert removes_container_with_force(call.value) is expected


def test_every_docker_operator_removes_its_container_with_force() -> None:
    # With auto_remove="success" the provider's `finally` removes the container without force:
    # after a timeout it is still running, Docker answers 409, the error replaces the timeout,
    # and the Spark job keeps writing while the retry starts a second one.
    calls = [(name, call) for name in DAG_FILES for call in docker_operator_calls(name)]

    assert calls
    wrong = [
        f"{name}:{call.lineno}" for name, call in calls if not removes_container_with_force(call)
    ]
    assert not wrong, f"DockerOperator without auto_remove='force' or spark_job_kwargs: {wrong}"


def test_spark_job_kwargs_remove_the_container_with_force(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in SPARK_SILVER_ENV:
        monkeypatch.setenv(key, f"value of {key}")

    assert spark_job_kwargs("lake_writers")["auto_remove"] == "force"


def test_the_merge_container_has_a_fixed_name() -> None:
    # One silver writer: while a container of this name exists, a second start gets 409 from
    # Docker and fails instead of writing to the same checkpoint.
    merge = dag_keywords("silver_upsert.py", "DockerOperator")

    assert ast.literal_eval(merge["task_id"]) == "merge"
    assert "container_name" in merge, "merge has no container_name"
    assert ast.literal_eval(merge["container_name"]) == "lakehouse-silver-merge"
