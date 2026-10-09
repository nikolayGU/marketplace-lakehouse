# W3-T05a DAG `silver_upsert` и `dbt_build` (W3-T05, коммит 1)

> До первого шага прочитай `README.md` этой папки: протокол, стоп-условия, отчёт.

| | |
|---|---|
| Спека | `07-w3-spec.md`, карточка W3-T05; решения D9, D10, D13 |
| Коммит | `orchestrate: silver_upsert and dbt_build dags` |
| Оценка | A: 1.5 ч; B: 1.5 ч |
| Часть A | любая среда |
| Часть B | только локально; с этого шага писатель silver это Airflow; порция реплея 60 с |

## Цель

`silver_upsert` каждые 5 минут мержит в silver то, что bronze закоммитил, и пропускает запуск без нового снапшота bronze; `dbt_build` перестраивает gold по Asset `lake.silver`.

Проверено 09.10 в образе W3-T04: оба DAG импортируются через `BundleDagBag` Airflow 3.3.2 (папка DAG сама попадает в `sys.path`, поэтому пакет `lakehouse` рядом с DAG виден и при разборе, и в задачах); цепочка `bronze_has_new_snapshot → merge → remember_snapshot`; у `merge` pool `lake_writers`, outlet `Asset('lake.silver')`, сеть `lakehouse_lake`, `mem_limit 2g`, `auto_remove success`, `mount_tmp_dir False`; секреты из `private_environment` не попадают в сериализованный DAG; шаблон `dbt_vars` даёт `{}` для запуска по Asset.

## Вход

```bash
git log --oneline -1                                                      # коммит W3-T04
docker compose --env-file .env -f docker/compose.yaml ps --format '{{.Service}} {{.Health}}' | grep airflow   # три healthy
docker compose --env-file .env -f docker/compose.yaml exec airflow-scheduler airflow pools list | grep lake_writers
```

## Файлы

- Создать: `airflow/dags/.airflowignore`, `airflow/dags/lakehouse/__init__.py`, `airflow/dags/lakehouse/settings.py`, `airflow/dags/lakehouse/checks.py`, `airflow/dags/lakehouse/sql.py`, `airflow/dags/lakehouse/clients.py`, `airflow/dags/silver_upsert.py`, `airflow/dags/dbt_build.py`, `tests/unit/test_dags.py`.
- Изменить: `pyproject.toml`, `OPERATIONS.md`, `DECISIONS.md`, `ARCHITECTURE.md`, `docs/planning/00-mini-architecture-review.md`.

## Что задача даёт следующим

Пакет `lakehouse` (W3-T05b дополнит `settings`, `checks`, `sql`, `clients`): `Settings`, `spark_silver_environment(environ)`, `dbt_command(subcommand)`, константы `SILVER_ASSET_NAME`, `LAST_BRONZE_SNAPSHOT`, `LAKE_WRITERS_POOL`, `checks.new_bronze_snapshot`, `sql.LATEST_BRONZE_SNAPSHOT`, `clients.trino_rows`. Asset `lake.silver`, Variable `silver_upsert_last_bronze_snapshot`.

## Часть A. Код

### A1. Пути для тестов и mypy

Пакет `lakehouse` не импортирует airflow, поэтому тестируется на хосте. DAG-файлы mypy не проверяет: без Airflow на хосте он их не типизирует. В репо есть каталог `airflow/`, и ruff иначе счёл бы одноимённый пакет своим.

<!-- edit: pyproject.toml -->
Найти:
```toml
"streaming/**" = ["N802", "N812"]
```
Заменить на:
```toml
"streaming/**" = ["N802", "N812"]

[tool.ruff.lint.isort]
# The repo has an airflow/ directory; the package of that name is the installed library.
known-third-party = ["airflow"]
```

<!-- edit: pyproject.toml -->
Найти:
```toml
# mypy fails on a directory without .py files; add streaming and airflow/dags as they appear.
files = ["scripts", "tests", "oltp", "streaming"]
# `replayer` and `spark_jobs` are top-level packages, which is what their containers see too.
mypy_path = "oltp:streaming"
```
Заменить на:
```toml
# DAG files are left out: without Airflow on the host, mypy cannot type them.
files = ["scripts", "tests", "oltp", "streaming", "airflow/dags/lakehouse"]
# `replayer`, `spark_jobs` and `lakehouse` are top-level packages, as their containers see them.
mypy_path = "oltp:streaming:airflow/dags"
```

