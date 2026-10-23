import socket
from decimal import Decimal

import pytest
from lakehouse import checks, metrics, sql
from lakehouse.settings import Settings


def test_gauge_line_carries_tags_in_dogstatsd_format() -> None:
    line = metrics.gauge_line(
        "lakehouse.table_freshness_seconds", 42, {"layer": "silver", "table": "orders"}
    )

    assert line == "lakehouse.table_freshness_seconds:42|g|#layer:silver,table:orders"


def test_gauge_line_without_tags_has_no_tag_section() -> None:
    assert metrics.gauge_line("lakehouse.silver_lag_seconds", 0, {}) == (
        "lakehouse.silver_lag_seconds:0|g"
    )


def test_a_negative_value_is_not_sent() -> None:
    # In StatsD "-5|g" lowers the gauge by 5; it does not set it to -5.
    assert metrics.gauge_line("lakehouse.x", -5, {}) is None


def test_a_missing_or_nonnumeric_value_is_not_sent() -> None:
    assert metrics.gauge_line("lakehouse.x", None, {}) is None
    assert metrics.gauge_line("lakehouse.x", "n/a", {}) is None
    assert metrics.gauge_line("lakehouse.x", float("nan"), {}) is None


def test_trino_numbers_are_sent_as_numbers() -> None:
    assert metrics.gauge_line("lakehouse.x", Decimal("7"), {}) == "lakehouse.x:7|g"
    assert metrics.gauge_line("lakehouse.x", "12", {}) == "lakehouse.x:12|g"


def test_tag_values_cannot_break_the_line() -> None:
    line = metrics.gauge_line("lakehouse.x", 1, {"table": "a,b|c:d"})

    assert line == "lakehouse.x:1|g|#table:a_b_c_d"


def test_send_to_an_unresolvable_host_warns_and_does_not_raise(
    capsys: pytest.CaptureFixture[str],
) -> None:
    metrics.send(["lakehouse.x:1|g"], "no-such-host.invalid", 9125)

    assert "statsd" in capsys.readouterr().out.lower()


def test_send_skips_none_and_delivers_the_rest() -> None:
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    receiver.settimeout(2)
    port = receiver.getsockname()[1]
    try:
        metrics.send([None, "lakehouse.x:1|g", None, "lakehouse.y:2|g"], "127.0.0.1", port)
        received = {receiver.recv(1024).decode(), receiver.recv(1024).decode()}
    finally:
        receiver.close()

    assert received == {"lakehouse.x:1|g", "lakehouse.y:2|g"}


def test_settings_default_to_the_statsd_exporter() -> None:
    settings = Settings()

    assert (settings.statsd_host, settings.statsd_port) == ("statsd-exporter", 9125)


def test_silver_lag_is_zero_when_silver_merged_the_latest_snapshot() -> None:
    assert checks.silver_lag_seconds(latest=7, remembered="7", oldest_unmerged_age=None) == 0


def test_silver_lag_is_the_age_of_the_oldest_unmerged_snapshot() -> None:
    assert checks.silver_lag_seconds(latest=9, remembered="7", oldest_unmerged_age=420) == 420


def test_silver_lag_is_unknown_without_the_variable() -> None:
    assert checks.silver_lag_seconds(latest=9, remembered=None, oldest_unmerged_age=420) is None


def test_silver_lag_is_unknown_when_the_remembered_snapshot_is_gone() -> None:
    # The query finds no snapshot newer than one that does not exist: not "0", not known.
    assert checks.silver_lag_seconds(latest=9, remembered="7", oldest_unmerged_age=None) is None


def test_silver_lag_is_zero_for_an_empty_bronze() -> None:
    assert checks.silver_lag_seconds(latest=None, remembered=None, oldest_unmerged_age=None) == 0


def test_unmerged_age_query_takes_only_a_numeric_snapshot_id() -> None:
    assert "snapshot_id = 123" in str(sql.oldest_unmerged_snapshot_age("123"))
    assert sql.oldest_unmerged_snapshot_age("1 or 1=1") is None


def test_bronze_freshness_is_per_source_table() -> None:
    assert "group by source_table" in sql.BRONZE_FRESHNESS
    assert "max(ingest_ts)" in sql.BRONZE_FRESHNESS
