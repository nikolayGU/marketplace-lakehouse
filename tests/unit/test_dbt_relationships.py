"""A relationships test on a model that keeps deleted rows filters them out.

`fct_order_items` keeps deleted items (`is_deleted`), while `fct_orders` and the dimensions drop
deleted entities. Without `where: "not is_deleted"` a legally deleted order turns the test red on
every build and the models after it are skipped.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

MARTS = Path(__file__).resolve().parents[2] / "dbt" / "models" / "marts"
KEEPS_DELETED_ROWS = {"fct_order_items"}


def relationship_tests() -> list[tuple[str, str, dict[str, Any]]]:
    found = []
    for path in sorted(MARTS.glob("*.yml")):
        for model in yaml.safe_load(path.read_text()).get("models", []):
            if model["name"] not in KEEPS_DELETED_ROWS:
                continue
            for column in model.get("columns", []):
                for test in column.get("data_tests", []):
                    if isinstance(test, dict) and "relationships" in test:
                        found.append((model["name"], column["name"], test["relationships"]))
    return found


def test_the_scan_finds_the_relationships_of_fct_order_items() -> None:
    assert {column for _, column, _ in relationship_tests()} == {
        "order_id",
        "product_id",
        "seller_id",
    }


@pytest.mark.parametrize(("model", "column", "test"), relationship_tests())
def test_relationships_of_a_model_with_deleted_rows_skip_them(
    model: str, column: str, test: dict[str, Any]
) -> None:
    assert test.get("config", {}).get("where") == "not is_deleted", f"{model}.{column}"
