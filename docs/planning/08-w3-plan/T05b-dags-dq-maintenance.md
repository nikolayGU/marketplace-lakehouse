# W3-T05b DAG `dq_checks` и `iceberg_maintenance` (W3-T05, коммит 2)

> До первого шага прочитай `README.md` этой папки: протокол, стоп-условия, отчёт.

| | |
|---|---|
| Спека | `07-w3-spec.md`, карточка W3-T05; решения D10, D11 |
| Коммит | `orchestrate: dq_checks and iceberg_maintenance dags` |
| Оценка | A: 1 ч; B: 1 ч и сутки наблюдения |
| Часть A | любая среда |
| Часть B | только локально; порция реплея 60 с |

## Цель

`dq_checks` раз в 15 минут валит DAG на дубле ключа в silver и на расхождении silver с Postgres в покое, остальное пишет в лог строками `dq <name>=<value>` (экспорт в Prometheus это W4-T03). `iceberg_maintenance` раз в сутки делает `optimize` таблиц silver через Trino в одном pool с merge.

## Вход

```bash
git log --oneline -1                     # коммит W3-T05a
ls airflow/dags                          # dbt_build.py, lakehouse, silver_upsert.py
uv run pytest tests/unit/test_dags.py -q | tail -1   # 9 passed
```

## Файлы

- Создать: `airflow/dags/dq_checks.py`, `airflow/dags/iceberg_maintenance.py`.
- Перезаписать целиком: `airflow/dags/lakehouse/checks.py`, `airflow/dags/lakehouse/sql.py`, `airflow/dags/lakehouse/clients.py`, `tests/unit/test_dags.py`, `airflow/README.md`.
- Изменить: `airflow/dags/lakehouse/settings.py`, `OPERATIONS.md`, `DECISIONS.md`, `ARCHITECTURE.md`.

## Часть A. Код

### A1. Тесты первым

Новые проверки: ключи silver равны `x-primary-key` контрактов; таблица входов «покой или в пути»; список расходящихся таблиц.

<!-- file: tests/unit/test_dags.py -->
```python
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]
from lakehouse import checks
from lakehouse.settings import (
    SILVER_KEYS,
    SPARK_SILVER_ENV,
    SPARK_SILVER_SECRETS,
    dbt_command,
    spark_silver_environment,
)

REPO = Path(__file__).resolve().parents[2]


def spark_silver_compose_env() -> dict[str, str]:
    compose = yaml.safe_load((REPO / "docker" / "compose.yaml").read_text())
    return dict(compose["services"]["spark-silver"]["environment"])


def airflow_env() -> dict[str, str]:
    pairs = {}
    for line in (REPO / "docker" / "airflow" / "airflow.env").read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and not line.startswith("#"):
            pairs[key] = value
    return pairs


def test_dag_passes_every_key_compose_gives_spark_silver() -> None:
    # A key compose adds to spark-silver and the DAG forgets: Airflow's silver run would differ
    # from make silver, or go to another catalog.
    assert set(SPARK_SILVER_ENV) == set(spark_silver_compose_env())


def test_airflow_env_carries_spark_silver_values_unchanged() -> None:
    compose_env = spark_silver_compose_env()
    passed = airflow_env()

    assert {key: passed.get(key) for key in compose_env} == compose_env


def test_secrets_go_to_private_environment_only() -> None:
    environ = {key: f"value of {key}" for key in SPARK_SILVER_ENV}

    public, private = spark_silver_environment(environ)

    assert set(private) == set(SPARK_SILVER_SECRETS)
    assert set(public) | set(private) == set(SPARK_SILVER_ENV)
    assert not set(public) & set(private)


def test_missing_key_fails_at_parse_time() -> None:
    environ = {key: "x" for key in SPARK_SILVER_ENV if key != "S3_SECRET_KEY"}

    with pytest.raises(KeyError, match="S3_SECRET_KEY"):
        spark_silver_environment(environ)


def test_silver_keys_are_the_primary_keys_of_the_contracts() -> None:
    contracts = {
        path.stem: json.loads(path.read_text())["x-primary-key"]
        for path in (REPO / "contracts" / "silver").glob("*.json")
    }

    assert {t: list(k) for t, k in SILVER_KEYS.items() if t != "quarantine"} == contracts


@pytest.mark.parametrize(
    ("latest", "remembered", "expected"),
    [
        (42, None, 42),  # silver_upsert never ran
        (42, "41", 42),  # bronze committed since
        (42, "42", None),  # nothing new: skip
        (None, None, None),  # bronze empty
    ],
)
def test_new_bronze_snapshot(
    latest: int | None, remembered: str | None, expected: int | None
) -> None:
    assert checks.new_bronze_snapshot(latest, remembered) == expected


NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("latest", "committed_ago", "remembered", "expected"),
    [
        (42, timedelta(minutes=6), "42", True),  # quiet and merged
        (42, timedelta(minutes=4), "42", False),  # bronze still moving
        (42, timedelta(minutes=6), "41", False),  # silver behind bronze
        (42, timedelta(minutes=6), None, False),  # silver_upsert never ran
        (None, None, None, True),  # empty bronze: nothing in flight
    ],
)
def test_at_rest(
    latest: int | None,
    committed_ago: timedelta | None,
    remembered: str | None,
    expected: bool,
) -> None:
    committed_at = NOW - committed_ago if committed_ago is not None else None

    assert checks.at_rest(latest, committed_at, remembered, NOW) is expected


def test_count_differences_lists_only_tables_that_differ() -> None:
    postgres = {"orders": 10, "payments": 7}
    silver = {"orders": 10, "payments": 6}

    assert checks.count_differences(postgres, silver) == {"payments": (7, 6)}


def test_dbt_writes_only_to_tmp() -> None:
    # The project is mounted read-only into Airflow.
    command = dbt_command("build")

    assert "--project-dir /opt/dbt" in command
    assert "--target-path /tmp/dbt/target" in command
    assert "--log-path /tmp/dbt/logs" in command
```

