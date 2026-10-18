from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]
from lakehouse import checks
from lakehouse.settings import (
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


def test_dbt_writes_only_to_tmp() -> None:
    # The project is mounted read-only into Airflow.
    command = dbt_command("build")

    assert "--project-dir /opt/dbt" in command
    assert "--target-path /tmp/dbt/target" in command
    assert "--log-path /tmp/dbt/logs" in command
