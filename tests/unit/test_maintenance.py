"""The maintenance job (W5-T05a): the rules run on the host without a JVM, the procedures against
a local Hadoop catalog in the image (`make test-spark`)."""

import json
import os
import shutil
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from glob import glob
from pathlib import Path
from typing import Any

import pytest
from pyspark.sql import SparkSession
from spark_jobs import maintenance
from spark_jobs.maintenance import (
    PolicyError,
    before_today_filter,
    check_expire,
    check_orphans,
    check_rewrite_data,
    error_line,
    execute,
    expire_sql,
    main,
    older_than_literal,
    orphan_location,
    orphans_sql,
    parse_args,
    parse_table,
    procedure_table,
    result_line,
    rewrite_data_sql,
    rewrite_position_deletes_sql,
    run_tables,
    table_location,
)

REPO = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 23, 3, 30, 15, 123456, tzinfo=timezone.utc)  # noqa: UP017

HAS_JAVA = shutil.which("java") is not None
SPARK_JARS = f"{os.environ.get('SPARK_HOME', '/opt/spark')}/jars"
HAS_ICEBERG = bool(glob(f"{SPARK_JARS}/iceberg-spark-runtime-*"))
needs_iceberg = pytest.mark.skipif(
    not (HAS_JAVA and HAS_ICEBERG), reason="needs the Iceberg runtime jar: run `make test-spark`"
)


# Table names.


@pytest.mark.parametrize(
    ("raw", "table"),
    [
        ("silver.sellers", "lake.silver.sellers"),
        ("lake.silver.sellers", "lake.silver.sellers"),
        (" Lake.Gold.Orders_Daily ", "lake.gold.orders_daily"),
        ("bronze.cdc_events", "lake.bronze.cdc_events"),
        ("demo.orders", "lake.demo.orders"),
    ],
)
def test_table_names_are_qualified_with_the_catalog(raw: str, table: str) -> None:
    assert parse_table(raw) == table
    assert procedure_table(table) == table.removeprefix("lake.")


@pytest.mark.parametrize(
    "raw",
    [
        "sellers",  # no namespace
        "silver.sellers; drop table x",
        "silver.sellers'",
        "silver.sell ers",
        "lake.silver.sellers.extra",
        "other.sellers",  # not a layer of ours
        "silver.",
        "",
    ],
)
def test_odd_table_names_are_refused(raw: str) -> None:
    with pytest.raises(PolicyError):
        parse_table(raw)


# Rules in code, not only in the DAG.


@pytest.mark.parametrize("raw", ["lake.bronze.cdc_events", "bronze.cdc_events"])
@pytest.mark.parametrize("days", [0, 7, 365])
def test_expire_snapshots_of_bronze_is_refused_for_any_age(raw: str, days: int) -> None:
    with pytest.raises(PolicyError, match="ADR-021"):
        check_expire(parse_table(raw), days)


@pytest.mark.parametrize("raw", ["silver.orders", "gold.orders_daily"])
@pytest.mark.parametrize("days", [0, 1, 6])
def test_expire_snapshots_younger_than_a_week_is_refused_for_silver_and_gold(
    raw: str, days: int
) -> None:
    with pytest.raises(PolicyError, match="7 days"):
        check_expire(parse_table(raw), days)


@pytest.mark.parametrize("raw", ["silver.orders", "gold.orders_daily"])
def test_expire_snapshots_of_a_week_or_more_is_allowed(raw: str) -> None:
    check_expire(parse_table(raw), 7)
    check_expire(parse_table(raw), 30)


@pytest.mark.parametrize("days", [0, 1, 7])
def test_the_demo_sandbox_takes_any_age(days: int) -> None:
    check_expire(parse_table("lake.demo.orders"), days)
    check_orphans(parse_table("lake.demo.orders"), days, None)


def test_orphans_of_bronze_data_is_refused_without_the_metadata_location() -> None:
    bronze = parse_table("lake.bronze.cdc_events")

    for suffix in (None, "", "data", "metadata/../data", "meta"):
        with pytest.raises(PolicyError, match="ADR-021"):
            check_orphans(bronze, 7, suffix)
    check_orphans(bronze, 7, "metadata")


