# W3-T04 Образ Airflow и профиль `orchestrate`

> До первого шага прочитай `README.md` этой папки: протокол, стоп-условия, отчёт.

| | |
|---|---|
| Спека | `07-w3-spec.md`, карточка W3-T04; решения D9, D12; уточнения 6-10 README плана |
| Уже сделано | шаг 4 карточки (Fernet в `make secrets`), PR #1 |
| Коммит | `orchestrate: airflow image, env and pool` |
| Оценка | A: 1 ч; B: 1.5 ч, первая сборка образа около 10 минут |
| Часть A | любая среда |
| Часть B | только локально: правка живого `.env`, профиль `orchestrate` |

## Цель

`make up PROFILE=orchestrate` поднимает три сервиса Airflow 3.3.2, healthy; задачи проходят execution API; логи задач видны в UI; scheduler достучится до Docker; pool `lake_writers` на 1 слот; dbt в отдельном venv образа.

Проверено 09.10 сборкой этого Dockerfile: Airflow 3.3.2, Python 3.12.14, провайдеры docker 4.5.9 и standard 1.19.0, pydantic-settings 2.15.0, trino 0.339.0, psycopg 3.3.5, dbt-core 1.10.23 с dbt-trino 1.10.4 в `/opt/dbt-venv`; образ 3.47 GB.

## Вход

```bash
git log --oneline -1                                             # коммит W3-T03
ls airflow                                                       # README.md, нет Dockerfile
grep -c 'AIRFLOW_ADMIN_PASSWORD' .env.example                    # 1
awk -F= '/^AIRFLOW_FERNET_KEY=/{print length($2)}' .env          # 32 (старый ключ) или 44
stat -c %g /var/run/docker.sock                                  # gid сокета, на ноутбуке 1001
```

## Файлы

- Создать: `airflow/Dockerfile`, `tests/unit/test_airflow_env.py`.
- Перезаписать целиком: `docker/airflow/airflow.env`.
- Изменить: `docker/compose.yaml`, `.env.example`, `Makefile`, `scripts/chaos/lib.sh`, `OPERATIONS.md`, `DECISIONS.md`, `docs/planning/00-mini-architecture-review.md`.

## Что задача даёт следующим

Образ `lakehouse/airflow:dev`; переменные окружения задач (`TRINO_HOST`, `OLTP_*`, окружение spark-silver, `COMPOSE_PROJECT_NAME`); pool `lake_writers`; в `lib.sh`: `airflow_cli`, `dag_run_state <dag> <run>`, `run_dag <dag> <run> [conf]`.

## Часть A. Код

### A1. Тест первым

Неизвестная `${VAR}` в `env_file` compose молча подставляет пустую строку: Airflow стартовал бы с пустым секретом.

<!-- file: tests/unit/test_airflow_env.py -->
```python
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AIRFLOW_ENV = REPO / "docker" / "airflow" / "airflow.env"
ENV_EXAMPLE = REPO / ".env.example"
GENERATED_SECRETS = ("AIRFLOW_FERNET_KEY", "AIRFLOW_JWT_SECRET", "AIRFLOW_API_SECRET_KEY")


def env_example() -> dict[str, str]:
    pairs = {}
    for line in ENV_EXAMPLE.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.lstrip().startswith("#"):
            pairs[key.strip()] = value.split("#", 1)[0].strip()
    return pairs


def test_every_variable_airflow_env_reads_is_in_env_example() -> None:
    # Compose substitutes an empty string for an unknown ${VAR}: a typo would start Airflow with
    # an empty secret instead of failing.
    settings = [line for line in AIRFLOW_ENV.read_text().splitlines() if not line.startswith("#")]
    used = set(re.findall(r"\$\{(\w+)", "\n".join(settings)))

    assert used - env_example().keys() == set()


def test_airflow_secrets_are_generated_by_make_secrets() -> None:
    example = env_example()

    assert {key: example.get(key) for key in GENERATED_SECRETS} == dict.fromkeys(
        GENERATED_SECRETS, "change_me"
    )
```

