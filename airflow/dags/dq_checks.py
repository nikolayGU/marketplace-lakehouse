"""dq_checks: every 15 minutes, check silver against its own keys and against Postgres.

Fails the run: a primary key twice in a silver table; live row counts that differ from Postgres
while nothing is in flight (checks.at_rest) and CDC is not stalled; a value that differs between
the source and silver, or silver and gold, at rest (reconcile_values, W5-T04). A CDC that stands
(the source wrote and the slot moved no further, checks.cdc_state) is "in flight, no verdict" for
the source-silver comparisons and the gauge `lakehouse.dq.cdc_stalled` (W6-D9). Every value is
logged as a `dq <name>=<value>` line and sent to statsd-exporter as a `lakehouse.*` gauge
(lakehouse/metrics.py, observability/statsd/mapping.yml). Not exported: new quarantine rows,
a Modify gate of the owner (W4-D8).
"""

import json
import shlex
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from airflow.sdk import Variable, dag, task
from lakehouse import checks, metrics, reconcile, sql
from lakehouse.clients import postgres_rows, postgres_value, trino_rows, trino_value
from lakehouse.settings import (
    CDC_STATE_SEEN,
    LAST_BRONZE_SNAPSHOT,
    SILVER_KEYS,
    SOURCE_TABLES,
    Settings,
    dbt_command,
)

settings = Settings()
FRESHNESS_TARGET = "/tmp/dbt/freshness"


def export(*gauges: tuple[str, object, dict[str, str]]) -> None:
    """Send (name, value, tags) gauges to statsd-exporter; a failure is printed, not raised."""
    lines = [metrics.gauge_line(name, value, tags) for name, value, tags in gauges]
    metrics.send(lines, settings.statsd_host, settings.statsd_port)


