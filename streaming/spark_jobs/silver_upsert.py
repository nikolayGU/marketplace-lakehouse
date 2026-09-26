"""`lake.bronze.cdc_events` -> `lake.silver.<table>`, one MERGE per table per micro-batch.

Runs with `Trigger.AvailableNow`: reads every bronze snapshot committed since the last run,
then exits, so Airflow can schedule it (ADR-007). Bronze is at-least-once and Spark replays a
micro-batch whose commit it did not record, so both steps are idempotent: inside a batch only
the newest event per primary key survives, and MERGE overwrites a row only with a newer one.
Deletes are soft (`_is_deleted`, ADR-009; Iceberg reserves `_deleted` for a metadata column).
Events silver cannot type go to `silver.quarantine` with a reason, once per Kafka record.
"""

import logging
import operator
import time
from functools import reduce
from pathlib import Path

from pyspark.sql import Column, DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from spark_jobs.catalog import CATALOG, build_session
from spark_jobs.contracts import TableContract, load_contracts
from spark_jobs.settings import Settings

BRONZE = f"{CATALOG}.bronze.cdc_events"
SILVER = f"{CATALOG}.silver"
QUARANTINE = f"{SILVER}.quarantine"
QUERY_NAME = "silver_upsert"
OPS = ("c", "u", "d", "r")
METADATA = [("_is_deleted", "boolean"), ("_last_lsn", "bigint"), ("_updated_at", "timestamp")]

# Physical layout (ADR-010). An order changes status several times after it is inserted, so its
# MERGE writes position deletes instead of rewriting whole files; the other tables rarely change
# a row twice and stay copy-on-write.
MERGE_ON_READ = {
    "write.merge.mode": "merge-on-read",
    "write.update.mode": "merge-on-read",
    "write.delete.mode": "merge-on-read",
    # Already Spark's default, but the Iceberg docs list `partition`, so it is spelled out.
    "write.delete.granularity": "file",
}
PARTITIONS: dict[str, tuple[str, ...]] = {"orders": ("months(order_purchase_timestamp)",)}
PROPERTIES: dict[str, dict[str, str]] = {"orders": MERGE_ON_READ}

# Bronze columns an image keeps: ordering needs some, quarantine needs the rest.
BRONZE_KEPT = (
    "topic",
    "kafka_partition",
    "kafka_offset",
    "key",
    "op",
    "lsn",
    "ts_ms",
    "raw",
    "ingest_ts",
    "source_table",
)
QUARANTINE_DDL = f"""
create table if not exists {QUARANTINE} (
    topic string,
    kafka_partition int,
    kafka_offset bigint,
    source_table string,
    reason string,
    op string,
    key string,
    lsn bigint,
    payload string,
    ingest_ts timestamp,
    quarantined_at timestamp,
    batch_id bigint
)
using iceberg
tblproperties ('format-version' = '2')
"""

log = logging.getLogger(QUERY_NAME)


def row_images(events: DataFrame, contract: TableContract) -> DataFrame:
    """One row per bronze event: the typed silver columns, what ordering and quarantine need,
    and `_reason`, null when the event can become a silver row. A delete carries its row in
    `before`, everything else in `after`."""
    payload = F.when(F.col("op") == "d", F.col("before")).otherwise(F.col("after"))
    parsed = events.select(
        F.from_json(payload, contract.wire_schema).alias("_p"),
        # The same payload with every value as text: present here but null once typed means the
        # value did not fit its column.
        F.from_json(payload, "map<string,string>").alias("_fields"),
        payload.alias("_payload"),
        *BRONZE_KEPT,
    )
    images = parsed.select(
        *contract.typed("_p"),
        (F.col("op") == "d").alias("_is_deleted"),
        F.col("lsn").alias("_last_lsn"),
        "_fields",
        "_payload",
        *BRONZE_KEPT,
    )
    return images.withColumn("_reason", reason(contract))


def reason(contract: TableContract) -> Column:
    """Why an event cannot become a silver row, or null. The first match wins. A delete is
    checked only for its key: MERGE flags the row and never writes its other values, so a bad
    value in `before` must not keep a deleted row alive in silver."""
    key_missing = reduce(operator.or_, [F.col(k).isNull() for k in contract.primary_key])
    mismatch = reduce(
        operator.or_,
        [F.col("_fields")[c.name].isNotNull() & F.col(c.name).isNull() for c in contract.columns],
    )
    required_missing = reduce(
        operator.or_, [F.col(c.name).isNull() for c in contract.columns if not c.nullable]
    )
    return (
        F.when(F.col("op").isNull(), "unparsed_envelope")
        .when(~F.col("op").isin(*OPS), "unknown_op")
        .when(key_missing, "null_key")
        .when((F.col("op") != "d") & mismatch, "type_mismatch")
        .when((F.col("op") != "d") & required_missing, "null_required")
    )


