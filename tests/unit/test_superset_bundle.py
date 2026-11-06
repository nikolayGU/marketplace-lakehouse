"""The Superset dashboard bundle must keep the BI user inside the Trino rules for `superset`.

The bundle is the only definition of the database connection Superset (and its MCP endpoint) uses:
the user in the URI is the Trino user whose rights docker/trino/etc/rules.json limits, and the
database flags decide whether Superset itself may write.
"""

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
import yaml

BUNDLE = Path(__file__).parents[2] / "docker" / "superset" / "dashboards"
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