Запусти: `uv run pytest tests/unit/test_dags.py -q` → ошибка импорта `cannot import name 'SILVER_KEYS'`.

### A2. Пакет

<!-- edit: airflow/dags/lakehouse/settings.py -->
Найти:
```python
# The environment compose gives spark-silver (docker/compose.yaml); the DAG passes the same to
```
Заменить на:
```python
# Primary keys of the silver tables, as contracts/silver/<table>.json declares them; quarantine
# holds one row per Kafka record. tests/unit/test_dags.py compares them with the contracts.
SILVER_KEYS: dict[str, tuple[str, ...]] = {
    "customers": ("customer_id",),
    "sellers": ("seller_id",),
    "products": ("product_id",),
    "orders": ("order_id",),
    "order_items": ("order_id", "order_item_id"),
    "payments": ("order_id", "payment_sequential"),
    "reviews": ("review_id", "order_id"),
    "quarantine": ("topic", "kafka_partition", "kafka_offset"),
}
SOURCE_TABLES = tuple(t for t in SILVER_KEYS if t != "quarantine")

# The environment compose gives spark-silver (docker/compose.yaml); the DAG passes the same to
```

Покой: bronze молчит 5 минут, и `silver_upsert` смержил его последний снапшот. Только тогда silver и Postgres сравнимы; во время порции реплея сверка всегда «расходится».

<!-- file: airflow/dags/lakehouse/checks.py -->
```python
"""Decisions the DAGs make, as plain functions over what the tasks read."""

from collections.abc import Mapping
from datetime import datetime, timedelta

# Bronze commits every 20 s while Kafka has events; five quiet minutes mean the source stopped.
QUIET = timedelta(minutes=5)


def new_bronze_snapshot(latest: int | None, remembered: str | None) -> int | None:
    """Bronze's latest snapshot when silver has not merged it yet, else None."""
    if latest is None or str(latest) == remembered:
        return None
    return latest


def at_rest(
    latest: int | None,
    committed_at: datetime | None,
    remembered: str | None,
    now: datetime,
) -> bool:
    """Nothing is on its way into silver: bronze has been quiet for QUIET and silver_upsert has
    merged its latest snapshot. Only then may silver and Postgres be compared."""
    if latest is None:
        return True
    if committed_at is None or now - committed_at < QUIET:
        return False
    return str(latest) == remembered


def count_differences(
    postgres: Mapping[str, int], silver: Mapping[str, int]
) -> dict[str, tuple[int, int]]:
    """Tables whose live row counts differ, as {table: (postgres, silver)}."""
    return {t: (n, silver.get(t, 0)) for t, n in postgres.items() if silver.get(t, 0) != n}
```

Две метрики дублей: повтор LSN видит повторы доставки (chaos 2b), но не повторы источника, у которых новый LSN (chaos 3 дал 95 no-op UPDATE и 0 повторов LSN).

