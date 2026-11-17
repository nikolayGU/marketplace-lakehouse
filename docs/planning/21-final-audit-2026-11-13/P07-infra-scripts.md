# P07. Скрипты, Makefile, shellcheck, якоря compose, тест SQL offsets, цена набора
Статус: не начат. Сессия на Opus по `13-harness.md`: `/task docs/planning/21-final-audit-2026-11-13/P07-infra-scripts.md`.

## Цель

Проверка offsets bronze в `make verify` исполняется тестом и краснеет на ослаблении; chaos-скрипты
не обрываются молча, не зашивают имя проекта и не копируют проверки `lib.sh`; bash под
shellcheck (если прогон чистый); `make help` показывает `chaos-%`; `.env.*` не попадает в git;
у нового клона `TRINO_XMX=2g`; общие блоки compose на якорях без смены хэша ни одного сервиса;
подстрочные и виснущие тесты заменены поведением; набор быстрее примерно на 40 с. Один коммит.

## Находки пакета

| ID | серьёзность | суть | где подробности |
|---|---|---|---|
| QA-06 (= DP-08, PF-32) | средняя | SQL дыр и повторов offsets (`bronze_offsets_ok`) не исполняется тестом: мутация O1 зелёная | `reports/QA.md` QA-06; `work/QA/offsets_sqlite_probe.py.txt` |
| IN-05 (R-03) | низкая | `run_dag` и `break-dbt-test.sh` молча выходят при сбое `dags list-runs` | `reports/IN.md`, IN-05 |
| IN-06 (R-04, R-43) | низкая | имя контейнера литералом, копия SQL offsets в `spark-kill.sh`, пять `fail()`, два токена REST | `reports/IN.md`, IN-06 |
| IN-07 (R-43) | низкая | bash только под `bash -n` | `reports/IN.md`, IN-07 |
| IN-09 (R-09) | низкая | `make help` не видит `chaos-%` | `reports/IN.md`, IN-09 |
| IN-11 (PF-13) | низкая | `.gitignore` закрывает только `.env` | `reports/IN.md`, IN-11 |
| IN-13 (R-22, часть) | низкая | `TRINO_XMX=2500m` в `.env.example`; текст OPERATIONS правит P11 | `reports/IN.md`, IN-13 |
| IN-14 (R-41) | низкая | дубли env Spark и Superset, `networks: [lake]` у 27 сервисов | `reports/IN.md`, IN-14 |
| QA-05 (остаток, R-08) | низкая | подстрочные `test_trino_access.py:121-123`, `test_superset_import.py:69`, `test_compose.py:167-168` | `reports/QA.md`, таблица R-08 |
| QA-07 (часть) | низкая | тест дедлайна Trino виснет вместо красного | `reports/QA.md`, QA-07 |
| QA-08 (R-27, часть) | низкая | цена: `SILVER_KILL_*` 1 с и 8 повторных режимов в `test_verify_script` | `reports/QA.md`, «Цена набора» |
| QA-10 (= OB-09, PF-65) | низкая | сокет exporter в `tmp_path`: длинный `--basetemp` даёт 2 errors | `reports/QA.md`, QA-10 |
| OR-05 (часть) | низкая | шапка `scripts/verify.sh:2` «Bronze holds every Kafka record exactly once» | `reports/OR.md`, OR-05; README папки, раздел 2 |
| Б17 (реестр, раздел 4) | низкая | комментарий `lib.sh:50-51` обещает `curl: not found` | `registry.md`, раздел 4 |

## Решения владельца и действия класса C

- **В-12** (рекомендация «да»): shellcheck разово, находки исправить; в `make lint` и CI только
  при чистом прогоне. Скачивание пакета отклонял классификатор auto mode: по «ок» на точный текст
  `uv add --group dev shellcheck-py==0.11.0.1` (последняя на PyPI, 2025-08-09, сверено 13.11).
- **Сверх В-n, тем же вопросом:** `git push origin main` коммита пакета, чтобы run CI доказал шаг
  shellcheck и якоря compose (C). Без него шаг 11 стоит «не проверено в CI».
- **Сверх В-n, тем же вопросом:** два сокращения набора тестов. Это не подгонка под результат,
  но изменение проверок по `AGENTS.md` решает владелец: удалить `test_compose.py:167-168`
  (охраняет давно убранную фразу) и оставить один режим у семи медленных проб
  `test_verify_script` (36 -> 28 тестов, шаг 9). Без «ок»: не делать, строка в «Итог».
