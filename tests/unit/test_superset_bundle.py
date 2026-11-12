"""The Superset dashboard bundle must keep the BI user inside the Trino rules for `superset`.

The bundle is the only definition of the database connection Superset (and its MCP endpoint) uses:
the user in the URI is the Trino user whose rights docker/trino/etc/rules.json limits, and the
database flags decide whether Superset itself may write. Every dataset column must also be
described in the dbt YAML of its model and selected by the model SQL, so a rename or a lost
description fails here and not in a chart.
"""

import json
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
import yaml
from dbt_sql import without_comments

BUNDLE = Path(__file__).parents[2] / "docker" / "superset" / "dashboards"
DBT_MODELS = Path(__file__).parents[2] / "dbt" / "models"
EXPOSED_TABLE = re.compile(r"(fct|dim|mart)_.*")


def _load(pattern: str) -> list[dict[str, Any]]:
    docs = [yaml.safe_load(p.read_text()) for p in sorted(BUNDLE.glob(pattern))]
    assert docs, pattern
    return docs


def _database() -> dict[str, Any]:
    (database,) = _load("databases/*.yaml")
    return database


def test_database_connects_as_superset_to_the_read_only_catalog_without_a_password() -> None:
    url = urlsplit(_database()["sqlalchemy_uri"])

    assert url.scheme == "trino"
    assert url.username == "superset"
    assert url.password is None
    assert url.path == "/lake_ro"


@pytest.mark.parametrize("flag", ["allow_dml", "allow_ctas", "allow_cvas", "allow_file_upload"])
def test_database_allows_no_writes(flag: str) -> None:
    database = _database()

    assert flag in database, f"{flag} must be explicit"
    assert database[flag] is False


def test_every_dataset_is_a_gold_mart_of_lake_ro_in_this_database() -> None:
    database_uuid = _database()["uuid"]

    for dataset in _load("datasets/**/*.yaml"):
        assert dataset["catalog"] == "lake_ro", dataset["table_name"]
        assert dataset["schema"] == "gold", dataset["table_name"]
        assert EXPOSED_TABLE.fullmatch(dataset["table_name"]), dataset["table_name"]
        assert dataset["database_uuid"] == database_uuid, dataset["table_name"]
        assert not dataset.get("sql"), "a virtual dataset would run its own SQL"


def test_charts_and_dashboard_refer_to_objects_of_the_bundle() -> None:
    dataset_uuids = {d["uuid"] for d in _load("datasets/**/*.yaml")}
    charts = _load("charts/*.yaml")
    chart_uuids = {c["uuid"] for c in charts}
    (dashboard,) = _load("dashboards/*.yaml")
    in_position = {
        node["meta"]["uuid"]
        for node in dashboard["position"].values()
        if isinstance(node, dict) and node.get("type") == "CHART"
    }

    assert {c["dataset_uuid"] for c in charts} <= dataset_uuids
    assert in_position == chart_uuids


def _dbt_columns() -> dict[str, dict[str, str]]:
    """Model name to {column: description} over every `dbt/models/**/_*.yml`."""
    models: dict[str, dict[str, str]] = {}
    for path in sorted((DBT_MODELS).glob("**/_*.yml")):
        for model in (yaml.safe_load(path.read_text()) or {}).get("models", []):
            columns = models.setdefault(model["name"], {})
            for column in model.get("columns", []):
                columns[column["name"]] = str(column.get("description") or "").strip()
    return models


def _plain_columns(dataset: dict[str, Any]) -> list[str]:
    return [
        c["column_name"]
        for c in dataset.get("columns", [])
        if not (c.get("expression") or "").strip()
    ]


def test_every_dataset_column_is_described_in_dbt() -> None:
    described = _dbt_columns()
    missing = {}
    for dataset in _load("datasets/**/*.yaml"):
        columns = described.get(dataset["table_name"], {})
        absent = [c for c in _plain_columns(dataset) if not columns.get(c)]
        if absent:
            missing[dataset["table_name"]] = absent

    assert not missing, f"dataset columns without a dbt description: {missing}"


