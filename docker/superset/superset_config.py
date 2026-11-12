"""Superset settings of the lakehouse stack: everything secret comes from the environment."""

import os

# Metadata database of Superset (postgres-meta, database `superset`).
SQLALCHEMY_DATABASE_URI = os.environ["SUPERSET_DATABASE_URI"]
SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]

# No usage reporting, no example dashboards (the default flag is read from the environment).
SCARF_ANALYTICS = False
LOAD_EXAMPLES = False

# One process cache is enough for a single gunicorn worker on a laptop.
CACHE_CONFIG = {"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 300}
DATA_CACHE_CONFIG = {"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 300}

# Keeps a careless chart or SQL Lab query from pulling the whole lake into 1280M of memory.
ROW_LIMIT = 10000
SQL_MAX_ROW = 10000
DISPLAY_MAX_ROW = 10000

# Links that the MCP service puts into its answers: Superset inside the compose network for the
# service itself, the published port for the person who opens a link.
SUPERSET_WEBSERVER_ADDRESS = "http://superset:8088"
WEBDRIVER_BASEURL = "http://superset:8088/"
WEBDRIVER_BASEURL_USER_FRIENDLY = "http://127.0.0.1:8088/"

# MCP service (profile bi, port 5008) runs every tool as this user. That is the local
# single-user mode, like Airflow without a login (D12): the ports are bound to BIND_IP=127.0.0.1.
# Any deployment reachable from outside the machine must set MCP_AUTH_ENABLED with a JWT
# provider instead and drop this line.
MCP_DEV_USERNAME = "admin"

# Harbor palette of docs/planning/20-superset-dashboard.md section 3.2: the default scheme of every
# chart, so no chart has to pick colours by hand.
EXTRA_CATEGORICAL_COLOR_SCHEMES = [
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

# Sequential and diverging schemes of the same palette; the blue ramp is the default for heatmaps.
EXTRA_SEQUENTIAL_COLOR_SCHEMES = [
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

# Last N days/months/quarter/year count from the first day of the month of the latest order
# (SUPERSET_DATA_ANCHOR); DATETIME("today") and calendar phrases would point past the Olist data.
DEFAULT_RELATIVE_START_TIME = os.environ.get("SUPERSET_DATA_ANCHOR", "today")
DEFAULT_RELATIVE_END_TIME = os.environ.get("SUPERSET_DATA_ANCHOR", "today")

# `series` is a dict on purpose: Superset merges the override with lodash mergeWith, a dict is
# merged into every series of the chart while a list would replace all of them.
_LINE_OVERRIDES = {
    "echarts_timeseries_line": {
        "series": {
            "lineStyle": {"width": 3},
            "smooth": True,
            "smoothMonotone": "x",
            "showSymbol": False,
        }
    }
}

# A theme replaces the whole Superset default, and importing superset here would be circular, so
# every default token is copied literally (Superset 6.1.0) and only the Harbor tokens differ.
THEME_DEFAULT = {
    "token": {
        "brandAppName": "Superset",
        "brandLogoAlt": "Apache Superset",
        "brandLogoUrl": "/static/assets/images/superset-logo-horiz.png",
        "brandLogoMargin": "18px 0",
        "brandLogoHref": "/",
        "brandLogoHeight": "24px",
        "brandSpinnerUrl": None,
        "brandSpinnerSvg": None,
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
        "colorEditorSelection": "#fff5cf",
    },
    "algorithm": "default",
    "echartsOptionsOverridesByChartType": _LINE_OVERRIDES,
}

# Dark twin built like the Superset default file does: light tokens as base, dark ones on top.
THEME_DARK = {
    **THEME_DEFAULT,
    "token": {
        **THEME_DEFAULT["token"],
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
        "colorEditorSelection": "#5c4d1a",
    },
    "algorithm": "dark",
}