<!-- file: airflow/dags/lakehouse/sql.py -->
```python
"""SQL the DAGs run through Trino (catalog lake) and Postgres (schema shop)."""

LATEST_BRONZE_SNAPSHOT = """
select snapshot_id, committed_at
from lake.bronze."cdc_events$snapshots"
order by committed_at desc
limit 1
"""


def duplicate_keys(table: str, key: tuple[str, ...]) -> str:
    columns = ", ".join(key)
    return f"""
select count(*) from (
    select {columns} from lake.silver.{table} group by {columns} having count(*) > 1
)
"""


def silver_live_rows(table: str) -> str:
    return f"select count(*) from lake.silver.{table} where not _is_deleted"


def postgres_rows(table: str) -> str:
    return f"select count(*) from shop.{table}"


def freshness_seconds(table: str) -> str:
    return (
        f"select date_diff('second', max(_updated_at), current_timestamp) from lake.silver.{table}"
    )


# Delivery repeats: Debezium sent the same change again (same LSN), as after a Connect kill.
LSN_REPEATS_LAST_HOUR = """
select count(*) from (
    select source_table, key, lsn
    from lake.bronze.cdc_events
    where ingest_ts >= current_timestamp - interval '1' hour and lsn is not null
    group by source_table, key, lsn
    having count(*) > 1
)
"""

# Source repeats: an UPDATE that changed nothing gets a new LSN, so the query above misses it.
NOOP_UPDATES_LAST_HOUR = """
select count(*)
from lake.bronze.cdc_events
where ingest_ts >= current_timestamp - interval '1' hour and op = 'u' and before = after
"""

QUARANTINED_LAST_HOUR = """
select count(*)
from lake.silver.quarantine
where quarantined_at >= current_timestamp - interval '1' hour
"""


def optimize(table: str) -> str:
    return f"alter table lake.silver.{table} execute optimize"
```

<!-- file: airflow/dags/lakehouse/clients.py -->
```python
"""Connections the tasks open: Trino for the lake, Postgres for the source."""

from contextlib import closing
from typing import Any

import psycopg
import trino

from lakehouse.settings import Settings


def trino_rows(settings: Settings, query: str) -> list[list[Any]]:
    connection = trino.dbapi.Connection(
        host=settings.trino_host, port=settings.trino_port, user="airflow", catalog="lake"
    )
    with closing(connection):
        cursor = connection.cursor()
        cursor.execute(query)
        rows: list[list[Any]] = cursor.fetchall()
        return rows


def trino_value(settings: Settings, query: str) -> Any:
    return trino_rows(settings, query)[0][0]


def postgres_value(settings: Settings, query: str) -> Any:
    conninfo = psycopg.conninfo.make_conninfo(
        host=settings.oltp_host,
        port=settings.oltp_port,
        dbname=settings.oltp_db,
        user=settings.oltp_user,
        password=settings.oltp_password,
    )
    with psycopg.connect(conninfo) as connection, connection.cursor() as cursor:
        cursor.execute(query)
        row = cursor.fetchone()
        if row is None:
            raise ValueError(f"no row from: {query}")
        return row[0]
```

Проверка: `uv run pytest tests/unit/test_dags.py -q` → `16 passed`.

### A3. DAG

Код выхода 1 у `dbt source freshness` это устаревший источник, то есть нет трафика: он пишется в лог, DAG не валит. Код 2 это сбой самого dbt.

