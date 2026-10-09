# W3-T00 Путь с чистого клона: `make start`, `bootstrap`, `verify`, `replay-burst`

> До первого шага прочитай `README.md` этой папки: протокол, стоп-условия, отчёт.

| | |
|---|---|
| Спека | `07-w3-spec.md`, карточка W3-T00; решения D1, D2 |
| Уже сделано | шаг 6 карточки (`REPLAY_DATA`), PR #1, c52d5cc |
| Коммит | `infra: make start, bootstrap, verify and replay-burst` |
| Оценка | A: 1 ч; B: 2 ч, из них около часа ожидания сборки и загрузки |
| Часть A | любая среда |
| Часть B | только локально: живой стек останавливается, поднимается одноразовый проект `lakehouse-fresh` |

## Цель

`make bootstrap` доводит чистый клон до данных в bronze и silver и печатает `verify ok`; повторный запуск ничего не ломает; контейнер реплеера сам не стартует (D1); порции реплея идут командой `make replay-burst` (D2).

## Вход

```bash
git status --short                                     # пусто
git merge-base --is-ancestor c52d5cc HEAD && echo ok   # ok
grep -c '^replay:' Makefile                            # 1: старая цель ещё на месте
grep -c 'def raw_dir(settings' oltp/replayer/load.py   # 1: шаг 6 сделан
uv run pytest tests/unit -q 2>&1 | tail -1             # 120 passed, 62 skipped
```

## Файлы

- Создать: `tests/unit/test_makefile.py`, `scripts/replay-burst.sh`, `scripts/verify.sh`, `scripts/bootstrap.sh`.
- Изменить: `scripts/chaos/lib.sh`, `Makefile`, `README.md`, `OPERATIONS.md`, `DECISIONS.md`, `scripts/README.md`, `docs/HANDOFF.md`.

## Что задача даёт следующим

- `make start`: `core` без `oltp-replayer` плюс `trino`. `make up` отказывается (код 2), если `PROFILE` содержит `core`.
- `make bootstrap`, `make verify` (последняя строка `verify ok` или `verify failed: <причина>`), `make replay-burst SECONDS=<n> [SPEED=720]`, `make replay-live`.
- В `scripts/chaos/lib.sh`: `service_healthy <service>`, `bronze_offsets_ok`, `virtual_now`.

## Часть A. Код

### A1. Тест на отказ, первым

Тест подменяет `COMPOSE` на `echo`: даже старая цель `up` ничего не запускает, поэтому его безопасно гонять до правки Makefile.

<!-- file: tests/unit/test_makefile.py -->
```python
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def make(*args: str) -> subprocess.CompletedProcess[str]:
    # COMPOSE=echo: a target that does not refuse prints its compose command instead of starting
    # containers, so no run of this file can start the replayer. make also reads PROFILE, SECONDS
    # and SPEED from the environment; a developer's shell must not decide the outcome.
    env = {k: v for k, v in os.environ.items() if k not in {"PROFILE", "SECONDS", "SPEED"}}
    return subprocess.run(
        ["make", "--no-print-directory", "-C", str(REPO), "COMPOSE=echo docker compose", *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


@pytest.mark.parametrize("profile", ["core", "core,query", "query,core"])
def test_up_refuses_any_profile_with_core(profile: str) -> None:
    result = make("up", f"PROFILE={profile}")

    assert result.returncode == 2
    assert "make start" in result.stderr


def test_up_without_profile_means_core_and_refuses() -> None:
    result = make("up")

    assert result.returncode == 2
    assert "make start" in result.stderr


@pytest.mark.parametrize("args", [(), ("SECONDS=abc",), ("SECONDS=60", "SPEED=0")])
def test_replay_burst_refuses_without_positive_seconds_and_speed(args: tuple[str, ...]) -> None:
    result = make("replay-burst", *args)

    assert result.returncode == 2
    assert "usage: make replay-burst" in result.stderr
```

Запусти: `uv run pytest tests/unit/test_makefile.py -q`
Ожидается: `7 failed`. Увидел `passed`: стоп, Makefile уже менялся.

