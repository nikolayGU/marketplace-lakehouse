"""`lake.bronze.cdc_events` -> `lake.silver.<table>`, one MERGE per table per micro-batch.

Runs with `Trigger.AvailableNow`: reads every bronze snapshot committed since the last run,
then exits, so Airflow can schedule it (ADR-007). Bronze is at-least-once and Spark replays a
micro-batch whose commit it did not record, so both steps are idempotent: inside a batch only
the newest event per primary key survives, and MERGE overwrites a row only with a newer one.
Deletes are soft (`_is_deleted`, ADR-009; Iceberg reserves `_deleted` for a metadata column).
"""

import logging
from functools import reduce
from pathlib import Path

from pyspark.sql import Column, DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from spark_jobs.catalog import CATALOG, build_session
from spark_jobs.contracts import TableContract, load_contracts
from spark_jobs.settings import Settings

BRONZE = f"{CATALOG}.bronze.cdc_events"
SILVER = f"{CATALOG}.silver"
QUERY_NAME = "silver_upsert"
OPS = ("c", "u", "d", "r")
METADATA = [("_is_deleted", "boolean"), ("_last_lsn", "bigint"), ("_updated_at", "timestamp")]

log = logging.getLogger(QUERY_NAME)


def row_images(events: DataFrame, contract: TableContract) -> DataFrame:
    """Typed silver columns plus what ordering needs, one row per bronze event. A delete carries
    its row in `before`, everything else in `after`."""
    payload = F.when(F.col("op") == "d", F.col("before")).otherwise(F.col("after"))
    return events.select(
        F.from_json(payload, contract.wire_schema).alias("_p"), "op", "lsn", "ts_ms", "kafka_offset"
    ).select(
        *contract.typed("_p"),
        "op",
        (F.col("op") == "d").alias("_is_deleted"),
        F.col("lsn").alias("_last_lsn"),
        "ts_ms",
        "kafka_offset",
    )


def valid(contract: TableContract) -> Column:
    """Known op, the whole primary key, and for anything but a delete every column the source
    declares NOT NULL. A missing, unparseable or wrongly typed field comes out of the parse as
    null, so this is where it is caught. A delete only needs the key: with REPLICA IDENTITY
    DEFAULT its `before` would hold nothing else (ADR-018)."""
    key = [F.col(k).isNotNull() for k in contract.primary_key]
    required = [F.col(c.name).isNotNull() for c in contract.columns if not c.nullable]
    return (
        F.col("op").isin(*OPS)
        & reduce(Column.__and__, key)
        & ((F.col("op") == "d") | reduce(Column.__and__, required))
    )


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


def ensure_table(spark: SparkSession, contract: TableContract) -> None:
    """Create the silver table, or fail with the fix if it no longer matches its contract.
    Schema evolution is deliberate: contract first, then ALTER TABLE (contracts/README.md)."""
    table = f"{SILVER}.{contract.table}"
    metadata_ddl = ", ".join(f"{name} {kind}" for name, kind in METADATA)
    spark.sql(
        f"create table if not exists {table} ({contract.column_ddl}, {metadata_ddl}) "
        "using iceberg tblproperties ('format-version' = '2')"
    )
    expected = {(c.name, c.silver_type) for c in contract.columns} | set(METADATA)
    actual = {(f.name, f.dataType.simpleString()) for f in spark.table(table).schema.fields}
    if actual != expected:
        raise RuntimeError(
            f"{table} does not match contracts/silver/{contract.table}.json: "
            f"missing {sorted(expected - actual)}, unexpected {sorted(actual - expected)}. "
            "Align the contract and the table (ALTER TABLE ... ADD COLUMN) first."
        )


def merge_batch(batch: DataFrame, batch_id: int, contracts: dict[str, TableContract]) -> None:
    # The batch is read once per table; without persist each read goes back to MinIO.
    spark = batch.sparkSession
    batch.persist()
    try:
        counts = batch.groupBy("source_table").count().collect()
        for table, events in sorted((r["source_table"], r["count"]) for r in counts):
            contract = contracts.get(table)
            if contract is None:
                log.warning("batch %s: %s %s events skipped, no contract", batch_id, events, table)
                continue
            images = row_images(batch.where(F.col("source_table") == table), contract)
            images.persist()
            rejected = images.where(~valid(contract)).count()
            if rejected:
                log.warning("batch %s: %s invalid %s events skipped", batch_id, rejected, table)
            view = f"silver_upsert_{table}"
            latest_per_key(images.where(valid(contract)), contract).createOrReplaceTempView(view)
            spark.sql(merge_sql(f"{SILVER}.{table}", view, contract))
            images.unpersist()
            log.info("batch %s: %s events merged into %s.%s", batch_id, events, SILVER, table)
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
