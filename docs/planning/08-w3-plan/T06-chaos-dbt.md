# W3-T06 Chaos 9 (на нём Operate-гейт dbt) и optional chaos 10

> До первого шага прочитай `README.md` этой папки: протокол, стоп-условия, отчёт.

| | |
|---|---|
| Спека | `07-w3-spec.md`, карточка W3-T06 |
| Коммит | `dbt: chaos 9, a failing dbt test in airflow` |
| Оценка | A: 0.5 ч; B: 0.5 ч |
| Часть A | любая среда |
| Часть B | только локально; Airflow поднят, реплей не играет |

## Цель

Поломка в batch-слое видна и не портит данные: `dbt_build` красный, витрины остаются прошлой версией, повтор без переключателя зелёный. Chaos 9 обязателен: на `make chaos-break-dbt-test` стоит Operate-гейт dbt (`02-learning-gates.md`). Chaos 10 делается, только если владелец скажет.

## Вход

```bash
git log --oneline -1                                   # коммит W3-T05b
grep -c 'chaos-%' Makefile                             # 1: общая цель make chaos-<name>
```

## Файлы

- Создать: `dbt/tests/assert_chaos_break_test.sql`, `scripts/chaos/break-dbt-test.sh`.
- Изменить: `dbt/tests/_tests.yml` (дописать), `OPERATIONS.md`, `docs/planning/00-mini-architecture-review.md`.
- Только для optional chaos 10: `dbt/profiles.yml` (дописать), `scripts/chaos/trino-memory.sh`.

## Часть A. Код

### A1. Тест-переключатель

Без переменной тест возвращает ноль строк. С `--vars '{chaos_break_test: true}'` возвращает все заказы и падает; `dbt build` тогда пропускает всё после `fct_orders`.

<!-- file: dbt/tests/assert_chaos_break_test.sql -->
```sql
-- Chaos 9 (OPERATIONS.md): fails only under --vars '{chaos_break_test: true}'. dbt build then
-- skips every model after fct_orders, and the marts keep their previous version.
select order_id
from {{ ref('fct_orders') }}
where {{ 'true' if var('chaos_break_test', false) else 'false' }}
```

<!-- append: dbt/tests/_tests.yml -->
```yaml
  - name: assert_chaos_break_test
    description: >
      Chaos 9 switch: returns every order, so fails, only when dbt runs with
      --vars '{chaos_break_test: true}'; otherwise returns nothing.
```

### A2. Сценарий

`run_dag` из W3-T04 не снимает паузу; скрипт сам отказывается, если `dbt_build` на паузе, и проверяет, что реплеер не играет (merge silver запустил бы ещё один `dbt_build`).

<!-- file: scripts/chaos/break-dbt-test.sh -->
```bash
#!/usr/bin/env bash
# Chaos 9: a dbt test fails inside Airflow. dbt_build goes red, every model after fct_orders is
# skipped and the marts keep their previous snapshot; a run without the switch is green again
# (OPERATIONS.md, scenario 9). Needs orchestrate up with dbt_build unpaused, and no replay: a
# silver merge in between would start another dbt_build and change the marts.
. "$(dirname "$0")/lib.sh"

paused=$(airflow_cli dags list -o json 2>/dev/null | python3 -c '
import json, sys
lines = sys.stdin.read().splitlines()
start = next(i for i, line in enumerate(lines) if line.strip() == "[" or line.lstrip().startswith("[{"))
print(next(str(d["is_paused"]) for d in json.loads("\n".join(lines[start:])) if d["dag_id"] == "dbt_build"))')
if [ "$paused" != False ]; then
  echo "dbt_build is paused (or not there): unpause it first, a paused DAG only queues runs" >&2
  exit 2
fi
no_other_replayer

snapshots() { trino_value "select count(*) from gold.\"mart_daily_sales\$snapshots\""; }
run=chaos9-$(date -u +%Y%m%dT%H%M%S)

before=$(snapshots)
run_dag dbt_build "$run-broken" '{"dbt_vars": "{chaos_break_test: true}"}' || true
state=$(dag_run_state dbt_build "$run-broken")
after=$(snapshots)
echo "dbt_build $run-broken: $state; mart_daily_sales snapshots before $before, after $after"
if [ "$state" != failed ]; then
  echo "FAIL: the run with the switch ended $state, expected failed" >&2
  exit 1
fi
if [ "$before" != "$after" ]; then
  echo "FAIL: mart_daily_sales changed although a test upstream of it failed" >&2
  exit 1
fi

run_dag dbt_build "$run-fixed" || {
  echo "FAIL: dbt_build without the switch did not recover" >&2
  exit 1
}
echo "ok: the failed run left the marts as they were; the run without the switch is green"
```

