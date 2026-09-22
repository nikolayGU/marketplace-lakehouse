"""Configuration for the Spark jobs. Every value arrives from compose as an environment variable.

The image runs Python 3.10 (Ubuntu 22.04 in apache/spark), so this package avoids 3.11+ syntax.
"""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    kafka_bootstrap: str = "kafka:9092"

    # rest arrives with W2-T09 (ADR-005); until then anything else fails at startup.
    catalog_type: Literal["jdbc"] = "jdbc"
    catalog_jdbc_url: str = "jdbc:postgresql://postgres-meta:5432/iceberg_catalog"
    catalog_jdbc_user: str = "meta"
    catalog_jdbc_password: str = ""
    catalog_warehouse: str = "s3a://lakehouse/warehouse"
    checkpoint_root: str = "s3a://lakehouse/checkpoints"

    s3_endpoint: str = "http://minio:9000"
    s3_access_key: str = ""
    s3_secret_key: str = ""

    bronze_topic_pattern: str = r"oltp\.shop\..*"
    bronze_trigger_seconds: int = 20
    bronze_max_offsets_per_trigger: int = 20000

    metrics_port: int = 4041
