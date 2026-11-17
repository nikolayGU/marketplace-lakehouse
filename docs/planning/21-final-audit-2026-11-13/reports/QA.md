# QA. Тесты

Дерево: HEAD `a8c1d49` плюс незакоммиченная починка CI владельца (не трогалась). Репозиторий и
стенд не менялись: `git status --short` в конце аудита тот же, что в начале (5 изменённых файлов
владельца и `?? docs/planning/21-final-audit-2026-11-13/`). Рабочие файлы:
`<scratchpad>/audit/QA-work/`
(`full-run.txt`, `counts.txt`, `mutate.py`, `mutations*.json`, `mutations-result.txt`,
`offsets_sqlite_probe.py`, копия дерева `copy/`).

## Оценки

- QA: 4 из 5. Ключевые инварианты (сверка, гейт gold, выключатель обслуживания, контракты, D4,
  FAIL_ON_SKIP) краснеют на мутациях, пропуски хоста исполняются в CI; но мета-тесты CI, проводка
  DAG `silver_upsert`, метрики KPI Superset и проверка offsets в `verify` мутации не ловят.
- Тимлид, нанимающий: 3 из 5. 2073 теста с именами-предложениями и поведенческими проверками
  shell и DAG, но 49% набора это харнесс агентов, `tests/README.md` устарел и не даёт карты,
  что живёт только на стенде, нигде не сказано.

## Сильные стороны

- Пропуск нигде не молчит в CI: `tests/unit/conftest.py:12-28` превращает любой skip (маркер,
  `pytest.skip()`, фикстура, `importorskip`) в отказ при `FAIL_ON_SKIP=1`; мета-тест
  `tests/unit/test_makefile.py:225` гоняет все три вида. Мутации K6 (conftest) и K7 (флаг снят в
  `Makefile`) красные.
- Postgres-половина сверки исполняется на настоящем Postgres того же digest против независимого
  расчёта в Python: `tests/unit/test_reconcile_postgres.py`, CI run 43400391213, job
  `lint-and-test`, строка `62 passed in 0.61s` (09:23:42Z).
- Логика `dq_checks` проверена прогоном задач на фейковых клиентах (`dq.run("reconcile_values",
  ...)`, около 40 сценариев: CDC стоит, bronze движется, gold отстал, GMV, отказ метаданных):
  мутации G1, G2, G3 красные (`tests/unit/test_dags.py:553`, `tests/unit/test_reconcile.py:119,237`).
- Выключатель обслуживания проверен дважды: AST-графом рёбер `tests/unit/test_dags.py:914-923` и
  настоящим Airflow в `make dags-check` (`Makefile:191-194`, CI `airflow-image`). Мутации S1-S4
  красные.
- Shell проверяется поведением с фейковыми `docker` и `airflow`, включая сигналы: SIGINT и SIGTERM
  во время зависшей пробы, добивание после grace (`tests/unit/test_verify_script.py`, 36 тестов),
  весь сценарий 10b `silver-kill.sh` (`tests/unit/test_chaos_silver_kill.py`, 40 тестов).
- Spark-поведение на локальном Iceberg-каталоге: потерянный checkpoint перечитывает bronze, а
  silver сохраняет значения и `_updated_at` (`tests/unit/test_silver_upsert.py:432-468`), поздние
  события, мягкое удаление, quarantine; CI `spark-tests` `239 passed` при запрете пропусков.
- Статическая защита D4 для каждого потребителя staging (`tests/unit/test_dbt_soft_delete.py`):
  мутация D1 (`dim_sellers` без `where not is_deleted`) красная.

## Карта набора

Сбор: `uv run pytest tests/unit --collect-only -q` 2073 теста; полный прогон
`uv run pytest tests/unit -q --durations=25 -rs`: `1927 passed, 146 skipped in 204.18s (0:03:24)`.

