"""Configuration for the Spark jobs. Every value arrives from compose as an environment variable.

The image runs Python 3.10 (Ubuntu 22.04 in apache/spark), so this package avoids 3.11+ syntax.
"""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    kafka_bootstrap: str = "kafka:9092"

    # rest: Lakekeeper (ADR-005). jdbc: the pre-cutover JdbcCatalog in postgres-meta, only through
    # the rollback in docs/runbooks/catalog-cutover.md. Anything else fails at startup.
    catalog_type: Literal["jdbc", "rest"] = "rest"
    catalog_jdbc_url: str = "jdbc:postgresql://postgres-meta:5432/iceberg_catalog"
    catalog_jdbc_user: str = "meta"
    catalog_jdbc_password: str = ""
    catalog_warehouse: str = "s3a://lakehouse/warehouse"
    lakekeeper_uri: str = "http://lakekeeper:8181/catalog"
    lakekeeper_warehouse: str = "lake"
    checkpoint_root: str = "s3a://lakehouse/checkpoints"

    s3_endpoint: str = "http://minio:9000"
    s3_access_key: str = ""
    s3_secret_key: str = ""

    bronze_topic_pattern: str = r"oltp\.shop\..*"
    bronze_trigger_seconds: int = 20
    bronze_max_offsets_per_trigger: int = 20000

    metrics_port: int = 4041

    contracts_dir: str = "/opt/app/contracts/silver"
    # Soft cap per micro-batch: the first run reads all of bronze in several batches.
    silver_max_rows_per_batch: int = 200000
    # local[2] has two cores; the default 200 would write up to 200 small files per MERGE.
    # Spark stores the value in the checkpoint on the first run and restores it on every later
    # one, so changing it takes effect only with a new checkpoint.
    silver_shuffle_partitions: int = 4