- Живые chaos не запускать (C, расход реплея). `.env` владельца остаётся 2500m: сменить его и
  пересоздать `trino` решает владелец сам (C).

## Зависимости

- После P01 (в HEAD, CI зелёный): шаг shellcheck ложится в `lint-and-test` и в его тест
  `test_lint_and_test_runs_every_check_it_claims`.
- После P02: он меняет вызовы `python3 "$ROOT/..."` в `scripts/verify.sh`,
  `scripts/report.sh`, `Makefile` (IN-03; `scripts/chaos/lib.sh` он не трогает) и добавляет тест в `tests/unit/test_verify_script.py`.
- После P06: он меняет `docker/compose.yaml` (снимает `CATALOG_JDBC_*`, mount `oltp-replayer`) и
  `tests/unit/test_compose.py`. Якоря делаются по его итоговому файлу.
- P05 меняет `test_dags.py` и `test_reconcile.py` (часть QA-05): не трогать. P11 правит
  OPERATIONS про `TRINO_XMX` после этого пакета. P10 снимает ID в старых комментариях `lib.sh`
  (`W4-D12`, `D12`, `W4-D7`); новые строки P07 пишутся без ID.
- Всё ниже искать по цитате: номера даны на `a8c1d49`, после P02 и P06 они сдвинутся.

## Вход

- `scripts/verify.sh:2`: «Bronze holds every Kafka record exactly once,»; `:60`
  `bronze_offsets_ok || fail ...`. `scripts/chaos/lib.sh:194` «Every record of the CDC topics is in
  bronze»; `:50-51` «...object store (MinIO) fails: ...curl: not found»; `:219-227`
  `bronze_offsets_ok` (`having count(*) > count(distinct kafka_offset) or max(kafka_offset) -
  min(kafka_offset) + 1 > count(distinct kafka_offset)`); `:317` `state=$(dag_run_state "$dag"
  "$run")` без `||`; `:153-158` `service_healthy`; `:333-343` `task_log` берёт токен сам.
- `scripts/chaos/break-dbt-test.sh:24` `state=$(dag_run_state dbt_build "$run-broken")`;
  `silver-kill.sh:186` уже `|| state=unknown`, `:12` `fail()`, `:24-28` `api_get` (токен);
  `spark-kill.sh:6` `container=lakehouse-spark-bronze-1`, `:69-77` копия SQL offsets;
  `connect-restart.sh:9` `container=lakehouse-kafka-connect-1`; `late.sh:14-15`
  `healthy lakehouse-spark-bronze-1`; `connect/snapshot.sh:33` подсказка с литералом;
  `fail()` в `connect-pause.sh:8`, `kafka-down.sh:7`, `postgres-restart.sh:7`,
  `scripts/demo/watermark.sh:15` (`verify.sh:29` свой, «verify failed:», остаётся).
- Unit-тесты скриптов есть только у `lib.sh` (`test_reconcile_shell.py`, `test_verify_script.py`,
  `test_chaos_silver_kill.py`, `test_makefile.py`), `silver-kill.sh` (`test_chaos_silver_kill.py`),
  `verify.sh`, `report.sh` (`test_report.py`); у прочих chaos-скриптов и `connect/snapshot.sh` нет
  (`grep -l <имя> tests/unit/*.py`). Фейк `test_chaos_silver_kill.py:95` отвечает по тексту
  `having count(*) >`: текст запроса в `lib.sh` не менять.
- `Makefile:10` `grep -E '^[a-zA-Z_-]+:.*?## '` (43 цели, с `%` 44); `:138-145` `lint`.
- `.gitignore:1` `.env`; `git check-ignore -q .env.bak` -> код 1. `.env.example:51`
  `TRINO_XMX=2500m`; `docker/trino/etc/config.properties` «at TRINO_XMX=2g as well as 2500m».
- `docker/compose.yaml`: env трёх Spark-сервисов (`:308-326`, `:368-387`, `:426-439`), Superset
  (`:825-829`, `:863-866`, `:904-907`), `networks: [lake]` 27 раз, `x-common` без `networks`.
