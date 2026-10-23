from spark_jobs.offsets import kafka_lag


def test_latest_offset_null_gives_no_lag() -> None:
    assert kafka_lag('{"t": {"0": 5}}', "null") == {}
    assert kafka_lag('{"t": {"0": 5}}', None) == {}


def test_invalid_json_gives_no_lag() -> None:
    assert kafka_lag('{"t": {"0": 5}}', "{not json") == {}


def test_partition_missing_from_end_offset_counts_from_zero() -> None:
    assert kafka_lag('{"t": {"0": 5}}', '{"t": {"0": 8, "1": 3}}') == {("t", 0): 3, ("t", 1): 3}


def test_missing_or_null_end_offset_counts_from_zero() -> None:
    assert kafka_lag(None, '{"t": {"0": 4}}') == {("t", 0): 4}
    assert kafka_lag("null", '{"t": {"0": 4}}') == {("t", 0): 4}


def test_end_offset_ahead_of_latest_is_zero_not_negative() -> None:
    assert kafka_lag('{"t": {"0": 9}}', '{"t": {"0": 7}}') == {("t", 0): 0}


def test_two_topics() -> None:
    end = '{"a": {"0": 10, "1": 20}, "b": {"0": 5}}'
    latest = '{"a": {"0": 12, "1": 20}, "b": {"0": 105}}'
    assert kafka_lag(end, latest) == {("a", 0): 2, ("a", 1): 0, ("b", 0): 100}


def test_offsets_of_the_wrong_shape_are_skipped() -> None:
    # JSON, but not {"topic": {"partition": offset}}: the listener must not raise on it.
    assert kafka_lag(None, '{"t": [1]}') == {}
    assert kafka_lag(None, '{"t": {"0": null, "1": 4}}') == {("t", 1): 4}
    assert kafka_lag(None, '{"t": {"x": 3}}') == {}
    assert kafka_lag('{"t": {"0": "a"}}', '{"t": {"0": 4}}') == {("t", 0): 4}