Запусти: `uv run pytest tests/unit/test_airflow_env.py -q` → `1 failed, 1 passed` (нет `AIRFLOW_API_SECRET_KEY` в `.env.example`).

### A2. Образ

<!-- file: airflow/Dockerfile -->
```dockerfile
# Airflow 3.3.2 on Python 3.12, the Python of the host and CI (ADR-011). The bare 3.3.2 tag is
# Python 3.13. The docker provider is part of the image's extras.
FROM apache/airflow:3.3.2-python3.12

# Clients the DAG package imports, pinned by the constraints the image was built with.
RUN pip install --no-cache-dir --constraint "${HOME}/constraints.txt" \
      "apache-airflow==3.3.2" pydantic-settings trino "psycopg[binary]"

# dbt in Airflow's environment would fight Airflow over shared dependencies: a venv of its own,
# pinned to the versions in uv.lock.
USER root
RUN python -m venv /opt/dbt-venv \
    && /opt/dbt-venv/bin/pip install --no-cache-dir \
         dbt-core==1.10.23 dbt-trino==1.10.4 dbt-adapters==1.24.5 dbt-common==1.39.0
USER airflow
```

### A3. Конфигурация

<!-- file: docker/airflow/airflow.env -->
```bash
# Airflow 3.3.2, LocalExecutor (ADR-011). One file for api-server, scheduler and dag-processor:
# the JWT and API secrets must be the same in all three. Compose fills ${VAR} from .env here too.
AIRFLOW__CORE__EXECUTOR=LocalExecutor
# Tasks run as processes inside the scheduler container (600 MB limit): dbt build alone is one.
AIRFLOW__CORE__PARALLELISM=2
AIRFLOW__CORE__LOAD_EXAMPLES=False
# A new DAG starts paused: turning on silver_upsert makes Airflow the silver writer.
AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION=True
AIRFLOW__CORE__FERNET_KEY=${AIRFLOW_FERNET_KEY}
# No login, everyone is admin (D12): single-user laptop, port on 127.0.0.1 only.
AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_ALL_ADMINS=True
AIRFLOW__CORE__EXECUTION_API_SERVER_URL=http://airflow-api-server:8080/execution/
AIRFLOW__API_AUTH__JWT_SECRET=${AIRFLOW_JWT_SECRET}
# Signs the api-server's requests for task logs, which the scheduler container serves.
AIRFLOW__API__SECRET_KEY=${AIRFLOW_API_SECRET_KEY}
AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://${META_USER}:${META_PASSWORD}@postgres-meta:5432/${AIRFLOW_DB}
AIRFLOW__DAG_PROCESSOR__REFRESH_INTERVAL=60
_AIRFLOW_DB_MIGRATE=true

# silver_upsert starts spark-silver through DockerOperator: the compose network and the same
# environment as docker/compose.yaml gives spark-silver. tests/unit/test_dags.py compares them.
COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME}
SPARK_MASTER=${SPARK_MASTER}
SPARK_DRIVER_MEMORY=${SPARK_DRIVER_MEMORY}
CATALOG_TYPE=${CATALOG_TYPE}
CATALOG_JDBC_URL=jdbc:postgresql://postgres-meta:5432/${CATALOG_DB}
CATALOG_JDBC_USER=${META_USER}
CATALOG_JDBC_PASSWORD=${META_PASSWORD}
CATALOG_WAREHOUSE=s3a://${S3_BUCKET}/warehouse
CHECKPOINT_ROOT=s3a://${S3_BUCKET}/checkpoints
LAKEKEEPER_URI=${LAKEKEEPER_URI}
LAKEKEEPER_WAREHOUSE=${LAKEKEEPER_WAREHOUSE}
S3_ENDPOINT=${S3_ENDPOINT}
S3_ACCESS_KEY=${S3_ACCESS_KEY}
S3_SECRET_KEY=${S3_SECRET_KEY}

# dbt_build and dq_checks
TRINO_HOST=trino
TRINO_PORT=8080
OLTP_HOST=postgres-oltp
OLTP_PORT=5432
OLTP_DB=${OLTP_DB}
OLTP_USER=${OLTP_USER}
OLTP_PASSWORD=${OLTP_PASSWORD}
```