- `tests/unit/test_trino_access.py:121-123` (`"- ./trino/etc:/etc/trino:ro" in compose` текстом);
  `test_superset_import.py:69` (`"metadata.yaml" in SCRIPT.read_text()`); `test_compose.py:167-168`
  (`"skips an existing" not in`); `test_check_dashboards.py:216-227` (дедлайн; без
  `scripts/obs/check_dashboards.py:152-153` тест виснет); `test_container_exporter.py:260-268`
  (сокет в `tmp_path`); `test_chaos_silver_kill.py:184,186` (`SILVER_KILL_BURST`, `_POLL` = "1").
- `git ls-files '*.sh'`: 26 файлов, 2123 строки; shellcheck на хосте нет.
- Базы до правок (снять самому): `uv run --no-sync pytest tests/unit/test_chaos_silver_kill.py
  tests/unit/test_verify_script.py -q --durations=5` (аудит: 69.3 и 39.8 с, 40 и 36 тестов);
  хэши compose шага 10.

## Границы

- Менять можно: `scripts/chaos/*.sh`, `scripts/demo/watermark.sh`, `connect/snapshot.sh`,
  `scripts/verify.sh` (только шапка), `Makefile` (`help`, `lint`), `.gitignore`, `.env.example`,
  `docker/compose.yaml` (только якоря), `.github/workflows/ci.yml` (только шаг shellcheck),
  `pyproject.toml` и `uv.lock` (только `shellcheck-py`), тесты: `test_offsets_check.py` и
  `test_chaos_lib.py` (новые), `test_makefile.py`, `test_compose.py`, `test_trino_access.py`,
  `test_superset_import.py`, `test_check_dashboards.py`, `test_container_exporter.py`,
  `test_chaos_silver_kill.py`, `test_verify_script.py`, `test_workflows.py`.
- Нельзя: текст SQL `bronze_offsets_ok` и логику проверок; OPERATIONS, README (P11, P13);
  `test_dags.py`, `test_reconcile.py` (P05); в скриптах, которые идут в образ или в контейнер
  (`streaming/run-job.sh` в образе Spark, `docker/superset/init.sh`,
  `docker/minio/create-bucket.sh`, `oltp/init/01-debezium.sh`), по shellcheck только `# shellcheck disable=SCxxxx` с причиной.
- Живой стек: только цикл verify. Chaos, `make replay-*`, пересоздание контейнеров: нет.
- Хук блокирует запись в любой путь `.env` из Bash и Write, и в scratchpad: фейковый `.env` для
  bash-тестов создаёт сам тест в `tmp_path`, как `test_reconcile_shell.py:44-49`.

## Шаги

Код пишет `implementer` по брифу (части 1-3 и 8-9 в разных файлах можно параллельно), правки до
~20 строк в одном файле (шаги 4-7) оркестратор сам. У каждой правки тест на отказ первым.

1. **Тест SQL offsets (QA-06).** Новый `tests/unit/test_offsets_check.py`: запрос из `lib.sh`
   regex'ом `bronze_offsets_ok\(\) \{.*?trino_value "(.*?)"\)` (re.S), исполнить на `sqlite3`
   (`attach ':memory:' as bronze`, таблица `topic, kafka_partition, kafka_offset`). Кейсы и
   ожидание: чистые две темы 0; партиция с начала не с нуля (7, 8) 0; дубль 1; дыра 1; дыра в
   другой партиции 1; дубль и дыра в разных партициях 2. Красный до правки нельзя (правки кода
   нет): доказательство мутациями O1 (`work/QA/mutations5.json.txt`, `tests` -> новый файл), `>=`
   вместо `>` во второй ветке, `and` вместо `or`: все `RED`. Прототип 13.11: 6 passed, три
   мутанта красные.
2. **Молчаливый выход (IN-05).** Новый `tests/unit/test_chaos_lib.py`, обвязка как
   `test_reconcile_shell.py:44-66` (копия `lib.sh` во временный корень, `.env` там же): заглушка
   `airflow_cli` (`dags trigger` код 0, остальное код 1), `RUN_DAG_WAIT=0 run_dag d r` -> код 1 и в
   stderr `d run r still unknown after 0 s`. Сейчас код 1 без строки (выход по `set -e`).
   Правка: `|| state=unknown` в `lib.sh:317` и `break-dbt-test.sh:24`, как в `silver-kill.sh:186`.
