"""Orders per minute, a stateful streaming job (W5-T01a, ADR-024).

Reads the new-order events (`op = 'c'`) of `oltp.shop.orders` from Kafka and counts distinct
orders per one-minute window of `order_purchase_timestamp`, with a watermark of five minutes.

- Why `update`: a window is written as soon as its count changes, and a window the watermark has
  closed is dropped from state. `append` would hold every row back until its window closes.
- Why `size(collect_set(order_id))`, not `count(*)`: Debezium delivers at least once, and a resend
  after a Connect kill would raise a count. Spark 3.5 cannot chain `dropDuplicatesWithinWatermark`
  and an aggregation in `update` mode, so the distinct set lives in the aggregate itself.
- Why only `c`: a snapshot read (`r`) comes in table order, not in time order, and nearly all of it
  would be behind the watermark. An update does not create an order.
- A window is closed when its end is not later than the watermark, which trails the largest event
  time seen by the delay. A late event for a closed window is dropped, counted in
  `numRowsDroppedByWatermark`; one for an open window changes the count.

Python 3.10 in the image: no syntax newer than that.
"""

import logging
from typing import Any

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from spark_jobs.bronze_cdc_ingest import ENVELOPE
from spark_jobs.catalog import build_session
from spark_jobs.contracts import MAX_EPOCH_MS, MIN_EPOCH_MS
from spark_jobs.metrics import start_metrics
from spark_jobs.settings import Settings

QUERY_NAME = "orders_per_minute"

log = logging.getLogger(QUERY_NAME)

DDL = """
create table if not exists {target} (
    window_start timestamp_ntz,
    orders bigint,
    _updated_at timestamp
)
using iceberg
partitioned by (days(window_start))
tblproperties ('format-version' = '2')
"""
COLUMNS = ("window_start", "orders", "_updated_at")


def parse_orders(kafka: DataFrame) -> DataFrame:
    """(order_id, purchase_ts) of every new order in `kafka`, a frame with a `value` column.
    Anything else (not an envelope, another op, no id, a time Spark cannot represent) is left
    out rather than failing the query; silver quarantines such records, this job only counts."""
    env = F.from_json(F.col("value").cast("string"), ENVELOPE)
    order_id = F.get_json_object(env["after"], "$.order_id")
    purchase_ms = F.get_json_object(env["after"], "$.order_purchase_timestamp").cast("long")
    return (
        kafka.select(env["op"].alias("op"), order_id.alias("order_id"), purchase_ms.alias("ms"))
        .where(
            (F.col("op") == "c")
            & F.col("order_id").isNotNull()
            & (F.col("order_id") != "")
            & F.col("ms").between(MIN_EPOCH_MS, MAX_EPOCH_MS)
        )
        .select("order_id", F.expr("timestamp_millis(ms)").alias("purchase_ts"))
    )


def windowed_counts(events: DataFrame, delay: str) -> DataFrame:
    """(window_start, orders): distinct orders per minute of purchase_ts, under a watermark."""
    return (
        events.withWatermark("purchase_ts", delay)
        .groupBy(F.window("purchase_ts", "1 minute").alias("window"))
        .agg(F.size(F.collect_set("order_id")).cast("long").alias("orders"))
        .select(F.col("window.start").cast("timestamp_ntz").alias("window_start"), "orders")
    )


def ensure_table(spark: SparkSession, target: str) -> None:
    """Create the target, or fail when an existing table does not have the columns we write."""
    spark.sql(DDL.format(target=target))
    columns = tuple(spark.table(target).columns)
    if columns != COLUMNS:
        raise RuntimeError(f"{target} has columns {columns}, expected {COLUMNS}")


def upsert(batch: DataFrame, batch_id: int, target: str) -> None:
    """MERGE by window. A count only ever rises: a replayed batch, or a rerun after a reset
    checkpoint that has seen fewer orders, cannot lower what an earlier run wrote."""
    # The batch frame carries the stateful aggregation and is re-run by every action on it. Each
    # run would add to the progress counters (dropped rows, state rows) and repeat the state
    # update; persisted, it runs once.
    batch.persist()
    try:
        if batch.isEmpty():
            return
        view = f"opm_batch_{batch_id}"
        batch.createOrReplaceTempView(view)
        batch.sparkSession.sql(
            f"""
            merge into {target} t using {view} s on t.window_start = s.window_start
            when matched and s.orders > t.orders
                then update set t.orders = s.orders, t._updated_at = current_timestamp()
            when not matched
                then insert (window_start, orders, _updated_at)
                values (s.window_start, s.orders, current_timestamp())
            """
        )
    finally:
        batch.unpersist()


def describe(progress: dict[str, Any]) -> str:
    """One log line for a progress dict (`query.recentProgress`): where the watermark is, how many
    windows are in state, how many rows it dropped."""
    state = (progress.get("stateOperators") or [{}])[0]
    watermark = (progress.get("eventTime") or {}).get("watermark", "none")
    return (
        f"progress batch={progress.get('batchId')} watermark={watermark} "
        f"state_rows={state.get('numRowsTotal', 0)} "
        f"dropped={state.get('numRowsDroppedByWatermark', 0)} "
        f"input_rows={progress.get('numInputRows', 0)}"
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings()
    spark = build_session(QUERY_NAME, settings)
    # The window boundaries and the casts to timestamp_ntz are meant in UTC.
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    spark.conf.set("spark.sql.shuffle.partitions", str(settings.opm_shuffle_partitions))
    spark.streams.addListener(start_metrics(settings.metrics_port))

    target = settings.opm_target
    spark.sql(f"create namespace if not exists {target.rsplit('.', 1)[0]}")
    ensure_table(spark, target)

    kafka = (
        spark.readStream.format("kafka")
        .option("kafka.bootstrap.servers", settings.kafka_bootstrap)
        .option("subscribe", settings.opm_source_topic)
        .option("startingOffsets", settings.opm_starting_offsets)
        .option("maxOffsetsPerTrigger", settings.bronze_max_offsets_per_trigger)
        # Offsets that retention deleted before we read them are lost data: fail loudly.
        .option("failOnDataLoss", "true")
        .load()
    )
    available_now = settings.opm_trigger == "available_now"
    checkpoint = settings.opm_checkpoint or f"{settings.checkpoint_root}/{QUERY_NAME}"
    writer = (
        windowed_counts(parse_orders(kafka), settings.opm_watermark)
        .writeStream.queryName(QUERY_NAME)
        .outputMode("update")
        .foreachBatch(lambda batch, batch_id: upsert(batch, batch_id, target))
        .option("checkpointLocation", checkpoint)
    )
    if available_now:
        writer = writer.trigger(availableNow=True)
    else:
        writer = writer.trigger(processingTime=f"{settings.opm_trigger_seconds} seconds")
    query = writer.start()
    query.awaitTermination()
    if available_now:
        for progress in query.recentProgress:
            print(describe(progress))
        spark.stop()


if __name__ == "__main__":
    main()