<!-- edit: .env.example -->
Найти:
```bash
AIRFLOW_JWT_SECRET=change_me
AIRFLOW_ADMIN_PASSWORD=change_me
```
Заменить на:
```bash
AIRFLOW_JWT_SECRET=change_me
AIRFLOW_API_SECRET_KEY=change_me
# group of /var/run/docker.sock (stat -c %g /var/run/docker.sock); empty means 0
DOCKER_GID=
```

<!-- edit: docker/compose.yaml -->
Найти:
```yaml
    env_file: ./airflow/airflow.env   # TODO(W3): executor, db url, fernet, jwt, statsd
```
Заменить на:
```yaml
    env_file: ./airflow/airflow.env   # TODO(W4-T01): statsd
```

<!-- edit: docker/compose.yaml -->
Найти:
```yaml
    command: scheduler
    env_file: ./airflow/airflow.env
```
Заменить на:
```yaml
    command: scheduler
    env_file: ./airflow/airflow.env
    # Tasks run here (LocalExecutor), DockerOperator among them: the socket's group, root on the
    # host in effect (ADR-011).
    group_add: ["${DOCKER_GID:-0}"]
```

Проверка: `uv run pytest tests/unit/test_airflow_env.py -q` → `2 passed`; `docker compose --env-file .env.example -f docker/compose.yaml --profile orchestrate config | grep -A1 group_add` → `- "0"`.

### A4. Pool и помощники

<!-- edit: Makefile -->
Найти:
```makefile
lakekeeper-bootstrap: ## bootstrap Lakekeeper and create its warehouse (safe to re-run)
	$(COMPOSE) --profile core run --rm lakekeeper-bootstrap
```
Заменить на:
```makefile
lakekeeper-bootstrap: ## bootstrap Lakekeeper and create its warehouse (safe to re-run)
	$(COMPOSE) --profile core run --rm lakekeeper-bootstrap

airflow-init: ## pool lake_writers, 1 slot, for silver_upsert and optimize (safe to re-run)
	$(COMPOSE) exec airflow-scheduler airflow pools set lake_writers 1 \
	  "silver writers: the silver_upsert merge and iceberg_maintenance optimize (ADR-010)"
```

<!-- edit: Makefile -->
Найти:
```makefile
lakekeeper-bootstrap lint
```
Заменить на:
```makefile
lakekeeper-bootstrap airflow-init lint
```

Помощники дописываются в конец `scripts/chaos/lib.sh`. `run_dag` никогда не снимает паузу: запуск DAG на паузе остаётся в очереди, а снятие паузы `silver_upsert` это решение вызывающего.

<!-- append: scripts/chaos/lib.sh -->
```bash

# The Airflow CLI inside the scheduler container.
airflow_cli() { "${COMPOSE[@]}" exec -T airflow-scheduler airflow "$@"; }

# dag_run_state <dag_id> <run_id>: queued, running, success or failed; missing before it exists.
dag_run_state() {
  airflow_cli dags list-runs "$1" -o json 2>/dev/null | python3 -c '
import json, sys
lines = sys.stdin.read().splitlines()
start = next((i for i, line in enumerate(lines)
              if line.strip() in ("[", "[]") or line.lstrip().startswith("[{")), None)
runs = json.loads("\n".join(lines[start:])) if start is not None else []
print(next((r["state"] for r in runs if r["run_id"] == sys.argv[1]), "missing"))' "$2"
}

# run_dag <dag_id> <run_id> [conf json]: trigger one run and wait up to RUN_DAG_WAIT seconds
# (default 900) for it to end: 0 on success, 1 when it failed or did not end in time. It never
# unpauses: a run of a paused DAG stays queued, and unpausing silver_upsert is the caller's call.
run_dag() {
  local dag=$1 run=$2 conf=${3:-"{}"} state limit=${RUN_DAG_WAIT:-900}
  local deadline=$((SECONDS + limit))
  airflow_cli dags trigger "$dag" --run-id "$run" --conf "$conf" >/dev/null
  while :; do
    state=$(dag_run_state "$dag" "$run")
    case $state in
      success) return 0 ;;
      failed)
        echo "$dag run $run failed" >&2
        return 1
        ;;
    esac
    if ((SECONDS >= deadline)); then
      echo "$dag run $run still $state after $limit s (a paused DAG keeps runs queued)" >&2
      return 1
    fi
    sleep 10
  done
}
```

