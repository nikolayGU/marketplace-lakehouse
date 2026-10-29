"""Configuration of the DAGs, all from the environment of the Airflow containers
(docker/airflow/airflow.env)."""

from collections.abc import Mapping

from pydantic_settings import BaseSettings, SettingsConfigDict

SILVER_ASSET_NAME = "lake.silver"
# Id of the bronze snapshot that silver_upsert merged last; dq_checks reads it to tell rest from
# work in flight.
LAST_BRONZE_SNAPSHOT = "silver_upsert_last_bronze_snapshot"
# Where the previous dq_checks run left the write counter of schema shop and the position the
# slot had confirmed (sql.CDC_PROGRESS, JSON); checks.cdc_state tells from them whether CDC stands.
CDC_STATE_SEEN = "dq_checks_cdc_state"
# The replication slot Debezium reads (connect/shop-connector.json, slot.name).
SHOP_SLOT = "shop_slot"
LAKE_WRITERS_POOL = "lake_writers"
# Gold writers: dbt_build and the gold maintenance, so a CREATE OR REPLACE and an expire_snapshots
# of one table never commit at once (W5-D11).
GOLD_WRITERS_POOL = "gold_writers"

# Primary keys of the silver tables, as contracts/silver/<table>.json declares them; quarantine
# holds one row per Kafka record. tests/unit/test_dags.py compares them with the contracts.
SILVER_KEYS: dict[str, tuple[str, ...]] = {
    "customers": ("customer_id",),
    "sellers": ("seller_id",),
    "products": ("product_id",),
    "orders": ("order_id",),
    "order_items": ("order_id", "order_item_id"),
    "payments": ("order_id", "payment_sequential"),
    "reviews": ("review_id", "order_id"),
    "quarantine": ("topic", "kafka_partition", "kafka_offset"),
}
SOURCE_TABLES = tuple(t for t in SILVER_KEYS if t != "quarantine")

# Silver tables the maintenance DAGs treat: the contract tables, quarantine, and the streaming
# aggregate (W5-D12). Snapshots are kept this many days (Trino refuses fewer than 7, ADR-025).
MAINTENANCE_TABLES = (*SILVER_KEYS, "orders_per_minute")
RETENTION_DAYS = 7

# The environment compose gives spark-silver (docker/compose.yaml); the DAG passes the same to
# the container it starts. The secrets go to DockerOperator's private_environment, which the
# Airflow UI does not render.
SPARK_SILVER_ENV = (
    "SPARK_MASTER",
    "SPARK_DRIVER_MEMORY",
    "CATALOG_TYPE",
    "CATALOG_JDBC_URL",
    "CATALOG_JDBC_USER",
    "CATALOG_JDBC_PASSWORD",
    "CATALOG_WAREHOUSE",
    "CHECKPOINT_ROOT",
    "LAKEKEEPER_URI",
    "LAKEKEEPER_WAREHOUSE",
    "S3_ENDPOINT",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
)
SPARK_SILVER_SECRETS = ("CATALOG_JDBC_PASSWORD", "S3_ACCESS_KEY", "S3_SECRET_KEY")

DBT = "/opt/dbt-venv/bin/dbt"
DBT_PROJECT = "/opt/dbt"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    compose_project_name: str = "lakehouse"
    spark_image: str = "lakehouse/spark:dev"

    trino_host: str = "trino"
    trino_port: int = 8080

    oltp_host: str = "postgres-oltp"
    oltp_port: int = 5432
    oltp_db: str = "shop"
    oltp_user: str = "shop"
    oltp_password: str = ""

    # statsd-exporter of profile obs; dq_checks sends its gauges there (W4-D2).
    statsd_host: str = "statsd-exporter"
    statsd_port: int = 9125

    @property
    def lake_network(self) -> str:
        """Compose names the network `<project>_lake`; a fresh clone runs as lakehouse-fresh."""
        return f"{self.compose_project_name}_lake"


def spark_silver_environment(environ: Mapping[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """(public, private) environment for the spark-silver container.

    Raises KeyError for a key airflow.env lacks: the DAG file then fails to import, which the UI
    and `airflow dags list-import-errors` show, instead of a silver run on another catalog.
    """
    missing = [key for key in SPARK_SILVER_ENV if key not in environ]
    if missing:
        raise KeyError(f"docker/airflow/airflow.env lacks {missing}")
    public = {k: environ[k] for k in SPARK_SILVER_ENV if k not in SPARK_SILVER_SECRETS}
    private = {k: environ[k] for k in SPARK_SILVER_SECRETS}
    return public, private


def dbt_command(subcommand: str, target_path: str = "/tmp/dbt/target") -> str:
    """dbt inside Airflow: the project is mounted read-only, so target and logs go to /tmp."""
    return (
        f"{DBT} {subcommand} --project-dir {DBT_PROJECT} --profiles-dir {DBT_PROJECT}"
        f" --target dev --target-path {target_path} --log-path /tmp/dbt/logs"
    )