3. **Chaos в одном месте (IN-06).** В `lib.sh`: `container_of <service>` (id через
   `"${COMPOSE[@]}" --profile '*' ps -q`, пустой ответ: сообщение в stderr и код 1); один `fail()`
   («FAIL: $*», exit 1); `airflow_api_get <path>` (токен `/auth/token` и GET, как
   `silver-kill.sh:24-28`), им же пользуется `task_log`. Скрипты: `spark-kill.sh` и
   `connect-restart.sh` берут id через `container_of` (в сообщениях имя сервиса); `late.sh` через
   `service_healthy spark-bronze`; `snapshot.sh:33` подсказка `make logs S=kafka-connect | grep -i
   'incremental snapshot'`; `spark-kill.sh:69-77` -> `bronze_offsets_ok || { echo "FAIL: ..." >&2;
   exit 1; }`; свои `fail()` и `api_get` удалить. Тесты первыми в `test_chaos_lib.py`:
   `container_of` с фейковым `docker` на `PATH` (id и пустой ответ); `fail`; `airflow_api_get`
   с фейковым `curl` (заголовок `Authorization: Bearer <token>`); статический: в `scripts/` и
   `connect/` нет `count(distinct kafka_offset)` вне `lib.sh` и нет `lakehouse-[a-z-]+-1` вне
   строк-комментариев. `test_chaos_silver_kill.py` остаётся зелёным без правки ожиданий.
4. **Формулировки** (оркестратор). `verify.sh:2-3`: вместо «Bronze holds every Kafka record
   exactly once» смысл «bronze holds no Kafka offset twice and no gap between the lowest and the
   highest offset of each partition, and has caught up with Kafka's end offsets» (начало
   партиции, удалённое retention до bronze, не проверяется: README папки, раздел 2, ADR-019).
   `lib.sh:194` так же. `lib.sh:50-51`: `curl: not found` -> `curl: command not found` (код 127).
5. **`make help` (IN-09).** Тест в `test_makefile.py`: `make("help").stdout` содержит `chaos-%`
   (сейчас красный). Правка `Makefile:10`: `[a-zA-Z_%-]`.
6. **`.gitignore` (IN-11).** Тест: `git check-ignore -q .env.bak` код 0, для `.env.example` код 1
   (subprocess, `cwd` корень; сейчас красный). Правка: после `.env` строки `.env.*` и
   `!.env.example`.
7. **`TRINO_XMX` (IN-13).** Тест в `test_compose.py`: `TRINO_XMX=2g` среди строк `.env.example`
   (рядом с `test_env_example_binds_to_loopback`). Правка `.env.example:51`.
8. **Подстрочные и виснущие тесты (QA-05, QA-07, QA-10).**
   - `test_trino_access.py:121-123`: `yaml.safe_load` compose, `"./trino/etc:/etc/trino:ro"` в
     `services.trino.volumes`. Мутация T4 (`work/QA/mutations2.json.txt`, кавычки) -> `GREEN`.
   - `test_superset_import.py:69`: строку удалить; новый тест загружает `import_bundle.py`
     (`importlib.util.spec_from_file_location`, superset импортируется только в `main`), для
     `SqlaTable`, `Slice`, `Dashboard`: `_with_type(_read_bundle(bundle), t)` даёт `type == t`,
     прежний `timestamp`, прочие файлы равны, вход не изменён. T5 -> `RED` (прототип: 2 failed).
   - `test_compose.py:167-168`: удалить (охраняет давно убранную фразу).
   - `test_check_dashboards.py:216-227`: фейковый `urlopen` со счётчиком, после 10 вызовов
     `AssertionError("trino_query polls past its deadline")`. Проверка: копия без
     `check_dashboards.py:152-153` -> `FAILED` за секунды (прототип: `1 failed` за 0.1 с).
   - `test_container_exporter.py:260-268`: сокет в `tempfile.mkdtemp(dir="/tmp")`, в teardown
     `shutil.rmtree`. До правки: `B=/tmp/pytest-long-$(printf 'x%.0s' $(seq 100))`, `uv run
     pytest tests/unit/test_container_exporter.py -q --basetemp="$B"` -> `14 passed, 2 errors`
     (путь новый: pytest очищает `--basetemp`).
