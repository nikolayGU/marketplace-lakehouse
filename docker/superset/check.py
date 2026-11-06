"""Live check of the Marketplace dashboard: every chart answers through the REST API with rows.

Run inside the superset container (the admin password is in its environment):
    docker compose exec superset python /app/check.py
Prints `<chart>: <rows> rows` per chart; exit code 1 if a chart fails, is empty or none exists.
"""

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("SUPERSET_URL", "http://localhost:8088")
DASHBOARD = "marketplace"
TIMEOUT = 120


def call(path: str, token: str | None = None, body: dict | None = None) -> dict:
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(
            f"HTTP {error.code}: {error.read()[:200].decode(errors='replace')}"
        ) from error


def login() -> str:
    credentials = {
        "username": "admin",
        "password": os.environ["SUPERSET_ADMIN_PASSWORD"],
        "provider": "db",
        "refresh": False,
    }
    return str(call("/api/v1/security/login", body=credentials)["access_token"])


def chart_rows(token: str, chart_id: int) -> int:
    result = call(f"/api/v1/chart/{chart_id}/data/", token)["result"][0]
    if result.get("error"):
        raise RuntimeError(str(result["error"]))
    return int(result["rowcount"])


def main() -> int:
    try:
        token = login()
        charts = call(f"/api/v1/dashboard/{DASHBOARD}/charts", token)["result"]
    except (KeyError, OSError, RuntimeError) as error:
        print(f"cannot read the dashboard: {type(error).__name__}", file=sys.stderr)
        return 1
    if not charts:
        print(f"dashboard {DASHBOARD} has no charts", file=sys.stderr)
        return 1
    failed = 0
    for chart in sorted(charts, key=lambda c: c["id"]):
        name = chart["slice_name"]
        try:
            rows = chart_rows(token, chart["id"])
        except (urllib.error.URLError, KeyError, OSError, RuntimeError, ValueError) as error:
            print(f"{name}: FAILED {type(error).__name__}: {str(error)[:200]}")
            failed += 1
            continue
        print(f"{name}: {rows} rows")
        failed += rows == 0
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