| Компонент | Файлы тестов | Тестов | Где исполняются | Что ловят | Чего не ловят |
|---|---|---|---|---|---|
| Харнесс агентов | `test_agent_hooks`, `test_agent_state` | 1010 (48.7%) | хост, CI `lint-and-test` | решения guard, отметки, гейты | разбирают HG, HS |
| CDC-конверт, контракты | `test_envelope`, `test_contracts` | 72 (4 skip) | хост; JVM-часть в CI `lint-and-test` и `spark-tests` | контракт против миграции, типы, NOT NULL, PK; приведение типов в Spark | сужение `enum` (C3 зелёная) |
| Bronze, метрики стрима | `test_bronze_cdc_ingest`, `test_iceberg_sink`, `test_offsets`, `test_spark_settings`, `test_metrics_listener` | 47 (22 skip) | хост частично; Iceberg только `spark-tests` | пропуск эпохи по query id, лаг, настройки каталога | живой Lakekeeper REST и MinIO |
| Silver MERGE | `test_silver_upsert` | 40 (40 skip) | JVM-часть `lint-and-test`, Iceberg-часть только `spark-tests` | LSN-guard, повтор, late, delete, quarantine, потеря checkpoint | дубли при повторе в `test_replaying_a_batch_changes_nothing` (QA-07) |
| orders_per_minute | `test_orders_per_minute` | 11 (11 skip) | `lint-and-test`, `spark-tests` | окно, watermark | живой Kafka |
| Spark-обслуживание | `test_maintenance`, `test_iceberg_demo` | 91 (10 skip) | хост, `spark-tests` | правила job, expire, orphans dry-run | |
| Реплеер | `test_replay_*`, `test_replayer_cli`, `test_load`, `test_progress`, `test_settings`, `test_sample`, `test_fetch_data` | 49 | хост, CI | выбор, часы, эволюция схемы, CLI | ядро `step()`: P1, P2 зелёные (PF-31) |
| Сверка | `test_reconcile`, `test_reconcile_sql`, `test_reconcile_shell`, `test_reconcile_postgres` | 126 (59 skip) | хост; Postgres-часть шагом CI с `FAIL_ON_SKIP` | состав 7 таблиц, отпечаток, `floor`, `collate "C"` (в CI), GMV-статусы | фильтр `_is_deleted` на стороне silver в сверке по значениям (R1) |
| DAG и DQ | `test_dags`, `test_dq_metrics`, `test_airflow_env` | 188 | хост, CI; плюс `make dags-check` в `airflow-image` | гейт gold, stale, выключатель, таймауты, force-remove | проводка `silver_upsert`: W1, W2, W4, W5 зелёные (QA-02) |
| verify, chaos, Makefile | `test_verify_script`, `test_chaos_silver_kill`, `test_report`, `test_makefile`, `test_make_env` | 120 | хост, CI | пробы, сигналы, сценарий 10b, `make silver` | семантика SQL offsets (O1 зелёная, QA-06) |
| dbt статично | `test_dbt_soft_delete`, `test_dbt_relationships`, `test_dbt_bi_columns` | 32 | хост, CI | фильтр D4, водяной знак, relationships | сам `dbt build` и dbt-тесты (`PASS=79 WARN=4`, HANDOFF 30.10): только живой стенд |
| Superset | `test_superset_bundle`, `test_superset_import`, `test_superset_style` | 50 | хост, CI | колонки против dbt, фильтр категорий, тема, порядок импорта | формулы KPI: B2, B3, B4 зелёные (QA-03) |
| Grafana, экспортер | `test_marketplace_dashboard`, `test_check_dashboards`, `test_container_exporter` | 63 | хост, CI | только `lake_ro.gold`, нет `double`, разбор метрик | зависание без дедлайна (тест виснет, QA-07) |
| Конфиг и CI | `test_compose`, `test_pinning`, `test_minio_image`, `test_trino_access`, `test_workflows` | 174 | хост, CI | digest, SHA actions, порты, ACL Trino на своём оценщике | выпадение шагов CI и файлов `SPARK_TESTS`: K1-K5 зелёные (QA-01) |
| Алерты | `observability/prometheus/alerts_test.yml` (promtool) | 13 из 13 алертов имеют кейс | CI `alerts-test` | пороги, `for`, absent | мутации не гонялись (нет promtool на хосте) |

Вне pytest: `make dbt-build` (живой Trino), `make chaos-*`, `smoke.yml` (bootstrap, минута реплея,
`verify`, повторный bootstrap; без dbt).

## Пропуски на хосте (146) и где они исполняются

Факт (`full-run.txt`, суммы по `-rs`):