@pytest.mark.parametrize("raw", ["silver.orders", "gold.x", "demo.x"])
@pytest.mark.parametrize("suffix", ["..", "../bronze", "metadata/../..", "/wh", "data/x", ""])
def test_orphans_stay_inside_their_table_in_every_layer(raw: str, suffix: str) -> None:
    # A location outside the table lists files of other tables (bronze among them) as orphans.
    with pytest.raises(PolicyError, match="inside the table"):
        check_orphans(parse_table(raw), 30, suffix)


@pytest.mark.parametrize("suffix", [None, "metadata", "data"])
def test_orphans_take_the_table_or_one_of_its_directories(suffix: str | None) -> None:
    check_orphans(parse_table("silver.orders"), 7, suffix)


def test_retain_last_is_at_least_one() -> None:
    with pytest.raises(SystemExit):
        parse_args(["expire", "--retain-last", "0", "silver.orders"])


@pytest.mark.parametrize("raw", ["lake.bronze.cdc_events", "lake.silver.orders", "gold.x"])
def test_orphans_younger_than_a_week_is_refused_outside_the_sandbox(raw: str) -> None:
    # A stream writes its files before it commits: a younger file may be a commit in flight.
    with pytest.raises(PolicyError, match="7 days"):
        check_orphans(parse_table(raw), 3, "metadata")


def test_rewriting_bronze_needs_the_before_today_limit() -> None:
    bronze = parse_table("lake.bronze.cdc_events")

    with pytest.raises(PolicyError, match="--before-today"):
        check_rewrite_data(bronze, before_today=False)
    check_rewrite_data(bronze, before_today=True)
    check_rewrite_data(parse_table("lake.demo.orders"), before_today=False)


# SQL.


def test_older_than_is_a_timestamp_literal_in_utc() -> None:
    assert older_than_literal(NOW, 7) == "TIMESTAMP '2026-10-16 03:30:15.123456'"
    assert older_than_literal(NOW, 0) == "TIMESTAMP '2026-10-23 03:30:15.123456'"


def test_older_than_converts_another_zone_to_utc() -> None:
    moscow = datetime(2026, 10, 23, 6, 30, 15, 123456, tzinfo=timezone(timedelta(hours=3)))

    assert older_than_literal(moscow, 7) == "TIMESTAMP '2026-10-16 03:30:15.123456'"


def test_older_than_refuses_a_time_without_a_zone() -> None:
    with pytest.raises(ValueError, match="zone"):
        older_than_literal(datetime(2026, 10, 23, 3, 30), 7)


def test_expire_snapshots_sql_keeps_the_latest_snapshot() -> None:
    assert expire_sql("lake.silver.sellers", older_than_literal(NOW, 7), 1) == (
        "call lake.system.expire_snapshots(table => 'silver.sellers', "
        "older_than => TIMESTAMP '2026-10-16 03:30:15.123456', retain_last => 1)"
    )


def test_orphans_sql_names_the_location_only_when_given() -> None:
    older = older_than_literal(NOW, 7)

    assert orphans_sql("lake.silver.sellers", older, True, None) == (
        "call lake.system.remove_orphan_files(table => 'silver.sellers', "
        "older_than => TIMESTAMP '2026-10-16 03:30:15.123456', dry_run => true)"
    )
    assert orphans_sql("lake.bronze.cdc_events", older, False, "s3://b/t/metadata") == (
        "call lake.system.remove_orphan_files(table => 'bronze.cdc_events', "
        "older_than => TIMESTAMP '2026-10-16 03:30:15.123456', dry_run => false, "
        "location => 's3://b/t/metadata')"
    )


def test_a_quote_in_a_location_cannot_leave_its_string() -> None:
    sql = orphans_sql("lake.demo.orders", older_than_literal(NOW, 0), True, "s3://b/it's")

    assert "location => 's3://b/it\\'s'" in sql


def test_orphan_location_appends_the_suffix_to_the_table_location() -> None:
    assert orphan_location("s3://lakehouse/wh/bronze/cdc_events-1/", "metadata") == (
        "s3://lakehouse/wh/bronze/cdc_events-1/metadata"
    )
    assert orphan_location("s3://lakehouse/wh/t", None) is None