Проверки: `bash -n scripts/chaos/break-dbt-test.sh && echo ok`; `make dbt-parse`; `cd dbt && uv run sqlfluff lint tests; cd ..`.

### A3. Документация (числа заполняет часть B)

<!-- edit: OPERATIONS.md -->
Найти:
```text
| 9 (optional) | Airflow task failure (dbt test) | `chaos-break-dbt-test` | planned (week 3) |
```
Заменить на:
```text
| 9 | Airflow task failure (dbt test) | `chaos-break-dbt-test` | done CHAOS9_DATE |
```

<!-- edit: OPERATIONS.md -->
Найти:
```text
## Runbooks
```
Заменить на:
````text
### 9. Airflow task failure (dbt test)

```
make chaos-break-dbt-test   # orchestrate up, dbt_build unpaused, no replay running
```

What happened: `dbt_build` ran with the conf `{"dbt_vars": "{chaos_break_test: true}"}`. The
singular test `assert_chaos_break_test` on `fct_orders` returned every order under that switch and
failed.
What monitoring shows: `dbt_build` red in the Airflow UI; the task log names the test
(`Failure in test assert_chaos_break_test`). Alert `AirflowDagFailed` comes with week 4. Seen when
the run ends, CHAOS9_SECONDS s after the trigger.
Data at risk: none. `fct_orders` was rebuilt before its test ran; every model after it was skipped,
so the marts kept their previous snapshot (`mart_daily_sales`: CHAOS9_SNAPSHOTS snapshots before
and after).
Recovery: manual. Remove the cause (here the switch) and trigger `dbt_build`; the next silver merge
triggers it too. The run without the switch was green.
Why no loss or duplication: `dbt build` skips the children of a failed test, and a mart is either
replaced atomically (`CREATE OR REPLACE`) or not touched.
Verification SQL:

```
select committed_at, operation from gold."mart_daily_sales$snapshots"
order by committed_at desc limit 3;
```

## Runbooks
````

<!-- edit: docs/planning/00-mini-architecture-review.md -->
Найти:
```markdown
| 9 (optional) | Airflow task failure (dbt test) |
```
Заменить на:
```markdown
| 9 | Airflow task failure (dbt test) |
```

### A4. Optional chaos 10: только по слову владельца

Лимит памяти задаётся сессионным свойством отдельного target dbt; конфиг Trino не меняется. `query_max_memory` в Trino 483 не виден в `SHOW SESSION`, но работает: проверено 09.10, join с лимитом 1 MB падает с `Query exceeded distributed user memory limit of 1MB`.

<!-- append: dbt/profiles.yml -->
```yaml
    # Chaos 10: the same Trino with a 1 MB memory limit per query, set for this session only.
    chaos_low_memory:
      type: trino
      method: none
      user: dbt
      host: "{{ env_var('TRINO_HOST', '127.0.0.1') }}"
      port: "{{ env_var('TRINO_PORT', '8080') | as_number }}"
      database: lake
      schema: gold
      threads: 1
      session_properties:
        query_max_memory: 1MB
```

