"""`make iceberg-demo`: snapshots, time travel, rollback, small files and expiration, shown on a
sandbox copy of silver.orders.

Bronze and silver are never touched: expiring bronze snapshots breaks silver's AvailableNow read
(ADR-021), and rolling back silver would rewind what gold was built from. The sandbox
`lake.demo.orders` is rebuilt on every run.
"""

from pyspark.errors import PySparkException
from pyspark.sql import SparkSession

from spark_jobs.catalog import CATALOG, build_session
from spark_jobs.settings import Settings

DEMO = f"{CATALOG}.demo.orders"
NAME = "demo.orders"
SOURCE = f"{CATALOG}.silver.orders"


def show(spark: SparkSession, title: str, sql: str) -> None:
    print(f"\n=== {title}\n{sql.strip()}")
    # Spark's default of 20 rows would cut the snapshot list at the default 20 appends.
    spark.sql(sql).show(n=100, truncate=False)


def run(spark: SparkSession, title: str, sql: str) -> None:
    print(f"\n=== {title}\n{sql.strip()}")
    spark.sql(sql)


def scalar(spark: SparkSession, sql: str) -> int:
    return int(spark.sql(sql).first()[0])  # type: ignore[index]


def now_literal(spark: SparkSession) -> str:
    """CALL accepts only literals, so the time is formatted, not written as a function."""
    value = spark.sql(
        "select date_format(current_timestamp(), 'yyyy-MM-dd HH:mm:ss.SSSSSS')"
    ).first()
    return f"TIMESTAMP '{value[0]}'"  # type: ignore[index]


def show_time_travel_fails(spark: SparkSession, table: str, snapshot_id: int) -> None:
    expired = f"select count(*) from {table} version as of {snapshot_id}"
    print(f"\n=== Time travel to an expired snapshot fails\n{expired}")
    try:
        spark.sql(expired).collect()
    except PySparkException as error:
        print(str(error).splitlines()[0])
    else:
        raise RuntimeError(f"snapshot {snapshot_id} of {table} is still readable after expire")


def build(spark: SparkSession, rows: int, appends: int) -> None:
    spark.sql(f"create namespace if not exists {CATALOG}.demo")
    spark.sql(f"drop table if exists {DEMO} purge")
    # Iceberg plans a multi-file table's files in no fixed order, so without `order by` every
    # slice comes from a different row order: the slices overlap and order_id repeats.
    live = f"select * from {SOURCE} where not _is_deleted order by order_id"
    spark.sql(
        f"create table {DEMO} using iceberg tblproperties ('format-version' = '2') as "
        f"{live} limit {rows}"
    )
    # One commit per insert: every one adds a snapshot and a tiny file, the small-files problem.
    for i in range(appends):
        spark.sql(f"insert into {DEMO} {live} limit 5 offset {rows + 5 * i}")


def walkthrough(spark: SparkSession, rows: int = 1000, appends: int = 20) -> dict[str, int]:
    result: dict[str, int] = {}
    build(spark, rows, appends)
    count = f"select count(*) from {DEMO}"
    result["rows"] = scalar(spark, f"select count(*) from {DEMO}") - 5 * appends

    show(
        spark,
        "Every commit is a snapshot",
        f"select committed_at, snapshot_id, operation, summary['added-records'] as added "
        f"from {DEMO}.snapshots order by committed_at",
    )
    first = scalar(spark, f"select snapshot_id from {DEMO}.snapshots order by committed_at limit 1")
    show(
        spark,
        "Time travel: the first snapshot against now",
        f"select (select count(*) from {DEMO} version as of {first}) as first_snapshot, "
        f"({count}) as now",
    )

    good = scalar(
        spark, f"select snapshot_id from {DEMO}.snapshots order by committed_at desc limit 1"
    )
    run(spark, "An accidental DELETE", f"delete from {DEMO} where order_status = 'delivered'")
    result["after_accident"] = scalar(spark, count)
    accident = scalar(
        spark, f"select snapshot_id from {DEMO}.snapshots order by committed_at desc limit 1"
    )
    show(spark, "Rows left after the DELETE", count)
    show(
        spark,
        "Rollback moves the pointer; nothing is rewritten",
        f"call {CATALOG}.system.rollback_to_snapshot(table => '{NAME}', snapshot_id => {good})",
    )
    result["after_rollback"] = scalar(spark, count)
    show(spark, "All rows are back", count)
    show(
        spark,
        "The rolled-back snapshot still exists, off the current line",
        f"select made_current_at, snapshot_id, is_current_ancestor from {DEMO}.history "
        "order by made_current_at desc limit 5",
    )
    show(
        spark,
        "...so the rollback itself can be undone",
        f"call {CATALOG}.system.set_current_snapshot(table => '{NAME}', snapshot_id => {accident})",
    )
    result["after_undo"] = scalar(spark, count)
    show(spark, "The accident is current again", count)
    show(
        spark,
        "Back to the good snapshot before compaction",
        f"call {CATALOG}.system.rollback_to_snapshot(table => '{NAME}', snapshot_id => {good})",
    )

    files = f"select count(*) as files, sum(file_size_in_bytes) as bytes from {DEMO}.files"
    result["files_before"] = scalar(spark, files)
    show(spark, "Small files in the current snapshot", files)
    show(
        spark,
        "Compaction: many small files into one",
        f"call {CATALOG}.system.rewrite_data_files(table => '{NAME}', "
        "options => map('min-input-files', '2'))",
    )
    result["files_after"] = scalar(spark, files)
    show(spark, "The current snapshot after compaction", files)
    show(
        spark,
        "Old files are still referenced by old snapshots",
        f"select count(distinct file_path) as all_data_files from {DEMO}.all_data_files",
    )

    show(
        spark,
        "Expire every snapshot but the current one",
        f"call {CATALOG}.system.expire_snapshots(table => '{NAME}', "
        f"older_than => {now_literal(spark)}, retain_last => 1)",
    )
    snapshots = f"select count(*) as snapshots from {DEMO}.snapshots"
    result["snapshots_after_expire"] = scalar(spark, snapshots)
    show(spark, "One snapshot is left", snapshots)
    show(
        spark,
        "Unreferenced files are gone",
        f"select count(distinct file_path) as all_data_files from {DEMO}.all_data_files",
    )
    show_time_travel_fails(spark, DEMO, first)

    print(
        "\nThe same in Trino (make trino):\n"
        '  select * from demo."orders$snapshots";\n'
        "  select count(*) from demo.orders for version as of <snapshot_id>;\n"
        '  select content, count(*) from demo."orders$files" group by 1;'
    )
    return result


def main() -> None:
    spark = build_session("iceberg_demo", Settings())
    # From a terminal `docker compose run` gets a TTY that merges Spark's INFO log on stderr into
    # the transcript, so the log is cut here rather than by the caller's redirect.
    spark.sparkContext.setLogLevel("WARN")
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    walkthrough(spark)
    spark.stop()


if __name__ == "__main__":
    main()