def unknown_fields(images: DataFrame, contract: TableContract) -> list[str]:
    """Payload fields the contract does not declare: the source gained a column (W2-T07)."""
    known = [c.name for c in contract.columns]
    keys = images.select(F.explode(F.map_keys("_fields")).alias("field"))
    return sorted(r["field"] for r in keys.where(~F.col("field").isin(*known)).distinct().collect())


def latest_per_key(images: DataFrame, contract: TableContract) -> DataFrame:
    """One row per primary key, the newest event.

    Newest is the highest LSN. An incremental snapshot read has no LSN (ADR-019) and loses to
    any streamed change of the same key; between two reads the later Debezium time wins. The
    Kafka offset only breaks ties between exact duplicates, which Debezium re-sends after a
    restart.
    """
    newest_first = Window.partitionBy(*contract.primary_key).orderBy(
        F.col("_last_lsn").desc_nulls_last(),
        F.col("ts_ms").desc_nulls_last(),
        F.col("kafka_offset").desc(),
    )
    return (
        images.withColumn("_rank", F.row_number().over(newest_first))
        .where("_rank = 1")
        .select(*[c.name for c in contract.columns], "_is_deleted", "_last_lsn")
        .withColumn("_updated_at", F.current_timestamp())
    )


def merge_sql(target: str, source_view: str, contract: TableContract) -> str:
    """A target row with a null `_last_lsn` came from an incremental snapshot read, which any
    later event replaces. An equal LSN is a replay and changes nothing. A delete only flags the
    row, so it keeps the last values silver saw."""
    on = " and ".join(f"t.{k} = s.{k}" for k in contract.primary_key)
    newer = "(t._last_lsn is null or s._last_lsn > t._last_lsn)"
    return f"""
merge into {target} t
using {source_view} s
on {on}
when matched and s._is_deleted and {newer} then update set
    t._is_deleted = true, t._last_lsn = s._last_lsn, t._updated_at = s._updated_at
when matched and {newer} then update set *
when not matched then insert *
"""


def partition_fields(spark: SparkSession, table: str) -> set[str]:
    """Partition transforms as DESCRIBE prints them, e.g. `months(order_purchase_timestamp)`."""
    rows = spark.sql(f"describe table {table}").collect()
    return {r["data_type"] for r in rows if r["col_name"].startswith("Part ")}


def converge_layout(
    spark: SparkSession, table: str, partitions: tuple[str, ...], properties: dict[str, str]
) -> None:
    """Bring an existing table to its layout. Metadata only: files already written keep their
    old spec and write mode until compaction rewrites them."""
    current = {r["key"]: r["value"] for r in spark.sql(f"show tblproperties {table}").collect()}
    missing = {k: v for k, v in properties.items() if current.get(k) != v}
    if missing:
        pairs = ", ".join(f"'{k}' = '{v}'" for k, v in sorted(missing.items()))
        spark.sql(f"alter table {table} set tblproperties ({pairs})")
        log.info("%s: set %s", table, pairs)
    fields = partition_fields(spark, table)
    for transform in partitions:
        if transform not in fields:
            spark.sql(f"alter table {table} add partition field {transform}")
            log.info("%s: partitioned by %s from now on", table, transform)


def ensure_table(spark: SparkSession, contract: TableContract) -> None:
    """Create the silver table, or fail with the fix if it no longer matches its contract, then
    converge its layout. Schema evolution is deliberate: contract first, then ALTER TABLE
    (contracts/README.md). Layout is physical and converges on its own."""
    table = f"{SILVER}.{contract.table}"
    partitions = PARTITIONS.get(contract.table, ())
    properties = PROPERTIES.get(contract.table, {})
    metadata_ddl = ", ".join(f"{name} {kind}" for name, kind in METADATA)
    partitioned = f" partitioned by ({', '.join(partitions)})" if partitions else ""
    pairs = ", ".join(f"'{k}' = '{v}'" for k, v in {"format-version": "2", **properties}.items())
    spark.sql(
        f"create table if not exists {table} ({contract.column_ddl}, {metadata_ddl}) "
        f"using iceberg{partitioned} tblproperties ({pairs})"
    )
    expected = {(c.name, c.silver_type) for c in contract.columns} | set(METADATA)
    actual = {(f.name, f.dataType.simpleString()) for f in spark.table(table).schema.fields}
    if actual != expected:
        raise RuntimeError(
            f"{table} does not match contracts/silver/{contract.table}.json: "
            f"missing {sorted(expected - actual)}, unexpected {sorted(actual - expected)}. "
            "Align the contract and the table (ALTER TABLE ... ADD COLUMN) first."
        )
    converge_layout(spark, table, partitions, properties)