| Класс | Причина | Число | Файлы | Где исполняется | Доказательство (CI run 43400391213 на `da7ad2f`, последний зелёный) |
|---|---|---|---|---|---|
| Postgres | `RECONCILE_TEST_DSN is not set` | 59 | `test_reconcile_postgres.py` | отдельный шаг `lint-and-test` с `FAIL_ON_SKIP=1` (`.github/workflows/ci.yml`, шаг после `pytest tests/unit`) | `lint-and-test 2026-11-13T09:23:42.6277366Z 62 passed in 0.61s` |
| JVM без Iceberg | `local SparkSession needs a JVM` (26 и 23 с двумя текстами) | 49 | `test_silver_upsert`, `test_bronze_cdc_ingest`, `test_contracts`, `test_orders_per_minute` | `lint-and-test` на JDK раннера и повторно `spark-tests` | `lint-and-test ... 09:23:41.5832811Z 1974 passed, 97 skipped`: 97 = 59 + 38, то есть 49 JVM-тестов там прошли |
| Iceberg jar | `needs the Iceberg runtime jar: run make test-spark` | 38 | `test_silver_upsert`, `test_maintenance`, `test_orders_per_minute`, `test_iceberg_*`, `test_bronze_cdc_ingest` | только `spark-tests` (`make test-spark`, `FAIL_ON_SKIP=1`, `-p no:skipping`) | `spark-tests ... 09:22:09.7296780Z 239 passed, 9 warnings in 93.60s`; 239 = сумма тестов 8 файлов `SPARK_TESTS` (22+28+44+4+3+40+11+87) |

Вывод: все 146 пропусков исполняются в CI, 49 JVM-тестов дважды. Красный CI на `4adbab9` и
`a8c1d49` (run 43420783131, 43423260590: `Image: ubuntu-26.04`, `getSubject is not supported`)
дали именно эти 49 повторных тестов в `lint-and-test`; починка в дереве (`actions/setup-java`, JDK
17) не проверена run'ом (ведёт IN).

## Цена набора (R-27)

Факт: полный прогон 204.18 с (`real 3m25s`); CI `lint-and-test` pytest 185.55 с, `spark-tests`
93.60 с. По файлам отдельными прогонами: `test_agent_hooks` 65.1 с (859), `test_chaos_silver_kill`
69.3 с (40), `test_verify_script` 39.8 с (36), `test_agent_state` 6.0 с (151), остальные 43 файла
около 25 с. Харнесс: 1010 тестов из 2073 (48.7%), 71 с из 204 (35%).

Без правки хуков (класс A, только тесты):
- `SILVER_KILL_BURST` и `SILVER_KILL_POLL` 1 -> 0.2 в `tests/unit/test_chaos_silver_kill.py:184,186`:
  проверено в копии, `40 passed in 43.50s` против 69.28 с (−26 с).
- `test_verify_script.py`: один режим (`""`) вместо двух у медленных проб, где режим не влияет
  (пробы идут до ветки режима, `scripts/verify.sh:50-58`): по `--durations` сумма вторых режимов
  13.8 с (ctrl_c 3.03 + 2.03 + 2.04, signal 2.03, hangs 1.54 + 1.04 + 1.05 + 1.04). Оценка, не
  прогон.
- Итого около 204 -> 164 с на хосте.

Требует патча владельца: guard в процессе вместо 859 подпроцессов `python guard.py` (`hook()`,
`tests/unit/test_agent_hooks.py:20-30`); прежняя оценка R-27 −46 с, не перемерено. `pytest-xdist`
не делать: новая зависимость.

## Мутации (копия дерева, прогон из копии venv репозитория)

Мутации брались прицельно в подозрительные места, поэтому доля зелёных не характеризует набор в
целом. Полный вывод: `QA-work/mutations-result.txt`.

| Инвариант | Красные (поймано) | Зелёные (пропущено) |
|---|---|---|
| Выключатель обслуживания | S1, S2, S3, S4 | |
| Гейт gold | G1, G2, G3 | |
| Сверка 7 таблиц | R2 (Trino без `_is_deleted`), R3 (контракт пропал), R4 (колонка выпала), R5 (без `floor`) | R1 (silver-сторона сверки по значениям без `_is_deleted`); R6 (без `collate "C"`) на хосте, в CI ловит Postgres-шаг (Итог Б16, не перепроверено) |
| Контракты silver | C1 (масштаб decimal), C2 (nullable) | C3 (из `enum` выпал `boleto`) |
| Один писатель silver и Asset | W3 (имя контейнера) | W1 (`max_active_runs=2`), W2 (без пула), W4 (без `outlets`), W5 (снапшот запоминается до merge) |
| D4 в dbt | D1 | |
| Бандл Superset | B1 (GMV категорий без `NOT is_deleted`), T1b | B2 (GMV KPI с отменами), B3 (`paid_orders` = `COUNT(*)`), B4 (отмены с `unavailable`), T5 (`_with_type` не ставит тип) |
| CI и гейты набора | K6, K7 | K1 (шаг `pytest tests/unit` удалён), K2 (job с `contents: write`), K3 (`test_silver_upsert.py` выпал из `SPARK_TESTS`), K4 (`make dbt-parse` удалён), K5 (gitleaks удалён) |
| Проверка offsets в `verify` | | O1 (дыры не считаются) |
| Реплеер | | P1 (события не помечаются `emitted_at`), P2 (late не откладывается) |
| Подстрочные тесты | T2 | T1 (колонка gold пропала из select, `test_reconcile.py`); ложный красный на равносильной правке: T3 (перенос строки вызова), T4 (кавычки в compose) |
| Дедлайн Trino в `check_dashboards.py` | | без проверки дедлайна тест виснет (прерван `timeout 20`) |

