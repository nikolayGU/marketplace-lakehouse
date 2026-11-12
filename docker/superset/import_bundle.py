"""Import the Marketplace bundle into Superset, overwriting datasets, charts and the dashboard.

`superset import-dashboards` imports the datasets and charts of a bundle with overwrite=False
(only the dashboard is overwritten), and the CLI has no chart import with overwrite. A metric,
column or chart changed in the bundle would never reach an instance that already has the object.
This script calls the import commands itself, with overwrite=True, in dependency order.

Each command checks the `type` in metadata.yaml against its own model (SqlaTable, Slice,
Dashboard), so every command gets its own copy of the bundle with that type. The database is
imported by all three, as the files of the bundle sit in each copy.

The Superset CLI logs an import error and exits 0; here any error exits 1, so `superset-init`
fails instead of reporting a dashboard that was not imported. Superset is imported inside main:
the module is also read on hosts without it. The command modules need an initialised app, so they
are imported inside its context.
"""

import logging
import sys
from pathlib import Path

import yaml

logger = logging.getLogger("import_bundle")


def _read_bundle(bundle: Path) -> dict[str, str]:
    return {
        path.relative_to(bundle).as_posix(): path.read_text()
        for path in sorted(bundle.rglob("*"))
        if path.is_file()
    }


def _with_type(files: dict[str, str], model_type: str) -> dict[str, str]:
    metadata = yaml.safe_load(files["metadata.yaml"])
    metadata = {"version": "1.0.0", "type": model_type, "timestamp": metadata["timestamp"]}
    return {**files, "metadata.yaml": yaml.safe_dump(metadata)}


def main(bundle: Path) -> None:
    files = _read_bundle(bundle)
    try:
        # pylint: disable=import-outside-toplevel
        from superset.app import create_app

        app = create_app()
        with app.app_context():
            from superset import security_manager
            from superset.commands.chart.importers.v1 import ImportChartsCommand
            from superset.commands.dashboard.importers.v1 import ImportDashboardsCommand
            from superset.commands.dataset.importers.v1 import ImportDatasetsCommand
            from superset.utils.core import override_user

            with override_user(security_manager.find_user(username="admin")):
                ImportDatasetsCommand(_with_type(files, "SqlaTable"), overwrite=True).run()
                ImportChartsCommand(_with_type(files, "Slice"), overwrite=True).run()
                ImportDashboardsCommand(_with_type(files, "Dashboard"), overwrite=True).run()
    except Exception:
        logger.exception("importing the bundle %s failed", bundle)
        sys.exit(1)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