<!-- file: airflow/dags/dq_checks.py -->
```python
"""dq_checks: every 15 minutes, check silver against its own keys and against Postgres.

Fails the run: a primary key twice in a silver table; live row counts that differ from Postgres
while nothing is in flight (checks.at_rest). Only logged, as `dq <name>=<value>` lines that W4
exports: the same differences while work is in flight, delivery repeats and source no-ops in the
last hour, new quarantine rows, freshness per silver table, dbt source freshness.
"""

from datetime import UTC, datetime

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import Variable, dag, task
from lakehouse import checks, sql
from lakehouse.clients import postgres_value, trino_rows, trino_value
from lakehouse.settings import (
    LAST_BRONZE_SNAPSHOT,
    SILVER_KEYS,
    SOURCE_TABLES,
    Settings,
    dbt_command,
)

settings = Settings()


@dag(
    schedule="*/15 * * * *",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
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
        failed = {table: count for table, count in duplicates.items() if count}
        if failed:
            raise ValueError(f"silver holds a primary key more than once: {failed}")

    @task
    def silver_matches_postgres() -> None:
        rows = trino_rows(settings, sql.LATEST_BRONZE_SNAPSHOT)
        latest, committed_at = (int(rows[0][0]), rows[0][1]) if rows else (None, None)
        remembered = Variable.get(LAST_BRONZE_SNAPSHOT, default=None)
        postgres = {t: int(postgres_value(settings, sql.postgres_rows(t))) for t in SOURCE_TABLES}
        silver = {t: int(trino_value(settings, sql.silver_live_rows(t))) for t in SOURCE_TABLES}
        differences = checks.count_differences(postgres, silver)
        resting = checks.at_rest(latest, committed_at, remembered, datetime.now(UTC))
        print(f"dq reconcile_tables_differing={len(differences)} at_rest={resting}")
        for table, (source, lake) in differences.items():
            print(f"{table}: postgres {source}, silver {lake}")
        if differences and resting:
            raise ValueError(f"silver differs from Postgres at rest: {differences}")
        if differences:
            print("in flight: bronze or silver has not caught up yet, no verdict")

    @task
    def report() -> None:
        print(f"dq lsn_repeats_last_hour={trino_value(settings, sql.LSN_REPEATS_LAST_HOUR)}")
        print(f"dq noop_updates_last_hour={trino_value(settings, sql.NOOP_UPDATES_LAST_HOUR)}")
        print(f"dq quarantined_last_hour={trino_value(settings, sql.QUARANTINED_LAST_HOUR)}")
        for table in SILVER_KEYS:
            seconds = trino_value(settings, sql.freshness_seconds(table))
            print(f"dq silver_freshness_seconds{{table={table}}}={seconds}")

    source_freshness = BashOperator(
        task_id="dbt_source_freshness",
        # Exit code 1 is a stale source: no traffic, which is logged, not a failure. 2 is dbt
        # itself failing.
        bash_command=(
            dbt_command("source freshness") + "; rc=$?; "
            'echo "dq dbt_source_freshness_exit_code=$rc"; [ "$rc" -le 1 ]'
        ),
    )

    [silver_keys_unique(), silver_matches_postgres(), report(), source_freshness]


dq_checks()
```

Optimize одновременно с MoR MERGE на `silver.orders` даёт конфликт коммита (ADR-010), поэтому оба в pool на 1 слот; mapped-задачи занимают слот по одной.

<!-- file: airflow/dags/iceberg_maintenance.py -->
```python
"""iceberg_maintenance: daily optimize of every silver table through Trino (D11).

Compaction of small files, and folding the delete files of merge-on-read silver.orders. In the
pool lake_writers with silver_upsert's merge: two commits to silver.orders at once and the loser
fails (ADR-010). Bronze, expire_snapshots and remove_orphan_files are week 5 (ADR-021).
"""

from datetime import datetime

from airflow.sdk import dag, task
from lakehouse import sql
from lakehouse.clients import trino_rows
from lakehouse.settings import LAKE_WRITERS_POOL, SILVER_KEYS, Settings

settings = Settings()


@dag(
    schedule="@daily",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    tags=["maintenance"],
)
def iceberg_maintenance() -> None:
    @task(pool=LAKE_WRITERS_POOL)
    def optimize(table: str) -> None:
        for row in trino_rows(settings, sql.optimize(table)):
            print(f"{table}: {row}")

    optimize.expand(table=list(SILVER_KEYS))


iceberg_maintenance()
```

### A4. Статические проверки

```bash
make lint && make test 2>&1 | tail -1    # 145 passed, 62 skipped
```

### A5. Документация

<!-- file: airflow/README.md -->
```markdown
# airflow

Airflow 3.3.2, LocalExecutor, batch only: the bronze stream is not a DAG (ADR-011). How to run it:
OPERATIONS.md, "Airflow".

| DAG | Schedule | Does |
|---|---|---|
| `silver_upsert` | every 5 min, `max_active_runs=1`, 1 retry | skips without a new bronze snapshot; DockerOperator starts spark-silver (`Trigger.AvailableNow`) in pool `lake_writers`; publishes Asset `lake.silver` |
| `dbt_build` | Asset `lake.silver` | `dbt build` of `lake.gold` (BashOperator, `/opt/dbt-venv`), no retries |
| `dq_checks` | every 15 min | a duplicate key in silver, or silver against Postgres at rest, fails it; repeats, no-ops, quarantine and freshness are logged |
| `iceberg_maintenance` | daily | `optimize` of the silver tables through Trino, in pool `lake_writers` |

- `dags/lakehouse/`: settings from the environment, SQL, decisions, clients. It imports no
  airflow, so `tests/unit/test_dags.py` runs it on the host; `.airflowignore` keeps it out of DAG
  parsing.
- `Dockerfile`: `apache/airflow:3.3.2-python3.12`, the docker provider of the image, the clients
  the DAGs import, dbt in `/opt/dbt-venv`.
```

