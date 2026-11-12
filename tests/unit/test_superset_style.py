"""The Superset settings carry the Harbor look: themes, colour schemes, line style, time anchor.

The settings file cannot import superset (circular import, and the host runs without it), so
the themes copy every default token and these tests pin both the copy and the overrides.
"""

import importlib.util
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).parents[2]
CONFIG = ROOT / "docker" / "superset" / "superset_config.py"
COMPOSE = ROOT / "docker" / "compose.yaml"

LIGHT_TOKENS = {
    "colorPrimary": "#175fa4",
    "colorLink": "#175fa4",
    "colorLinkHover": "#064883",
    "colorSuccess": "#3a9742",
    "colorSuccessText": "#256c2c",
    "colorSuccessBg": "#e8f9e7",
    "colorWarning": "#f4af2d",
    "colorWarningText": "#794d0b",
    "colorWarningBg": "#fff4db",
    "colorError": "#d03c3c",
    "colorErrorText": "#aa2a2c",
    "colorErrorBg": "#ffebe9",
    "colorInfo": "#2c71b7",
    "colorBgLayout": "#f4f7fa",
    "colorBgContainer": "#ffffff",
    "colorTextBase": "#131a24",
    "colorText": "#131a24",
    "colorTextSecondary": "#48505d",
    "colorTextTertiary": "#626a75",
    "colorBorder": "#c3cad1",
    "colorBorderSecondary": "#e4e8ec",
    "colorSplit": "#e4e8ec",
    "borderRadius": 8,
}
DARK_TOKENS = {
    "colorPrimary": "#2f74bb",
    "colorLink": "#76afee",
    "colorLinkHover": "#76afee",
    "colorSuccess": "#54b05a",
    "colorSuccessText": "#71c575",
    "colorSuccessBg": "#1c2e1c",
    "colorWarning": "#f4af2d",
    "colorWarningText": "#f1bf5b",
    "colorWarningBg": "#37290f",
    "colorError": "#e55551",
    "colorErrorText": "#f3827a",
    "colorErrorBg": "#401f1f",
    "colorInfo": "#3f83cb",
    "colorBgLayout": "#0d1115",
    "colorBgContainer": "#181c21",
    "colorTextBase": "#edf0f4",
    "colorText": "#edf0f4",
    "colorTextSecondary": "#bac2ca",
    "colorTextTertiary": "#979fa8",
    "colorBorder": "#3f464d",
    "colorBorderSecondary": "#272c31",
    "colorSplit": "#272c31",
    "borderRadius": 8,
}
DEFAULT_TOKENS: dict[str, Any] = {
    "brandAppName": "Superset",
    "brandLogoAlt": "Apache Superset",
    "brandLogoUrl": "/static/assets/images/superset-logo-horiz.png",
    "brandLogoMargin": "18px 0",
    "brandLogoHref": "/",
    "brandLogoHeight": "24px",
    "brandSpinnerUrl": None,
    "brandSpinnerSvg": None,
    "fontUrls": [],
    "fontFamily": "Inter, Helvetica, Arial, sans-serif",
    "fontFamilyCode": "'IBM Plex Mono', 'Courier New', monospace",
    "transitionTiming": 0.3,
    "brandIconMaxWidth": 37,
    "fontSizeXS": "8",
    "fontSizeXXL": "28",
    "fontWeightNormal": "400",
    "fontWeightLight": "300",
    "fontWeightStrong": "500",
    "fontWeightBold": "700",
}

CATEGORICAL = [
    {
        "id": "harbor",
        "description": "Marketplace Lakehouse palette",
        "label": "Harbor",
        "isDefault": True,
        "colors": [
            "#2c71b7",
            "#d6781c",
            "#0f9b89",
            "#795dba",
            "#9e6128",
            "#3498bf",
            "#bb8d1c",
            "#c55b96",
        ],
    }
]
SEQUENTIAL = [
    {
        "id": "harbor_blue",
        "description": "Harbor blue, light to dark",
        "label": "Harbor blue",
        "isDefault": True,
        "isDiverging": False,
        "colors": [
            "#ecf1f7",
            "#cadbee",
            "#a7c4e5",
            "#82abda",
            "#5c93cf",
            "#337ac3",
            "#1762a9",
            "#024b89",
            "#003768",
        ],
    },
    {
        "id": "harbor_diverging",
        "description": "Harbor blue to orange with a grey midpoint",
        "label": "Harbor diverging",
        "isDefault": False,
        "isDiverging": True,
        "colors": [
            "#024884",
            "#3377be",
            "#80afe3",
            "#e8eaec",
            "#da9b6b",
            "#ad5d00",
            "#6c3803",
        ],
    },
]