9. **Цена (QA-08).** `test_chaos_silver_kill.py:184,186`: `"0.2"`. В `test_verify_script.py`
   оставить один режим `""` (полный: он проверяет, что `spark-silver` не вызван) у
   `test_catalog_lake_that_hangs_...`, `test_ctrl_c_during_the_first_probe_...`,
   `test_trino_that_hangs_...` (оба лимита остаются), `test_ctrl_c_during_a_hung_probe_...`,
   `test_signal_during_an_answering_probe_...`, `test_storage_that_hangs_...`,
   `test_ctrl_c_during_the_catalog_probe_...`; быстрые `..._down_...` и `..._lake_down_...` с двумя
   режимами не трогать. Итого `test_verify_script` 36 -> 28.
10. **Якоря compose (IN-14), по файлу после P06.** До правки и после, вывод в scratchpad:
    `docker compose --env-file .env.example -f docker/compose.yaml --profile '*' config --hash '*'
    > <scratchpad>/hash-<до|после>.txt` и тот же вызов с `config --no-interpolate >
    <scratchpad>/model-<до|после>.yaml` (ссылки `${VAR}`, без значений). Правка: `x-spark-env:
    &spark-env` с ключами, общими трём Spark-сервисам (`<<: *spark-env` в их `environment`,
    отличия остаются у сервиса), `x-superset-env: &superset-env` (`SUPERSET_SECRET_KEY`,
    `SUPERSET_DATABASE_URI`, `SUPERSET_CONFIG_PATH`), `networks: [lake]` в `x-common` и снять у
    сервисов с `<<: *common`. Условие: `diff hash-до hash-после` пуст по всем сервисам и модель без
    ключей `x-*` равна (команда в «Готово, когда»); иначе стоп: откат правки compose, вопрос
    владельцу. Прототип на `a8c1d49`: 27 из 27 хэшей равны, модель равна, 942 -> 905 строк, тесты,
    читающие compose, 1226 passed.
11. **shellcheck (IN-07, В-12).** По «ок»: `uv add --group dev shellcheck-py==0.11.0.1`. Первый
    прогон до правок: `uv run shellcheck -x -S warning $(git ls-files '*.sh')`, число находок по
    кодам в «Итог». Исправить или подавить `# shellcheck disable=SCxxxx` с причиной (в файлах из
    «Границ», которые идут в образ или контейнер, только подавление). Чисто: в `Makefile` `lint`
    строка `uv run shellcheck -x -S warning $$(git ls-files '*.sh')` после `bash -n`, в `ci.yml`
    шаг `- run: uv run shellcheck -x -S warning $(git ls-files '*.sh')` после `bash -n`, в
    `test_lint_and_test_runs_every_check_it_claims` эта строка (тест первым, красный). Не чисто
    за размер M: `uv remove --group dev shellcheck-py`, ни `lint`, ни CI; список в «Итог».
12. **Проверки, ревью, коммит.** `bash -n` всех `*.sh`; `make check`; `reviewer` (предмет `код`,
    весь diff, этот «Готово, когда», вывод мутаций и хэшей); не больше двух кругов; цикл verify
    и коммит по разделу 5 `13-harness.md`. Сообщение: `scripts: chaos helpers in one place, offsets
    check under test, shellcheck, compose anchors, faster tests`. Push по «ок», затем CI.

## Готово, когда

- [ ] `uv run --no-sync pytest tests/unit/test_offsets_check.py tests/unit/test_chaos_lib.py
      tests/unit/test_chaos_silver_kill.py tests/unit/test_reconcile_shell.py
      tests/unit/test_verify_script.py tests/unit/test_makefile.py tests/unit/test_compose.py
      tests/unit/test_trino_access.py tests/unit/test_superset_import.py
      tests/unit/test_check_dashboards.py tests/unit/test_container_exporter.py -q` -> без failed
- [ ] мутации O1, `>=`, `and` -> `RED`; T5 -> `RED`; T4 -> `GREEN`; копия без дедлайна ->
      `FAILED`, не зависание (`timeout 60`)
- [ ] `--basetemp="$B"` (шаг 8) -> `16 passed`
- [ ] `for s in $(git ls-files '*.sh'); do bash -n "$s" || echo "$s"; done` -> пусто
- [ ] `grep -rnE 'lakehouse-[a-z-]+-1' scripts connect` -> только строки-комментарии;
      `grep -rln 'count(distinct kafka_offset)' scripts` -> `scripts/chaos/lib.sh`;
      `grep -rn '^fail()' scripts` -> `scripts/chaos/lib.sh`, `scripts/verify.sh`