### A2. Функции в `scripts/chaos/lib.sh`

<!-- edit: scripts/chaos/lib.sh -->
Найти:
```bash
healthy() { [ "$(docker inspect -f '{{.State.Health.Status}}' "$1" 2>/dev/null)" = healthy ]; }
```
Заменить на:
```bash
healthy() { [ "$(docker inspect -f '{{.State.Health.Status}}' "$1" 2>/dev/null)" = healthy ]; }

# service_healthy <service>: the container of a compose service reports healthy. Looked up by id,
# so it works under any COMPOSE_PROJECT_NAME (a fresh clone runs as lakehouse-fresh).
service_healthy() {
  local id
  id=$("${COMPOSE[@]}" --profile '*' ps -q "$1") && [ -n "$id" ] && healthy "$id"
}
```

<!-- edit: scripts/chaos/lib.sh -->
Найти:
```bash
# Returns 2, so a script under set -e stops with 2 before it touches anything.
```
Заменить на:
```bash
# The replayer's virtual clock; fails when there is no replay state (`replayer status` exits 1).
virtual_now() {
  (cd "$ROOT" && PYTHONPATH=oltp .venv/bin/python -m replayer status) |
    python3 -c 'import json, sys; print(json.load(sys.stdin)["virtual_now"])'
}

# Returns 2, so a script under set -e stops with 2 before it touches anything.
```

<!-- edit: scripts/chaos/lib.sh -->
Найти:
```bash
         from bronze.cdc_events group by 1, 2 order by 1, 2"
}
```
Заменить на:
```bash
         from bronze.cdc_events group by 1, 2 order by 1, 2"
}

# bronze_offsets_report for scripts: 1 when some topic partition holds an offset twice or misses
# one between its lowest and highest offset, 2 when the query fails.
bronze_offsets_ok() {
  local bad
  bad=$(trino_value "select count(*) from (
                       select 1 from bronze.cdc_events group by topic, kafka_partition
                       having count(*) > count(distinct kafka_offset)
                          or max(kafka_offset) - min(kafka_offset) + 1
                            > count(distinct kafka_offset))") || return 2
  [ "$bad" = 0 ]
}
```

Проверка: `bash -n scripts/chaos/lib.sh && echo ok` печатает `ok`.

### A3. Три скрипта

Скрипты, как и chaos-сценарии, запускаются через `bash` и не помечаются исполняемыми.

<!-- file: scripts/replay-burst.sh -->
```bash
#!/usr/bin/env bash
# make replay-burst SECONDS=<n> [SPEED=720]: play <n> real seconds of the replay schedule on the
# host, then stop. The virtual clock before and after shows what the burst spent of the replay
# budget (D2 in docs/planning/07-w3-spec.md).
set -euo pipefail
seconds=${1:-}
speed=${2:-720}
if ! [[ $seconds =~ ^[1-9][0-9]*$ && $speed =~ ^[1-9][0-9]*$ ]]; then
  echo "usage: make replay-burst SECONDS=<n> [SPEED=720], both positive integers" >&2
  exit 2
fi
. "$(dirname "$0")/chaos/lib.sh"

no_other_replayer
before=$(virtual_now)
echo "virtual_now before: $before"
CHAOS_REPLAY_SPEED=$speed replay_burst "$seconds"
after=$(virtual_now)
echo "virtual_now after:  $after"
```

`scripts/verify.sh`. Порядок важен: сначала отказы (Airflow, реплеер), потом ожидание bronze, один merge silver, проверки. Ожидание `VERIFY_WAIT` по умолчанию 900 с: initial load полного набора около полумиллиона событий, bronze берёт 20 000 offsets за триггер 20 с.