<!-- file: scripts/chaos/trino-memory.sh -->
```bash
#!/usr/bin/env bash
# Chaos 10 (optional): a dbt model fails halfway on a query memory limit. The incremental
# mart_daily_sales keeps its last good state, and a run on the normal target finishes the work
# (OPERATIONS.md, scenario 10). The limit is the session property query_max_memory of the dbt
# target chaos_low_memory; Trino's config does not change. Run it with Airflow down or
# dbt_build paused: a dbt_build in between would rebuild the mart.
. "$(dirname "$0")/lib.sh"

snapshots() { trino_value "select count(*) from gold.\"mart_daily_sales\$snapshots\""; }
dbt_host() { (cd "$ROOT/dbt" && uv run dbt "$@" --profiles-dir .); }

no_other_replayer
before=$(snapshots)
log=$(mktemp -t chaos-trino-memory.XXXXXX.log)
if dbt_host run --target chaos_low_memory --select mart_daily_sales >"$log" 2>&1; then
  echo "inconclusive: mart_daily_sales fit in the limit; full log: $log" >&2
  exit 1
fi
if ! grep -q 'exceeded distributed user memory limit' "$log"; then
  tail -20 "$log" >&2
  echo "FAIL: dbt failed for another reason than the memory limit; full log: $log" >&2
  exit 1
fi
after=$(snapshots)
echo "mart_daily_sales failed on the memory limit; snapshots before $before, after $after"
if [ "$before" != "$after" ]; then
  echo "FAIL: the failed run committed to mart_daily_sales" >&2
  exit 1
fi
make -C "$ROOT" --no-print-directory dbt-build >"$log" 2>&1 || {
  tail -20 "$log" >&2
  echo "FAIL: dbt build on the normal target did not finish the work; full log: $log" >&2
  exit 1
}
rm -f "$log"
echo "ok: the failed run left mart_daily_sales as it was; dbt build on the normal target passed," \
  "the full recompute test included"
```

### A5. Статические проверки

```bash
make lint && make test 2>&1 | tail -1 && make dbt-parse
```

## Часть B. Живая проверка

Предусловия: `orchestrate` поднят (`TRINO_XMX=2g`), `dbt_build` снят с паузы, реплеер не играет, последний `dbt_build` зелёный.

### B1. Chaos 9

```bash
time make chaos-break-dbt-test
```
Ожидается: строка `dbt_build chaos9-...-broken: failed; mart_daily_sales snapshots before N, after N` с одинаковыми N и последняя строка `ok: the failed run left the marts as they were; ...`. В UI лог задачи упавшего запуска содержит `Failure in test assert_chaos_break_test`.

### B2. Числа в OPERATIONS

Замени `CHAOS9_DATE` (сегодня), `CHAOS9_SECONDS` (длительность упавшего запуска: `end_date - start_date` из `af dags list-runs dbt_build -o table`), `CHAOS9_SNAPSHOTS` (N из B1). Затем `git grep -n 'CHAOS9_' -- . ':!docs/planning/08-w3-plan'` пусто.

### B3. Optional chaos 10, если владелец сказал «да»

`dbt_build` на паузу, иначе merge silver пересоберёт витрину посреди сценария:

```bash
af dags pause dbt_build
make chaos-trino-memory
af dags unpause dbt_build
```
Ожидается: `ok: the failed run left mart_daily_sales as it was; dbt build on the normal target passed, ...`. Затем в OPERATIONS строка 10 таблицы `done <дата>` и страница сценария 10 по шаблону из пяти ответов (раздел Template), с числами из вывода. Скрипт печатает `inconclusive`: витрина уложилась в лимит, это не сбой; в отчёт.

## Готово, когда

- `make chaos-break-dbt-test` воспроизводится: `dbt_build` красный, снапшотов `mart_daily_sales` до и после поровну, повтор без conf зелёный (B1).
- OPERATIONS: сценарий 9 с числами, статус в таблице; в `00-mini-architecture-review.md` §8 у сценария 9 нет пометки optional.
- Если делался chaos 10: после повтора тест полного пересчёта PASS (последняя строка скрипта).

## Если не так

| Симптом | Причина | Что делать |
|---|---|---|
| `dbt_build is paused (or not there)` | DAG на паузе | `af dags unpause dbt_build`, повтор |
| `a replayer already answers on :8000` | играет реплеер | дождаться конца порции, повтор |
| `FAIL: the run with the switch ended success` | тест не видит переменную | сравни тест и conf с планом; стоп |
| `FAIL: mart_daily_sales changed ...` | между замерами прошёл другой `dbt_build` | убедись, что реплей не играл и `silver_upsert` пропускал merge; повтор; снова: стоп |

## Blast radius и пайплайн

Нет. Упавший запуск не трогает витрины; запуск без переключателя это обычный `dbt build` со служебными операциями D13.

## Отчёт: что собрать

Вывод B1 и `time`, числа B2, при chaos 10 его вывод, `git diff --stat`.

## Коммит

```bash
git add dbt/tests scripts/chaos/break-dbt-test.sh OPERATIONS.md docs/planning/00-mini-architecture-review.md
# только если делался chaos 10:
git add dbt/profiles.yml scripts/chaos/trino-memory.sh
git commit -m "dbt: chaos 9, a failing dbt test in airflow"
```