### A5. Документация

Абзац про Fernet из PR #1 переезжает из раздела Lakekeeper в новый раздел Airflow.

<!-- edit: OPERATIONS.md -->
Найти:
````text
Airflow Fernet key. A `.env` from `make secrets` before the fix holds a 32-character
`AIRFLOW_FERNET_KEY`, and Airflow accepts only urlsafe base64 of 32 bytes (44 characters).
`make secrets` never rewrites an existing `.env`, so replace that one line from the repo root
before Airflow first starts; the command prints nothing. Once Airflow has stored connections or
variables, a new key makes them unreadable.

```
sed -i "s|^AIRFLOW_FERNET_KEY=.*|AIRFLOW_FERNET_KEY=$(python3 -c 'import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())')|" .env
```

After the cutover. Never start a Spark job with `CATALOG_TYPE=jdbc` (in `.env`, as
````
Заменить на:
```text
After the cutover. Never start a Spark job with `CATALOG_TYPE=jdbc` (in `.env`, as
```

<!-- edit: OPERATIONS.md -->
Найти:
```text
## Failure scenarios
```
Заменить на:
````text
## Airflow

Profile `orchestrate`: `airflow-api-server` (UI and REST API on `127.0.0.1:8090`, no login, every
visitor is admin: D12), `airflow-scheduler` (LocalExecutor: tasks run as processes inside this
container) and `airflow-dag-processor`. One image, `lakehouse/airflow:dev` from
`airflow/Dockerfile`: Airflow 3.3.2 on Python 3.12, dbt in `/opt/dbt-venv`. Config is
`docker/airflow/airflow.env`, values from `.env`. Metadata lives in the `airflow` database of
`postgres-meta`; the same instance holds `lakekeeper` and `iceberg_catalog`, which nothing here
touches.

Before the first start, once per `.env`, from the repo root (each command prints nothing):

```
sed -i "s|^AIRFLOW_FERNET_KEY=.*|AIRFLOW_FERNET_KEY=$(python3 -c 'import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())')|" .env
grep -q '^AIRFLOW_API_SECRET_KEY=' .env || printf 'AIRFLOW_API_SECRET_KEY=%s\n' "$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')" >> .env
grep -q '^DOCKER_GID=' .env || printf 'DOCKER_GID=%s\n' "$(stat -c %g /var/run/docker.sock)" >> .env
```

- Fernet key: a `.env` from `make secrets` before 2026-10-09 holds a 32-character
  `AIRFLOW_FERNET_KEY`, and Airflow accepts only urlsafe base64 of 32 bytes (44 characters).
  Replace it only before Airflow first starts: once Airflow has stored connections or variables,
  a new key makes them unreadable.
- `AIRFLOW_API_SECRET_KEY` signs the api-server's requests for task logs, which the scheduler
  container serves. Without it each process makes up its own, and the UI shows no task log.
- `DOCKER_GID` is the group of `/var/run/docker.sock`; the scheduler joins it (`group_add`) to
  start spark-silver through DockerOperator. Without it: `permission denied` on the socket.

Start, with Trino on a 2 GB heap (RAM, `docs/planning/00-mini-architecture-review.md` §6):

```
TRINO_XMX=2g make start          # recreates trino with -J-Xmx2g
make up PROFILE=orchestrate      # builds lakehouse/airflow:dev on the first run
make airflow-init                # pool lake_writers, 1 slot; safe to re-run
```

While `orchestrate` runs, every `make start` needs `TRINO_XMX=2g` in front: compose takes it from
the shell over `.env`, and without it recreates Trino with the 2500m of `.env`. Stop Airflow with
`make down PROFILE=orchestrate`; the next plain `make start` puts Trino back on 2500m.

Check it:

```
docker compose --env-file .env -f docker/compose.yaml exec airflow-scheduler airflow pools list
docker compose --env-file .env -f docker/compose.yaml exec airflow-scheduler airflow dags list-import-errors
docker compose --env-file .env -f docker/compose.yaml exec airflow-scheduler \
  python -c "import docker; print(docker.from_env().ping())"   # True
```

A new DAG starts paused (`AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION`): unpause it in the UI or
with `airflow dags unpause <dag_id>` in the scheduler container. A trigger of a paused DAG stays
queued. A new DAG file shows up within a minute (`AIRFLOW__DAG_PROCESSOR__REFRESH_INTERVAL=60`).

Measured on AIRFLOW_STATS_DATE (`docker stats`, idle, Trino at 2g): AIRFLOW_STATS.

## Failure scenarios
````

`DECISION_DATE` это дата «ок» владельца на D9 и D12, ISO.

<!-- edit: DECISIONS.md -->
Найти:
```text
| ADR-011 | Airflow 3 LocalExecutor, batch only, BashOperator for dbt (no Cosmos) | accepted |
```
Заменить на:
```text
| ADR-011 | Airflow 3 LocalExecutor, batch only, BashOperator for dbt (no Cosmos), DockerOperator for Spark silver | accepted |
```

<!-- edit: DECISIONS.md -->
Найти:
```text
## ADR-013 Spark metrics
```
Заменить на:
```text
## ADR-011 Airflow 3: LocalExecutor, dbt through BashOperator, Spark through DockerOperator

Context: Airflow orchestrates batch only (silver merge, dbt, data quality, maintenance); the bronze
stream is not a DAG. On a 16 GB laptop there is no room for Celery, a triggerer or Cosmos
(ADR-015).

Decision (DECISION_DATE, D9 and D12 of the week 3 spec):

- LocalExecutor; api-server, scheduler and dag-processor run one image, `lakehouse/airflow:dev`
  (`apache/airflow:3.3.2-python3.12`, the Python of the host). Tasks are processes in the
  scheduler container; `[core] parallelism` is 2 to fit its 600 MB.
- dbt through BashOperator: `dbt build` from a venv of its own in the image (`/opt/dbt-venv`,
  versions from `uv.lock`), because dbt next to Airflow fights it over shared dependencies. The
  project is mounted read-only, so target and log paths go to `/tmp`.
- Spark silver through DockerOperator: the scheduler starts `lakehouse/spark:dev` on the network
  `<COMPOSE_PROJECT_NAME>_lake` with the environment compose gives `spark-silver`, through the
  Docker socket. The socket is root on the host in effect; accepted for a single-user laptop with
  every port on 127.0.0.1. Only the scheduler joins the socket's group (`group_add`, `DOCKER_GID`
  in `.env`). The alternative, BashOperator with `docker compose run`, needs the compose CLI and
  the repo with its `.env` inside the image.
- No login (D12): SimpleAuthManager with `simple_auth_manager_all_admins`. Any process on the
  laptop can drive the DAGs, which is acceptable here. `AIRFLOW_ADMIN_PASSWORD` is gone from
  `.env.example`.
- `.env` gains `AIRFLOW_API_SECRET_KEY` (the api-server signs task-log requests to the scheduler
  with it; without a shared value the UI shows no task log) and `DOCKER_GID`.

Consequences: an image of AIRFLOW_IMAGE_SIZE to build, the socket as the price of DockerOperator,
the dbt version pinned twice (`uv.lock` and `airflow/Dockerfile`).

## ADR-013 Spark metrics
```

<!-- edit: docs/planning/00-mini-architecture-review.md -->
Найти:
```markdown
lakekeeper 91 MiB из лимита 256 MiB (36%, замер сразу после переключения каталога). spark-bronze в этот момент не замерялся.
```
Заменить на:
```markdown
lakekeeper 91 MiB из лимита 256 MiB (36%, замер сразу после переключения каталога). spark-bronze в этот момент не замерялся.

Замер AIRFLOW_STATS_DATE (W3-T04, `docker stats`, `orchestrate` в простое, Trino на 2g): AIRFLOW_STATS.
```

### A6. Статические проверки

```bash
make lint && make test 2>&1 | tail -1    # 129 passed, 62 skipped
```

## Часть B. Живая проверка

Предусловия: стек поднят; реплеер не играет. `$COMPOSE` это `docker compose --env-file .env -f docker/compose.yaml`.

### B1. Живой `.env`

Ключ Fernet меняется только до первого старта Airflow: потом им зашифрованы connections и variables. Airflow на этом ноутбуке ещё не запускался.

```bash
sed -i "s|^AIRFLOW_FERNET_KEY=.*|AIRFLOW_FERNET_KEY=$(python3 -c 'import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())')|" .env
grep -q '^AIRFLOW_API_SECRET_KEY=' .env || printf 'AIRFLOW_API_SECRET_KEY=%s\n' "$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')" >> .env
grep -q '^DOCKER_GID=' .env || printf 'DOCKER_GID=%s\n' "$(stat -c %g /var/run/docker.sock)" >> .env
awk -F= '/^AIRFLOW_FERNET_KEY=/{print length($2)} /^AIRFLOW_API_SECRET_KEY=/{print "api key set"} /^DOCKER_GID=/{print}' .env
```
Ожидается: `44`, `api key set`, `DOCKER_GID=1001`. Значения ключей в отчёт не попадают.

### B2. Старт

```bash
TRINO_XMX=2g make start
make up PROFILE=orchestrate
bash -c '. scripts/chaos/lib.sh; for s in airflow-api-server airflow-scheduler airflow-dag-processor; do wait_until 180 "$s healthy" service_healthy $s && echo "$s healthy"; done'
docker inspect -f '{{json .Config.Cmd}}' $($COMPOSE --profile '*' ps -q trino)
curl -s 127.0.0.1:8090/api/v2/monitor/health | head -c 200; echo
```
Ожидается: три строки `healthy` за 3 минуты; в команде Trino `-J-Xmx2g`; ответ health с `healthy`.

### B3. Pool, импорт DAG, сокет, dbt

```bash
make airflow-init
$COMPOSE exec airflow-scheduler airflow pools list
$COMPOSE exec airflow-scheduler airflow dags list-import-errors
$COMPOSE exec airflow-scheduler python -c "import docker; print(docker.from_env().ping())"
$COMPOSE exec airflow-scheduler /opt/dbt-venv/bin/dbt --version
```
Ожидается: `lake_writers` со слотами `1`; ошибок импорта нет; `True`; dbt-core 1.10.23 и trino 1.10.4.

### B4. Пробный DAG через execution API

Файл временный, в git не идёт.

```bash
cat > airflow/dags/probe_echo.py <<'EOF'
from datetime import datetime

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import dag


@dag(schedule=None, start_date=datetime(2026, 10, 1), catchup=False)
def probe_echo() -> None:
    BashOperator(task_id="echo", bash_command="echo ok")


probe_echo()
EOF
bash -c '. scripts/chaos/lib.sh; wait_until 120 "probe_echo parsed" bash -c "airflow_cli dags list 2>/dev/null | grep -q probe_echo"'
$COMPOSE exec airflow-scheduler airflow dags unpause probe_echo
bash -c '. scripts/chaos/lib.sh; run_dag probe_echo probe-1 && echo "probe ok"'
```
Ожидается: `probe ok`. Затем в UI `http://127.0.0.1:8090`: DAG `probe_echo`, запуск `probe-1`, задача `echo`, вкладка логов содержит `ok`. Пустой лог или 403: `AIRFLOW_API_SECRET_KEY` не дошёл до контейнеров, B1. После проверки: `rm airflow/dags/probe_echo.py` (только этот файл, созданный тобой).

### B5. Замеры

```bash
docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' | grep -E 'airflow|trino'
docker images lakehouse/airflow:dev --format '{{.Size}}'
```
Замени `AIRFLOW_STATS` (память трёх сервисов и Trino, как в выводе), `AIRFLOW_STATS_DATE` (сегодня), `AIRFLOW_IMAGE_SIZE` (размер образа), `DECISION_DATE` (дата «ок» на D9 и D12). Затем `git grep -nE 'AIRFLOW_STATS|AIRFLOW_IMAGE_SIZE|DECISION_DATE' -- . ':!docs/planning/08-w3-plan'` пусто и `make lint && make test` зелёные.

## Готово, когда

- `TRINO_XMX=2g make start && make up PROFILE=orchestrate`: три сервиса healthy за 3 минуты, `127.0.0.1:8090` отвечает, у Trino `-J-Xmx2g` (B2).
- `airflow pools list`: `lake_writers`, 1 слот; `airflow dags list-import-errors` пусто (B3).
- Пробный DAG с `echo ok` успешен, лог виден в UI (B4).
- `/opt/dbt-venv/bin/dbt --version`: dbt-trino 1.10.4 (B3).
- `make test` (тест `.env`), `make lint` зелёные; `docker stats` записан (B5).

## Если не так

| Симптом | Причина | Что делать |
|---|---|---|
| B2: api-server не healthy, в логе `Fernet key must be 32 url-safe base64-encoded bytes` | B1 не выполнен | B1, затем `make up PROFILE=orchestrate` |
| B2: scheduler падает с OOM (`docker inspect -f '{{.State.OOMKilled}}'` true) | 600 MB мало | стоп: лимиты это решение владельца |
| B3: `PermissionError` или `permission denied` на сокете | `DOCKER_GID` пуст или не тот | B1, затем `make up PROFILE=orchestrate`; снова: стоп |
| B4: задача в `queued` или падает с ошибкой авторизации execution API | разные JWT у сервисов или неверный `EXECUTION_API_SERVER_URL` | сверь `docker/airflow/airflow.env` с блоком плана; стоп |
| B4: лог задачи пустой или 403 | нет общего `AIRFLOW_API_SECRET_KEY` | B1, пересоздать сервисы `make up PROFILE=orchestrate` |
| сборка образа: конфликт зависимостей pip | constraints образа не приняли пакет | стоп, вывод сборки в отчёт |

## Ловушки

- Ключ Fernet в 32 символа Airflow не примет; менять его безопасно только до первого запуска.
- Разные JWT-секреты у api-server и scheduler: задачи падают на авторизации в execution API.
- `EXECUTION_API_SERVER_URL` по умолчанию смотрит в localhost контейнера scheduler: задачи не стартуют.
- dbt в одном окружении с Airflow ломает зависимости Airflow, поэтому отдельный venv.
- `make start` без `TRINO_XMX=2g` при работающем Airflow пересоздаёт Trino на 2500m.

## Blast radius и пайплайн

Нет. Правка живого `.env` (B1) безопасна только потому, что Airflow ещё не стартовал. В `postgres-meta` живут БД `lakekeeper` и `iceberg_catalog`: их не трогать. Удаляется только временный `airflow/dags/probe_echo.py`.

## Отчёт: что собрать

Вывод B1 без значений ключей, B2 и B3, `probe ok` и подтверждение лога в UI, замеры B5, `git diff --stat`.

## Коммит

```bash
git add airflow/Dockerfile docker/airflow/airflow.env docker/compose.yaml .env.example Makefile \
  scripts/chaos/lib.sh tests/unit/test_airflow_env.py OPERATIONS.md DECISIONS.md \
  docs/planning/00-mini-architecture-review.md
git commit -m "orchestrate: airflow image, env and pool"
```