Не прогонялись: Spark (нет JVM), promtool (нет на хосте), Postgres (нет DSN): см. «Не проверено».

## Тесты по подстроке исходника (R-08), текущее дерево

| file:line | Что | Решение |
|---|---|---|
| `tests/unit/test_dags.py:827-831` | подстрока вызова в `iceberg_orphans.py` | заменить на AST (T3: ложный красный на переносе строки) |
| `tests/unit/test_trino_access.py:121-123` | строка тома в compose | заменить на `yaml.safe_load` (T4: ложный красный на кавычках) |
| `tests/unit/test_reconcile.py:40-45` | `\bcolumn\b` по сырому SQL модели с комментариями | заменить на `output_columns` (`test_superset_bundle.py:111`, вынести в `tests/unit/dbt_sql.py`); T1 зелёная |
| `tests/unit/test_superset_import.py:69` | `"metadata.yaml" in` тексте скрипта | заменить поведением: `_with_type(_read_bundle(bundle), "Slice")`, модуль импортируется на хосте; T5 зелёная |
| `tests/unit/test_compose.py:167-168` | фразы `skips an existing` нет в compose | удалить: охраняет давно убранную фразу, любая другая ложная проходит |
| `tests/unit/test_maintenance.py:387-391` | `"${@:2}"` в `run-job.sh` | оставить: одна строка `exec`, поведение требует `spark-submit` |
| `tests/unit/test_dags.py:783` | `pools set gold_writers 1` в Makefile | оставить, дополнить `lake_writers` (QA-02) |
| `tests/unit/test_makefile.py:90-95` | regex `container_name` в DAG | оставить: при переносе в константу падает громко |
| `tests/unit/test_compose.py:64-65,128-136` | строка `.env.example`, шапка compose | оставить: конфиг как контракт |
| `tests/unit/test_minio_image.py:122-135` | текст `check-minio-images.sh` | оставить: скрипт исполняется в CI на образах, тест держит его силу |
| `tests/unit/test_superset_import.py:89-93` | строка вызова в `init.sh` | оставить |
| `tests/unit/test_verify_script.py:346-354` | литерал 7 таблиц против контрактов | оставить: сверка двух файлов, мутации красные (Б20) |
| `tests/unit/test_reconcile.py:253-265` | `materialized='incremental'` | оставить: ошибается только громко |
| `tests/unit/test_superset_bundle.py:271-273`, `tests/unit/test_marketplace_dashboard.py:61-65` | запрещённые слова в YAML и JSON | оставить: так задуман deny-list |
| `tests/unit/test_workflows.py:45-56` | `make verify`, `grep -qx 'verify ok'` в smoke | оставить |
| `tests/unit/test_dbt_soft_delete.py`, `test_dbt_bi_columns.py:12-15`, `test_reconcile.py:55-63` | regex по SQL dbt без комментариев | оставить: статический заменитель живых dbt-тестов, мутации красные |
| `tests/unit/test_agent_hooks.py:1165-1187` (docker хоста), `:1910-1918` (`load_guard`), `tests/unit/test_agent_state.py:518-523` (текст роли) | харнесс | решают HG и HS |

## Старый бэклог

