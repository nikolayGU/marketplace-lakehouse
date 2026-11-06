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