<!-- edit: OPERATIONS.md -->
Найти:
```text
| `dbt_build` | Asset `lake.silver` | `dbt build` of `lake.gold` from `/opt/dbt-venv`, no retries; a manual run takes dbt vars from its conf, `{"dbt_vars": "{...}"}` |
```
Заменить на:
```text
| `dbt_build` | Asset `lake.silver` | `dbt build` of `lake.gold` from `/opt/dbt-venv`, no retries; a manual run takes dbt vars from its conf, `{"dbt_vars": "{...}"}` |
| `dq_checks` | every 15 min | fails on a primary key twice in silver, or on silver differing from Postgres at rest; logs `dq <name>=<value>` lines: delivery repeats and source no-ops of the last hour, new quarantine rows, freshness of each silver table, `dbt source freshness` |
| `iceberg_maintenance` | daily | `optimize` of each silver table through Trino, in pool `lake_writers`; bronze is not touched (D11) |
```

<!-- edit: OPERATIONS.md -->
Найти:
```text
Airflow continues from the checkpoint of the last `make silver`.
```
Заменить на:
```text
Airflow continues from the checkpoint of the last `make silver`.

A red `dq_checks` means one of two things. `silver_keys_unique`: silver holds a primary key
twice, which MERGE must never produce; read the last `silver_upsert` log and the quarantine.
`silver_matches_postgres`: counts differ although bronze has been quiet for 5 minutes and silver
merged its latest snapshot, so a change never reached silver; `make verify` (with the scheduler
stopped) shows the offsets and the counts. Differences with `at_rest=False` are normal during a
replay burst. A stale `dbt source freshness` (exit code 1) is logged, not failed: no traffic is not
a broken pipeline.
```

<!-- edit: DECISIONS.md -->
Найти:
```text
  it onto the Asset is the owner's Modify gate).
```
Заменить на:
```text
  it onto the Asset is the owner's Modify gate).
- Maintenance in week 3 (D11): only `optimize` of the silver tables, in the pool `lake_writers`
  (1 slot) together with the silver merge, since two commits to `silver.orders` at once fail one
  of them (ADR-010). `expire_snapshots` and `remove_orphan_files` wait for the policy of week 5
  (ADR-021).
```

<!-- edit: ARCHITECTURE.md -->
Найти:
```markdown
7. `dq_checks` reconciles counts source vs silver vs gold, measures freshness and duplicate
   ratio, and exports gauges to Prometheus. `iceberg_maintenance` compacts files, rewrites
   position deletes, expires snapshots and removes orphans.
```
Заменить на:
```markdown
7. `dq_checks` fails on a duplicate key in silver and on silver differing from Postgres at rest,
   and logs delivery repeats, source no-ops, quarantine growth and freshness (exported to
   Prometheus in week 4). `iceberg_maintenance` compacts the silver tables daily (`optimize`);
   snapshot expiry and orphan removal wait for week 5.
```

## Часть B. Живая проверка

Предусловия: W3-T05a B прошла; `silver_upsert` и `dbt_build` сняты с паузы; реплеер не играет. `af`, `q`, `$COMPOSE` как в W3-T05a.

### B1. Четыре DAG, снять паузу с `dq_checks`

```bash
af dags list-import-errors
af dags list | grep -cE 'silver_upsert|dbt_build|dq_checks|iceberg_maintenance'   # 4
af dags unpause dq_checks
```
`iceberg_maintenance` пока на паузе: его первый запуск ручной, в B3.

### B2. `dq_checks` в покое

Покой: прошло больше 5 минут с последнего коммита bronze, и последний `silver_upsert` смержил его снапшот.