- [ ] `make help | grep -c 'chaos-%'` -> `1`
- [ ] `git check-ignore -q .env.bak && ! git check-ignore -q .env.example && echo ok` -> `ok`
- [ ] `grep -n '^TRINO_XMX=' .env.example` -> `TRINO_XMX=2g`
- [ ] `diff <scratchpad>/hash-до.txt <scratchpad>/hash-после.txt` -> пусто; `uv run --no-sync
      python -c 'import sys, yaml; a, b = (yaml.safe_load(open(p)) for p in sys.argv[1:]); s =
      lambda d: {k: v for k, v in d.items() if not k.startswith("x-")}; print("model equal" if
      s(a) == s(b) else "MODEL DIFFERS")' <model-до> <model-после>` -> `model equal`
- [ ] `uv run --no-sync pytest tests/unit/test_chaos_silver_kill.py tests/unit/test_verify_script.py
      -q` быстрее базы Входа не меньше чем на 30 с; `test_verify_script` собирает 28
- [ ] shellcheck: `uv run shellcheck -x -S warning $(git ls-files '*.sh')` -> код 0 и строка в
      `make lint` и CI; либо `grep -c shellcheck pyproject.toml` -> `0` и список в «Итоге»
- [ ] `make check` -> зелёный; `reviewer` «принять» или «принять с замечаниями»; `make verify`
      -> `verify ok`
- [ ] после push по «ок»: `gh run watch <id> --exit-status` -> exit 0 на HEAD, в логе
      `lint-and-test` шаг shellcheck (если он добавлен)

## Не входит

- IN-08 (CI на `make lint`): не делаем. IN-03 (`python3` хоста): P02. IN-10, DP-01 (compose):
  P06. IN-12, IN-15, OR-05 вне `verify.sh:2`, DP-07: P13. OPERATIONS про `TRINO_XMX`: P11.
- QA-05 в `test_dags.py`, `test_reconcile.py`: P05. QA-07 в `test_silver_upsert.py`: P06.
- Guard в процессе (часть R-27): P03. Живые chaos и smoke. Комментарии compose
  `lakehouse-trino-1`, `lakehouse-prometheus-1` (`compose.yaml:521,660`).

## Риски и откат

- Chaos-скрипты кроме `silver-kill.sh` не имеют unit-тестов: правки шага 3 и shellcheck в них
  доказаны только `bash -n`, shellcheck, статическим тестом и ревью. Правка не механическая:
  не делать, записать.
- `container_of` берёт id по `--profile '*'`, как `service_healthy`: `docker start <id>` после
  `docker kill` работает (контейнер остаётся). Сообщения называют сервис, а не id.
- `TRINO_XMX=2g` в `.env.example` значит smoke и новый клон на 2g; все профили на 2g проверены
  10.11 (`README.md:60-61`), smoke на 2g не гонялся: финальная приёмка P14.
- Якоря: равенство доказывают хэши и модель без значений; если P06 оставил сервисы с разными
  наборами ключей, якорь берёт только общее.
- Откат: `git revert` коммита; shellcheck снимается `uv remove --group dev shellcheck-py`.

## Расхождения с отчётом аудита

- PF-32: OR пишет «не делать», DP (DP-08) и QA (QA-06) «делать»; по `registry.md` разделу 3 и
  карте пакетов делать, здесь.
- IN-05: тест с `RUN_DAG_WAIT=1` и строкой `after 1 s` ждёт 10 с (`sleep 10` в цикле); с
  `RUN_DAG_WAIT=0` отказ сразу, строка `after 0 s`.
- IN-06: `connect/snapshot.sh:33` только подсказка в `echo`, контейнер там не ищется. «Поведение не
  меняется» тестами не доказать: unit-тестов у 9 из 10 chaos-скриптов нет.
- IN-14: «минус 75 строк» из файла 19 не воспроизведено: прототип 13.11 до P06 даёт минус 37.
- QA-08: «пробы идут до ветки режима» неточно: проверка scheduler (`verify.sh:34-44`) в полном
  режиме идёт до проб, merge после; поэтому оставлен режим `""`, а не `--no-merge`.
- QA-10 и OB-09: фикстура на `test_container_exporter.py:260-268` (в отчётах 261-263 и 260-262).
- OR-05: та же формулировка в комментарии `lib.sh:194` добавлена в шаг 4. Б17 добавлен по
  `registry.md`, раздел 4; в брифе пакета его не было.

## Итог

Заполняет исполнитель по разделу 6 `13-harness.md`.