def output_columns(sql: str) -> set[str]:
    """Names of the columns of the last top-level `select` of a model.

    Each item of the select list is named by the identifier after its last `as`, else by its last
    identifier (so `i.order_id` is `order_id`). Not a SQL parser: it relies on the model style of
    this repo (one select list, items separated by top-level commas).
    """
    sql = re.sub(r"'[^']*'", "''", without_comments(sql))
    depth, selects, parts = 0, [], []
    for match in re.finditer(r"\bselect\b|\bfrom\b|\(|\)|,", sql, flags=re.IGNORECASE):
        token = match.group().lower()
        if token == ")":
            depth -= 1
        if depth == 0 and token == "select":
            selects.append(match.end())
        if token == "(":
            depth += 1
    start = selects[-1]
    depth, item_start = 0, start
    for match in re.finditer(r"\bfrom\b|\(|\)|,", sql[start:], flags=re.IGNORECASE):
        token = match.group().lower()
        if token == ")":
            depth -= 1
        if depth == 0 and token in {",", "from"}:
            parts.append(sql[item_start : start + match.start()])
            item_start = start + match.end()
            if token == "from":
                break
        if token == "(":
            depth += 1
    names = set()
    for part in parts:
        part = re.sub(r"^\s*distinct\b", "", part.strip(), flags=re.IGNORECASE)
        found = re.search(r"\bas\s+(\w+)\s*$", part, flags=re.IGNORECASE) or re.search(
            r"(\w+)\s*$", part
        )
        if found:
            names.add(found.group(1).lower())
    return names


def test_every_dataset_column_is_selected_by_its_model() -> None:
    """Every dataset column without expression is an output name of the model's final select.

    Checks names only, not types or values.
    """
    missing = {}
    for dataset in _load("datasets/**/*.yaml"):
        (model,) = DBT_MODELS.glob(f"**/{dataset['table_name']}.sql")
        produced = output_columns(model.read_text())
        absent = [c for c in _plain_columns(dataset) if c.lower() not in produced]
        if absent:
            missing[f"{dataset['table_name']} ({model.name})"] = absent

    assert not missing, f"dataset columns absent from the model SQL: {missing}"


def _metrics(table: str) -> dict[str, dict[str, Any]]:
    (dataset,) = [d for d in _load("datasets/**/*.yaml") if d["table_name"] == table]
    return {m["metric_name"]: m for m in dataset["metrics"]}


def test_category_chart_counts_live_items_of_paid_orders() -> None:
    """PF-42: GMV of items is the saved metric and excludes deleted items and unpaid orders."""
    expression = _metrics("fct_order_items")["gmv"]["expression"]

    assert "NOT is_deleted" in expression
    assert "'canceled'" in expression
    assert "'unavailable'" in expression
    items_uuid = next(
        d["uuid"] for d in _load("datasets/**/*.yaml") if d["table_name"] == "fct_order_items"
    )
    on_items = [c for c in _load("charts/*.yaml") if c["dataset_uuid"] == items_uuid]
    assert on_items
    for chart in on_items:
        assert chart["params"]["metrics"] == ["gmv"], chart["slice_name"]


def test_every_ratio_metric_guards_division() -> None:
    for dataset in _load("datasets/**/*.yaml"):
        for metric in dataset["metrics"]:
            if "/" in metric["expression"]:
                assert "NULLIF" in metric["expression"], (
                    f"{dataset['table_name']}.{metric['metric_name']}"
                )


def _native_filters() -> dict[str, dict[str, Any]]:
    (dashboard,) = _load("dashboards/*.yaml")
    filters = dashboard["metadata"]["native_filter_configuration"]
    return {f["id"]: f for f in filters}


def _stems_by_chart_id() -> dict[int, str]:
    by_uuid = {c["uuid"]: stem for stem, c in _charts().items()}
    return {
        node["meta"]["chartId"]: by_uuid[node["meta"]["uuid"]]
        for node in _dashboard()["position"].values()
        if isinstance(node, dict) and node.get("type") == "CHART"
    }