| ID | статус сейчас | делать / не делать | причина |
|---|---|---|---|
| R-02 | открыт: `tests/unit/test_agent_hooks.py:39-44` `decision()` не смотрит `guard.py failed` | решает HG | харнесс |
| R-08 | не-харнесс: открыты `test_dags.py:827-831`, `test_trino_access.py:121-123`, `test_compose.py:167-168` (было 164-165), `test_maintenance.py:387-391`; харнесс открыт | делать QA-05 (кроме `run-job.sh`: оставить) | ложный красный T3, T4; слабые T1, T5 |
| R-27 | открыт: 204 с хост, 185 с CI | делать QA-08 без хуков; guard в процессе через HG и владельца | −40 с без патча измеримо |
| PF-31 (F-05) | открыт: P1, P2 зелёные | не делать | реплеер это генератор нагрузки: его вывод сверяется ниже по потоку, бюджет реплея закрыт, тест M на Postgres CI |
| PF-32 | открыт: `scripts/chaos/lib.sh:218-227`, тест только по тексту фейка `test_chaos_silver_kill.py:95`; O1 зелёная | делать QA-06 | ослабление проверки exactly-once в `verify` проходит набор |
| PF-40, QA-03 (F-06) | открыт: `smoke.yml` без dbt; документы не говорят, что gold, DAG и дашборды проверены только вживую | E2E не делать (решение 18, раздел 5); строку в документах делать (QA-09) | честность для читателя |
| PF-41 | тестовая часть закрыта: `test_superset_bundle.py:99,152`, T1b красная; job сборки образа Superset нет | job решают IN и GB | |
| PF-42 | закрыт: `test_superset_bundle.py:173`, B1 красная | | |
| PF-65 | открыт, воспроизведён: `--basetemp` длиной 112 даёт `2 errors` в `test_container_exporter.py` (`:261-263`) | делать QA-10 | падает в scratchpad агентов и глубоких CI-путях |
| QA-02 | принято: Spark-тесты в CI `spark-tests` с `FAIL_ON_SKIP` | не делать | доказано run'ом |
| QA-05 | заменён таблицей R-08 выше | | |
| QA-06, 14 §7 (expire только по ключу) | закрыт: `test_maintenance.py:455-457` | | |
| QA-07 | закрыт: `test_iceberg_sink.py:185` (две query) | | |
| QA-09 | закрыт: R3 красная | | |
| Б16 (`collate "C"`, `floor`) | закрыт в `b40a329`; R5 красная на хосте, R6 только в CI | | |
| 14 §7: права job в smoke | открыт: K2 зелёная | делать в QA-01 | |
| 14 §7: тест дедлайна Trino виснет | открыт: без проверки дедлайна тест висит (прерван `timeout 20`), `tests/unit/test_check_dashboards.py:216-227` | делать QA-07 | зависание вместо красного съедает 15 мин job |
| HANDOFF 13.11: `annotation_layers` в `queries[0]` не сверяется (`test_superset_bundle.py:324` смотрит только `params`), `rename` для одной метрики (`:540-551`) | открыт | решает GB | бандл Superset |

## Находки «делать»

### QA-01 [средняя] Мета-тесты CI не ловят выпадение шагов и файлов Spark-набора
Где: `tests/unit/test_workflows.py:59-71`; `Makefile:159-160` (`SPARK_TESTS`).
Факт: комментарий `test_workflows.py:60` «Dropping a step must turn a test red», но тест проверяет
только 4 job. Зелёные мутации: K1 (удалён `uv run pytest tests/unit -q`), K4 (`make dbt-parse`),
K5 (gitleaks), K2 (job `alerts-test` с `permissions: contents: write`), K3 (`test_silver_upsert.py`
убран из `SPARK_TESTS`: 21 Iceberg-тест MERGE не исполнялся бы нигде, CI зелёный).
Чем плохо: правка CI или новый Spark-файл без строки в `SPARK_TESTS` оставляют CI зелёным с
меньшим числом проверок: ложный зелёный по главному инварианту.
Правка: тесты первыми, красные на мутациях K1-K5. (1) `test_ci_runs_the_checks_it_claims`: для
`lint-and-test` требовать `uv run pytest tests/unit -q`, `make dbt-parse`, `uv run mypy`, `ruff
check`, `compose ... config -q` и шаг `uses: gitleaks/gitleaks-action@`. (2) Новый тест: ни у
одного job ни одного workflow нет `permissions`, кроме `read` (14 §7). (3) Новый тест в
`test_makefile.py`: множество файлов `tests/unit/test_*.py`, где есть `needs_iceberg`, `needs_java`
или `SparkSession`-фикстура, равно `SPARK_TESTS` (через `make -n test-spark`, как
`test_makefile.py:189-194`); файл с пропуском по `RECONCILE_TEST_DSN` ровно тот, что идёт в шаге
CI с `FAIL_ON_SKIP` (есть `test_reconcile_postgres.py:343-361`, дополнить общим правилом).
Проверка: `uv run pytest tests/unit/test_workflows.py tests/unit/test_makefile.py -q` зелёный;
мутации K1-K5 в копии (`QA-work/mutations3.json`, `python QA-work/mutate.py ... K1 K2 K3 K4 K5`)
дают `RED`.
Размер: S; класс A; «ок» на карточку.
Старый ID: 14 §7 (права job smoke); нет.