<!-- edit: pyproject.toml -->
Найти:
```toml
# `replayer` lives in oltp/ and `spark_jobs` in streaming/, same as inside the images.
pythonpath = ["oltp", "streaming", "."]
```
Заменить на:
```toml
# `replayer` lives in oltp/, `spark_jobs` in streaming/, `lakehouse` in airflow/dags/, as in the images.
pythonpath = ["oltp", "streaming", "airflow/dags", "."]
```

### A2. Тесты первым

Тест на расхождение env DAG и compose это первый тест на отказ (D9): ключ, который compose дал `spark-silver`, а DAG забыл, увёл бы silver из Airflow в другой каталог.

<!-- file: tests/unit/test_dags.py -->
```python
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]
from lakehouse import checks
from lakehouse.settings import (
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


def test_dbt_writes_only_to_tmp() -> None:
    # The project is mounted read-only into Airflow.
    command = dbt_command("build")

    assert "--project-dir /opt/dbt" in command
    assert "--target-path /tmp/dbt/target" in command
    assert "--log-path /tmp/dbt/logs" in command
```

Запусти: `uv run pytest tests/unit/test_dags.py -q` → ошибка сборки `ModuleNotFoundError: No module named 'lakehouse'`.

### A3. Пакет `lakehouse`

`.airflowignore` (синтаксис glob, умолчание Airflow 3.3.2) убирает пакет из разбора DAG.

<!-- file: airflow/dags/.airflowignore -->
```text
lakehouse/
```

<!-- file: airflow/dags/lakehouse/__init__.py -->
```python
"""What the DAGs share. Nothing here imports airflow, so tests run it on the host."""
```

<!-- file: airflow/dags/lakehouse/settings.py -->
```python
"""Configuration of the DAGs, all from the environment of the Airflow containers
(docker/airflow/airflow.env)."""

from collections.abc import Mapping

from pydantic_settings import BaseSettings, SettingsConfigDict

SILVER_ASSET_NAME = "lake.silver"
# Id of the bronze snapshot that silver_upsert merged last; dq_checks reads it to tell rest from
# work in flight.
LAST_BRONZE_SNAPSHOT = "silver_upsert_last_bronze_snapshot"
LAKE_WRITERS_POOL = "lake_writers"

# The environment compose gives spark-silver (docker/compose.yaml); the DAG passes the same to
# the container it starts. The secrets go to DockerOperator's private_environment, which the
# Airflow UI does not render.
SPARK_SILVER_ENV = (
    "SPARK_MASTER",
    "SPARK_DRIVER_MEMORY",
    "CATALOG_TYPE",
    "CATALOG_JDBC_URL",
    "CATALOG_JDBC_USER",
    "CATALOG_JDBC_PASSWORD",
    "CATALOG_WAREHOUSE",
    "CHECKPOINT_ROOT",
    "LAKEKEEPER_URI",
    "LAKEKEEPER_WAREHOUSE",
    "S3_ENDPOINT",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
)
SPARK_SILVER_SECRETS = ("CATALOG_JDBC_PASSWORD", "S3_ACCESS_KEY", "S3_SECRET_KEY")

DBT = "/opt/dbt-venv/bin/dbt"
DBT_PROJECT = "/opt/dbt"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    compose_project_name: str = "lakehouse"
    spark_image: str = "lakehouse/spark:dev"

    trino_host: str = "trino"
    trino_port: int = 8080

    oltp_host: str = "postgres-oltp"
    oltp_port: int = 5432
    oltp_db: str = "shop"
    oltp_user: str = "shop"
    oltp_password: str = ""

    @property
    def lake_network(self) -> str:
        """Compose names the network `<project>_lake`; a fresh clone runs as lakehouse-fresh."""
        return f"{self.compose_project_name}_lake"


def spark_silver_environment(environ: Mapping[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """(public, private) environment for the spark-silver container.

    Raises KeyError for a key airflow.env lacks: the DAG file then fails to import, which the UI
    and `airflow dags list-import-errors` show, instead of a silver run on another catalog.
    """
    missing = [key for key in SPARK_SILVER_ENV if key not in environ]
    if missing:
        raise KeyError(f"docker/airflow/airflow.env lacks {missing}")
    public = {k: environ[k] for k in SPARK_SILVER_ENV if k not in SPARK_SILVER_SECRETS}
    private = {k: environ[k] for k in SPARK_SILVER_SECRETS}
    return public, private


def dbt_command(subcommand: str) -> str:
    """dbt inside Airflow: the project is mounted read-only, so target and logs go to /tmp."""
    return (
        f"{DBT} {subcommand} --project-dir {DBT_PROJECT} --profiles-dir {DBT_PROJECT}"
        " --target dev --target-path /tmp/dbt/target --log-path /tmp/dbt/logs"
    )
```

