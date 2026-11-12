"""The dashboard filters by customer state, so fct_order_items must carry and describe it."""

import re
from pathlib import Path

import yaml
from test_dbt_soft_delete import without_comments

MARTS = Path(__file__).parents[2] / "dbt" / "models" / "marts"


def test_fct_order_items_selects_the_customer_state() -> None:
    sql = without_comments((MARTS / "fct_order_items.sql").read_text())

    assert re.search(r"\bo\.customer_state\b", sql)


def test_core_yml_describes_the_customer_state_of_order_items() -> None:
    models = yaml.safe_load((MARTS / "_core.yml").read_text())["models"]
    (model,) = [m for m in models if m["name"] == "fct_order_items"]
    columns = {c["name"]: c for c in model["columns"]}

    assert "customer_state" in columns
    assert str(columns["customer_state"].get("description", "")).strip()