def test_position_deletes_sql() -> None:
    assert rewrite_position_deletes_sql("lake.silver.orders") == (
        "call lake.system.rewrite_position_delete_files(table => 'silver.orders')"
    )


def test_before_today_stops_at_midnight_utc() -> None:
    assert before_today_filter(NOW) == "ingest_ts < TIMESTAMP '2026-10-23 00:00:00'"


def test_rewrite_data_sql_limits_partitions_and_passes_options() -> None:
    sql = rewrite_data_sql(
        "lake.bronze.cdc_events", before_today_filter(NOW), {"min-input-files": "2"}
    )

    assert sql == (
        "call lake.system.rewrite_data_files(table => 'bronze.cdc_events', "
        "where => \"ingest_ts < TIMESTAMP '2026-10-23 00:00:00'\", "
        "options => map('min-input-files', '2'))"
    )
    assert "where" not in rewrite_data_sql("lake.demo.orders", None, {})


# Output.


def test_a_result_is_one_json_line() -> None:
    line = result_line(
        "expire",
        "lake.silver.sellers",
        [{"deleted_data_files_count": 3, "deleted_manifest_files_count": 5}],
    )

    assert "\n" not in line
    assert json.loads(line) == {
        "op": "expire",
        "table": "lake.silver.sellers",
        "deleted_data_files_count": 3,
        "deleted_manifest_files_count": 5,
    }


def test_a_dry_run_reports_candidates_and_says_it_deleted_nothing() -> None:
    rows = [{"orphan_file_location": f"s3://b/t/data/f{i}.parquet"} for i in range(3)]

    result = json.loads(result_line("orphans", "lake.silver.sellers", rows, dry_run=True))

    assert result["dry_run"] is True
    assert result["candidates"] == 3
    assert result["files"] == [r["orphan_file_location"] for r in rows]
    assert "removed" not in result


def test_a_real_run_reports_removed_files() -> None:
    rows = [{"orphan_file_location": "s3://b/t/metadata/old.json"}]

    result = json.loads(result_line("orphans", "lake.bronze.cdc_events", rows, dry_run=False))

    assert (result["dry_run"], result["removed"]) == (False, 1)
    assert "candidates" not in result


def test_a_long_file_list_is_cut_but_counted() -> None:
    rows = [{"orphan_file_location": f"f{i}"} for i in range(maintenance.MAX_LISTED_FILES + 50)]

    result = json.loads(result_line("orphans", "lake.silver.sellers", rows, dry_run=True))

    assert result["candidates"] == maintenance.MAX_LISTED_FILES + 50
    assert len(result["files"]) == maintenance.MAX_LISTED_FILES
    assert result["files_truncated"] is True


def test_an_error_is_one_json_line_too() -> None:
    line = error_line("expire", "lake.silver.sellers", RuntimeError("boom\nsecond line"))

    assert "\n" not in line
    assert json.loads(line) == {
        "op": "expire",
        "table": "lake.silver.sellers",
        "error": "RuntimeError: boom second line",
    }


def test_one_failing_table_does_not_stop_the_others_and_the_code_is_1() -> None:
    printed: list[str] = []
    seen: list[str] = []

    def action(table: str) -> list[dict[str, Any]]:
        seen.append(table)
        if table == "lake.silver.b":
            raise RuntimeError("commit failed")
        return [{"deleted_data_files_count": 1}]

    code = run_tables(
        "expire", ["lake.silver.a", "lake.silver.b", "lake.silver.c"], action, printed.append
    )

    assert code == 1
    assert seen == ["lake.silver.a", "lake.silver.b", "lake.silver.c"]
    assert [json.loads(line).get("error") is not None for line in printed] == [False, True, False]


def test_all_tables_succeeding_gives_code_0() -> None:
    printed: list[str] = []

    code = run_tables("expire", ["lake.silver.a"], lambda t: [{"x": 1}], printed.append)

    assert code == 0
    assert len(printed) == 1


# The command line.