<!-- file: scripts/verify.sh -->
```bash
#!/usr/bin/env bash
# make verify: data went through the whole stack. Bronze holds every Kafka record exactly once,
# silver equals Postgres, all seven source tables reached bronze. Ends with `verify ok` or the
# reason and a non-zero exit code. It runs one silver merge, so it refuses while Airflow may run
# another (two writers on one checkpoint) and while a replayer plays (reconcile would compare a
# moving source).
. "$(dirname "$0")/chaos/lib.sh"

fail() {
  echo "verify failed: $*" >&2
  exit 1
}

if [ -n "$("${COMPOSE[@]}" --profile '*' ps -q airflow-scheduler)" ]; then
  echo "airflow-scheduler is running and may merge silver at the same time: pause silver_upsert" \
    "and stop the scheduler first (OPERATIONS.md, Airflow)" >&2
  exit 2
fi
no_other_replayer
wait="${VERIFY_WAIT:-900}"
wait_until "$wait" "bronze to catch up with Kafka" bronze_caught_up ||
  fail "bronze did not catch up with Kafka in $wait s"
run_silver || fail "silver_upsert failed"
bronze_offsets_ok || fail "bronze holds a Kafka offset twice or misses one"
reconcile || fail "silver differs from Postgres, or a count query failed (table above)"
tables=$(trino_value "select count(distinct source_table) from bronze.cdc_events
                      where source_table in ('customers', 'sellers', 'products', 'orders',
                                             'order_items', 'payments', 'reviews')") ||
  fail "counting the source tables in bronze failed"
[ "$tables" = 7 ] || fail "bronze holds events of $tables of the 7 source tables"
echo "verify ok"
```

`scripts/bootstrap.sh`. Каждый шаг идемпотентен; `protect.sh` последним, потому что на чистом стеке таблиц silver нет до первого merge внутри `verify`.

<!-- file: scripts/bootstrap.sh -->
```bash
#!/usr/bin/env bash
# make bootstrap: from a fresh clone with a .env (make secrets) to verified data in bronze and
# silver, protected in Lakekeeper. Safe to re-run: each step checks before it changes anything,
# and none deletes. The first run on the full dataset is long: Spark image build, initial load.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$root/.env" ] || { echo "no .env in $root: run make secrets first" >&2; exit 2; }
. "$root/scripts/chaos/lib.sh"

in_root() { make -C "$ROOT" --no-print-directory "$@"; }

in_root start
for service in spark-bronze kafka-connect trino; do
  wait_until 300 "$service to turn healthy" service_healthy "$service"
done
in_root migrate
bash "$ROOT/connect/register.sh"
if status=$(cd "$ROOT" && PYTHONPATH=oltp .venv/bin/python -m replayer status 2>&1); then
  echo "replay state exists, load skipped"
elif [[ $status == *"no replay state"* ]]; then
  in_root replay-load
else
  printf '%s\n' "$status" >&2
  echo "bootstrap: replayer status failed, output above" >&2
  exit 1
fi
bash "$ROOT/scripts/verify.sh"
# Last: on a fresh stack the silver tables appear only with verify's first silver run.
bash "$ROOT/scripts/lakekeeper/protect.sh"
```

Проверка: `for f in scripts/replay-burst.sh scripts/verify.sh scripts/bootstrap.sh; do bash -n $f || echo "BAD $f"; done` ничего не печатает.

### A4. Makefile

<!-- edit: Makefile -->
Найти:
```makefile
PROFILE ?= core
```
Заменить на:
```makefile
PROFILE ?= core
SPEED ?= 720
```

<!-- edit: Makefile -->
Найти:
```makefile
# ---------------------------------------------------------------- lifecycle
up: ## start profiles: make up PROFILE=core,query
	$(COMPOSE) $(PROFILE_FLAGS) up -d --build
```
Заменить на:
```makefile
# ---------------------------------------------------------------- lifecycle
start: ## core without the replayer container, plus trino (ADR-016)
	$(COMPOSE) --profile core --profile query up -d --build spark-bronze kafka-connect trino

up: ## start profiles other than core: make up PROFILE=orchestrate (core goes through make start)
	@case ",$(PROFILE)," in *,core,*) \
	  echo "PROFILE=$(PROFILE) includes core, whose oltp-replayer plays at REPLAY_SPEED;" \
	    "use make start (ADR-016)" >&2; exit 2;; esac
	$(COMPOSE) $(PROFILE_FLAGS) up -d --build
```

Цель `replay` удаляется: она запускала второй реплеер в контейнере, где первый уже держит порт 8000.

