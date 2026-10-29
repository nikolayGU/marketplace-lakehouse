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
        for table in SOURCE_TABLES:
            if query == sql.postgres_rows(table):
                return self.postgres_counts.get(table, 10)
        return "10 fp"

    def postgres_rows(self, _settings: object, query: str) -> list[tuple[Any, ...]]:
        self.queries.append(query)
        if query == sql.CDC_PROGRESS:
            return [] if self.cdc is None else [self.cdc]
        return []

    def trino_rows(self, _settings: object, query: str) -> list[list[Any]]:
        self.queries.append(query)
        if query == sql.LATEST_BRONZE_SNAPSHOT:
            return self.bronze
        for gold in reconcile.GOLD_PAIRS:
            if query == reconcile.gold_pairs_sql_trino(gold, "gold") and self.gold_differs:
                return [["key", "changed"]]
            if query == reconcile.gold_pairs_sql_trino(gold, "silver"):
                return [["key", "original"]]
        return []

    def trino_value(self, _settings: object, query: str) -> Any:
        self.queries.append(query)
        for table in SOURCE_TABLES:
            if query == sql.silver_live_rows(table):
                return 10
        if self.gold_differs and query in {
            reconcile.gold_sql_trino(g) for g in reconcile.GOLD_PAIRS
        }:
            return "10 other"
        if query in (reconcile.SILVER_CUSTOMERS_WITH_ORDERS, reconcile.GOLD_CUSTOMERS):
            return 4
        if query in (reconcile.GOLD_UPDATED, reconcile.SILVER_UPDATED):
            return "2026-10-01 00:00:00"
        return "10 fp"

    def at_rest(self) -> None:
        self.variables[LAST_BRONZE_SNAPSHOT] = "5"

    def queried_source_values(self) -> bool:
        return any(query == reconcile.fingerprint_sql_postgres("orders") for query in self.queries)

    def queried_gold_values(self) -> bool:
        gold = next(iter(reconcile.GOLD_PAIRS))
        return reconcile.gold_sql_trino(gold) in self.queries

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


def test_nothing_is_compared_while_bronze_is_moving(dq: DqChecks) -> None:
    dq.variables[LAST_BRONZE_SNAPSHOT] = "4"

    dq.run("reconcile_values", False)

    assert not dq.queried_source_values()
    assert not dq.queried_gold_values()
    assert dq.gauge("lakehouse.dq.reconcile_in_flight") == 1


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
