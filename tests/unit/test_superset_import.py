"""The Superset bundle import must overwrite datasets, charts and the dashboard, and fail loudly.

`superset import-dashboards` imports datasets and charts with overwrite=False, so a metric added
to the bundle never reaches an existing instance. `docker/superset/import_bundle.py` calls the
import commands itself. It runs inside the Superset image, so these tests read it with `ast` and
never import superset.
"""

import ast
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "docker" / "superset" / "import_bundle.py"
INIT = REPO / "docker" / "superset" / "init.sh"
COMPOSE = REPO / "docker" / "compose.yaml"
COMMANDS = ["ImportDatasetsCommand", "ImportChartsCommand", "ImportDashboardsCommand"]


def _main() -> ast.FunctionDef:
    tree = ast.parse(SCRIPT.read_text())
    (main,) = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"]
    return main


def _command_runs() -> list[tuple[str, ast.Call]]:
    """(command name, constructor call) for every `Command(...).run()` in main, in source order."""
    runs = []
    for node in ast.walk(_main()):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"
            and isinstance(node.func.value, ast.Call)
            and isinstance(node.func.value.func, ast.Name)
            and node.func.value.func.id in COMMANDS
        ):
            runs.append((node.func.value.func.id, node.func.value))
    return sorted(runs, key=lambda run: (run[1].lineno, run[1].col_offset))


def test_bundle_import_overwrites_datasets_charts_dashboard_in_order() -> None:
    runs = _command_runs()

    assert [name for name, _ in runs] == COMMANDS
    for name, call in runs:
        overwrite = [k.value for k in call.keywords if k.arg == "overwrite"]
        assert len(overwrite) == 1, name
        assert isinstance(overwrite[0], ast.Constant) and overwrite[0].value is True, name


def test_each_import_gets_its_own_metadata_type() -> None:
    expected = {
        "ImportDatasetsCommand": "SqlaTable",
        "ImportChartsCommand": "Slice",
        "ImportDashboardsCommand": "Dashboard",
    }

    for name, call in _command_runs():
        (argument,) = call.args
        assert isinstance(argument, ast.Call), name
        assert ast.unparse(argument.func) == "_with_type", name
        assert len(argument.args) == 2, name
        model_type = argument.args[1]
        assert isinstance(model_type, ast.Constant), name
        assert model_type.value == expected[name], name
    assert "metadata.yaml" in SCRIPT.read_text()


def test_import_failure_exits_non_zero() -> None:
    tries = [n for n in ast.walk(_main()) if isinstance(n, ast.Try)]
    exits = [
        n
        for t in tries
        for h in t.handlers
        for n in ast.walk(h)
        if isinstance(n, ast.Call) and ast.unparse(n.func) == "sys.exit"
    ]

    assert exits
    for call in exits:
        (code,) = call.args
        assert isinstance(code, ast.Constant), ast.unparse(call)
        assert isinstance(code.value, int) and code.value != 0, ast.unparse(call)


def test_init_runs_the_bundle_import() -> None:
    text = INIT.read_text()

    assert '/init/import_bundle.py "$BUNDLE_DIR"' in text
    assert "import-dashboards" not in text


def test_superset_init_mounts_the_import_script() -> None:
    service: dict[str, Any] = yaml.safe_load(COMPOSE.read_text())["services"]["superset-init"]

    assert "./superset/import_bundle.py:/init/import_bundle.py:ro" in service["volumes"]


def test_commands_are_imported_inside_the_app_context() -> None:
    """Command modules need an initialised app: only `create_app` may be imported before it."""
    main = _main()
    (context,) = [
        n
        for n in ast.walk(main)
        if isinstance(n, ast.With)
        and any(
            isinstance(i.context_expr, ast.Call)
            and ast.unparse(i.context_expr.func).endswith("app_context")
            for i in n.items
        )
    ]
    inside = {id(n) for stmt in context.body for n in ast.walk(stmt)}
    imports = [n for n in ast.walk(main) if isinstance(n, ast.ImportFrom)]
    before = [n for n in imports if id(n) not in inside]
    within = {n.module for n in imports if id(n) in inside}

    assert [(n.module, [a.name for a in n.names]) for n in before] == [
        ("superset.app", ["create_app"])
    ]
    assert "superset" in within and "superset.utils.core" in within
    for command in ("dataset", "chart", "dashboard"):
        assert f"superset.commands.{command}.importers.v1" in within