<!-- edit: Makefile -->
Найти:
```makefile
# ---------------------------------------------------------------- operate
replay: ## register debezium connector and start the replayer
	bash connect/register.sh
	$(COMPOSE) exec oltp-replayer python -m replayer start

```
Заменить на:
```makefile
bootstrap: ## fresh clone to verified data: start, migrate, connector, load, verify, protect
	@bash scripts/bootstrap.sh

# ---------------------------------------------------------------- operate
verify: ## bronze holds every Kafka record once and silver equals Postgres: prints verify ok
	@bash scripts/verify.sh

replay-burst: ## play SECONDS of history on the host, then stop: make replay-burst SECONDS=60 [SPEED=720]
	@bash scripts/replay-burst.sh "$(SECONDS)" "$(SPEED)"

replay-live: ## spends the replay budget: the oltp-replayer container plays at REPLAY_SPEED until stopped
	$(COMPOSE) --profile core up -d --build oltp-replayer

```

<!-- edit: Makefile -->
Найти:
```makefile
replay-reset up down status logs nuke replay replay-status silver
```
Заменить на:
```makefile
replay-reset start up down status logs nuke bootstrap verify replay-burst replay-live replay-status silver
```

Проверки:

- `uv run pytest tests/unit/test_makefile.py -q` → `7 passed`.
- `make up PROFILE=core; echo "exit $?"` → строка `PROFILE=core includes core, ... use make start (ADR-016)` и `exit 2`. Ничего не запускается.
- `make -n start` → одна строка `docker compose ... --profile core --profile query up -d --build spark-bronze kafka-connect trino`.
- `make help | grep -E '^  (start|bootstrap|verify|replay-burst|replay-live) '` → пять строк.

### A5. Статические проверки

```bash
make lint                       # код 0
make test 2>&1 | tail -1        # 127 passed, 62 skipped
```

### A6. Документация

Маркеры `FRESH_MINUTES`, `FRESH_BUILD_MINUTES`, `FRESH_DATE`, `DECISION_DATE` заполняет часть B (B8). Облачная сессия оставляет их как есть.

<!-- edit: README.md -->
Найти:
````text
make secrets                 # generates .env from .env.example
make hooks                   # installs pre-commit hooks (ruff, yamllint, gitleaks)
make data                    # downloads the Olist dataset into data/raw (Kaggle CLI or manual)
make up PROFILE=core         # postgres x2, kafka, connect, minio, lakekeeper, spark-bronze, replayer
make up PROFILE=query        # trino
make replay                  # initial load + start replaying history
make psql                    # source database
make trino                   # trino cli
```

Never start every profile at once on 16 GB. Working combinations are listed in
[OPERATIONS.md](OPERATIONS.md).
````
Заменить на:
````text
make secrets                  # generates .env from .env.example
make hooks                    # installs pre-commit hooks (ruff, yamllint, gitleaks)
make data                     # downloads the Olist dataset into data/raw (Kaggle CLI or manual)
make bootstrap                # core + trino, schema, connector, initial load; ends with "verify ok"
make replay-burst SECONDS=60  # plays about 12 virtual hours of the remaining history, then stops
make verify                   # bronze holds every Kafka record once, silver equals Postgres
make psql                     # source database
make trino                    # trino cli
```

Without a Kaggle account, skip `make data` and set `REPLAY_DATA=sample` in `.env`: the
committed 2 000-order slice in `data/sample`. From a fresh clone on the sample, `make bootstrap`
took FRESH_MINUTES minutes with the images built; the first build of the Spark image adds
FRESH_BUILD_MINUTES minutes, mostly 400 MB of jars (FRESH_DATE).

`make start` brings up `core` and `query` without the replayer container, which would play the
rest of the history at full speed; `make up` refuses any `PROFILE` that contains `core`
(ADR-016). Never start every profile at once on 16 GB. Working combinations are listed in
[OPERATIONS.md](OPERATIONS.md).
````