def _excluded_stems(filter_id: str) -> set[str]:
    stems = _stems_by_chart_id()
    return {stems[i] for i in _native_filters()[filter_id]["scope"]["excluded"]}


def test_period_filter_defaults_to_last_quarter_and_skips_trends() -> None:
    period = _native_filters()["NATIVE_FILTER-period001"]

    assert period["name"] == "Period"
    assert period["filterType"] == "filter_time"
    assert period["defaultDataMask"]["extraFormData"]["time_range"] == "Last quarter"
    assert period["defaultDataMask"]["filterState"]["value"] == "Last quarter"
    assert period["scope"]["rootPath"] == ["ROOT_ID"]
    assert _excluded_stems("NATIVE_FILTER-period001") == {
        "data_through",
        "daily_sales",
        "on_time_by_month",
        "cancellations",
    }


def test_state_filter_targets_the_customer_state_of_orders() -> None:
    state = _native_filters()["NATIVE_FILTER-cstate001"]
    orders_uuid = next(
        d["uuid"] for d in _load("datasets/**/*.yaml") if d["table_name"] == "fct_orders"
    )

    assert state["filterType"] == "filter_select"
    assert state["targets"] == [{"column": {"name": "customer_state"}, "datasetUuid": orders_uuid}]
    assert _excluded_stems("NATIVE_FILTER-cstate001") == {"data_through"}
    assert state["controlValues"]["multiSelect"] is True
    assert state["controlValues"]["enableEmptyFilter"] is False
    assert state["defaultDataMask"]["filterState"]["value"] is None


HARBOR = ["#2c71b7", "#d6781c", "#0f9b89", "#795dba", "#9e6128", "#3498bf", "#bb8d1c", "#c55b96"]
OLD_UUIDS = {
    "daily_sales": "fedd884c-a753-54d2-8d42-7f11d9bc5540",
    "gmv_by_category": "38fb522a-dbb6-534c-9c83-5345c61a1240",
    "delivery_sla": "203f021c-39d0-5703-baa6-abd82d61b845",
    "cancellations": "664e832f-1b2d-578a-b059-ac81f90ac19c",
}
ANCHORED_RANGE = re.compile(r"^(Last \w+|Last \d+ \w+|No filter)$")


def _charts() -> dict[str, dict[str, Any]]:
    return {p.stem: yaml.safe_load(p.read_text()) for p in sorted(BUNDLE.glob("charts/*.yaml"))}


def _dashboard() -> dict[str, Any]:
    (dashboard,) = _load("dashboards/*.yaml")
    return dashboard


def _metric_names(params: dict[str, Any]) -> list[Any]:
    return params["metrics"] if "metrics" in params else [params["metric"]]


def test_harbor_is_the_scheme_everywhere() -> None:
    for path in BUNDLE.rglob("*.yaml"):
        assert "supersetColors" not in path.read_text(), path.name
    assert _dashboard()["metadata"]["color_scheme"] == "harbor"
    for stem, chart in _charts().items():
        if "color_scheme" in chart["params"]:
            assert chart["params"]["color_scheme"] == "harbor", stem


def test_dashboard_metadata_pins_the_harbor_colours_and_the_comparison_series() -> None:
    metadata = _dashboard()["metadata"]

    assert metadata["color_scheme_domain"] == HARBOR
    assert metadata["label_colors"]["GMV"] == "#2c71b7"
    assert metadata["label_colors"]["GMV__1 year ago"] == "#8c959f"


def test_kpis_treat_growth_of_freight_and_cancellations_as_bad() -> None:
    kpis = {s: c["params"] for s, c in _charts().items() if c["viz_type"] == "pop_kpi"}

    assert len(kpis) == 6
    for stem, params in kpis.items():
        bad = params["metric"] in {"freight_share", "cancellation_rate"}
        assert params["comparison_color_scheme"] == ("Red" if bad else "Green"), stem
        assert params["comparison_color_enabled"] is True, stem
        assert params["time_compare"] == ["inherit"], stem


