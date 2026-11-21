"""Configuration for the Spark jobs. Every value arrives from compose as an environment variable.

The image runs Python 3.10 (Ubuntu 22.04 in apache/spark); ruff checks this as py310 (pyproject).
"""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    kafka_bootstrap: str = "kafka:9092"

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

    # orders_per_minute (ADR-024). An empty checkpoint means <checkpoint_root>/orders_per_minute.
    opm_source_topic: str = "oltp.shop.orders"
    opm_target: str = "lake.silver.orders_per_minute"
    opm_checkpoint: str = ""
    opm_watermark: str = "5 minutes"
    opm_trigger: Literal["processing", "available_now"] = "processing"
    opm_trigger_seconds: int = 20
    # Stored in the checkpoint on the first run: 200 state partitions would mean hundreds of small
    # files per batch in S3A, and only a new checkpoint changes the number.
    opm_shuffle_partitions: int = 2