<!-- edit: README.md -->
Найти:
```text
lakekeeper (Iceberg REST catalog), spark-bronze, oltp-replayer | ~7.5 GB |
```
Заменить на:
```text
lakekeeper (Iceberg REST catalog), spark-bronze; oltp-replayer only through `make replay-live` | ~7.5 GB |
```

<!-- edit: OPERATIONS.md -->
Найти:
```text
| Daily work on ingestion | `make up PROFILE=core,query` | ~11 GB limits, ~7 GB real |
| Working on dbt / Airflow | `make up PROFILE=core,query,orchestrate` (Trino `Xmx` drops to 2g via `TRINO_XMX`); stop `orchestrate` when not working on batch | ~13 GB limits, ~9 GB real |
| Full pipeline with monitoring | `make up PROFILE=core,query,orchestrate,obs` | ~14 GB limits, ~10 GB real |
```
Заменить на:
```text
| Daily work on ingestion | `make start` | ~11 GB limits, ~7 GB real |
| Working on dbt / Airflow | `make start && make up PROFILE=orchestrate` (Trino `Xmx` drops to 2g via `TRINO_XMX`); stop `orchestrate` when not working on batch | ~13 GB limits, ~9 GB real |
| Full pipeline with monitoring | `make start && make up PROFILE=orchestrate,obs` | ~14 GB limits, ~10 GB real |
```

<!-- edit: OPERATIONS.md -->
Найти:
````text
`rest` profile any more. Both images in `core` (`lakehouse/replayer:dev`, `lakehouse/spark:dev`)
are built by `make up`. To work on one service without the replayer playing, start it by name
(Spark and Trino bring Lakekeeper up first):

```
docker compose --env-file .env -f docker/compose.yaml --profile core up -d spark-bronze
```
````
Заменить на:
```text
`rest` profile any more. `make start` brings up `core` without `oltp-replayer`, plus `trino`: it
names `spark-bronze kafka-connect trino`, and their `depends_on` pull in the rest of `core`
(ADR-016). `make up` refuses any `PROFILE` that contains `core`, because that would start the
replayer container, which plays at `REPLAY_SPEED` (2880, one virtual day per 30 s) until stopped.
The rest of the history is a budget for the remaining weeks (D2 in
`docs/planning/07-w3-spec.md`), so traffic comes in bursts from the host:
`make replay-burst SECONDS=<n>` plays `n` real seconds at 720x and stops. `make replay-live`
starts the container on purpose, for a continuous demo; stop it with
`docker compose --env-file .env -f docker/compose.yaml stop oltp-replayer`.
```

<!-- edit: OPERATIONS.md -->
Найти:
````text
First run, source side:

```
make data            # download Olist into data/raw
make migrate         # create schema shop
make replay-load     # shift dates onto today, load the initial share, build the schedule
make replay-start    # play the rest on the virtual clock (REPLAY_SPEED, default 1 day / 30 s)
```
````
Заменить на:
````text
First run, from a fresh clone:

```
make secrets         # .env with generated passwords; REPLAY_DATA=sample skips the download
make data            # download Olist into data/raw (not needed with REPLAY_DATA=sample)
make bootstrap       # start, migrate, connector, replay-load, verify, protect; safe to re-run
```

`make bootstrap` runs, in order: `make start`; a wait of up to 5 minutes for `spark-bronze`,
`kafka-connect` and `trino` to turn healthy; `make migrate`; `connect/register.sh`;
`make replay-load` unless a replay state exists (`replay state exists, load skipped`);
`make verify`; `scripts/lakekeeper/protect.sh`. None of the steps deletes anything. From a fresh
clone on the sample it took FRESH_MINUTES minutes with the images built; the first build of the
Spark image adds FRESH_BUILD_MINUTES minutes (FRESH_DATE).

`make verify` refuses (exit 2) while `airflow-scheduler` runs or a replayer answers on port 8000.
Otherwise it waits up to `VERIFY_WAIT` seconds (default 900) for bronze to catch up with Kafka,
runs one silver merge, and checks that every Kafka offset is in bronze exactly once, that live
silver rows equal Postgres for all seven tables, and that all seven tables reached bronze. The
last line is `verify ok` or `verify failed: <reason>`.

