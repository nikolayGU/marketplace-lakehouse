"""Alert rules: annotations, runbooks and no compose project name in expressions."""

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / "observability" / "prometheus" / "alerts.yml"
DASHBOARDS = ROOT / "observability" / "grafana" / "dashboards"
OPERATIONS = ROOT / "OPERATIONS.md"
TEMPLATE = re.compile(r"\{\{(.*?)\}\}")
LABEL_REF = re.compile(r"\s*\$labels\.[a-z_]+\s*")


def _rules() -> list[dict[str, Any]]:
    groups = yaml.safe_load(RULES.read_text())["groups"]
    return [rule for group in groups for rule in group["rules"]]


def _rule_id(rule: dict[str, Any]) -> str:
    cause = rule.get("labels", {}).get("cause")
    return f"{rule['alert']}-{cause}" if cause else str(rule["alert"])


def _exprs(node: Any) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "expr" and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_exprs(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_exprs(item))
    return found


def _runbooks_section() -> str:
    text = OPERATIONS.read_text()
    start = text.index("\n## Runbooks")
    end = text.find("\n## ", start + 1)
    return text[start:end]


RULES_LIST = _rules()


def test_sixteen_rules() -> None:
    assert len(RULES_LIST) == 16


@pytest.mark.parametrize("rule", RULES_LIST, ids=_rule_id)
def test_annotations_have_summary_and_runbook_only(rule: dict[str, Any]) -> None:
    annotations = rule.get("annotations") or {}
    assert set(annotations) == {"summary", "runbook_url"}
    assert all(isinstance(v, str) and v.strip() for v in annotations.values())


@pytest.mark.parametrize("rule", RULES_LIST, ids=_rule_id)
def test_templates_are_label_references_only(rule: dict[str, Any]) -> None:
    for text in (rule.get("annotations") or {}).values():
        assert "$value" not in text
        for body in TEMPLATE.findall(text):
            assert LABEL_REF.fullmatch(body), body


@pytest.mark.parametrize("rule", RULES_LIST, ids=_rule_id)
def test_runbook_exists_names_the_alert_and_is_listed(rule: dict[str, Any]) -> None:
    url = (rule.get("annotations") or {}).get("runbook_url", "")
    assert url.startswith("docs/runbooks/")
    path = ROOT / url
    assert path.is_file(), url
    assert rule["alert"] in path.read_text()
    assert url in _runbooks_section()


@pytest.mark.parametrize("rule", RULES_LIST, ids=_rule_id)
def test_rule_expr_has_no_project_name(rule: dict[str, Any]) -> None:
    assert "lakehouse-" not in rule["expr"]


@pytest.mark.parametrize("path", sorted(DASHBOARDS.glob("*.json")), ids=lambda p: p.name)
def test_dashboard_exprs_have_no_project_name(path: Path) -> None:
    for expr in _exprs(json.loads(path.read_text())):
        assert "lakehouse-" not in expr, expr
