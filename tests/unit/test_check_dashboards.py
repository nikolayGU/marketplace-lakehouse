import json
import urllib.request
from collections.abc import Mapping
from pathlib import Path

from scripts.obs import check_dashboards


def _dashboard(path: Path, panels: list[dict[str, object]]) -> Path:
    path.write_text(json.dumps({"title": "t", "panels": panels}))
    return path


def test_every_panel_with_data_passes(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    path = _dashboard(
        tmp_path / "a.json",
        [{"title": "lag", "targets": [{"expr": "up"}, {"expr": "sum(up)"}]}],
    )

    code = check_dashboards.check([path], lambda expr: [{"metric": {}, "value": [0, "1"]}])

    assert code == 0
    assert "queries ok: 2" in capsys.readouterr().out


def test_an_empty_result_fails_and_names_the_panel(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    path = _dashboard(tmp_path / "a.json", [{"title": "typo", "targets": [{"expr": "upp"}]}])

    code = check_dashboards.check([path], lambda expr: [])

    out = capsys.readouterr().out
    assert code == 1
    assert "typo" in out and "upp" in out


def test_a_panel_without_targets_does_not_crash(tmp_path: Path) -> None:
    path = _dashboard(tmp_path / "a.json", [{"title": "text"}, {"title": "row", "targets": []}])

    assert check_dashboards.check([path], lambda expr: []) == 0


def test_nested_row_panels_are_checked(tmp_path: Path) -> None:
    row: dict[str, object] = {
        "title": "row",
        "type": "row",
        "panels": [{"title": "p", "targets": [{"expr": "x"}]}],
    }
    path = _dashboard(tmp_path / "a.json", [row])

    assert check_dashboards.check([path], lambda expr: []) == 1


def test_a_failed_query_counts_as_empty(tmp_path: Path) -> None:
    path = _dashboard(tmp_path / "a.json", [{"title": "p", "targets": [{"expr": "x"}]}])

    def broken(expr: str) -> list[dict[str, object]]:
        raise OSError("prometheus down")

    assert check_dashboards.check([path], broken) == 1


def test_a_typo_behind_or_vector_fails(tmp_path: Path) -> None:
    # `or vector(0)` always returns a row; the metric names in front of it must exist.
    expr = 'sum(increase(airflow_ti_finsh_total{state="failed"}[1h])) or vector(0)'
    path = _dashboard(tmp_path / "a.json", [{"title": "p", "targets": [{"expr": expr}]}])
    asked: list[str] = []

    def prometheus(query: str) -> list[dict[str, object]]:
        asked.append(query)
        return [] if "airflow_ti_finsh_total" in query else [{"metric": {}, "value": [0, "0"]}]

    assert check_dashboards.check([path], prometheus) == 1
    assert "group(last_over_time(airflow_ti_finsh_total[7d]))" in asked


def test_a_failed_name_lookup_counts_as_empty(tmp_path: Path) -> None:
    path = _dashboard(
        tmp_path / "a.json", [{"title": "p", "targets": [{"expr": "sum(x_total) or vector(0)"}]}]
    )

    def prometheus(query: str) -> list[dict[str, object]]:
        if query.startswith("group("):
            raise OSError("prometheus down")
        return [{"metric": {}, "value": [0, "0"]}]

    assert check_dashboards.check([path], prometheus) == 1


def test_metric_names_skip_functions_labels_and_keywords() -> None:
    expr = (
        'sum by (topic) (rate(a_total{state="x"}[5m])) / ignoring(job) b_count offset 1h '
        'or count(ALERTS{alertstate="firing"}) or vector(0)'
    )

    assert check_dashboards.metric_names(expr) == {"a_total", "b_count"}


def _trino_dashboard(path: Path, sql: str = "select 1") -> Path:
    target = {"datasource": {"uid": "trino"}, "rawSQL": sql, "refId": "A"}
    return _dashboard(path, [{"title": "sales", "targets": [target]}])


def test_a_trino_target_is_run_not_skipped(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    path = _trino_dashboard(tmp_path / "a.json", "select 7")
    asked: list[str] = []

    def trino(sql: str) -> list[dict[str, object]]:
        asked.append(sql)
        return [{"row": [7]}]

    code = check_dashboards.check([path], lambda expr: [], trino)

    assert code == 0
    assert asked == ["select 7"]
    assert "queries ok: 1" in capsys.readouterr().out


def test_an_empty_trino_result_fails_and_names_the_panel(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    path = _trino_dashboard(tmp_path / "a.json", "select 1 where false")

    code = check_dashboards.check([path], lambda expr: [], lambda sql: [])

    out = capsys.readouterr().out
    assert code == 1
    assert "sales" in out and "select 1 where false" in out


def test_a_failed_trino_query_counts_as_empty(tmp_path: Path) -> None:
    path = _trino_dashboard(tmp_path / "a.json")

    def broken(sql: str) -> list[dict[str, object]]:
        raise OSError("trino down")

    assert check_dashboards.check([path], lambda expr: [], broken) == 1


class _Response:
    def __init__(self, body: Mapping[str, object]) -> None:
        self._body = json.dumps(body).encode()

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def test_trino_query_follows_next_uri_and_collects_rows(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    pages: dict[str, Mapping[str, object]] = {
        "http://127.0.0.1:8080/v1/statement": {"nextUri": "http://127.0.0.1:8080/v1/s/1"},
        "http://127.0.0.1:8080/v1/s/1": {"data": [[1]], "nextUri": "http://127.0.0.1:8080/v1/s/2"},
        "http://127.0.0.1:8080/v1/s/2": {"data": [[2]]},
    }
    seen: list[tuple[str, str, dict[str, str]]] = []

    def urlopen(request, timeout):  # type: ignore[no-untyped-def]
        seen.append((request.get_method(), request.full_url, dict(request.header_items())))
        return _Response(pages[request.full_url])

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    rows = check_dashboards.trino_query("select x from lake_ro.gold.t")

    assert rows == [{"row": [1]}, {"row": [2]}]
    assert [method for method, _, _ in seen] == ["POST", "GET", "GET"]
    for _, _, raw in seen:
        headers = {k.lower(): v for k, v in raw.items()}
        # The panels name lake_ro.gold.<table>; the plugin sends no catalog, so neither does this.
        assert "x-trino-catalog" not in headers
        assert headers["x-trino-user"] == "grafana"


def test_trino_query_runs_as_the_given_user(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    users: list[str] = []

    def urlopen(request, timeout):  # type: ignore[no-untyped-def]
        users.append(dict(request.header_items())["X-trino-user"])
        return _Response({"data": [[1]]})

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    check_dashboards.trino_query("select 1", user="someone")

    assert users == ["someone"]


def test_main_runs_trino_panels_as_the_datasource_user(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    path = _trino_dashboard(tmp_path / "a.json")
    users: list[str] = []

    def urlopen(request, timeout):  # type: ignore[no-untyped-def]
        users.append(dict(request.header_items())["X-trino-user"])
        return _Response({"data": [[1]]})

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    assert check_dashboards.main([str(path)]) == 0
    assert users == ["grafana"]


def test_trino_query_raises_on_a_query_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    error = {"error": {"message": "Table 'lake.gold.nope' does not exist"}}
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: _Response(error))

    try:
        check_dashboards.trino_query("select 1 from lake.gold.nope")
    except OSError as raised:
        assert "does not exist" in str(raised)
    else:
        raise AssertionError("a Trino error must not read as an empty result")


def test_trino_query_stops_at_the_deadline_when_the_query_never_finishes(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    clock = iter([0.0, 1.0, 50.0, 200.0, 300.0])
    pages = {"nextUri": "http://127.0.0.1:8080/v1/s/1"}
    monkeypatch.setattr("scripts.obs.check_dashboards.monotonic", lambda: next(clock))
    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: _Response(pages))

    try:
        check_dashboards.trino_query("select 1")
    except OSError as raised:
        assert "120" in str(raised)
    else:
        raise AssertionError("a query that never finishes must hit the deadline")


def test_a_non_json_trino_answer_is_a_failed_query_not_a_traceback(  # type: ignore[no-untyped-def]
    tmp_path: Path, capsys, monkeypatch
) -> None:
    class _Html(_Response):
        def read(self) -> bytes:
            return b"<html>502</html>"

    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout: _Html({}))
    path = _trino_dashboard(tmp_path / "a.json")

    code = check_dashboards.check([path], lambda expr: [])

    out = capsys.readouterr().out
    assert code == 1
    assert "query failed for select 1" in out


SPARK_EXPR = 'spark_streaming_state_rows{query="orders_per_minute"}'


def _spark_check(  # type: ignore[no-untyped-def]
    tmp_path: Path,
    expr: str = SPARK_EXPR,
    known=lambda name: True,
    age=lambda query: 20.0,
    has_batches=lambda query: False,
    seen=lambda selector: True,
    query=lambda e: [],
) -> int:
    path = _dashboard(tmp_path / "a.json", [{"title": "state", "targets": [{"expr": expr}]}])
    return check_dashboards.check(
        [path],
        query,
        known=known,
        last_batch_age=age,
        has_batches=has_batches,
        seen_before=seen,
    )


def test_an_empty_spark_panel_of_a_live_query_is_idle(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert _spark_check(tmp_path) == 0

    out = capsys.readouterr().out
    assert f"idle: a.json: state: {SPARK_EXPR}" in out
    assert "empty:" not in out


def test_a_misspelled_spark_metric_is_empty_even_with_a_fresh_batch(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    expr = 'spark_streaming_bach_duration_seconds{query="orders_per_minute"}'

    code = _spark_check(tmp_path, expr, known=lambda name: "bach" not in name)

    out = capsys.readouterr().out
    assert code == 1
    assert f"empty: a.json: state: {expr}" in out and "idle:" not in out


def test_a_stale_last_batch_is_empty_not_idle(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert _spark_check(tmp_path, age=lambda query: 301.0) == 1
    assert "empty:" in capsys.readouterr().out


def test_a_missing_last_batch_is_empty_not_idle(tmp_path: Path) -> None:
    assert _spark_check(tmp_path, age=lambda query: None) == 1


def test_a_failed_idle_lookup_is_empty_not_idle(tmp_path: Path) -> None:
    def broken(name: str) -> bool:
        raise OSError("prometheus down")

    assert _spark_check(tmp_path, known=broken) == 1


def test_an_empty_panel_of_another_job_is_never_idle(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    code = _spark_check(tmp_path, 'airflow_x{query="orders_per_minute"}')

    assert code == 1
    assert "empty:" in capsys.readouterr().out


def test_a_spark_panel_with_a_non_spark_metric_is_never_idle(tmp_path: Path) -> None:
    expr = 'spark_streaming_state_rows{query="orders_per_minute"} / up'

    assert _spark_check(tmp_path, expr) == 1


def test_a_spark_panel_without_a_query_label_is_never_idle(tmp_path: Path) -> None:
    assert _spark_check(tmp_path, "spark_streaming_state_rows") == 1


def test_a_failed_panel_query_is_empty_not_idle(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    def broken(expr: str) -> list[dict[str, object]]:
        raise OSError("HTTP Error 400")

    assert _spark_check(tmp_path, query=broken) == 1
    out = capsys.readouterr().out
    assert "query failed" in out and "idle:" not in out


def test_a_query_that_made_batches_with_data_is_never_idle(tmp_path: Path) -> None:
    assert _spark_check(tmp_path, has_batches=lambda query: True) == 1


def test_a_failed_batch_lookup_is_empty_not_idle(tmp_path: Path) -> None:
    def broken(query: str) -> bool:
        raise OSError("prometheus down")

    assert _spark_check(tmp_path, has_batches=broken) == 1


def test_a_selector_without_a_series_in_the_retention_is_not_idle(tmp_path: Path) -> None:
    # A label name or value typo, or a metric the query never had: no series, ever.
    expr = 'spark_streaming_kafka_lag{query="bronze_cdc_ingest", topik="x"}'
    asked: list[str] = []

    def seen(selector: str) -> bool:
        asked.append(selector)
        return "topik" not in selector

    assert _spark_check(tmp_path, expr, seen=seen) == 1
    assert asked == [expr]


def test_a_vector_matching_expression_is_never_idle(tmp_path: Path) -> None:
    expr = (
        'spark_streaming_kafka_lag{query="q"} / on(topic) '
        'spark_streaming_batch_duration_seconds{query="q"}'
    )

    assert _spark_check(tmp_path, expr) == 1


def test_two_different_query_labels_are_never_idle(tmp_path: Path) -> None:
    expr = 'spark_streaming_state_rows{query="a"} + spark_streaming_state_rows{query="b"}'

    assert _spark_check(tmp_path, expr) == 1


def test_a_batch_exactly_300_seconds_old_is_idle(tmp_path: Path) -> None:
    assert _spark_check(tmp_path, age=lambda query: 300.0) == 0


def test_known_checks_the_metric_type_for_the_total_suffix() -> None:
    types = {
        "spark_streaming_input_rows": "counter",
        "spark_streaming_state_rows": "gauge",
    }

    def prometheus_get(path: str) -> dict[str, object]:
        name = path.rsplit("=", 1)[1]
        return {"data": {name: [{"type": types[name]}]} if name in types else {}}

    known = check_dashboards.metric_known(prometheus_get)

    assert known("spark_streaming_input_rows_total")
    assert not known("spark_streaming_input_rows")
    assert known("spark_streaming_state_rows")
    assert not known("spark_streaming_state_rows_total")


def test_pipeline_health_spark_panels_say_why_they_are_empty() -> None:
    dashboard = json.loads((check_dashboards.DASHBOARDS / "pipeline-health.json").read_text())
    spark_only = []
    for panel in check_dashboards.panels(dashboard):
        for target in panel.get("targets", []):
            expr = target.get("expr", "")
            names = check_dashboards.metric_names(expr)
            if (
                names
                and all(n.startswith("spark_streaming_") for n in names)
                and not expr.startswith("time() - ")
            ):
                spark_only.append(panel)
    assert len(spark_only) >= 7
    for panel in spark_only:
        text = panel["fieldConfig"]["defaults"].get("noValue")
        assert text and "or the job is down" in text, panel["title"]
        bronze = 'query="bronze_cdc_ingest"' in panel["targets"][0]["expr"]
        assert ("Seconds since the last bronze batch" in text) == bronze, panel["title"]
    titles = [p["title"] for p in check_dashboards.panels(dashboard)]
    assert "Seconds since the last bronze batch" in titles
