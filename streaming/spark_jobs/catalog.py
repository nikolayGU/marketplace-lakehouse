"""SparkSession with the Iceberg catalog `lake` and S3A pointed at MinIO."""

from pyspark.sql import SparkSession

from spark_jobs.settings import Settings

CATALOG = "lake"


def catalog_conf(settings: Settings) -> dict[str, str]:
    """Spark conf for catalog `lake` and S3A. Kept apart from the builder so it is testable
    without a JVM."""
    cat = f"spark.sql.catalog.{CATALOG}"
    conf = {
        "spark.sql.extensions": "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        cat: "org.apache.iceberg.spark.SparkCatalog",
        # Both catalogs read and write through S3A. JdbcCatalog defaults to HadoopFileIO already;
        # the REST client would pick S3FileIO for s3 and s3a paths, and the image has no AWS SDK v2.
        f"{cat}.io-impl": "org.apache.iceberg.hadoop.HadoopFileIO",
        "spark.hadoop.fs.s3a.impl": "org.apache.hadoop.fs.s3a.S3AFileSystem",
        # Lakekeeper places new tables under s3://, and Hadoop 3.3 binds only s3a to S3A. Kept for
        # jdbc too, so such tables stay readable after a rollback to JDBC.
        "spark.hadoop.fs.s3.impl": "org.apache.hadoop.fs.s3a.S3AFileSystem",
        "spark.hadoop.fs.s3a.endpoint": settings.s3_endpoint,
        "spark.hadoop.fs.s3a.access.key": settings.s3_access_key,
        "spark.hadoop.fs.s3a.secret.key": settings.s3_secret_key,
        "spark.hadoop.fs.s3a.path.style.access": "true",
        "spark.hadoop.fs.s3a.connection.ssl.enabled": "false",
    }
    if settings.catalog_type == "jdbc":
        conf |= {
            f"{cat}.type": "jdbc",
            f"{cat}.uri": settings.catalog_jdbc_url,
            f"{cat}.jdbc.user": settings.catalog_jdbc_user,
            f"{cat}.jdbc.password": settings.catalog_jdbc_password,
            f"{cat}.warehouse": settings.catalog_warehouse,
        }
    else:
        conf |= {
            f"{cat}.type": "rest",
            f"{cat}.uri": settings.lakekeeper_uri,
            f"{cat}.warehouse": settings.lakekeeper_warehouse,
        }
    return conf


def build_session(app_name: str, settings: Settings) -> SparkSession:
    """Master and driver memory come from spark-submit, because in local mode the driver JVM
    is already running by the time this builder sees any config."""
    builder = SparkSession.builder.appName(app_name)
    for key, value in catalog_conf(settings).items():
        builder = builder.config(key, value)
    return builder.getOrCreate()