```bash
bash -c '. scripts/chaos/lib.sh; run_dag dq_checks dq-rest-1 && echo "dq ok"'
```
Ожидается: `dq ok`. В UI в логах задач строки `dq silver_duplicate_keys{table=...}=0` по восьми таблицам, `dq reconcile_tables_differing=0 at_rest=True`, `dq lsn_repeats_last_hour=`, `dq noop_updates_last_hour=`, `dq quarantined_last_hour=`, `dq silver_freshness_seconds{table=...}=` по восьми таблицам, `dq dbt_source_freshness_exit_code=`.

### B3. Optimize не пересекается с merge

```bash
merge_running() {
  local run
  run=$(af dags list-runs silver_upsert -o json | python3 -c 'import json, sys; t = sys.stdin.read(); print(json.loads(t[t.index("["):])[0]["run_id"])')
  af tasks states-for-dag-run silver_upsert "$run" | grep -q 'merge.*running'
}
make replay-burst SECONDS=60 &
until merge_running; do sleep 10; done; echo "merge is running"
af dags unpause iceberg_maintenance
bash -c '. scripts/chaos/lib.sh; RUN_DAG_WAIT=1800 run_dag iceberg_maintenance maint-1 && echo "maintenance ok"'
wait
```
Затем в UI, вкладка Gantt обоих запусков: интервалы `merge` и всех `optimize` не пересекаются, `optimize` ждали в состоянии queued (pool `lake_writers`). Ожидается `maintenance ok`.

### B4. Delete files свёрнуты

```bash
q 'select content, count(*) from silver."orders$files" group by 1'
```
Ожидается: нет строки с `content = 1` (position deletes). Если `silver_upsert` успел смержить после optimize, строки 1 могли появиться снова: тогда повтори `run_dag iceberg_maintenance maint-2` в покое и запрос.

### B5. Рестарт scheduler

```bash
$COMPOSE restart airflow-scheduler
```
Ожидается: следующий запуск `silver_upsert` без новых данных снова пропускает `merge` (Variable пережила рестарт); `oom=false` как в W3-T05a B4.

### B6. Сутки без реплея

Через сутки:

```bash
for d in silver_upsert dbt_build dq_checks iceberg_maintenance; do echo "$d: $(af dags list-runs $d --state failed -o table | grep -c "$d")"; done
docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' | grep -E 'airflow|trino'
```
Ожидается: по нулю failed у каждого DAG; память записана в отчёт.

## Готово, когда

- `airflow dags list-import-errors` пусто, `airflow dags list` показывает четыре DAG (B1).
- `dq_checks` в покое success, в логе обе метрики дублей, freshness семи таблиц silver и карантина, результат `dbt source freshness` (B2).
- Во время порции ручной `iceberg_maintenance`: его задачи ждут в pool, интервалы `merge` и `optimize` не пересекаются, DAG success (B3).
- Сразу после `iceberg_maintenance` у `silver.orders` нет файлов с `content = 1` (B4).
- Сутки при остановленном реплее: все DAG зелёные, `docker stats` записан (B6).
- `make test`, `make lint` зелёные.

## Если не так

| Симптом | Причина | Что делать |
|---|---|---|
| B2: `silver_matches_postgres` failed при `at_rest=True` | событие не дошло до silver | стоп; Airflow на паузу, `make verify` после остановки scheduler, вывод в отчёт |
| B2: `silver_keys_unique` failed | дубль ключа в silver | стоп; это инцидент, не правка DAG |
| B3: `optimize` failed с конфликтом коммита | merge и optimize шли вместе | проверь `pool` у обеих задач и 1 слот в `lake_writers`; стоп |
| B6: `dq_checks` красный ночью | смотри первые две строки | стоп |

## Ловушки

- Сверка во время реплея всегда «расходится»: падать на ней можно только в покое.
- Одна метрика дублей по LSN не видит дубли источника, поэтому метрик две.
- `optimize` создаёт replace-снапшоты; старые файлы остаются до expire в W5.

## Blast radius и пайплайн

`optimize` переписывает файлы silver без удаления данных, старые файлы остаются до `expire_snapshots` в W5; streaming-чтение silver их не читает. Expire, orphan files и DROP не делаются. Порция реплея около 12 виртуальных часов.

## Отчёт: что собрать

Вывод B1, строки `dq` из лога B2, Gantt или времена задач B3, результат B4, сутки B6 с памятью, `virtual_now` до и после, `git diff --stat`.

## Коммит

```bash
git add airflow tests/unit/test_dags.py OPERATIONS.md DECISIONS.md ARCHITECTURE.md
git commit -m "orchestrate: dq_checks and iceberg_maintenance dags"
```
