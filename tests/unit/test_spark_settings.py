import pytest
from pydantic import ValidationError
from spark_jobs.catalog import catalog_conf
from spark_jobs.settings import Settings

CAT = "spark.sql.catalog.lake"


def test_unknown_catalog_type_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CATALOG_TYPE", "glue")

    with pytest.raises(ValidationError):
        Settings()


def test_rest_catalog_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CATALOG_TYPE", "rest")

    assert Settings().catalog_type == "rest"


def test_rest_catalog_points_at_lakekeeper_through_hadoop_file_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, value in {
        "CATALOG_TYPE": "rest",
        "LAKEKEEPER_URI": "http://catalog.test:8181/catalog",
        "LAKEKEEPER_WAREHOUSE": "wh",
        "CATALOG_JDBC_PASSWORD": "jdbc-secret",
        "S3_ENDPOINT": "http://minio.test:9000",
        "S3_ACCESS_KEY": "access",
        "S3_SECRET_KEY": "secret",
    }.items():
        monkeypatch.setenv(key, value)

    # The whole dict: no jdbc key leaks in, and the S3A block is the one jdbc gets.
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


def test_jdbc_catalog_keeps_its_keys_and_gains_only_the_file_io_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CATALOG_TYPE", raising=False)
    for key, value in {
        "CATALOG_JDBC_URL": "jdbc:postgresql://meta.test:5432/iceberg_catalog",
        "CATALOG_JDBC_USER": "jdbc-user",
        "CATALOG_JDBC_PASSWORD": "jdbc-secret",
        "CATALOG_WAREHOUSE": "s3a://bucket/warehouse",
        "S3_ENDPOINT": "http://minio.test:9000",
        "S3_ACCESS_KEY": "access",
        "S3_SECRET_KEY": "secret",
    }.items():
        monkeypatch.setenv(key, value)

    assert catalog_conf(Settings()) == {
        "spark.sql.extensions": "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        CAT: "org.apache.iceberg.spark.SparkCatalog",
        f"{CAT}.type": "jdbc",
        f"{CAT}.uri": "jdbc:postgresql://meta.test:5432/iceberg_catalog",
        f"{CAT}.jdbc.user": "jdbc-user",
        f"{CAT}.jdbc.password": "jdbc-secret",
        f"{CAT}.warehouse": "s3a://bucket/warehouse",
        "spark.hadoop.fs.s3a.impl": "org.apache.hadoop.fs.s3a.S3AFileSystem",
        "spark.hadoop.fs.s3a.endpoint": "http://minio.test:9000",
        "spark.hadoop.fs.s3a.access.key": "access",
        "spark.hadoop.fs.s3a.secret.key": "secret",
        "spark.hadoop.fs.s3a.path.style.access": "true",
        "spark.hadoop.fs.s3a.connection.ssl.enabled": "false",
        # The only additions of W2-T09: JdbcCatalog already defaults to HadoopFileIO, and s3://
        # tables created on the REST catalog stay readable after a rollback to JDBC.
        f"{CAT}.io-impl": "org.apache.iceberg.hadoop.HadoopFileIO",
        "spark.hadoop.fs.s3.impl": "org.apache.hadoop.fs.s3a.S3AFileSystem",
    }


def test_trigger_and_offsets_come_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRONZE_TRIGGER_SECONDS", "10")
    monkeypatch.setenv("BRONZE_MAX_OFFSETS_PER_TRIGGER", "5000")

    settings = Settings()

    assert (settings.bronze_trigger_seconds, settings.bronze_max_offsets_per_trigger) == (10, 5000)