### QA-02 [средняя] Проводка DAG `silver_upsert` (один писатель, Asset для gold) не защищена тестом
Где: `airflow/dags/silver_upsert.py:35` (`max_active_runs=1`), `:66` (`pool=LAKE_WRITERS_POOL`),
`:67` (`outlets=[Asset(SILVER_ASSET_NAME)]`), `:78` (`snapshot >> merge >> remember_snapshot`);
`Makefile:128` (`pools set lake_writers 1`).
Факт: из этого тестируется только имя контейнера (`tests/unit/test_dags.py:1173-1180`, W3 красная)
и таймауты; `make dags-check` проверяет тоже только `container_name` (`Makefile:190`). Зелёные: W1,
W2, W4, W5.
Чем плохо: без пула merge и обслуживание коммитят в одну таблицу одновременно (проигравший падает,
ADR-010); без `outlets` `dbt_build` не запускается и gold стоит (виден только алертом
`GoldStaleAtRest`); снапшот, записанный до merge, теряет повтор после упавшего merge до следующего
коммита bronze.
Правка: тест первым. В `test_dags.py`: `dag_keywords("silver_upsert.py", "dag")` даёт
`max_active_runs == 1`, `catchup is False`; у `DockerOperator` merge `pool` это `Name
LAKE_WRITERS_POOL`, `outlets` содержит `Asset(SILVER_ASSET_NAME)`; `dag_keywords("dbt_build.py",
"dag")["schedule"]` это `[Asset(SILVER_ASSET_NAME)]`; рёбра `("snapshot","merge")` и
`("merge","remember_snapshot")` через `dependency_edges` (`:860`), научив `names()` вызов
`ast.Call` (имя функции); `"pools set lake_writers 1"` рядом с проверкой `gold_writers` (`:783`).
Проверка: тесты зелёные; мутации W1, W2, W4, W5 (`QA-work/mutations.json`) дают `RED`.
Размер: S; класс A; «ок» на карточку.
Старый ID: нет.

### QA-03 [средняя] Формулы KPI Superset не проверяются: отмены в GMV и заказах проходят набор
Где: `docker/superset/dashboards/datasets/Lakehouse_Trino_lake_ro/fct_orders.yaml:29` (`gmv`),
`:45` (`paid_orders`), `:53-55` (`aov`), `:63-65` (`freight_share`), `:81` (`cancellation_rate`),
`:113` (`in_transit_orders`); тест есть только у GMV категорий (`tests/unit/test_superset_bundle.py:173`).
Факт: B2 (`gmv` = `SUM(items_value)`), B3 (`paid_orders` = `COUNT(*)`), B4 (отмены с
`unavailable`) зелёные на `test_superset_bundle`, `test_superset_style`, `test_superset_import`.
Чем плохо: дашборд молча показывает другие числа, чем gold и `dq_checks` (GMV без отмен, D8);
сверки Superset с gold нет.
Правка: тест первым. Для каждой метрики датасетов `fct_orders` и `fct_order_items` с
`order_status NOT IN (...)`: множество статусов в каждом вхождении равно
`reconcile.GMV_EXCLUDED_STATUSES` (разбор как `tests/unit/test_reconcile.py:48-52`, в нижнем
регистре), и число вхождений равно числу агрегатов `SUM`/`COUNT_IF` в выражении (каждый агрегат
отфильтрован); `cancellation_rate` считает только `'canceled'` в числителе. Таблица ожидаемых имён
метрик, чтобы удаление фильтра у новой метрики не прошло.
Проверка: `uv run pytest tests/unit/test_superset_bundle.py -q` зелёный; B2, B3, B4 дают `RED`.
Размер: S; класс A; «ок» на карточку. Пересекается с GB (метрики): свести в один пакет.
Старый ID: нет (рядом PF-42).

### QA-04 [низкая] Silver-сторона сверки по значениям без `_is_deleted` проходит набор
Где: `airflow/dags/lakehouse/reconcile.py:299`.
Факт: R1 (`where = ""`) зелёная на `test_reconcile.py`, `test_reconcile_sql.py`, `test_dags.py`;
Trino-сторону ни один тест не исполняет.
Чем плохо: после первого удаления в источнике `dq_checks` красный ложно (громко, не молча).
Правка: тест первым в `test_reconcile.py`: `where not _is_deleted` есть в
`fingerprint_sql_trino(t)` и `pairs_sql_trino(t)` для всех 7 таблиц и в `gold_silver_sql_trino(g)`
для трёх пар с `live_only`, и нет у `fct_order_items`.
Проверка: R1 даёт `RED`.
Размер: S; класс A.
Старый ID: нет.