def quarantine_rows(events: DataFrame, why: Column, payload: Column, batch_id: int) -> DataFrame:
    return events.select(
        "topic",
        "kafka_partition",
        "kafka_offset",
        "source_table",
        why.alias("reason"),
        "op",
        "key",
        "lsn",
        F.coalesce(payload, F.col("raw")).alias("payload"),
        "ingest_ts",
        F.current_timestamp().alias("quarantined_at"),
        F.lit(batch_id).cast("bigint").alias("batch_id"),
    )


def quarantine(rows: DataFrame) -> None:
    """Keyed by Kafka coordinates, so a replayed batch finds its events already there."""
    view = "silver_upsert_quarantine"
    rows.dropDuplicates(["topic", "kafka_partition", "kafka_offset"]).createOrReplaceTempView(view)
    rows.sparkSession.sql(
        f"merge into {QUARANTINE} q using {view} s "
        "on q.topic = s.topic and q.kafka_partition = s.kafka_partition "
        "and q.kafka_offset = s.kafka_offset "
        "when not matched then insert *"
    )


def merge_table(events: DataFrame, count: int, batch_id: int, contract: TableContract) -> None:
    images = row_images(events, contract).persist()
    try:
        rejected = images.where(F.col("_reason").isNotNull())
        why = {r["_reason"]: r["count"] for r in rejected.groupBy("_reason").count().collect()}
        if why:
            quarantine(quarantine_rows(rejected, F.col("_reason"), F.col("_payload"), batch_id))
            log.warning("batch %s: %s events quarantined: %s", batch_id, contract.table, why)
        extra = unknown_fields(images, contract)
        if extra:
            log.warning(
                "batch %s: %s payloads carry fields contracts/silver/%s.json does not declare: %s",
                batch_id,
                contract.table,
                contract.table,
                extra,
            )
        view = f"silver_upsert_{contract.table}"
        valid = images.where(F.col("_reason").isNull())
        latest_per_key(valid, contract).createOrReplaceTempView(view)
        started = time.monotonic()
        events.sparkSession.sql(merge_sql(f"{SILVER}.{contract.table}", view, contract))
        log.info(
            "batch %s: %s events merged into %s.%s in %.1f s",
            batch_id,
            count,
            SILVER,
            contract.table,
            time.monotonic() - started,
        )
    finally:
        images.unpersist()


def merge_batch(batch: DataFrame, batch_id: int, contracts: dict[str, TableContract]) -> None:
    # The batch is read once per table; without persist each read goes back to MinIO.
    batch.persist()
    try:
        counts = batch.groupBy("source_table").count().collect()
        for table, count in sorted((r["source_table"], r["count"]) for r in counts):
            events = batch.where(F.col("source_table") == table)
            contract = contracts.get(table)
            if contract is None:
                payload = F.coalesce(F.col("after"), F.col("before"))
                quarantine(quarantine_rows(events, F.lit("no_contract"), payload, batch_id))
                log.warning(
                    "batch %s: %s %s events quarantined, no contract", batch_id, count, table
                )
                continue
            merge_table(events, count, batch_id, contract)
    finally:
        batch.unpersist()


def run(
    spark: SparkSession,
    contracts: dict[str, TableContract],
    checkpoint: str,
    max_rows_per_batch: int,
) -> None:
    """Process everything bronze has committed since the checkpoint, then return."""
    spark.sql(f"create namespace if not exists {SILVER}")
    spark.sql(QUARANTINE_DDL)
    for contract in contracts.values():
        ensure_table(spark, contract)

    bronze = (
        spark.readStream.format("iceberg")
        .option("streaming-max-rows-per-micro-batch", max_rows_per_batch)
        .load(BRONZE)
    )
    query = (
        bronze.writeStream.queryName(QUERY_NAME)
        .foreachBatch(lambda batch, batch_id: merge_batch(batch, batch_id, contracts))
        .trigger(availableNow=True)
        .option("checkpointLocation", checkpoint)
        .start()
    )
    query.awaitTermination()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings()
    contracts = load_contracts(Path(settings.contracts_dir))
    spark = build_session(QUERY_NAME, settings)
    spark.conf.set("spark.sql.shuffle.partitions", str(settings.silver_shuffle_partitions))
    run(
        spark,
        contracts,
        f"{settings.checkpoint_root}/{QUERY_NAME}",
        settings.silver_max_rows_per_batch,
    )
    spark.stop()


if __name__ == "__main__":
    main()