@dag(
    schedule="*/15 * * * *",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=14),
    default_args={"execution_timeout": timedelta(minutes=10)},
    tags=["dq"],
)
def dq_checks() -> None:
    @task
    def silver_keys_unique() -> None:
        duplicates = {
            table: int(trino_value(settings, sql.duplicate_keys(table, key)))
            for table, key in SILVER_KEYS.items()
        }
        for table, count in duplicates.items():
            print(f"dq silver_duplicate_keys{{table={table}}}={count}")
        export(
            *(
                ("lakehouse.dq.silver_duplicate_keys", count, {"table": table})
                for table, count in duplicates.items()
            )
        )
        failed = {table: count for table, count in duplicates.items() if count}
        if failed:
            raise ValueError(f"silver holds a primary key more than once: {failed}")

    def _oldest_unmerged_age(latest: int | None, remembered: str | None) -> int | None:
        if latest is None or remembered is None or str(latest) == remembered:
            return None
        query = sql.oldest_unmerged_snapshot_age(remembered)
        return None if query is None else trino_value(settings, query)

    @task
    def cdc_progress() -> bool:
        """Whether CDC stands: the source wrote since the last run and the slot did not move."""
        rows = postgres_rows(settings, sql.CDC_PROGRESS)
        if not rows or rows[0][0] is None:
            raise RuntimeError("cannot read the write counter of schema shop")
        writes_now, flush_now = int(rows[0][0]), rows[0][1]
        before = checks.load_cdc_state(Variable.get(CDC_STATE_SEEN, default=None))
        stalled, kept = checks.cdc_state(writes_now, flush_now, before)
        Variable.set(CDC_STATE_SEEN, json.dumps(kept))
        print(f"dq cdc_stalled={int(stalled)} writes={writes_now} flush={flush_now}")
        print(f"dq cdc_before={before}")
        export(("lakehouse.dq.cdc_stalled", int(stalled), {}))
        return stalled

    @task
    def silver_matches_postgres(stalled: bool) -> None:
        rows = trino_rows(settings, sql.LATEST_BRONZE_SNAPSHOT)
        latest, committed_at = (int(rows[0][0]), rows[0][1]) if rows else (None, None)
        remembered = Variable.get(LAST_BRONZE_SNAPSHOT, default=None)
        postgres = {t: int(postgres_value(settings, sql.postgres_rows(t))) for t in SOURCE_TABLES}
        silver = {t: int(trino_value(settings, sql.silver_live_rows(t))) for t in SOURCE_TABLES}
        differences = checks.count_differences(postgres, silver)
        resting = checks.at_rest(latest, committed_at, remembered, datetime.now(UTC))
        outcome = checks.count_outcome(bool(differences), resting, stalled)
        print(f"dq reconcile_tables_differing={len(differences)} at_rest={resting}")
        age = _oldest_unmerged_age(latest, remembered)
        lag = checks.silver_lag_seconds(latest, remembered, age)
        print(f"dq silver_lag_seconds={lag}")
        at_rest = {"at_rest": str(resting).lower()}
        export(
            ("lakehouse.dq.reconcile_tables_differing", len(differences), at_rest),
            ("lakehouse.silver_lag_seconds", lag, {}),
        )
        for table, (source, lake) in differences.items():
            print(f"{table}: postgres {source}, silver {lake}")
        if outcome == "red":
            raise ValueError(f"silver differs from Postgres at rest: {differences}")
        if outcome == "in_flight":
            reason = "CDC stands" if stalled else "bronze or silver has not caught up yet"
            print(f"in flight: {reason}, no verdict")

    def _explain(table: str, keys: list[str]) -> dict[str, str]:
        """Why the first keys the source has are not in silver: quarantine, bronze, or neither."""
        shown = keys[: reconcile.REPORTED_KEYS]
        found: dict[str, set[str]] = {}
        for label, query in (
            ("quarantine", reconcile.quarantine_lookup_sql(table, shown)),
            ("bronze", reconcile.bronze_lookup_sql(table, shown)),
        ):
            ids = {str(r[0]) for r in trino_rows(settings, query)} if query else set()
            found[label] = {k for k in shown if k.split(":")[0] in ids}
        return reconcile.classify(shown, found["quarantine"], found["bronze"])

    @task
    def reconcile_values(stalled: bool) -> None:
        """Source against silver, and silver against gold, by value (W5-T04). Only at rest: with
        work in flight the layers differ for a reason that is not an error. A CDC that stands
        leaves out the source-silver pairs; silver-gold needs nothing from the source."""
        rows = trino_rows(settings, sql.LATEST_BRONZE_SNAPSHOT)
        latest, committed_at = (int(rows[0][0]), rows[0][1]) if rows else (None, None)
        remembered = Variable.get(LAST_BRONZE_SNAPSHOT, default=None)
        resting = checks.at_rest(latest, committed_at, remembered, datetime.now(UTC))
        if not resting:
            print("dq reconcile_in_flight=1")
            print("in flight: bronze or silver has not caught up yet, no verdict")
            export(("lakehouse.dq.reconcile_in_flight", 1, {}))
            return

        started = time.time()
        verdicts: list[reconcile.Verdict] = []
        skip_source = checks.skip_source_values(resting, stalled)
        if skip_source:
            print("dq reconcile_in_flight=1")
            print("in flight: CDC stands, the source-silver pairs wait, no verdict on them")
        gauges: list[tuple[str, object, dict[str, str]]] = [
            ("lakehouse.dq.reconcile_in_flight", int(skip_source), {})
        ]
        for table in () if skip_source else SOURCE_TABLES:
            verdict = reconcile.compare(
                "source_silver",
                table,
                postgres_value(settings, reconcile.fingerprint_sql_postgres(table)),
                trino_value(settings, reconcile.fingerprint_sql_trino(table)),
                lambda t=table: dict(postgres_rows(settings, reconcile.pairs_sql_postgres(t))),
                lambda t=table: dict(trino_rows(settings, reconcile.pairs_sql_trino(t))),
                explain=lambda keys, t=table: _explain(t, keys),
            )
            verdicts.append(verdict)
            gauges += [
                (
                    "lakehouse.dq.reconcile_rows",
                    verdict.rows_left,
                    {"layer": "source", "table": table},
                ),
                (
                    "lakehouse.dq.reconcile_rows",
                    verdict.rows_right,
                    {"layer": "silver", "table": table},
                ),
            ]

        # Gold is built by dbt after the merge: it is compared once it has caught up with silver.
        gold_updated = trino_value(settings, reconcile.GOLD_UPDATED)
        silver_updated = trino_value(settings, reconcile.SILVER_UPDATED)
        gold_ready = reconcile.gold_at_rest(gold_updated, silver_updated)
        # The verdict timestamp moves either way: this tells whether it covered gold too.
        gauges.append(("lakehouse.dq.reconcile_gold_compared", int(gold_ready), {}))
        if gold_ready:
            for gold in reconcile.GOLD_PAIRS:
                verdict = reconcile.compare(
                    "silver_gold",
                    gold,
                    trino_value(settings, reconcile.gold_silver_sql_trino(gold)),
                    trino_value(settings, reconcile.gold_sql_trino(gold)),
                    lambda g=gold: dict(
                        trino_rows(settings, reconcile.gold_pairs_sql_trino(g, "silver"))
                    ),
                    lambda g=gold: dict(
                        trino_rows(settings, reconcile.gold_pairs_sql_trino(g, "gold"))
                    ),
                )
                verdicts.append(verdict)
                gauges.append(
                    (
                        "lakehouse.dq.reconcile_rows",
                        verdict.rows_right,
                        {"layer": "gold", "table": gold},
                    )
                )
            customers_silver = int(trino_value(settings, reconcile.SILVER_CUSTOMERS_WITH_ORDERS))
            customers_gold = int(trino_value(settings, reconcile.GOLD_CUSTOMERS))
            customers = reconcile.Verdict(
                "silver_gold", "dim_customers", customers_silver, customers_gold
            )
            if customers_silver != customers_gold:
                customers.changed = ["row count"]
            verdicts.append(customers)
            gauges.append(
                (
                    "lakehouse.dq.reconcile_rows",
                    customers_gold,
                    {"layer": "gold", "table": "dim_customers"},
                )
            )
        else:
            print("gold has not caught up with silver: the silver-gold pairs wait for dbt_build")

        for verdict in verdicts:
            tags = {"pair": verdict.pair, "table": verdict.table}
            label = f"{verdict.pair},{verdict.table}"
            print(f"dq reconcile_values_differing{{{label}}}={len(verdict.changed)}")
            print(
                f"dq reconcile_keys_missing{{{label}}}="
                f"{len(verdict.only_left)}+{len(verdict.only_right)}"
            )
            gauges += [
                ("lakehouse.dq.reconcile_values_differing", len(verdict.changed), tags),
                (
                    "lakehouse.dq.reconcile_keys_missing",
                    len(verdict.only_left),
                    {**tags, "side": "right"},
                ),
                (
                    "lakehouse.dq.reconcile_keys_missing",
                    len(verdict.only_right),
                    {**tags, "side": "left"},
                ),
            ]
        gauges.append(("lakehouse.dq.reconcile_verdict_timestamp_seconds", time.time(), {}))
        export(*gauges)
        print(f"dq reconcile_seconds={time.time() - started:.1f}")

        wrong = [v for v in verdicts if not v.clean]
        if wrong:
            raise ValueError("values differ at rest:\n" + "\n".join(v.summary() for v in wrong))

    @task
    def report() -> None:
        lsn_repeats = trino_value(settings, sql.LSN_REPEATS_LAST_HOUR)
        noop_updates = trino_value(settings, sql.NOOP_UPDATES_LAST_HOUR)
        print(f"dq lsn_repeats_last_hour={lsn_repeats}")
        print(f"dq noop_updates_last_hour={noop_updates}")
        print(f"dq quarantined_last_hour={trino_value(settings, sql.QUARANTINED_LAST_HOUR)}")
        gauges: list[tuple[str, object, dict[str, str]]] = [
            ("lakehouse.dq.lsn_repeats_last_hour", lsn_repeats, {}),
            ("lakehouse.dq.noop_updates_last_hour", noop_updates, {}),
            ("lakehouse.dq.last_run_timestamp_seconds", time.time(), {}),
        ]
        for table in SILVER_KEYS:
            seconds = trino_value(settings, sql.freshness_seconds(table))
            print(f"dq silver_freshness_seconds{{table={table}}}={seconds}")
            if table in SOURCE_TABLES:  # quarantine has no row in the Prometheus series
                tags = {"layer": "silver", "table": table}
                gauges.append(("lakehouse.table_freshness_seconds", seconds, tags))
        for table, seconds in trino_rows(settings, sql.BRONZE_FRESHNESS):
            print(f"dq bronze_freshness_seconds{{table={table}}}={seconds}")
            tags = {"layer": "bronze", "table": table}
            gauges.append(("lakehouse.table_freshness_seconds", seconds, tags))
        export(*gauges)

    @task
    def dbt_source_freshness() -> None:
        # Exit code 1 is a stale source (no traffic, logged) or a freshness query that failed;
        # only sources.json tells them apart. A target path of its own: dbt_build may run now.
        sources_path = Path(FRESHNESS_TARGET) / "sources.json"
        sources_path.unlink(missing_ok=True)  # a run killed early must not read the last one
        result = subprocess.run(
            shlex.split(dbt_command("source freshness", target_path=FRESHNESS_TARGET)),
            capture_output=True,
            text=True,
            check=False,
        )
        print(result.stdout + result.stderr)
        print(f"dq dbt_source_freshness_exit_code={result.returncode}")
        export(("lakehouse.dq.dbt_source_freshness_exit_code", result.returncode, {}))
        if result.returncode not in (0, 1):  # negative when a signal (OOM) killed dbt
            raise RuntimeError(f"dbt source freshness failed, exit code {result.returncode}")
        sources = json.loads(sources_path.read_text())
        failed = checks.freshness_query_failures(sources)
        if failed:
            raise RuntimeError(f"the freshness query failed for {failed}")

    stalled = cdc_progress()
    [
        silver_keys_unique(),
        silver_matches_postgres(stalled),
        reconcile_values(stalled),
        report(),
        dbt_source_freshness(),
    ]


dq_checks()
