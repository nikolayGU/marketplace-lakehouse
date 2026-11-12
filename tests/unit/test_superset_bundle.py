"""The Superset dashboard bundle must keep the BI user inside the Trino rules for `superset`.

The bundle is the only definition of the database connection Superset (and its MCP endpoint) uses:
the user in the URI is the Trino user whose rights docker/trino/etc/rules.json limits, and the
database flags decide whether Superset itself may write. Every dataset column must also be
described in the dbt YAML of its model and selected by the model SQL, so a rename or a lost
description fails here and not in a chart.
"""

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
import yaml
from test_dbt_soft_delete import without_comments

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


def test_every_dataset_column_is_selected_by_its_model() -> None:
    missing = {}
    for dataset in _load("datasets/**/*.yaml"):
        (model,) = DBT_MODELS.glob(f"**/{dataset['table_name']}.sql")
        # A word followed by `as` is renamed away, not selected under its name.
        sql = without_comments(model.read_text())
        absent = [c for c in _plain_columns(dataset) if not re.search(rf"\b{c}\b(?!\s+as\b)", sql)]
        if absent:
            missing[f"{dataset['table_name']} ({model.name})"] = absent

    assert not missing, f"dataset columns absent from the model SQL: {missing}"
