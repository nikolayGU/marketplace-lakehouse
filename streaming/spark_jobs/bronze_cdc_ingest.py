"""Kafka `oltp.shop.*` -> `lake.bronze.cdc_events`, append-only (ADR-007, ADR-008).

Bronze is an at-least-once journal: it parses only what routing, dedup and ordering need (op,
lsn, sequence, times) and keeps `before` and `after` as JSON text. Typing happens in silver
against `contracts/`.
"""

import logging

from pyspark.sql import Column, DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import LongType, StringType, StructField, StructType

from spark_jobs.catalog import CATALOG, build_session
from spark_jobs.metrics import start_metrics
from spark_jobs.settings import Settings

TABLE = f"{CATALOG}.bronze.cdc_events"
QUERY_NAME = "bronze_cdc_ingest"

log = logging.getLogger(QUERY_NAME)

# The subset of contracts/cdc-envelope.schema.json that bronze reads; a unit test keeps the two
# in step. `before` and `after` are declared as strings: Spark's JSON parser then hands back the
# nested object as its raw JSON text, which is exactly what bronze stores.
ENVELOPE = StructType(
    [
        StructField("op", StringType()),
        StructField("ts_ms", LongType()),
        StructField("before", StringType()),
        StructField("after", StringType()),
        StructField(
            "source",
            StructType(
                [
                    StructField("lsn", LongType()),
                    StructField("sequence", StringType()),
                    StructField("ts_ms", LongType()),
                    StructField("table", StringType()),
                ]
            ),
        ),
    ]
)

DDL = f"""
create table if not exists {TABLE} (
    topic string,
    kafka_partition int,
    kafka_offset bigint,
    kafka_ts timestamp,
    key string,
    op string,
    lsn bigint,
    source_sequence string,
    ts_ms bigint,
    source_ts_ms bigint,
    source_table string,
    before string,
    after string,
    raw string,
    ingest_ts timestamp
)
using iceberg
partitioned by (source_table, days(ingest_ts))
tblproperties ('format-version' = '2')
"""

# Columns added after the table first shipped, as (name, type, after). The DDL above already has
# them in place for a fresh start; ensure_table adds them to an older table, where they must land
# in the same position because the streaming sink checks column order.
ADDED_COLUMNS = (("source_sequence", "string", "lsn"),)


def ensure_table(spark: SparkSession) -> None:
    """Create bronze, or add the columns it gained since. Iceberg has no ADD COLUMN IF NOT
    EXISTS, so the check is ours; a second run changes nothing."""
    spark.sql(DDL)
    existing = set(spark.table(TABLE).columns)
    for name, kind, after in ADDED_COLUMNS:
        if name not in existing:
            log.warning("%s lacks %s, adding it as %s after %s", TABLE, name, kind, after)
            spark.sql(f"alter table {TABLE} add column {name} {kind} after {after}")


def source_table(topic: Column) -> Column:
    """Taken from the topic name, not the payload, so an unparseable event still lands in the
    right partition and silver can quarantine it per table."""
    return F.element_at(F.split(topic, r"\."), -1)


def to_bronze(kafka: DataFrame) -> DataFrame:
    """Map Kafka records to bronze rows. `raw` keeps the original value only when the envelope
    did not parse into an `op`, which is what silver routes to quarantine."""
    value = F.col("value").cast("string")
    env = F.from_json(value, ENVELOPE)
    return kafka.select(
        F.col("topic"),
        F.col("partition").alias("kafka_partition"),
        F.col("offset").alias("kafka_offset"),
        F.col("timestamp").alias("kafka_ts"),
        F.col("key").cast("string").alias("key"),
        env["op"].alias("op"),
        env["source"]["lsn"].alias("lsn"),
        # [end of the previous transaction's commit record, this change's LSN] as text (ADR-022).
        env["source"]["sequence"].alias("source_sequence"),
        env["ts_ms"].alias("ts_ms"),
        env["source"]["ts_ms"].alias("source_ts_ms"),
        source_table(F.col("topic")).alias("source_table"),
        env["before"].alias("before"),
        env["after"].alias("after"),
        F.when(env["op"].isNull(), value).alias("raw"),
        F.current_timestamp().alias("ingest_ts"),
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings()
    spark = build_session(QUERY_NAME, settings)
    spark.streams.addListener(start_metrics(settings.metrics_port))

    spark.sql(f"create namespace if not exists {CATALOG}.bronze")
    ensure_table(spark)

    kafka = (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", settings.kafka_bootstrap)
        .option("subscribePattern", settings.bronze_topic_pattern)
        # Only consulted on the very first start; afterwards offsets come from the checkpoint.
        .option("startingOffsets", "earliest")
        .option("maxOffsetsPerTrigger", settings.bronze_max_offsets_per_trigger)
        # Offsets that retention deleted before we read them are lost data: fail loudly.
        .option("failOnDataLoss", "true")
        .load()
    )

    query = (
        to_bronze(kafka)
        .writeStream.format("iceberg")
        .queryName(QUERY_NAME)
        .outputMode("append")
        .trigger(processingTime=f"{settings.bronze_trigger_seconds} seconds")
        .option("checkpointLocation", f"{settings.checkpoint_root}/{QUERY_NAME}")
        # A micro-batch mixes all seven tables; fanout writes each partition without a sort.
        .option("fanout-enabled", "true")
        .toTable(TABLE)
    )
    query.awaitTermination()


if __name__ == "__main__":
    main()
