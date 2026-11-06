"""File-based access control in Trino: `grafana` and `superset` read marts of lake_ro.gold only.

Before access control every Trino user could do everything. The rules file must keep that for
dbt, Airflow, the CLI (`trino`) and any new user, and take it away from the Grafana datasource,
whose plugin runs any SQL a panel or Explore sends.

These tests check the rules file and the catalog files against the model of the Trino documentation
(https://trino.io/docs/483/security/file-system-access-control.html): rules go top down, the first
match applies, no match means deny, a missing section means allow (system_information excepted).
They do not run Trino: its behavior is proven by the live step (OPERATIONS.md, "Access control").

Two limits of the documentation shape the design. File-based access control has no privileges for
table procedures, so `ALTER TABLE ... EXECUTE expire_snapshots` is allowed whatever the rules say;
`grafana` therefore reads through the catalog `lake_ro` with `iceberg.security=read_only`, which
denies table procedures, DDL and DML for everyone. And `system.builtin` functions and the system
tables of `information_schema` are outside the rules, so nothing here asserts about them.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).parents[2]
ETC = REPO / "docker" / "trino" / "etc"
PROPERTIES = ETC / "access-control.properties"
CATALOGS = ETC / "catalog"
GRAFANA = "grafana"
SUPERSET = "superset"
READ_ONLY_CATALOG = "lake_ro"
OTHERS = ["dbt", "airflow", "trino", "dashboard-check", "a-new-client"]
ALL_TABLE_PRIVILEGES = {"SELECT", "INSERT", "DELETE", "UPDATE", "OWNERSHIP", "GRANT_SELECT"}
GOLD_TABLES = ["fct_orders", "mart_daily_sales", "fct_order_items", "dim_customers"]
# dbt views over silver (they run with the owner's rights) and the seed: hidden from the datasource.
HIDDEN_GOLD_TABLES = ["stg_orders", "stg_reviews", "int_daily_sales", "int_orders_enriched"]
DBT = REPO / "dbt"
EXPOSED_PREFIXES = ("fct_", "dim_", "mart_")


def _read_properties(path: Path) -> dict[str, str]:
    pairs = (
        line.split("=", 1)
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    return {k.strip(): v.strip() for k, v in pairs}


def _properties() -> dict[str, str]:
    return _read_properties(PROPERTIES)


def _rules() -> dict[str, Any]:
    path = ETC / Path(_properties()["security.config-file"]).name
    rules: dict[str, Any] = json.loads(path.read_text())
    return rules


def _matches(rule: dict[str, Any], **fields: str) -> bool:
    return all(re.fullmatch(rule.get(key, ".*"), value) for key, value in fields.items())


def _first(section: str, **fields: str) -> dict[str, Any] | None:
    for rule in _rules().get(section, []):
        if _matches(rule, **fields):
            return rule  # type: ignore[no-any-return]
    return None


def catalog_access(user: str, catalog: str) -> str:
    rule = _first("catalogs", user=user, catalog=catalog)
    return str(rule["allow"]) if rule else "none"


def schema_owner(user: str, catalog: str, schema: str) -> bool:
    rule = _first("schemas", user=user, catalog=catalog, schema=schema)
    return bool(rule and rule.get("owner", False))


def table_privileges(user: str, catalog: str, schema: str, table: str) -> set[str]:
    rule = _first("tables", user=user, catalog=catalog, schema=schema, table=table)
    return set(rule["privileges"]) if rule else set()


def can_call(user: str, catalog: str, schema: str, procedure: str) -> bool:
    rule = _first("procedures", user=user, catalog=catalog, schema=schema, procedure=procedure)
    return bool(rule and "EXECUTE" in rule["privileges"])


def can_use_function(user: str, catalog: str, schema: str, function: str) -> bool:
    rule = _first("functions", user=user, catalog=catalog, schema=schema, function=function)
    return bool(rule and "EXECUTE" in rule["privileges"])


def query_allowed(user: str, action: str, owner: str = "someone-else") -> bool:
    """Execute looks only at rules without `queryOwner`; view and kill at all; first match wins."""
    for rule in _rules().get("queries", []):
        if action == "execute":
            if "queryOwner" not in rule and _matches(rule, user=user):
                return "execute" in rule["allow"]
        elif _matches(rule, user=user, queryOwner=owner):
            return action in rule["allow"]
    return False


def system_information(user: str) -> set[str]:
    rule = _first("system_information", user=user)
    return set(rule["allow"]) if rule else set()


def test_properties_name_the_file_plugin_and_an_existing_rules_file() -> None:
    props = _properties()
    assert props["access-control.name"] == "file"
    config_file = Path(props["security.config-file"])
    assert config_file.parent == Path("/etc/trino")
    assert (ETC / config_file.name).is_file()


def test_etc_is_mounted_whole_so_no_compose_change_is_needed() -> None:
    compose = (REPO / "docker" / "compose.yaml").read_text()
    assert "- ./trino/etc:/etc/trino:ro" in compose


def test_rules_file_sections_are_the_known_ones() -> None:
    # Session property and impersonation sections are allowed: grafana needs no session property
    # limit (with no such section every user may set any), and the evaluator below does not model
    # them.
    known = {
        "catalogs",
        "schemas",
        "tables",
        "functions",
        "procedures",
        "queries",
        "system_information",
        "system_session_properties",
        "catalog_session_properties",
        "impersonation",
        "principals",
        "authorization",
    }
    assert set(_rules()) <= known


@pytest.mark.parametrize("table", GOLD_TABLES)
def test_grafana_selects_gold_of_the_read_only_catalog_and_nothing_else_there(table: str) -> None:
    assert table_privileges(GRAFANA, READ_ONLY_CATALOG, "gold", table) == {"SELECT"}


@pytest.mark.parametrize("table", [*HIDDEN_GOLD_TABLES, "category_translation"])
def test_grafana_cannot_select_staging_and_intermediate_views_or_the_seed(table: str) -> None:
    # A dbt view reads silver as its owner, so SELECT on stg_* would hand grafana the silver rows.
    assert table_privileges(GRAFANA, READ_ONLY_CATALOG, "gold", table) == set()


def _gold_object_names() -> dict[str, str]:
    """Every object dbt builds in gold: model file stems and seed file stems, by layer."""
    models = DBT / "models"
    names = {p.stem: p.relative_to(models).parts[0] for p in models.rglob("*.sql")}
    names |= {p.stem: "seeds" for p in (DBT / "seeds").glob("*.csv")}
    return names


def test_grafana_reads_exactly_the_marts_layer_of_every_dbt_object() -> None:
    # The rule is a table-name pattern, so a new model is exposed by its prefix alone: this pins
    # layer and prefix together (marts: fct_, dim_, mart_; staging, intermediate and seeds: hidden).
    names = _gold_object_names()
    assert {"stg_orders", "int_daily_sales", "fct_orders", "category_translation"} <= set(names)
    for name, layer in names.items():
        expected = {"SELECT"} if layer == "marts" else set()
        assert table_privileges(GRAFANA, READ_ONLY_CATALOG, "gold", name) == expected, name
        assert name.startswith(EXPOSED_PREFIXES) == (layer == "marts"), name


@pytest.mark.parametrize("schema", ["silver", "bronze", "gold_staging"])
def test_grafana_has_no_privileges_outside_gold(schema: str) -> None:
    assert table_privileges(GRAFANA, READ_ONLY_CATALOG, schema, "orders") == set()


def test_grafana_sees_only_the_read_only_catalog() -> None:
    assert catalog_access(GRAFANA, READ_ONLY_CATALOG) == "read-only"
    for catalog in ["lake", "system", "memory", "tpch", "a-new-catalog"]:
        assert catalog_access(GRAFANA, catalog) == "none", catalog


def test_grafana_has_no_table_privilege_in_the_writable_lake_or_in_system() -> None:
    for schema in ["gold", "silver", "bronze"]:
        assert table_privileges(GRAFANA, "lake", schema, "fct_orders") == set()
    assert table_privileges(GRAFANA, "system", "runtime", "queries") == set()


@pytest.mark.parametrize("schema", ["gold", "silver", "bronze", "brand_new_schema"])
@pytest.mark.parametrize("catalog", ["lake", READ_ONLY_CATALOG])
def test_grafana_owns_no_schema(catalog: str, schema: str) -> None:
    assert not schema_owner(GRAFANA, catalog, schema)


def test_grafana_calls_no_procedure_and_no_catalog_function() -> None:
    # Table procedures (ALTER TABLE ... EXECUTE) are not covered by the rules: lake_ro is read_only.
    for catalog, schema, procedure in [
        ("lake", "system", "unregister_table"),
        ("lake", "system", "register_table"),
        (READ_ONLY_CATALOG, "system", "unregister_table"),
        (READ_ONLY_CATALOG, "system", "register_table"),
        ("system", "runtime", "kill_query"),
    ]:
        assert not can_call(GRAFANA, catalog, schema, procedure)
    for catalog in ["lake", READ_ONLY_CATALOG]:
        assert not can_use_function(GRAFANA, catalog, "system", "table_changes")


def test_grafana_runs_queries_but_neither_views_nor_kills_foreign_ones() -> None:
    assert query_allowed(GRAFANA, "execute")
    for owner in ["dbt", "airflow", "trino"]:
        assert not query_allowed(GRAFANA, "view", owner)
        assert not query_allowed(GRAFANA, "kill", owner)


def test_grafana_has_no_system_information_access() -> None:
    assert system_information(GRAFANA) == set()


def test_the_read_only_catalog_is_lake_with_iceberg_security_read_only() -> None:
    # Only iceberg.security=read_only stops ALTER TABLE ... EXECUTE: the connector's
    # ReadOnlyAccessControl denies every check it does not allow, table procedures included.
    lake = _read_properties(CATALOGS / "lake.properties")
    read_only = _read_properties(CATALOGS / f"{READ_ONLY_CATALOG}.properties")

    assert read_only.pop("iceberg.security") == "read_only"
    assert "iceberg.security" not in lake
    assert read_only == lake


def test_the_read_only_catalog_takes_its_secrets_from_the_environment() -> None:
    read_only = _read_properties(CATALOGS / f"{READ_ONLY_CATALOG}.properties")
    secrets = {k: v for k, v in read_only.items() if re.search(r"key|secret|password", k)}

    assert secrets
    assert all(re.fullmatch(r"\$\{ENV:\w+\}", v) for v in secrets.values()), secrets


def test_rules_are_applied_by_restarting_trino_not_by_a_refresh_period() -> None:
    # A rule edit that applies silently on a bind-mounted file would skip the restart gate.
    assert "security.refresh-period" not in _properties()


@pytest.mark.parametrize("user", OTHERS)
@pytest.mark.parametrize("table", HIDDEN_GOLD_TABLES + GOLD_TABLES)
def test_other_clients_keep_every_privilege_on_every_gold_table(user: str, table: str) -> None:
    for catalog in ["lake", READ_ONLY_CATALOG]:
        assert table_privileges(user, catalog, "gold", table) == ALL_TABLE_PRIVILEGES


@pytest.mark.parametrize("user", OTHERS)
@pytest.mark.parametrize("schema", ["bronze", "silver", "gold"])
def test_other_clients_keep_every_table_privilege_in_lake(user: str, schema: str) -> None:
    assert catalog_access(user, "lake") == "all"
    assert table_privileges(user, "lake", schema, "orders") == ALL_TABLE_PRIVILEGES
    assert table_privileges(user, "lake", schema, "orders$snapshots") == ALL_TABLE_PRIVILEGES


@pytest.mark.parametrize("user", OTHERS)
def test_other_clients_keep_system_and_schema_ownership(user: str) -> None:
    assert catalog_access(user, "system") == "all"
    for schema in ["bronze", "silver", "gold", "gold_staging"]:
        assert schema_owner(user, "lake", schema)


@pytest.mark.parametrize("user", OTHERS)
def test_other_clients_keep_procedures_and_functions(user: str) -> None:
    assert can_call(user, "lake", "system", "unregister_table")
    assert can_call(user, "system", "runtime", "kill_query")
    assert can_use_function(user, "lake", "system", "table_changes")


@pytest.mark.parametrize("user", OTHERS)
def test_other_clients_keep_query_management(user: str) -> None:
    for action in ["execute", "view", "kill"]:
        assert query_allowed(user, action, owner="grafana")
        assert query_allowed(user, action, owner="airflow")


@pytest.mark.parametrize("user", OTHERS)
def test_other_clients_keep_system_information(user: str) -> None:
    assert system_information(user) == {"read", "write"}


def test_a_user_named_like_grafana_is_not_matched_by_prefix() -> None:
    gold = (READ_ONLY_CATALOG, "gold", "fct_orders")
    assert table_privileges("grafana-admin", *gold) == ALL_TABLE_PRIVILEGES
    assert table_privileges("grafana", *gold) == {"SELECT"}
    assert catalog_access("grafana-admin", "lake") == "all"


@pytest.mark.parametrize("table", GOLD_TABLES)
def test_superset_selects_gold_marts_of_the_read_only_catalog(table: str) -> None:
    assert table_privileges(SUPERSET, READ_ONLY_CATALOG, "gold", table) == {"SELECT"}


def test_superset_has_exactly_the_rights_of_grafana() -> None:
    probes = [
        (catalog, schema, table)
        for catalog in ["lake", READ_ONLY_CATALOG, "system", "memory"]
        for schema in ["gold", "silver", "bronze", "runtime", "brand_new_schema"]
        for table in [*GOLD_TABLES, *HIDDEN_GOLD_TABLES, "category_translation", "orders"]
    ]
    for catalog, schema, table in probes:
        assert table_privileges(SUPERSET, catalog, schema, table) == table_privileges(
            GRAFANA, catalog, schema, table
        ), (catalog, schema, table)
        assert schema_owner(SUPERSET, catalog, schema) == schema_owner(GRAFANA, catalog, schema)
        assert can_call(SUPERSET, catalog, schema, "register_table") == can_call(
            GRAFANA, catalog, schema, "register_table"
        )
        assert can_use_function(SUPERSET, catalog, schema, "table_changes") == can_use_function(
            GRAFANA, catalog, schema, "table_changes"
        )
    for catalog in ["lake", READ_ONLY_CATALOG, "system", "memory", "a-new-catalog"]:
        assert catalog_access(SUPERSET, catalog) == catalog_access(GRAFANA, catalog), catalog
    assert system_information(SUPERSET) == system_information(GRAFANA) == set()
    for action in ["execute", "view", "kill"]:
        assert query_allowed(SUPERSET, action, "dbt") == query_allowed(GRAFANA, action, "dbt")


def test_superset_can_only_select_and_only_in_the_read_only_catalog() -> None:
    assert catalog_access(SUPERSET, READ_ONLY_CATALOG) == "read-only"
    assert catalog_access(SUPERSET, "lake") == "none"
    for table in [*GOLD_TABLES, *HIDDEN_GOLD_TABLES]:
        assert table_privileges(SUPERSET, "lake", "gold", table) == set()
    assert not query_allowed(SUPERSET, "kill", "dbt")


def test_a_user_named_like_superset_is_not_matched_by_prefix() -> None:
    gold = (READ_ONLY_CATALOG, "gold", "fct_orders")
    assert table_privileges("superset-admin", *gold) == ALL_TABLE_PRIVILEGES
    assert table_privileges("superset", *gold) == {"SELECT"}
