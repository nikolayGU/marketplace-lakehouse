from types import SimpleNamespace

from spark_jobs.progress import state_totals, watermark_seconds


def test_the_initial_watermark_is_zero() -> None:
    assert watermark_seconds({"watermark": "1970-01-01T00:00:00.000Z"}) == 0


def test_a_watermark_with_and_without_fraction() -> None:
    assert watermark_seconds({"watermark": "2026-07-01T10:05:20.000Z"}) == 1782900320
    assert watermark_seconds({"watermark": "2026-07-01T10:05:20Z"}) == 1782900320
    assert watermark_seconds({"watermark": "2026-07-01T10:05:20.250Z"}) == 1782900320.25


def test_no_watermark_means_no_value() -> None:
    assert watermark_seconds({}) is None
    assert watermark_seconds(None) is None
    assert watermark_seconds({"watermark": "not a time"}) is None


def test_state_rows_add_up_over_the_operators() -> None:
    operators = [
        SimpleNamespace(numRowsTotal=3, numRowsDroppedByWatermark=1),
        SimpleNamespace(numRowsTotal=4, numRowsDroppedByWatermark=0),
    ]

    assert state_totals(operators) == (7, 1)


def test_dicts_work_like_objects() -> None:
    assert state_totals([{"numRowsTotal": 2, "numRowsDroppedByWatermark": 5}]) == (2, 5)


def test_no_operators_and_bad_values_are_zero() -> None:
    assert state_totals([]) == (0, 0)
    assert state_totals(None) == (0, 0)
    assert state_totals([{"numRowsTotal": -4, "numRowsDroppedByWatermark": "x"}]) == (0, 0)