<!-- file: airflow/dags/lakehouse/checks.py -->
```python
"""Decisions the DAGs make, as plain functions over what the tasks read."""


def new_bronze_snapshot(latest: int | None, remembered: str | None) -> int | None:
    """Bronze's latest snapshot when silver has not merged it yet, else None."""
    if latest is None or str(latest) == remembered:
        return None
    return latest
```

<!-- file: airflow/dags/lakehouse/sql.py -->
```python
"""SQL the DAGs run through Trino (catalog lake)."""

LATEST_BRONZE_SNAPSHOT = """
select snapshot_id, committed_at
from lake.bronze."cdc_events$snapshots"
order by committed_at desc
limit 1
"""
```

`trino.dbapi.Connection` вызывается напрямую: функция `connect` в клиенте не аннотирована, и strict mypy её не пропустит.

<!-- file: airflow/dags/lakehouse/clients.py -->
```python
"""Connections the tasks open: Trino for the lake."""

from contextlib import closing
from typing import Any

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
```

Проверка: `uv run pytest tests/unit/test_dags.py -q` → `9 passed`.

### A4. DAG

`print` в задаче попадает в её лог. `remember_snapshot` пишет id, прочитанный первым таском, а не текущий: пришедшее во время merge подберёт следующий запуск.

<!-- file: airflow/dags/silver_upsert.py -->
```python
"""silver_upsert: every 5 minutes, merge what bronze committed into silver (D10, ADR-021).

The merge is spark-silver, the same container as `make silver`, started by DockerOperator. A run
without a new bronze snapshot skips the merge and publishes no Asset event, so dbt_build sleeps.
"""

import os
from datetime import datetime, timedelta

from airflow.providers.docker.operators.docker import DockerOperator
from airflow.sdk import Asset, Variable, dag, task
from lakehouse import checks, sql
from lakehouse.clients import trino_rows
from lakehouse.settings import (
    LAKE_WRITERS_POOL,
    LAST_BRONZE_SNAPSHOT,
    SILVER_ASSET_NAME,
    Settings,
    spark_silver_environment,
)

settings = Settings()
public_env, private_env = spark_silver_environment(os.environ)


@dag(
    schedule="*/5 * * * *",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=1)},
    tags=["silver"],
)
def silver_upsert() -> None:
    @task.short_circuit
    def bronze_has_new_snapshot() -> int | bool:
        rows = trino_rows(settings, sql.LATEST_BRONZE_SNAPSHOT)
        latest = int(rows[0][0]) if rows else None
        remembered = Variable.get(LAST_BRONZE_SNAPSHOT, default=None)
        new = checks.new_bronze_snapshot(latest, remembered)
        print(f"bronze latest snapshot {latest}, silver merged {remembered}")
        return new if new is not None else False

    merge = DockerOperator(
        task_id="merge",
        image=settings.spark_image,
        command=["silver_upsert"],
        network_mode=settings.lake_network,
        environment=public_env,
        private_environment=private_env,
        mem_limit="2g",
        # Airflow runs in a container: a host temp dir to mount does not exist.
        mount_tmp_dir=False,
        auto_remove="success",
        pool=LAKE_WRITERS_POOL,
        outlets=[Asset(SILVER_ASSET_NAME)],
        do_xcom_push=False,
    )

    @task
    def remember_snapshot(snapshot_id: int) -> None:
        # The id read before the merge, not bronze's current one: whatever bronze committed
        # during the merge is the next run's work.
        Variable.set(LAST_BRONZE_SNAPSHOT, str(snapshot_id))

    snapshot = bronze_has_new_snapshot()
    snapshot >> merge >> remember_snapshot(snapshot)


silver_upsert()
```

Переменные dbt идут через окружение, а не через командную строку: так строка `{chaos_break_test: true}` не проходит через разбор shell.

<!-- file: airflow/dags/dbt_build.py -->
```python
"""dbt_build: dbt build of lake.gold after every silver merge (Asset lake.silver, D10).

No retries: a failed test stays failed. A manual run takes dbt vars from its conf, as
{"dbt_vars": "{chaos_break_test: true}"} (chaos 9); a run from the Asset has an empty conf.
"""

from datetime import datetime

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import Asset, dag
from lakehouse.settings import SILVER_ASSET_NAME, dbt_command


@dag(
    schedule=[Asset(SILVER_ASSET_NAME)],
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    tags=["gold"],
)
def dbt_build() -> None:
    BashOperator(
        task_id="dbt_build",
        bash_command=dbt_command("build") + ' --vars "$DBT_VARS"',
        # Through the environment, not the command line: the vars never pass the shell parser.
        env={"DBT_VARS": "{{ (dag_run.conf or {}).get('dbt_vars', '{}') }}"},
        append_env=True,
    )


dbt_build()
```