```
make replay-burst SECONDS=60   # about 12 virtual hours at 720x; prints virtual_now before and after
make replay-start              # plays until ctrl-c at REPLAY_SPEED (1 day / 30 s): spends the budget
```
````

<!-- edit: OPERATIONS.md -->
Найти:
```text
`lakehouse/spark:dev` with `pull_policy: never`, so build that image first (`make up` does);
```
Заменить на:
```text
`lakehouse/spark:dev` with `pull_policy: never`, so build that image first (`make start` does);
```

<!-- edit: OPERATIONS.md -->
Найти:
```text
re-creatable from the repo. `make nuke && make up && make replay` is the restore procedure and
is itself a test that the repo is complete.
```
Заменить на:
```text
re-creatable from the repo. `make nuke && make bootstrap` is the restore procedure and is itself
a test that the repo is complete.
```

Раздел ADR-016 (сейчас в `DECISIONS.md` только строка индекса). `DECISION_DATE` это дата «ок» владельца на D1, ISO.

<!-- edit: DECISIONS.md -->
Найти:
```text
| ADR-016 | Compose profiles and the rule "never all profiles at once" as the RAM strategy | accepted |
```
Заменить на:
```text
| ADR-016 | Compose profiles and the rule "never all profiles at once" as the RAM strategy; `core` starts without the replayer container (`make start`) | accepted |
```

<!-- edit: DECISIONS.md -->
Найти:
```text
## ADR-018 REPLICA IDENTITY FULL on the source tables
```
Заменить на:
```text
## ADR-016 Compose profiles; the replayer container only on request

Context: on a 16 GB laptop the services run in profiles (`core`, `query`, `orchestrate`, `obs`,
`bi`, `tools`), never all at once (OPERATIONS.md, "Profiles"). `oltp-replayer` is in `core`, so
`make up PROFILE=core` also started the replayer container, which plays at `REPLAY_SPEED` (2880,
one virtual day per 30 s). From week 3 the rest of the history is a budget for weeks 3-6 (D2 in
`docs/planning/07-w3-spec.md`): on 2026-10-09 about 72 virtual days, 36 minutes at that speed.

Decision (DECISION_DATE, D1 of the week 3 spec): compose stays as it is. `make start` brings up
`core` without `oltp-replayer`, plus `trino`, by naming `spark-bronze kafka-connect trino`; their
`depends_on` pull in the rest of `core`. `make up` refuses any `PROFILE` that contains `core`.
Traffic comes from `make replay-burst SECONDS=<n>`, which plays `n` real seconds on the host and
stops; the container starts only through `make replay-live`.

Alternatives: a profile `replay` for `oltp-replayer` (one line of compose, but a change of
infrastructure); keeping `make up PROFILE=core` with a warning (the failure stays one command
away).

Consequences: `make up PROFILE=core` from older notes now fails with a hint instead of spending
the replay; a fresh clone starts with `make bootstrap`.

## ADR-018 REPLICA IDENTITY FULL on the source tables
```

<!-- edit: scripts/README.md -->
Найти:
```text
- `make_env.py`: generates `.env`.
```
Заменить на:
```text
- `make_env.py`: generates `.env`.
- `bootstrap.sh` (W3-T00, `make bootstrap`): fresh clone to verified data; start, migrate,
  connector, load unless a replay state exists, verify, protect. Safe to re-run, deletes nothing.
- `verify.sh` (W3-T00, `make verify`): waits for bronze to catch up with Kafka, runs one silver
  merge, checks Kafka offsets in bronze, silver against Postgres and all seven tables in bronze;
  prints `verify ok`. Refuses while `airflow-scheduler` runs or a replayer plays.
- `replay-burst.sh` (W3-T00, `make replay-burst SECONDS=<n> [SPEED=720]`): plays `n` real
  seconds of the replay schedule on the host, prints the virtual clock before and after.
```

