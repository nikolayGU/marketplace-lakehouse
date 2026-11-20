import pytest
from pydantic import ValidationError
from spark_jobs.catalog import catalog_conf
from spark_jobs.settings import Settings

CAT = "spark.sql.catalog.lake"


def test_catalog_type_is_not_a_setting() -> None:
    assert "catalog_type" not in Settings.model_fields


def test_catalog_type_env_cannot_switch_the_catalog_off_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CATALOG_TYPE", "jdbc")

    assert catalog_conf(Settings())[f"{CAT}.type"] == "rest"


def test_rest_catalog_points_at_lakekeeper_through_hadoop_file_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, value in {
        "LAKEKEEPER_URI": "http://catalog.test:8181/catalog",
        "LAKEKEEPER_WAREHOUSE": "wh",
        "S3_ENDPOINT": "http://minio.test:9000",
        "S3_ACCESS_KEY": "access",
        "S3_SECRET_KEY": "secret",
    }.items():
        monkeypatch.setenv(key, value)

    # The whole dict: nothing but the REST catalog and the S3A block.
    assert catalog_conf(Settings()) == {
        "spark.sql.extensions": "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        CAT: "org.apache.iceberg.spark.SparkCatalog",
        f"{CAT}.type": "rest",
        f"{CAT}.uri": "http://catalog.test:8181/catalog",
        f"{CAT}.warehouse": "wh",
        f"{CAT}.io-impl": "org.apache.iceberg.hadoop.HadoopFileIO",
        "spark.hadoop.fs.s3a.impl": "org.apache.hadoop.fs.s3a.S3AFileSystem",
        "spark.hadoop.fs.s3.impl": "org.apache.hadoop.fs.s3a.S3AFileSystem",
        "spark.hadoop.fs.s3a.endpoint": "http://minio.test:9000",
        "spark.hadoop.fs.s3a.access.key": "access",
        "spark.hadoop.fs.s3a.secret.key": "secret",
        "spark.hadoop.fs.s3a.path.style.access": "true",
        "spark.hadoop.fs.s3a.connection.ssl.enabled": "false",
    }


def test_trigger_and_offsets_come_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRONZE_TRIGGER_SECONDS", "10")
    monkeypatch.setenv("BRONZE_MAX_OFFSETS_PER_TRIGGER", "5000")

    settings = Settings()

    assert (settings.bronze_trigger_seconds, settings.bronze_max_offsets_per_trigger) == (10, 5000)


def test_orders_per_minute_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("OPM_SOURCE_TOPIC", "OPM_TARGET", "OPM_TRIGGER", "OPM_SHUFFLE_PARTITIONS"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings()

    assert settings.opm_source_topic == "oltp.shop.orders"
    assert settings.opm_target == "lake.silver.orders_per_minute"
    assert settings.opm_watermark == "5 minutes"
    assert settings.opm_trigger == "processing"
    assert settings.opm_shuffle_partitions == 2


def test_orders_per_minute_trigger_accepts_only_known_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPM_TRIGGER", "continuous")

    with pytest.raises(ValidationError):
        Settings()