### A5. Статические проверки

```bash
make lint && make test 2>&1 | tail -1    # 138 passed, 62 skipped
```

### A6. Документация

<!-- edit: OPERATIONS.md -->
Найти:
```text
## Failure scenarios
```
Заменить на:
```text
DAGs live in `airflow/dags/`; their shared code is `airflow/dags/lakehouse/`, which
`.airflowignore` keeps out of DAG parsing.

| DAG | Schedule | Does |
|---|---|---|
| `silver_upsert` | every 5 min, `max_active_runs=1`, 1 retry | `bronze_has_new_snapshot` skips the run when bronze has no snapshot silver has not merged; `merge` starts spark-silver (DockerOperator, pool `lake_writers`) and publishes the Asset `lake.silver`; `remember_snapshot` stores the merged snapshot id in the Variable `silver_upsert_last_bronze_snapshot` |
| `dbt_build` | Asset `lake.silver` | `dbt build` of `lake.gold` from `/opt/dbt-venv`, no retries; a manual run takes dbt vars from its conf, `{"dbt_vars": "{...}"}` |

One silver writer. While `silver_upsert` is unpaused, `make silver` and `make verify` must not
run: two processes on one checkpoint (`make verify` refuses while the scheduler runs). For a
manual merge: `airflow dags pause silver_upsert` in the scheduler container, wait until its
running `merge` ends, `make silver`, then `airflow dags unpause silver_upsert`. The first run from
Airflow continues from the checkpoint of the last `make silver`.

## Failure scenarios
```

<!-- edit: DECISIONS.md -->
Найти:
```text
  with it; without a shared value the UI shows no task log) and `DOCKER_GID`.
```
Заменить на:
```text
  with it; without a shared value the UI shows no task log) and `DOCKER_GID`.
- Cadence (D10): `silver_upsert` every 5 minutes, and its first task skips the run when bronze
  has no snapshot that silver has not merged, so no JVM starts for nothing and no Asset event
  wakes dbt; `dbt_build` on the Asset `lake.silver`; `dq_checks` every 15 minutes on time (moving
  it onto the Asset is the owner's Modify gate).
```

<!-- edit: ARCHITECTURE.md -->
Найти:
```markdown
   `mart_delivery_sla`) hourly, triggered by the silver asset. Tests and docs run with it.
```
Заменить на:
```markdown
   `mart_delivery_sla`) after every silver merge, triggered by the Asset `lake.silver`. Tests run
   with it; docs are generated on demand (`make dbt-docs`).
```

<!-- edit: docs/planning/00-mini-architecture-review.md -->
Найти:
```text
dbt_build (hourly)   dq_checks (15 min)
```
Заменить на:
```text
dbt_build (Asset)    dq_checks (15 min)
```

<!-- edit: docs/planning/00-mini-architecture-review.md -->
Найти:
```markdown
| Ручной SQL не тестируется и не документируется | Batch раз в час |
```
Заменить на:
```markdown
| Ручной SQL не тестируется и не документируется | После каждого merge silver (Asset `lake.silver`) |
```

## Часть B. Живая проверка

Предусловия: W3-T04 B прошла; `orchestrate` поднят с `TRINO_XMX=2g`; реплеер не играет. `$COMPOSE` и `q` как раньше; `af` это CLI Airflow:

```bash
af() { $COMPOSE exec -T airflow-scheduler airflow "$@"; }
```

### B1. DAG видны, ошибок импорта нет

```bash
bash -c '. scripts/chaos/lib.sh; wait_until 120 "dags parsed" bash -c "airflow_cli dags list 2>/dev/null | grep -q dbt_build"'
af dags list | grep -E 'silver_upsert|dbt_build'
af dags list-import-errors
```
Ожидается: обе строки с `is_paused` True; ошибок импорта нет.

### B2. `make verify` отказывается при работающем scheduler

Это отложенный пункт DoD W3-T00.

```bash
make verify; echo "exit $?"
```
Ожидается: `airflow-scheduler is running and may merge silver at the same time ...` и `exit 2`.

### B3. Снять паузу: Airflow становится писателем silver

С этого момента `make silver` и ручной `make dbt-build` запрещены, пока DAG не на паузе.

```bash
af dags unpause silver_upsert
af dags unpause dbt_build
```

### B4. Первый запуск: merge, затем `dbt_build` по Asset; память scheduler

Variable ещё нет, поэтому первый запуск делает merge. Пока идёт `dbt_build`, мерь память scheduler:

