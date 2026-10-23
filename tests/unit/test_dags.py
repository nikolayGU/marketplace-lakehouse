import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jinja2
import pytest
import yaml  # type: ignore[import-untyped]
from lakehouse import checks, sql
from lakehouse.maintenance_commands import (
    DRY_RUN_FLAG,
    compact_bronze_command,
    expire_command,
    gold_expire_command,
    gold_table,
    orphans_command,
    position_deletes_command,
    silver_tables,
)
from lakehouse.settings import (
    GOLD_WRITERS_POOL,
    MAINTENANCE_TABLES,
    RETENTION_DAYS,
    SILVER_KEYS,
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


def dry_run_flag(**params: object) -> str:
    return jinja2.Environment().from_string(DRY_RUN_FLAG).render(params=params)


def test_a_scheduled_orphans_run_is_a_dry_run() -> None:
    assert dry_run_flag(dry_run=True) == "--dry-run"


@pytest.mark.parametrize("value", ["false", "False", 0, None, ""])
def test_only_a_real_false_turns_the_dry_run_off(value: object) -> None:
    # A string "false" from a hand-typed conf is truthy in Jinja: it must not delete anything.
    assert dry_run_flag(dry_run=value) == "--dry-run"


def test_false_in_the_conf_turns_the_dry_run_off() -> None:
    assert dry_run_flag(dry_run=False) == "--no-dry-run"


def test_orphans_dag_is_a_weekly_dry_run_by_default() -> None:
    dag = dag_keywords("iceberg_orphans.py", "dag")

    assert ast.literal_eval(dag["params"]) == {"dry_run": True}
    assert ast.literal_eval(dag["schedule"]) == "0 4 * * 0"
    assert ast.literal_eval(dag["max_active_runs"]) == 1


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
        orphans_command([gold_table("orders_daily")]),
        orphans_command(["lake.bronze.cdc_events"], location_suffix="metadata"),
    ):
        assert_accepted_by_the_job(rendered(command, dry_run=dry_run))


def test_bronze_orphans_always_go_to_the_metadata_location() -> None:
    command = orphans_command(["lake.bronze.cdc_events"], location_suffix="metadata")

    assert command[command.index("--location-suffix") + 1] == "metadata"
    with pytest.raises(maintenance.PolicyError, match="ADR-021"):
        assert_accepted_by_the_job(rendered(orphans_command(["lake.bronze.cdc_events"])))
