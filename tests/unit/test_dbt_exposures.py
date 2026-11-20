"""Exposures must list what the dashboards read, and every chart metric needs a glossary block."""

import json
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).parents[2]
MODELS = ROOT / "dbt" / "models"
BUNDLE = ROOT / "docker" / "superset" / "dashboards"
GRAFANA = ROOT / "observability" / "grafana" / "dashboards" / "marketplace.json"


def exposure_refs(name: str) -> set[str]:
    exposures = yaml.safe_load((MODELS / "marts" / "_exposures.yml").read_text())["exposures"]
    (exposure,) = [e for e in exposures if e["name"] == name]
    return set(re.findall(r"ref\('(\w+)'\)", " ".join(exposure["depends_on"])))


def grafana_panels(panels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flat: list[dict[str, Any]] = []
    for panel in panels:
        flat.append(panel)
        flat.extend(grafana_panels(panel.get("panels", [])))
    return flat


def chart_metrics() -> set[str]:
    names: set[str] = set()
    for path in sorted((BUNDLE / "charts").glob("*.yaml")):
        params = yaml.safe_load(path.read_text())["params"]
        candidates = [
            *params.get("metrics", []),
            params.get("metric"),
            params.get("timeseries_limit_metric"),
        ]
        names.update(m for m in candidates if isinstance(m, str) and m)
    return names


def test_superset_exposure_depends_on_the_bundle_datasets() -> None:
    datasets = {
        yaml.safe_load(p.read_text())["table_name"]
        for p in (BUNDLE / "datasets" / "Lakehouse_Trino_lake_ro").glob("*.yaml")
    }

    assert exposure_refs("marketplace_superset") == datasets


def test_grafana_exposure_depends_on_the_tables_of_its_panels() -> None:
    dashboard = json.loads(GRAFANA.read_text())
    tables: set[str] = set()
    for panel in grafana_panels(dashboard["panels"]):
        for target in panel.get("targets", []):
            tables.update(re.findall(r"lake_ro\.gold\.(\w+)", target.get("rawSQL", "")))

    assert tables
    assert exposure_refs("marketplace_grafana") == tables


def test_every_dashboard_metric_has_a_glossary_block_used_by_dbt() -> None:
    metrics = chart_metrics()
    blocks = set(re.findall(r"{%\s*docs\s+(\w+)\s*%}", (MODELS / "docs.md").read_text()))
    used: set[str] = set()
    for path in MODELS.rglob("*.yml"):
        used.update(re.findall(r"doc\('(\w+)'\)", path.read_text()))

    assert metrics
    assert metrics - blocks == set()
    assert metrics - used == set()