### QA-05 [низкая] Подстрочные тесты: ложный красный на равносильной правке и слабые проверки (R-08)
Где и правка: таблица R-08 выше: заменить `test_dags.py:827-831` (AST: вызов `gold_orphans_command`
с аргументами `name` и `params or {}`, нет `orphans_command` с `gold_table`), `test_trino_access.py:121-123`
(`yaml.safe_load`, том в `services.trino.volumes`), `test_reconcile.py:40-45` (`output_columns`,
вынести из `test_superset_bundle.py:111` в `tests/unit/dbt_sql.py`), `test_superset_import.py:69`
(вызов `_with_type`); удалить `test_compose.py:167-168`.
Факт: T3, T4 красные на равносильных правках; T1, T5 зелёные на поломке.
Проверка: T3, T4 дают `GREEN`; T1, T2, T5 дают `RED` (`QA-work/mutations2.json`).
Размер: S; класс A.
Старый ID: R-08 (не-харнесс часть), QA-05.

### QA-06 [средняя] Проверка дыр и дублей offsets в `verify` без теста семантики (PF-32)
Где: `scripts/chaos/lib.sh:218-227` (`bronze_offsets_ok`), вызов `scripts/verify.sh:60`.
Факт: O1 (условие дыр удалено) зелёная на `test_chaos_silver_kill`, `test_verify_script`,
`test_reconcile_shell`, `test_makefile` (`109 passed`); фейк отвечает по тексту `having count(*) >`
(`test_chaos_silver_kill.py:95`). Проба `QA-work/offsets_sqlite_probe.py`: запрос из `lib.sh`
исполняется на `sqlite3` из стандартной библиотеки (`attach ':memory:' as bronze`) и даёт `clean 0,
duplicate 1, hole 1, hole in other partition 1`.
Чем плохо: ослабленная проверка exactly-once в `make verify` проходит набор: ложный зелёный гейта.
Правка: тест первым в новом `tests/unit/test_offsets_check.py`: извлечь запрос из `lib.sh` regex'ом
(как в пробе), прогнать на sqlite: чистый набор 0, дубль 1, дыра 1, дыра в другой партиции 1, две
темы без пересечения 0. Без новой зависимости.
Проверка: `uv run pytest tests/unit/test_offsets_check.py -q` зелёный; O1 (`QA-work/mutations5.json`)
даёт `RED`.
Размер: S; класс A.
Старый ID: PF-32.

### QA-07 [низкая] Два теста не падают как надо: повтор батча в silver и дедлайн Trino
Где: `tests/unit/test_silver_upsert.py:321-329` и хелпер `:304-305`;
`tests/unit/test_check_dashboards.py:216-227`.
Факт: `silver()` собирает dict по `order_id`, дубли строк в нём схлопываются, а тест повтора
сравнивает только ключи и `_last_lsn` (гипотеза: MERGE, заменённый на append, пройдёт этот тест;
его ловит соседний `:455` `count() == len(before)`; не прогонялось, нет JVM). Без проверки дедлайна
в `scripts/obs/check_dashboards.py:152-153` тест дедлайна не краснеет, а виснет: прогон прерван
`timeout 20`.
Правка: в тесте повтора `spark.table(...).count() == 2` и равенство полных строк, включая
`_updated_at`; в тесте дедлайна фейковый `urlopen` с счётчиком, `AssertionError` после 10 вызовов.
Проверка: `make test-spark SPARK_TESTS=test_silver_upsert.py` зелёный; удаление строк 152-153 в
копии даёт `FAILED`, а не зависание.
Размер: S; класс A.
Старый ID: 14 §7 (дедлайн).

### QA-08 [низкая] Цена набора: −40 с без правки хуков (R-27)
Где: `tests/unit/test_chaos_silver_kill.py:184,186`; `tests/unit/test_verify_script.py`
(параметр `mode` у медленных проб).
Факт: см. «Цена набора»: 69.3 -> 43.5 с измерено; −13.8 с по `--durations`.
Правка: `SILVER_KILL_BURST` и `SILVER_KILL_POLL` = `"0.2"`; у тестов ctrl_c, signal и hangs
оставить один режим, один дешёвый тест на `--no-merge` после отказа пробы сохранить.
Проверка: `uv run pytest tests/unit/test_chaos_silver_kill.py tests/unit/test_verify_script.py -q`
зелёный и быстрее примерно на 40 с; число тестов `test_verify_script` уменьшится на 8.
Размер: S; класс A.
Старый ID: R-27 (часть без хуков).