def test_orphans_default_to_a_dry_run() -> None:
    args = parse_args(["orphans", "silver.sellers"])

    assert args.dry_run is True
    assert args.days == 7


def test_a_real_orphans_run_needs_its_own_flag() -> None:
    assert parse_args(["orphans", "--no-dry-run", "silver.sellers"]).dry_run is False
    assert parse_args(["orphans", "--dry-run", "silver.sellers"]).dry_run is True


def test_expire_defaults_to_a_week() -> None:
    args = parse_args(["expire", "silver.sellers", "silver.orders"])

    assert (args.days, args.retain_last, args.tables) == (
        7,
        1,
        ["silver.sellers", "silver.orders"],
    )


def test_a_refused_command_exits_1_before_a_spark_session(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def no_session() -> None:
        raise AssertionError("a Spark session was started")

    monkeypatch.setattr(maintenance, "open_session", no_session)

    code = main(["expire", "lake.bronze.cdc_events"])

    assert code == 1
    assert "ADR-021" in capsys.readouterr().err


def test_one_forbidden_table_refuses_the_whole_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(maintenance, "open_session", lambda: pytest.fail("session started"))

    code = main(["expire", "silver.orders", "lake.bronze.cdc_events"])

    captured = capsys.readouterr()
    assert code == 1
    assert "ADR-021" in captured.err
    assert captured.out == ""


def test_bronze_orphans_in_data_are_refused_before_a_spark_session(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(maintenance, "open_session", lambda: pytest.fail("session started"))

    code = main(["orphans", "--no-dry-run", "lake.bronze.cdc_events"])

    assert code == 1
    assert "ADR-021" in capsys.readouterr().err


def test_run_job_forwards_the_arguments_after_the_job_name() -> None:
    script = (REPO / "streaming" / "run-job.sh").read_text()

    assert '"${@:2}"' in script
    assert script.index('"/opt/app/spark_jobs/${job}.py"') < script.index('"${@:2}"')


# The procedures, against a local catalog.


@pytest.fixture(scope="module")
def spark(tmp_path_factory: pytest.TempPathFactory) -> Iterator[SparkSession]:
    warehouse = tmp_path_factory.mktemp("warehouse")
    session = (
        SparkSession.builder.master("local[2]")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.sql.session.timeZone", "UTC")
        .config(
            "spark.sql.extensions",
            "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        )
        .config("spark.sql.catalog.lake", "org.apache.iceberg.spark.SparkCatalog")
        .config("spark.sql.catalog.lake.type", "hadoop")
        .config("spark.sql.catalog.lake.warehouse", f"file://{warehouse}")
        .config("spark.sql.catalog.lake.cache-enabled", "false")
        .getOrCreate()
    )
    yield session
    session.stop()


@pytest.fixture
def sandbox(spark: SparkSession) -> str:
    """lake.demo.events: day-partitioned, one small file per insert, six snapshots."""
    table = "lake.demo.events"
    spark.sql("create namespace if not exists lake.demo")
    spark.sql(f"drop table if exists {table}")
    spark.sql(
        f"create table {table} (id bigint, ingest_ts timestamp) using iceberg "
        "partitioned by (days(ingest_ts)) tblproperties ('format-version' = '2')"
    )
    for i in range(5):
        spark.sql(f"insert into {table} values ({i}, timestamp '2026-10-22 10:00:00')")
    spark.sql(f"insert into {table} values (99, timestamp '2026-10-23 10:00:00')")
    return table


def snapshots(spark: SparkSession, table: str) -> int:
    return spark.table(f"{table}.snapshots").count()


@needs_iceberg
def test_expire_leaves_one_snapshot_and_reports_deleted_files(
    spark: SparkSession, sandbox: str
) -> None:
    args = parse_args(["expire", "--days", "0", sandbox])
    rows_before = spark.table(sandbox).count()
    snapshots_before = snapshots(spark, sandbox)

    # The sandbox snapshots are written now: a fixed NOW stops covering them a day after it.
    later = datetime.now(timezone.utc) + timedelta(days=1)  # noqa: UP017
    [result] = execute(spark, args, sandbox, later)

    assert snapshots(spark, sandbox) == 1
    assert spark.table(sandbox).count() == rows_before
    # Every expired snapshot owns one manifest list and expire deletes it; the data files stay,
    # the surviving snapshot still reads them (QA-06: the key alone was also there for a no-op).
    assert snapshots_before > 1
    assert result["deleted_manifest_lists_count"] == snapshots_before - 1
    assert result["deleted_data_files_count"] == 0


@needs_iceberg
def test_orphans_dry_run_deletes_nothing_and_lists_candidates(
    spark: SparkSession, sandbox: str
) -> None:
    args = parse_args(["orphans", "--days", "2", sandbox])
    files_before = spark.table(f"{sandbox}.files").count()

    rows = execute(spark, args, sandbox, datetime.now(timezone.utc))  # noqa: UP017
    line = json.loads(result_line("orphans", sandbox, rows, dry_run=args.dry_run))

    assert line["dry_run"] is True
    assert line["candidates"] == len(rows)
    assert spark.table(f"{sandbox}.files").count() == files_before
    assert spark.table(sandbox).count() == 6


@needs_iceberg
def test_orphans_in_the_metadata_location_takes_the_table_location_from_the_catalog(
    spark: SparkSession, sandbox: str
) -> None:
    args = parse_args(["orphans", "--days", "2", "--location-suffix", "metadata", sandbox])

    rows = execute(spark, args, sandbox, datetime.now(timezone.utc))  # noqa: UP017

    assert table_location(spark, sandbox).endswith("/demo/events")
    # Only metadata is looked at: no candidate sits in data/.
    assert all("/data/" not in r["orphan_file_location"] for r in rows)
    assert spark.table(sandbox).count() == 6


@needs_iceberg
def test_rewrite_data_before_today_leaves_todays_partition_alone(
    spark: SparkSession, sandbox: str
) -> None:
    args = parse_args(["rewrite-data", "--before-today", "--option", "min-input-files=2", sandbox])
    today = "partition.ingest_ts_day >= date '2026-10-23'"
    today_files = {r.file_path for r in spark.table(f"{sandbox}.files").where(today).collect()}
    old_before = spark.table(f"{sandbox}.files").where("not (" + today + ")").count()

    [result] = execute(spark, args, sandbox, NOW)

    files = spark.table(f"{sandbox}.files").collect()
    assert old_before == 5
    assert result["rewritten_data_files_count"] == 5
    assert today_files <= {r.file_path for r in files}
    assert len(files) == 2
    assert spark.table(sandbox).count() == 6


@needs_iceberg
def test_rewrite_position_deletes_runs_on_a_merge_on_read_table(
    spark: SparkSession, sandbox: str
) -> None:
    spark.sql(f"alter table {sandbox} set tblproperties ('write.delete.mode' = 'merge-on-read')")
    spark.sql(f"delete from {sandbox} where id = 1")
    args = parse_args(["rewrite-position-deletes", sandbox])

    rows = execute(spark, args, sandbox, NOW)

    assert len(rows) == 1
    assert spark.table(sandbox).count() == 5


@needs_iceberg
def test_an_old_stray_file_is_listed_by_a_dry_run_and_removed_only_by_the_real_run(
    spark: SparkSession, sandbox: str
) -> None:
    stray = Path(table_location(spark, sandbox).removeprefix("file:")) / "data" / "stray.parquet"
    stray.write_bytes(b"not referenced by any snapshot")
    three_days_ago = (datetime.now(timezone.utc) - timedelta(days=3)).timestamp()  # noqa: UP017
    os.utime(stray, (three_days_ago, three_days_ago))
    now = datetime.now(timezone.utc)  # noqa: UP017

    dry = execute(spark, parse_args(["orphans", "--days", "2", sandbox]), sandbox, now)
    assert [r["orphan_file_location"].endswith("stray.parquet") for r in dry] == [True]
    assert stray.exists()

    real = execute(
        spark, parse_args(["orphans", "--days", "2", "--no-dry-run", sandbox]), sandbox, now
    )
    assert len(real) == 1
    assert not stray.exists()
    assert spark.table(sandbox).count() == 6
