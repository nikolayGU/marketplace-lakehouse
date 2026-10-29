"""The Marketplace dashboard reads lake.gold through the Trino datasource plugin (W6-D11)."""

import json
import re
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from scripts.obs import check_dashboards

REPO = Path(__file__).parents[2]
GRAFANA = REPO / "observability" / "grafana"
DASHBOARD = GRAFANA / "dashboards" / "marketplace.json"
PLUGIN = "trino-datasource"
TITLES = {"Daily sales", "GMV by category, top 10", "Delivery SLA by state", "Cancellations"}
MONEY = r"(?:\w+\.)?(?:gmv|canceled_gmv|price|freight_value|freight)"


def _dashboard() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(DASHBOARD.read_text())
    return data


def _targets() -> list[dict[str, Any]]:
    return [t for p in check_dashboards.panels(_dashboard()) for t in p.get("targets", [])]


def _sql(title: str) -> str:
    panel = next(p for p in check_dashboards.panels(_dashboard()) if p["title"] == title)
    return " ".join(str(panel["targets"][0]["rawSQL"]).lower().split())


def test_the_dashboard_has_the_four_panels_of_the_roadmap() -> None:
    titles = {p["title"] for p in check_dashboards.panels(_dashboard())}

    assert titles == TITLES


def test_every_panel_and_target_uses_the_trino_datasource() -> None:
    for panel in check_dashboards.panels(_dashboard()):
        assert panel["datasource"] == {"type": PLUGIN, "uid": "trino"}, panel["title"]
        assert panel["targets"], panel["title"]
        for target in panel["targets"]:
            assert target["datasource"] == {"type": PLUGIN, "uid": "trino"}, panel["title"]
            assert target["rawSQL"].strip(), panel["title"]


def test_the_queries_read_only_lake_gold() -> None:
    for target in _targets():
        sql = target["rawSQL"].lower()
        tables = re.findall(r"\b(?:from|join)\s+([\w.]+)", sql)
        assert tables, sql
        assert all(t.startswith("lake.gold.") for t in tables), tables
        assert not re.search(r"\b(silver|bronze)\b", sql), sql


def test_money_is_not_cast_to_double_in_the_queries() -> None:
    for target in _targets():
        sql = target["rawSQL"].lower()
        assert not re.search(r"cast\([^;]*?(gmv|price|freight)[^;]*?as\s+(double|real)\)", sql), sql


def test_every_target_returns_a_table() -> None:
    for target in _targets():
        assert target["format"] == 1, target["rawSQL"]


def test_money_has_no_arithmetic_that_leads_to_double() -> None:
    # `sum(gmv) * 1e0` or `* 1.0` turns a decimal into a double without a cast in sight.
    for target in _targets():
        sql = " ".join(target["rawSQL"].lower().split())
        assert not re.search(r"\b\d+\.\d+|\b\d+e[+-]?\d+\b", sql), sql
        assert not re.search(rf"{MONEY}\)?\s*[-+*/%]", sql), sql
        assert not re.search(rf"[-+*/%]\s*(?:(?:sum|avg|min|max)\()?{MONEY}", sql), sql
        if re.search(MONEY, sql):
            assert not re.search(r"\b(double|real|float)\b", sql), sql


def test_order_counts_come_from_fct_orders_not_from_the_per_state_mart() -> None:
    # mart_daily_sales has a row per date and seller state and counts an order in each state.
    for target in _targets():
        assert not re.search(
            r"sum\(\s*(orders_count|canceled_orders)\s*\)", target["rawSQL"].lower()
        )
    assert "from lake.gold.fct_orders" in _sql("Daily sales")
    assert "count(*)" in _sql("Daily sales")
    assert "from lake.gold.fct_orders" in _sql("Cancellations")
    assert "count_if(is_canceled)" in _sql("Cancellations")


def test_gmv_by_category_counts_live_items_of_orders_that_count_as_gmv() -> None:
    sql = _sql("GMV by category, top 10")

    assert "from lake.gold.fct_order_items" in sql
    assert "not is_deleted" in sql
    assert "order_status not in ('canceled', 'unavailable')" in sql


def test_delivery_sla_is_computed_from_orders_with_the_model_definition() -> None:
    sql = _sql("Delivery SLA by state")

    assert "from lake.gold.fct_orders" in sql
    assert "group by customer_state" in sql
    assert "count_if(is_delivered and not is_late)" in sql
    assert "count_if(is_delivered)" in sql
    assert "avg(delivery_days) filter (where is_delivered)" in sql
    assert "mart_delivery_sla" not in sql


def test_the_dashboard_does_not_refresh_faster_than_a_minute() -> None:
    refresh = _dashboard().get("refresh", "")

    assert refresh in ("", False) or refresh in ("1m", "5m", "15m", "30m", "1h")


def test_the_trino_datasource_is_provisioned_by_a_file() -> None:
    files = (GRAFANA / "provisioning" / "datasources").glob("*.yml")
    sources = [s for f in files for s in yaml.safe_load(f.read_text())["datasources"]]
    trino = [s for s in sources if s["uid"] == "trino"]

    assert len(trino) == 1
    assert trino[0]["type"] == PLUGIN
    assert trino[0]["url"] == "http://trino:8080"
    assert trino[0]["editable"] is False
    assert not trino[0].get("password")
    assert not trino[0].get("basicAuthPassword")


def test_grafana_pins_the_plugin_version_and_has_room_for_it() -> None:
    compose = yaml.safe_load((REPO / "docker" / "compose.yaml").read_text())
    grafana = compose["services"]["grafana"]

    # Synchronous: provisioning must find the plugin when the datasource file is read.
    assert grafana["environment"]["GF_PLUGINS_PREINSTALL_SYNC"] == f"{PLUGIN}@1.4.1"
    assert "GF_PLUGINS_PREINSTALL" not in grafana["environment"]
    assert grafana["deploy"]["resources"]["limits"]["memory"] == "384M"