### QA-09 [средняя] `tests/README.md` устарел; нигде не сказано, что проверено только вживую
Где: `tests/README.md:3-5` («envelope fixtures ..., dedup and LSN-guard logic ..., replayer virtual
clock»: 3 темы из 15 компонентов), `:14` (харнесс без `test_agent_state.py`); `README.md:211-221`
и `docs/evidence.md:153-185` без строки о том, что не в CI.
Чем плохо: читатель не видит карты набора, классов пропусков и того, что `dbt build` с
dbt-тестами, запуски DAG, chaos и дашборды доказаны только на стенде.
Правка: `tests/README.md` переписать по таблицам «Карта набора» и «Пропуски на хосте» (компонент,
файлы, где исполняется, что не ловит), одной строкой долю харнесса; в README «Testing and CI» и
evidence «CI and smoke» одна строка: CI исполняет `dbt parse` и статические проверки SQL, `dbt
build`, DAG, chaos и дашборды проверены на живом стенде (ссылки на evidence). Без чисел, которые
устареют, кроме ссылок на run.
Проверка: `grep -n 'test_agent_state\|RECONCILE_TEST_DSN\|spark-tests\|dbt build' tests/README.md`
находит все четыре; ссылки проверяет скрипт DC.
Размер: S; класс A; `docs-writer`.
Старый ID: PF-40 (часть документов).

### QA-10 [низкая] Тесты сокета экспортера падают при длинном `--basetemp` (PF-65)
Где: `tests/unit/test_container_exporter.py:261-263`.
Факт: `uv run pytest tests/unit/test_container_exporter.py --basetemp=<путь 112 символов>`:
`14 passed, 2 errors`.
Правка: сокет в `tempfile.mkdtemp(dir="/tmp")` с удалением в фикстуре.
Проверка: та же команда даёт `16 passed`.
Размер: S; класс A.
Старый ID: PF-65.

## Находки «не делать»

| ID | что | почему не делать |
|---|---|---|
| QA-N1 | Интеграционный тест ядра реплеера (PF-31, P1, P2 зелёные) | генератор нагрузки, не путь данных; его вывод сверяется ниже по потоку; бюджет реплея закрыт; M |
| QA-N2 | E2E с `dbt build` в smoke или CI (PF-40) | решение 18, раздел 5; честная строка в документах (QA-09) |
| QA-N3 | Перенос тестов харнесса в `tests/harness/` | меняет пути в `make test`, CI, `AGENTS.md`, `CLAUDE.md` (окно подтверждения); карта в `tests/README.md` даёт то же |
| QA-N4 | `pytest-xdist` | новая зависимость |
| QA-N5 | Не гонять 49 JVM-тестов в `lint-and-test` (они же в `spark-tests`) вместо `setup-java` | починка в дереве владельца уже есть; решает IN |
| QA-N6 | Тест: значения `enum` контракта против выборки (C3) | сужение `enum` громко видно на стенде (quarantine и красная сверка); правка контракта редка |
| QA-N7 | Разбить `test_dags.py` (1468 строк) | рефакторинг ради вкуса |
| QA-N8 | `test_makefile.py:90-95`, `test_maintenance.py:387-391` на AST или поведение | падают громко; поведение `run-job.sh` требует `spark-submit` |

## Разрыв с продом

- Нет E2E в CI дальше silver: `dbt build`, DAG Airflow, дашборды проверяются только на стенде.
- Нет измерения покрытия и мутационного тестирования в CI: мутации только ручные в аудитах.
- Spark-тесты идут на локальном Hadoop-каталоге, не на Lakekeeper REST и MinIO.
- ACL Trino проверяется собственным оценщиком правил (`test_trino_access.py`), не Trino.
- Нет таймаута на тест: зависший тест держит job до `timeout-minutes` (15 мин).
- Нет нагрузочных тестов и тестов на объёме больше выборки Olist.
- Почти половина набора (48.7%) тестирует харнесс агентов, а не продукт.

## Не проверено

- Spark-мутации MERGE (замена на append, `>=` в LSN-guard): нет JVM. Команда: мутация в копии и
  `make test-spark SPARK_TESTS=test_silver_upsert.py SPARK_IMAGE=lakehouse/spark:dev` (запрещено в
  этом аудите).
- R6 на Postgres: `RECONCILE_TEST_DSN=<одноразовый Postgres> FAIL_ON_SKIP=1 uv run pytest
  tests/unit/test_reconcile_postgres.py -q` в копии без `collate "C"`.
- Мутации правил алертов: `make alerts-test` на копии `observability/prometheus/alerts.yml`.
- Выигрыш guard в процессе (−46 с из R-27) не перемерен.
- Зелёный CI с починкой JDK в дереве: только run после push (IN).
- Содержание dbt-тестов и `dbt/tests/*.sql`: область GB.