@pytest.fixture
def load_config(monkeypatch: pytest.MonkeyPatch) -> Callable[[], ModuleType]:
    monkeypatch.setenv("SUPERSET_DATABASE_URI", "postgresql://u:p@h/db")
    monkeypatch.setenv("SUPERSET_SECRET_KEY", "k")
    monkeypatch.setenv("SUPERSET_DATA_ANCHOR", "2026-07-01")

    def load() -> ModuleType:
        spec = importlib.util.spec_from_file_location("superset_config_under_test", CONFIG)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return load


def test_harbor_is_the_only_default_categorical_scheme(
    load_config: Callable[[], ModuleType],
) -> None:
    assert load_config().EXTRA_CATEGORICAL_COLOR_SCHEMES == CATEGORICAL


def test_sequential_and_diverging_harbor_schemes(load_config: Callable[[], ModuleType]) -> None:
    schemes = load_config().EXTRA_SEQUENTIAL_COLOR_SCHEMES
    assert schemes == SEQUENTIAL
    assert [s["id"] for s in schemes if s["isDefault"]] == ["harbor_blue"]


@pytest.mark.parametrize(
    ("name", "algorithm", "tokens"),
    [("THEME_DEFAULT", "default", LIGHT_TOKENS), ("THEME_DARK", "dark", DARK_TOKENS)],
)
def test_theme_tokens_follow_harbor(
    load_config: Callable[[], ModuleType], name: str, algorithm: str, tokens: dict[str, Any]
) -> None:
    theme = getattr(load_config(), name)
    assert theme["algorithm"] == algorithm
    for key, value in {**DEFAULT_TOKENS, **tokens}.items():
        assert theme["token"][key] == value, key
    selection = "#fff5cf" if name == "THEME_DEFAULT" else "#5c4d1a"
    assert theme["token"]["colorEditorSelection"] == selection


@pytest.mark.parametrize("name", ["THEME_DEFAULT", "THEME_DARK"])
def test_line_override_is_an_object_for_every_series(
    load_config: Callable[[], ModuleType], name: str
) -> None:
    overrides = getattr(load_config(), name)["echartsOptionsOverridesByChartType"]
    series = overrides["echarts_timeseries_line"]["series"]
    assert isinstance(series, dict)
    assert series["lineStyle"]["width"] == 3
    assert series["smooth"] is True
    assert series["smoothMonotone"] == "x"
    assert series["showSymbol"] is False


def test_relative_time_anchor_comes_from_the_environment(
    load_config: Callable[[], ModuleType],
) -> None:
    module = load_config()
    assert module.DEFAULT_RELATIVE_START_TIME == "2026-07-01"
    assert module.DEFAULT_RELATIVE_END_TIME == "2026-07-01"


def test_relative_time_defaults_to_today_without_the_anchor(
    load_config: Callable[[], ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SUPERSET_DATA_ANCHOR")
    module = load_config()
    assert module.DEFAULT_RELATIVE_START_TIME == "today"
    assert module.DEFAULT_RELATIVE_END_TIME == "today"


def test_compose_passes_the_anchor_to_superset_and_its_mcp() -> None:
    services = yaml.safe_load(COMPOSE.read_text())["services"]
    for name in ("superset", "superset-mcp"):
        env = services[name]["environment"]
        if isinstance(env, list):
            env = dict(item.split("=", 1) for item in env)
        assert env["SUPERSET_DATA_ANCHOR"] == "${SUPERSET_DATA_ANCHOR:-2026-07-01}", name