<!-- edit: docs/HANDOFF.md -->
Найти:
```text
| W2-T09 Lakekeeper | сделано: side by side 5cf0fec, переключение 08.10, коммит `lake: spark and trino switched to lakekeeper` |
```
Заменить на:
```text
| W2-T09 Lakekeeper | сделано: side by side 5cf0fec, переключение 08.10, коммит `lake: spark and trino switched to lakekeeper` |
| W3-T00 путь с чистого клона | сделано FRESH_DATE: `make bootstrap` на сэмпле FRESH_MINUTES мин при собранных образах, первая сборка образа Spark ещё FRESH_BUILD_MINUTES мин |
```

Проверка части A: `make lint`, `make test` зелёные, `git grep -n 'make replay\b' -- README.md OPERATIONS.md` пусто.

## Часть B. Живая проверка

Предусловия: часть A сделана в этом рабочем дереве; Airflow не запущен; реплеер не играет (`curl -sf 127.0.0.1:8000/health` не отвечает).

### B1. Живой стек догоняет Kafka и останавливается

Тома остаются. Простой дольше 24 часов недопустим: непрочитанное уйдёт по retention Kafka.

```bash
bash -c '. scripts/chaos/lib.sh && wait_until 300 "bronze to catch up with Kafka" bronze_caught_up && echo caught up'
make down PROFILE=core,query
docker ps --format '{{.Names}}' | grep -c '^lakehouse-'
```
Ожидается: `caught up`, затем `0`.

### B2. Одноразовый клон с диффом задачи

```bash
git add -N scripts/replay-burst.sh scripts/verify.sh scripts/bootstrap.sh tests/unit/test_makefile.py
git clone --quiet "$PWD" ../lakehouse-fresh
git diff HEAD --binary | git -C ../lakehouse-fresh apply
cd ../lakehouse-fresh
make secrets
sed -i 's/^COMPOSE_PROJECT_NAME=.*/COMPOSE_PROJECT_NAME=lakehouse-fresh/; s/^REPLAY_DATA=.*/REPLAY_DATA=sample/' .env
grep -E '^(COMPOSE_PROJECT_NAME|REPLAY_DATA)=' .env
```
Ожидается: `COMPOSE_PROJECT_NAME=lakehouse-fresh` и `REPLAY_DATA=sample`. `git clone` упал, потому что `../lakehouse-fresh` уже есть: стоп, удалять каталог нельзя, нужен «ок» владельца.

### B3. `make bootstrap` с нуля, со временем

```bash
start=$(date +%s); make bootstrap; echo "exit $? after $(( ($(date +%s) - start) / 60 )) min"
```
Ожидается в конце: `verify ok`, `all 9 bronze and silver tables are protected`, `exit 0 after N min`. N это `FRESH_MINUTES`.

### B4. Повторный `make bootstrap`

```bash
make bootstrap 2>&1 | grep -E 'load skipped|verify ok|protected'
```
Ожидается: `replay state exists, load skipped`, `verify ok`, строки `already protected` и итоговая строка про 9 таблиц.

### B5. Контейнера реплеера нет

```bash
docker compose --env-file .env -f docker/compose.yaml --profile '*' ps -q oltp-replayer | wc -l
make up PROFILE=core; echo "exit $?"
```
Ожидается: `0`, затем отказ с подсказкой `make start` и `exit 2`.

### B6. Холодная сборка образа Spark

Образ `lakehouse/spark:dev` у проектов общий и уже был в кэше, поэтому B3 его не собирал. Честное время с нуля включает сборку; меряется отдельным тегом, рабочий образ не трогается.

```bash
start=$(date +%s)
docker build --no-cache --build-context contracts=contracts -t lakehouse/spark:cold-check streaming >/dev/null
echo "cold build $(( ($(date +%s) - start) / 60 )) min"
docker image rm lakehouse/spark:cold-check
```
Число это `FRESH_BUILD_MINUTES`.

### B7. Клон останавливается, живой стек поднимается

```bash
docker compose --env-file .env -f docker/compose.yaml --profile '*' down
cd -
make replay-status | grep virtual_now
make start
make verify
make replay-status | grep virtual_now
```
Ожидается: `down` без `-v` (тома клона остаются до «ок» владельца на их удаление), `verify ok` на живом стеке, `virtual_now` до и после одинаковое.

### B8. Замеры в документацию

