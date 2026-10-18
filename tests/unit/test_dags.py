import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]
from lakehouse import checks, sql
from lakehouse.settings import (
    SILVER_KEYS,
    SPARK_SILVER_ENV,
    SPARK_SILVER_SECRETS,
    dbt_command,
    spark_silver_environment,
)

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
