# Superset 6.1.0 with what the base image lacks: psycopg2 for the metadata database
# (postgres-meta), trino for the dashboard source (lake_ro) and fastmcp for the MCP endpoint
# (`superset mcp run`). The base is the digest of the image pulled by tag 6.1.0. Pins: psycopg2-binary
# as Superset's own `postgres` extra pins it; trino is the newest release that keeps SQLAlchemy
# 1.4; fastmcp is the newest release inside the 3.1 to 4.0 range of the `fastmcp` extra. The rest
# of what they pull in is pinned by constraints.txt.
FROM apache/superset:6.1.0@sha256:16b50bbef6648912a79e3293d418fefa743ce555d36c5af6b85d859119ed7f88

USER root
COPY constraints.txt /tmp/constraints.txt
RUN . /app/.venv/bin/activate \
 && uv pip install --no-cache -c /tmp/constraints.txt "psycopg2-binary==2.9.9" "trino==0.340.0" "fastmcp==3.4.11" \
 && rm /tmp/constraints.txt
USER superset