Замени во всех местах: `FRESH_MINUTES` (B3), `FRESH_BUILD_MINUTES` (B6), `FRESH_DATE` (сегодня, ISO), `DECISION_DATE` (дата «ок» владельца на D1, ISO).

```bash
git grep -nE 'FRESH_|DECISION_DATE' -- . ':!docs/planning'   # пусто
make lint && make test 2>&1 | tail -1
```

## Готово, когда

- Чистый клон на сэмпле: `make bootstrap` код 0 и `verify ok`; повторный запуск: код 0, `load skipped`, `verify ok` (B3, B4).
- `ps -q oltp-replayer` пуст в обоих проектах (B5 и тот же запрос в основном каталоге).
- Живой стек: `make start && make verify` печатает `verify ok`, `virtual_now` до и после одинаковое (B7).
- `make up PROFILE=core` отказывается и подсказывает `make start` (A4, B5).
- `make lint`, `make test` (127 passed) зелёные.
- Отказ `make verify` при запущенном `airflow-scheduler` проверяется в W3-T05a, когда Airflow появится.

## Если не так

| Симптом | Причина | Что делать |
|---|---|---|
| `port is already allocated` в B3 | живой стек не остановлен | B1 заново |
| `no .env in ...: run make secrets first` | пропущен `make secrets` | B2 заново с `make secrets` |
| `missing in data/sample` | `REPLAY_DATA` не `sample` или в клоне нет c52d5cc | проверить `.env` клона и вход задачи |
| `timed out ... spark-bronze to turn healthy` | первая сборка, медленный старт | `make bootstrap` ещё раз (идемпотентен); второй раз то же: стоп |
| `verify failed: bronze did not catch up` на полном наборе | initial load дольше 900 с | `VERIFY_WAIT=1800 make verify`; не помогло: стоп |
| `verify failed: silver differs from Postgres` | играл реплеер, или bronze не догнал | стоп, в отчёт таблицу `reconcile` |
| `protect.sh: no tables in namespace silver` | `verify` не дошёл до merge | стоп |
| `verify` на живом стеке печатает DIFF | живой стек не догнал до остановки | стоп, в отчёт вывод B1 и таблицу |

## Ловушки

- Скрипты, которые ищут контейнер по имени `lakehouse-<service>-1` (`spark-kill.sh`, `connect-restart.sh`, `late.sh`), в проекте `lakehouse-fresh` его не найдут. В `start`, `verify`, `bootstrap` только `$COMPOSE ps` и `exec`.
- Образы `lakehouse/spark:dev` и `lakehouse/replayer:dev` общие для обоих проектов: сборка в клоне перетегирует их, поэтому в клоне ровно код рабочего дерева.
- Порт 8000 один на хост: пока играет `make replay-start` или контейнер реплеера, `replay-burst` и `verify` отказываются с кодом 2. Это ожидаемо.
- `reconcile` при идущем реплее даёт ложный DIFF, поэтому `verify` сначала проверяет реплеер и ждёт bronze.
- `SECONDS` в bash служебная переменная; в Makefile это имя параметра, внутри `replay-burst.sh` оно читается как `$1`.

## Blast radius и пайплайн

В самих целях нет: ничего не удаляется. Живой стек только `down` без `-v`, после B1. Тома `lakehouse-fresh` после проверки остаются; удаление (`docker compose -p lakehouse-fresh down -v`) и удаление каталога `../lakehouse-fresh` только с «ок» владельца. Checkpoint, таблицы и offsets живого стека не меняются; `make verify` делает обычный merge silver.

## Отчёт: что собрать

Время B3 и B6, хвост вывода B3 и B4, вывод B5 в обоих каталогах, `virtual_now` до и после B7, `git diff --stat`.

## Коммит

После «ок» владельца:

```bash
git add Makefile README.md OPERATIONS.md DECISIONS.md docs/HANDOFF.md scripts/README.md \
  scripts/chaos/lib.sh scripts/replay-burst.sh scripts/verify.sh scripts/bootstrap.sh \
  tests/unit/test_makefile.py
git commit -m "infra: make start, bootstrap, verify and replay-burst"
```