def test_on_time_chart_draws_the_95_percent_target() -> None:
    params = _charts()["on_time_by_month"]["params"]
    (layer,) = params["annotation_layers"]

    assert layer["annotationType"] == "FORMULA"
    assert layer["value"] == "0.95"
    assert layer["style"] == "dashed"
    assert layer["width"] == 1.5
    assert layer["color"] == "#48505d"
    assert params["y_axis_bounds"] == [0.75, 1]
    assert params["y_axis_format"] == ".0%"


def test_states_table_hides_small_states_and_flags_misses() -> None:
    chart = _charts()["delivery_sla"]
    params = chart["params"]
    (having,) = [f for f in params["adhoc_filters"] if f["clause"] == "HAVING"]
    query = json.loads(chart["query_context"])["queries"][0]

    assert ">= 50" in having["sqlExpression"]
    assert params["row_limit"] == 8
    assert params["order_desc"] is False
    assert params["timeseries_limit_metric"] == "on_time_rate"
    assert query["orderby"] == [["on_time_rate", True]]
    (rule,) = params["conditional_formatting"]
    assert (rule["column"], rule["operator"], rule["targetValue"]) == ("on_time_rate", "<", 0.95)


def _time_ranges(node: Any) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "time_range" and isinstance(value, str):
                found.append(value)
            if key == "operator" and value == "TEMPORAL_RANGE":
                found.append(str(node["comparator"]))
            if key == "op" and value == "TEMPORAL_RANGE":
                found.append(str(node["val"]))
            found.extend(_time_ranges(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_time_ranges(item))
    return found


def test_time_ranges_use_only_anchored_phrases() -> None:
    found = []
    for chart in _charts().values():
        found += _time_ranges(chart["params"])
        found += _time_ranges(json.loads(chart["query_context"]))
    found += _time_ranges(_dashboard()["metadata"]["native_filter_configuration"])
    found += [
        f["defaultDataMask"]["filterState"].get("value") or "No filter"
        for f in _native_filters().values()
        if f["filterType"] == "filter_time"
    ]

    assert found
    for phrase in found:
        assert ANCHORED_RANGE.match(phrase), phrase


def test_query_context_repeats_params() -> None:
    for stem, chart in _charts().items():
        context = json.loads(chart["query_context"])
        (query,) = context["queries"]

        assert context["form_data"] == chart["params"], stem
        assert query["metrics"] == _metric_names(chart["params"]), stem


def test_the_four_old_charts_keep_their_uuids() -> None:
    charts = _charts()

    assert {stem: charts[stem]["uuid"] for stem in OLD_UUIDS} == OLD_UUIDS


def test_new_charts_have_derived_uuids() -> None:
    for stem, chart in _charts().items():
        if stem not in OLD_UUIDS:
            expected = uuid.uuid5(uuid.NAMESPACE_URL, f"lakehouse/superset/chart/{stem}")
            assert chart["uuid"] == str(expected), stem


def test_every_chart_in_the_state_filter_scope_uses_a_dataset_with_customer_state() -> None:
    datasets = {d["uuid"]: d for d in _load("datasets/**/*.yaml")}
    by_uuid = {c["uuid"]: c for c in _charts().values()}
    excluded = set(_native_filters()["NATIVE_FILTER-cstate001"]["scope"]["excluded"])
    in_scope = 0
    for node in _dashboard()["position"].values():
        if not isinstance(node, dict) or node.get("type") != "CHART":
            continue
        if node["meta"]["chartId"] in excluded:
            continue
        in_scope += 1
        columns = _plain_columns(datasets[by_uuid[node["meta"]["uuid"]]["dataset_uuid"]])
        assert "customer_state" in columns, node["id"]
    assert in_scope == 12


def test_every_chart_the_period_reaches_has_one_temporal_filter_on_its_time_column() -> None:
    """The backend applies the dashboard time range only to an existing TEMPORAL_RANGE filter."""
    datasets = {d["uuid"]: d["main_dttm_col"] for d in _load("datasets/**/*.yaml")}
    excluded = _excluded_stems("NATIVE_FILTER-period001")
    for stem, chart in _charts().items():
        if stem in excluded:
            continue
        column = datasets[chart["dataset_uuid"]]
        in_params = [
            f
            for f in chart["params"]["adhoc_filters"]
            if f.get("operator") == "TEMPORAL_RANGE" and f["subject"] == column
        ]
        (query,) = json.loads(chart["query_context"])["queries"]
        in_query = [
            f for f in query["filters"] if f["op"] == "TEMPORAL_RANGE" and f["col"] == column
        ]

        assert len(in_params) == 1, stem
        assert len(in_query) == 1, stem
        assert in_params[0]["comparator"] == in_query[0]["val"] == query["time_range"], stem


def test_the_gmv_comparison_series_is_not_recoloured_to_the_original() -> None:
    assert _charts()["daily_sales"]["params"]["time_shift_color"] is False


def test_cross_filters_are_off_because_they_would_filter_only_some_charts() -> None:
    assert _dashboard()["metadata"]["cross_filters_enabled"] is False


def test_states_table_formats_misses_with_a_flat_fill() -> None:
    (rule,) = _charts()["delivery_sla"]["params"]["conditional_formatting"]

    assert rule["useGradient"] is False


def test_bar_charts_sort_by_the_metric_descending_in_the_query() -> None:
    for stem in ("gmv_by_category", "orders_by_status"):
        chart = _charts()[stem]
        (query,) = json.loads(chart["query_context"])["queries"]
        metric = chart["params"]["metrics"][0]

        assert chart["params"]["x_axis_sort"] == metric, stem
        assert chart["params"]["x_axis_sort_asc"] is False, stem
        assert {"operation": "sort", "options": {"by": metric, "ascending": False}} in query[
            "post_processing"
        ], stem


def test_query_follows_from_params() -> None:
    for stem, chart in _charts().items():
        params = chart["params"]
        (query,) = json.loads(chart["query_context"])["queries"]
        simple = [
            {"col": f["subject"], "op": f["operator"], "val": f["comparator"]}
            for f in params["adhoc_filters"]
            if f["expressionType"] == "SIMPLE"
        ]
        having = [
            f["sqlExpression"] for f in params["adhoc_filters"] if f.get("clause") == "HAVING"
        ]
        where = [
            f["sqlExpression"]
            for f in params["adhoc_filters"]
            if f.get("clause") == "WHERE" and f["expressionType"] == "SQL"
        ]

        assert query["filters"] == simple, stem
        assert query["row_limit"] == params["row_limit"], stem
        assert query.get("time_range") == params.get("time_range"), stem
        assert query.get("time_offsets", []) == params.get("time_compare", []), stem
        assert query["extras"]["having"] == " AND ".join(f"({h})" for h in having), stem
        assert query["extras"]["where"] == " AND ".join(f"({w})" for w in where), stem
        assert query["order_desc"] == params.get("order_desc", True), stem
        if "timeseries_limit_metric" in params:
            assert query["orderby"] == [
                [params["timeseries_limit_metric"], not query["order_desc"]]
            ]
        elif query["orderby"]:
            assert query["orderby"] == [[_metric_names(params)[0], False]], stem


def test_dashboard_has_the_mockup_sections_and_footer() -> None:
    position = _dashboard()["position"]
    grid = [position[i] for i in position["GRID_ID"]["children"]]
    headers = [n["meta"]["text"] for n in grid if n["type"] == "HEADER"]
    footer = position[position["GRID_ID"]["children"][-1]]

    assert headers == ["Key figures", "Sales", "Delivery", "Orders"]
    assert footer["type"] == "ROW"
    (note,) = [position[c] for c in footer["children"]]
    assert note["type"] == "MARKDOWN"
    assert note["meta"]["width"] == 12
    assert "CC BY-NC-SA 4.0" in note["meta"]["code"]
    assert "lake_ro" in note["meta"]["code"]
