"""SparkSession with the Iceberg catalog `lake` and S3A pointed at MinIO."""

from pyspark.sql import SparkSession

from spark_jobs.settings import Settings

CATALOG = "lake"


def build_session(app_name: str, settings: Settings) -> SparkSession:
    """Master and driver memory come from spark-submit, because in local mode the driver JVM
    is already running by the time this builder sees any config."""
    cat = f"spark.sql.catalog.{CATALOG}"
    return (
        SparkSession.builder.appName(app_name)
        .config(
            "spark.sql.extensions",
            "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        )
        .config(cat, "org.apache.iceberg.spark.SparkCatalog")
        .config(f"{cat}.type", "jdbc")
        .config(f"{cat}.uri", settings.catalog_jdbc_url)
        .config(f"{cat}.jdbc.user", settings.catalog_jdbc_user)
        .config(f"{cat}.jdbc.password", settings.catalog_jdbc_password)
        .config(f"{cat}.warehouse", settings.catalog_warehouse)
        .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem")
        .config("spark.hadoop.fs.s3a.endpoint", settings.s3_endpoint)
        .config("spark.hadoop.fs.s3a.access.key", settings.s3_access_key)
        .config("spark.hadoop.fs.s3a.secret.key", settings.s3_secret_key)
        .config("spark.hadoop.fs.s3a.path.style.access", "true")
        .config("spark.hadoop.fs.s3a.connection.ssl.enabled", "false")
        .getOrCreate()
    )