```bash
sched=$($COMPOSE --profile '*' ps -q airflow-scheduler)
for i in $(seq 120); do docker stats --no-stream --format '{{.MemUsage}}' "$sched"; sleep 5; done | sort -h | tail -1
af dags list-runs silver_upsert -o table | head -5
af dags list-runs dbt_build -o table | head -5
docker inspect -f 'oom={{.State.OOMKilled}} restarts={{.RestartCount}}' "$sched"
```
Ожидается: последний запуск `silver_upsert` success, затем запуск `dbt_build` success (тип запуска asset_triggered); пик памяти scheduler меньше 600 MiB; `oom=false restarts=0`. OOM или рестарт: стоп, решение владельца (лимит scheduler или `PARALLELISM=1`).

### B5. Без новых данных merge пропускается

Дождись следующего запуска `silver_upsert` (до 5 минут):

```bash
run=$(af dags list-runs silver_upsert -o json | python3 -c 'import json, sys; t = sys.stdin.read(); print(json.loads(t[t.index("["):])[0]["run_id"])')
af tasks states-for-dag-run silver_upsert "$run"
af dags list-runs dbt_build -o table | head -4
```
Ожидается: `bronze_has_new_snapshot` success, `merge` и `remember_snapshot` skipped; новых запусков `dbt_build` нет.

### B6. Порция реплея проходит до gold

```bash
make replay-burst SECONDS=60
```
В течение 10 минут: `silver_upsert` success с выполненным `merge`, затем `dbt_build` success по Asset (B4 и B5 теми же командами). Успех `dbt_build` значит, что прошли все тесты, включая тест полного пересчёта витрины.

### B7. Финальные проверки

```bash
make lint && make test 2>&1 | tail -1
```

## Готово, когда

- Оба DAG без ошибок импорта (B1); `make verify` отказывается при работающем scheduler (B2).
- После порции реплея за 10 минут `silver_upsert` success с выполненным `merge`, затем `dbt_build` success по Asset; следующий `silver_upsert` без новых данных: `merge` skipped, `dbt_build` не запускался (B5, B6).
- Пик памяти scheduler под `dbt build` записан, OOM нет (B4).
- `make test`, `make lint` зелёные.

## Если не так

| Симптом | Причина | Что делать |
|---|---|---|
| B1: `No module named 'lakehouse'` в ошибках импорта | `.airflowignore` или пакет не там | пути из A3; не добавляй `sys.path` в DAG |
| B1: `docker/airflow/airflow.env lacks [...]` | ключа нет в `airflow.env` | сверь с W3-T04; `make up PROFILE=orchestrate` пересоздаст контейнеры |
| B4: `merge` падает с `permission denied` на сокете | `DOCKER_GID` | W3-T04 B1 и B3 |
| B4: `merge` падает, контейнер Spark не видит Lakekeeper | не та сеть | `COMPOSE_PROJECT_NAME` в `airflow.env`; `docker network ls` |
| B4: `dbt_build` не запускается после success `merge` | Asset не опубликован или `dbt_build` на паузе | `af dags list`; outlet у `merge` |
| B4: `dbt_build` failed | тест или модель упали | стоп; лог задачи из UI в отчёт |
| `remember_snapshot` падает на `Variable.set` | execution API | лог задачи в отчёт, стоп |

## Ловушки

- Ручной `make silver` при включённом DAG даёт два писателя на один checkpoint.
- Сеть compose называется `<COMPOSE_PROJECT_NAME>_lake`: имя из env, иначе в проекте `lakehouse-fresh` DAG пошёл бы в чужую сеть.
- DockerOperator по умолчанию монтирует временный каталог хоста, которого нет у Airflow в контейнере: `mount_tmp_dir=False`.
- Контейнер DockerOperator не подчиняется лимитам compose: `mem_limit` задан в операторе.
- Asset публикуется при любом успехе таска: без пропуска dbt перестраивал бы gold каждые 5 минут впустую.

## Blast radius и пайплайн

Checkpoint silver тот же, что у `make silver`: первый запуск из Airflow продолжает с места ручного. Служебные операции dbt по D13. Порция реплея около 12 виртуальных часов. Удалений нет.

## Отчёт: что собрать

Вывод B1, B2, пик памяти и `oom` из B4, состояния задач B5, запуски B6, `virtual_now` до и после, `git diff --stat`.

## Коммит

```bash
git add airflow/dags pyproject.toml tests/unit/test_dags.py OPERATIONS.md DECISIONS.md \
  ARCHITECTURE.md docs/planning/00-mini-architecture-review.md
git commit -m "orchestrate: silver_upsert and dbt_build dags"
```
