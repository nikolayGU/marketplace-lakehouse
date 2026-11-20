# P06. Путь данных: слой отката JDBC, мёртвый код, лог merge, Java 17 в Spark-тестах

Статус: исполнен 20.11.2026, `b18aefe`, `6020b64`. Opus, `/task docs/planning/21-final-audit-2026-11-13/P06-data-path.md`.

## Цель

Убрать мёртвый слой отката JDBC с паролем суперпользователя `postgres-meta` в Spark, Trino и
Airflow; снять мёртвый код streaming; починить лог merge, виды opm, mount реплеера; сверить домены
контрактов с CHECK; Spark-тесты хоста только на Java 17; тест повтора батча ловит append.

## Находки пакета

| ID | серьёзность | суть | где подробности |
|---|---|---|---|
| DP-01 (R-40, AR-07) | средняя | слой отката JDBC: код, compose, env, скрипт, ранбук, документы, тесты | `reports/DP.md` DP-01; `reports/AR.md` AR-07 |
| DP-02 (R-44) | низкая | мёртвый код streaming; `noqa: UP017` вместо `per-file-target-version` | `reports/DP.md` DP-02 |
| DP-03 (R-07) | низкая | лог merge считает карантин; `--option` без `=` падает после старта Spark | `reports/DP.md` DP-03 |
| DP-04 (PF-33) | низкая | временный вид `opm_batch_<id>` на каждый батч в долгом драйвере | `reports/DP.md` DP-04 |
| DP-05 (IN-10, PF-36) | низкая | мёртвый mount `${DATA_DIR}:/data` у `oltp-replayer` | `reports/DP.md` DP-05; `reports/IN.md` IN-10 |
| DP-06 (PF-35) | низкая | `enum`, `minimum`, `maximum` контрактов не сверены с CHECK; список коннектора не сверен с контрактами | `reports/DP.md` DP-06 |
| IN-02 | средняя | Spark-тесты проверяют только `which java`: на JDK 21/25 `make check` красный | `reports/IN.md` IN-02 |
| QA-07 (часть) | низкая | `test_replaying_a_batch_changes_nothing` не ловит append вместо MERGE | `reports/QA.md` QA-07 |
| AR-10 | низкая | отказ orphans по данным bronze ссылается на ADR-021 и ADR-005, а правило записано в ADR-025 | `reports/AR.md` AR-10; `P12-decisions.md`, «Расхождения» |

## Решения владельца и действия класса C

- В-03 (README, раздел 3). «Да»: шаги 2-3 и 9 целиком. «Нет»: из DP-01 только комментарии
  `docker/compose.yaml` (`:206-207`, `:312-313`, `:509`, `:539-540`, `:551`) и
  `streaming/spark_jobs/settings.py:16-17` по правде: «pre-cutover JDBC catalog, no longer a
  valid rollback (ADR-005, Rollback)»; `config --hash '*'` до и после равен. Остальное от В-03
  не зависит; новый код streaming тогда вживую только со следующей сборкой и пересозданием (C).
- Первым, до кода («код против ADR не пишется»): строка в ADR-005 после абзаца «Rollback:»
  (`DECISIONS.md:257-264`), пишет оркестратор, текст на «ок» владельца:

  ```text
  Removed, <YYYY-MM-DD>: the JDBC catalog path of the code and its settings (`CATALOG_TYPE`,
  `CATALOG_JDBC_*`, `CATALOG_DB`, the PostgreSQL driver in the Spark image, the `postgres-meta`
  credentials of Spark, Trino and the Spark environment of Airflow) and
  `scripts/lakekeeper/register.sh`; the cutover runbook moved to `docs/planning/archive/`. The
  rows in `iceberg_catalog` stay as data; a new `postgres-meta` volume no longer creates it.
  ```

  В индексе (`DECISIONS.md:12`) к статусу ADR-005: «; JDBC layer removed <date>».
- Класс C: «ок» на точный текст шага 9, `$COMPOSE` в запросе раскрыть. Сборка образа по
  `13-harness.md`, раздел 2, это B при условиях, но идёт в том же запросе.
- Сверх В-n, в первом вопросе сессии: снятие паузы `iceberg_maintenance` это C. Либо пауза на
  время правки `airflow/dags/lakehouse/settings.py` и снятие по «ок», либо правка и коммит вне
  окна 03:00-04:00 UTC при пустом `list-runs --state running`.
- Владельцу руками: `sudo rmdir docker/data` (пустой каталог root от мёртвого mount); строки
  `CATALOG_TYPE`, `CATALOG_DB` в `.env` ничем не читаются, удалить по желанию.

## Зависимости

- P01: CI зелёный с JDK 17; без `ci` success на HEAD шаг 9 не начинать. P05 правит DAG:
  строки искать по цитате. После P06: P07 (якоря compose), P10 (`test_spark_settings.py:97` уйдёт).

## Вход

Сверить первым шагом; номера по дереву 13.11 (HEAD `a8c1d49`):

1. Полный список слоя отката (106 строк в 15 файлах):

   ```bash
   PAT='CATALOG_TYPE|CATALOG_JDBC|CATALOG_DB|CATALOG_WAREHOUSE|catalog_type|catalog_jdbc'
   PAT="$PAT|catalog_warehouse|catalog-cutover|lakekeeper/register|postgresql-42"
   git grep -n -E "$PAT" -- ':!docs/planning' ':!docs/HANDOFF.md' ':!docs/NEXT_SESSION.md' \
     | cut -d: -f1 | sort | uniq -c
   ```

2. `catalog.py:34` «`if settings.catalog_type == "jdbc":`», комментарии `:21-22`, `:25-26`;
   `streaming/Dockerfile:22` `postgresql-42.7.8.jar`, другого JDBC в `streaming/spark_jobs` нет.
3. compose: `:206-207` «is kept as the rollback point»; `depends_on: postgres-meta` у
   `spark-bronze` `:301-302`, `spark-silver` `:416-418`, `trino` `:494-496`; env `:312-317`,
   `:372-376`, `:429-433`; `trino` `:509-512` и `:518` (`S3_BUCKET` не читает ни один файл
   `docker/trino/etc`); `:539-540`; `:551` «creates iceberg_catalog». Ожидание Spark и Trino
   держит цепочка `lakekeeper-bootstrap` -> `lakekeeper` -> `lakekeeper-migrate` -> `postgres-meta`.
4. Хэши (опыт повторён 13.11 на копии `git archive HEAD docker .env.example`, правка скриптом
   `work/DP/edit.py.txt`, `--env-file .env.example --profile '*' config --hash '*'` до и после
   из одного каталога): меняются ровно `airflow-api-server`, `airflow-dag-processor`,
   `airflow-scheduler`, `spark-bronze`, `spark-orders-per-minute`, `spark-silver`, `trino`;
   удаление mount DP-05 добавляет `oltp-replayer`. Хэш зависит от каталога (пути bind mount).
5. Живьём 13.11: bronze и opm уже `write.metadata.delete-after-commit.enabled true`; Trino
   `-J-Xmx2g`; opm на образе `9b41b55b`, тег `94bda0b9`. `SPARK_SILVER_ENV` берут `silver_upsert`
   и через `spark_task.py:15` `iceberg_maintenance` (`30 3 * * *`) и `iceberg_orphans` (на паузе).
6. DP-03: `silver_upsert.py:268-275` логирует `count`; `maintenance.py:300` «`dict(item.split("=",
   1) ...)`» исполняется после `open_session()` `:325`. Префикс строки merge читают
   `scripts/chaos/silver-kill.sh:43,154,171`, `late.sh:92`, `test_chaos_silver_kill.py:69-72`.
7. DP-04 `orders_per_minute.py:97` «`view = f"opm_batch_{batch_id}"`». DP-05 `compose.yaml:470,
   472-473`; `start` не читает `data_dir` (`load.py:115,199` только в `load`). DP-06
   `orders.json:12`, `payments.json:12`, `reviews.json:13` против `001_schema.sql:43-48,69-71,85`.
8. IN-02: `shutil.which("java")` в `test_bronze_cdc_ingest.py:38`, `test_contracts.py:31`,
   `test_maintenance.py:42`, `test_iceberg_sink.py:20`, `test_orders_per_minute.py:21`,
   `test_iceberg_demo.py:17`, `test_silver_upsert.py:43`; образец модуля `tests/unit/dbt_sql.py`.
   QA-07: `test_silver_upsert.py:321-329`, хелпер `silver()` `:304-305` схлопывает дубли в dict.

## Границы

- Менять можно: файлы «Входа» и шагов, `tests/unit/test_compose.py`, `test_contracts.py`, новые
  `tests/unit/spark_jvm.py` и `test_spark_jvm.py`, `pyproject.toml` (`[tool.ruff]`),
  `contracts/README.md`, `docker/postgres-meta/init/01-databases.sql`, `tests/README.md:7`.
- Нельзя: базу `iceberg_catalog` и её строки, checkpoint, `.env`, `.claude/` (шаблон `register`
  в `guard.py:299` остаётся, это P03), исторические абзацы ADR-005, `docs/evidence.md:331`,
  `docs/interview-notes.md:232`, `OPERATIONS.md:1115-1116`; ID карточек в коде (P10).
- Живой стек: до шага 9 только чтение и цикл verify (`13-harness.md`, раздел 5).

## Шаги

1. ADR-005 (оркестратор): строка выше по «ок» на текст. Без неё код не трогать.
2. DP-01, тесты на отказ (`implementer`). `test_compose.py`: (a) ни у одного сервиса нет ключа
   env с префиксом `CATALOG_`; (b) сервисы, чьи значения env содержат `META_PASSWORD`, это ровно
   `postgres-meta`, `lakekeeper-migrate`, `lakekeeper`, `superset`, `superset-init`,
   `superset-mcp`; (c) в `airflow.env` нет `CATALOG_`, а `META_PASSWORD` только в
   `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN`. `test_spark_settings.py`: `"catalog_type" not in
   Settings.model_fields`; при `CATALOG_TYPE=jdbc` в env `catalog_conf` даёт `type` `rest`.
   Красные на HEAD: `spark-bronze` `:312-317`, `trino` `:510-512`, `settings.py:18`.
3. DP-01, правка одним diff. `implementer`, два брифа параллельно: (А) `streaming/` и тесты:
   `catalog.py` только REST-блок, комментарии: HadoopFileIO, потому что в образе нет AWS SDK v2,
   `fs.s3.impl`, потому что Lakekeeper кладёт таблицы под `s3://`; `settings.py:16-22`;
   `Dockerfile:22`; в `test_spark_settings.py` удалить `:9-33` и `:68-101`, из `:36-65` убрать
   `CATALOG_TYPE`, `CATALOG_JDBC_PASSWORD` и комментарий `:50`. (Б) compose по «Входу» 3,
   `airflow.env:31-35`, `.env.example:37-40`, `01-databases.sql:1`,
   `airflow/dags/lakehouse/settings.py:53-57,65` (сначала пауза по `13-harness.md`, раздел 2, и
   решению об `iceberg_maintenance`); удалить `scripts/lakekeeper/register.sh`, поправить
   `protect.sh:5`. Оркестратор: `git mv docs/runbooks/catalog-cutover.md
   docs/planning/archive/catalog-cutover-2026-10-08.md`, ссылка `DECISIONS.md:197` на новый путь.
   `docs-writer`: `OPERATIONS.md:355,395-410`, «What deletes files» `:412-430` без колонки «JDBC
   catalog» и фраз об откате, `:567,1765`; `streaming/README.md:5-7,31-34`;
   `scripts/README.md:33-38`.
4. DP-02 без `ADDED_COLUMNS` («Расхождения»). `pyproject.toml` `[tool.ruff]`:
   `per-file-target-version` с `"streaming/**" = "py310"` и восемью файлами `SPARK_TESTS`
   (`Makefile:157-158`, они идут на Python 3.10 образа); снять `# noqa: UP017` в
   `maintenance.py:111,116,327` и `test_maintenance.py:40,448,467,482,529,531`; прозу о 3.10
   (`settings.py:3`, `orders_per_minute.py:17`, `maintenance.py:14`) свести к «ruff checks this as
   py310 (pyproject)». Удалить `opm_starting_offsets` (`settings.py:52`; в
   `orders_per_minute.py:143` литерал `"earliest"` с комментарием как `bronze_cdc_ingest.py:131`),
   `deletes.set_defaults(days=None)` (`maintenance.py:233`), поле `table` в `ENVELOPE`
   (`bronze_cdc_ingest.py:39`). На копии: ruff 0.16.8 с этим ключом «All checks passed!».
5. DP-03, тесты первыми: `test_maintenance.py`: `parse_args(["rewrite-data", "--option", "nokey",
   "silver.orders"])` -> `SystemExit` 2 (красный: сейчас `ValueError` позже, в `execute`).
   Spark-тест с `caplog`: батч из одного годного и одного битого события пишет «1 events merged»
   (красный: 2); в том же тесте число строк `lake.silver.orders.snapshots` до и после батча только
   из битых. Правка: `valid = count - sum(why.values())` в строке лога; MERGE при `valid == 0`
   пропускать со строкой «batch N: nothing to merge into lake.silver.<t>» только если тест
   показал пустой снапшот. Префикс «batch N: M events merged into lake.silver.<t> in X s» не
   менять. `--option`: `type=` с `argparse.ArgumentTypeError` без `=` или с пустым ключом.
5а. AR-10, тесты первыми (`implementer`, тем же брифом, что шаг 5): в
   `tests/unit/test_maintenance.py` два ожидания отказа orphans по данным bronze меняются с
   `ADR-021` на `ADR-025`: `match="ADR-021"` в
   `test_orphans_of_bronze_data_is_refused_without_the_metadata_location` (около `:120`) и
   `"ADR-021" in` в `test_bronze_orphans_in_data_are_refused_before_a_spark_session` (около
   `:384`); оба теста становятся красными. Затем `streaming/spark_jobs/maintenance.py:84`:
   `(ADR-021, ADR-005)` на `(ADR-025)`. Основание: правило «data files of bronze are never
   removed» записано в ADR-025 («The rules live in the job»), ADR-021 держит запрет expire
   снапшотов bronze. Тесты expire (`:92`, `:360`, `:372`) и docstring `:9-10` остаются на
   ADR-021: они верны.
6. DP-04: тест первым в `test_orders_per_minute.py`: после двух `upsert` в
   `spark.catalog.listTables()` нет временного вида с префиксом `opm_batch` (красный: 2);
   правка: `spark.catalog.dropTempView(view)` в `finally` или постоянное имя `opm_batch`.
7. DP-05: тест первым в `test_compose.py`: у `oltp-replayer` нет `volumes` и `DATA_DIR`; удалить
   `compose.yaml:470,472-473`. DP-06 (A): в `test_contracts.py` домены `enum`, `minimum`,
   `maximum` равны CHECK `001_schema.sql` (разбор как `source_tables()` `:46`) и множество
   `x-source-table` равно `table.include.list`; строка в `contracts/README.md` после абзаца
   «Adding a column» по тексту `reports/DP.md`, DP-06. Мутация в копии: без `"unavailable"` в
   `orders.json` тест красный.
8. IN-02 и QA-07 (`implementer`). `tests/unit/spark_jvm.py`: `java_major(text) -> int | None` и
   кэшированный `HAS_SPARK_JVM` (stderr `java -version`, major 17 или 11), причина skip «local
   SparkSession needs Java 17 (Spark 3.5); CI and the image have it». Тест первым
   `test_spark_jvm.py`: `openjdk version "25.0.5"` -> 25, `"17.0.21"` -> 17, `"1.8.0_392"` -> 8,
   мусор -> None (красный: модуля нет). Заменить 7 копий «Входа» 8; `Makefile:153` и
   `tests/README.md:7`: «without Java 17». QA-07: в тесте повтора добавить
   `spark.table(f"{SILVER}.orders").count() == 2` и `silver(spark) == first` (с `_updated_at`).
9. Проверки и коммит: «Готово, когда» до пункта «после пересоздания», `reviewer`, цикл verify и
   коммит по `13-harness.md`, раздел 5; push по «ок»; `gh run list --limit 1` -> `ci` success
   на HEAD. Затем класс C одним «ок» на этот текст («До» снять перед запросом):

   ```bash
   COMPOSE="docker compose --env-file .env -f docker/compose.yaml"
   af() { $COMPOSE exec -T airflow-scheduler airflow "$@"; }
   git status --short                         # пусто
   $COMPOSE --profile core build spark-bronze
   make test-spark                            # на новом образе: 0 failed
   for d in silver_upsert dbt_build dq_checks; do af dags pause "$d"; done
   for d in silver_upsert dbt_build dq_checks iceberg_maintenance; do
     af dags list-runs "$d" --state running   # пусто у всех
   done
   TRINO_XMX=2g make start       # пересоздаёт spark-bronze и trino; Trino на 2g, как сейчас
   make up PROFILE=stateful      # пересоздаёт spark-orders-per-minute
   make up PROFILE=orchestrate   # пересоздаёт три сервиса Airflow; DAG остаются на паузе
   $COMPOSE stop airflow-scheduler
   make verify                   # последняя строка: verify ok
   $COMPOSE start airflow-scheduler
   for d in silver_upsert dbt_build dq_checks; do af dags unpause "$d"; done
   ```
10. «Итог» по разделу 6 `13-harness.md`, HANDOFF, статус в README папки; коммит `docs:`.

## Готово, когда

- [ ] grep «Входа» 1 с исключением `':!DECISIONS.md'` -> пусто
- [ ] `uv run pytest tests/unit/test_{compose,spark_settings,dags,airflow_env,contracts}.py
      tests/unit/test_{maintenance,spark_jvm}.py -q` -> 0 failed
- [ ] `git grep -n -E 'opm_starting_offsets|noqa: UP017'` -> пусто; `make check`, `make
      dags-check` -> зелёные
- [ ] `grep -c 'ADR-021, ADR-005' streaming/spark_jobs/maintenance.py` -> `0`; `grep -c
      'ADR-025' tests/unit/test_maintenance.py` -> не меньше `2`
- [ ] `make test-spark` (8 файлов `SPARK_TESTS`) -> 0 failed, 0 skipped
- [ ] `docker compose --env-file .env.example -f docker/compose.yaml --profile '*' config -q`
      -> rc 0; `config --hash '*'` до и после: другие только 7 сервисов «Входа» 4 и реплеер
- [ ] после пересоздания `docker inspect -f '{{.Image}}'` у bronze и opm равен Id нового
      `lakehouse/spark:dev` (`docker image inspect -f '{{.Id}}' lakehouse/spark:dev`)
- [ ] `for c in spark-bronze spark-orders-per-minute trino airflow-scheduler; do docker exec
      lakehouse-$c-1 sh -c 'env | cut -d= -f1 | grep -c -E "^(CATALOG_|META_)"'; done` -> `0`
      четыре раза (до: 5, 5, 3, 5)
- [ ] `docker exec lakehouse-spark-bronze-1 sh -c 'ls /opt/spark/jars | grep -c postgresql'` -> `0`
- [ ] `select '<t>', key, value from lake.<ns>."<t>$properties"` по bronze и 9 таблицам silver в
      файл scratchpad до и после -> `diff` пуст
- [ ] `make verify` -> `verify ok`; `make connector-status` -> `RUNNING` у коннектора и задачи
- [ ] через 5 минут `curl -s 127.0.0.1:9090/api/v1/alerts | grep -c '"state":"firing"'` -> `0`;
      `docker ps` -> пересозданные `(healthy)`

## Не входит

- База `iceberg_catalog` и её строки, лаб-топики (blast radius); `ADDED_COLUMNS`; R-20, R-28;
  разбор JSON в `connect/register.sh`; Java в README (P13); якоря compose и дедлайн Trino (P07).

## Риски и откат

- Регламент: `make start` при новом образе пересоздаёт `spark-bronze` и включает удаление
  `metadata.json` bronze; свойство уже `true` (13.11), свойства сверяются. Checkpoint не трогать.
- Один писатель silver: нет `make silver` при живом scheduler; перед `make verify` scheduler
  остановлен, контейнера `lakehouse-silver-merge` нет (`docker ps -a`).
- Сборка качает все jar заново: нужна сеть, при сбое тег старый. Образы не удалять (C). Сборку,
  `test-spark` и `dags-check` не запускать одновременно (`OPERATIONS.md:14-21`).
- «Код, потом пересоздание» безопасно: старый образ без `CATALOG_TYPE` берёт `rest`, лишние ключи
  старого env игнорируются (`extra="ignore"`). Поле `table` в `ENVELOPE` вне схемы состояния opm:
  после пересоздания opm `(healthy)`, в логе нет `StateSchemaNotCompatible`.
- Откат: `git revert` коммита кода, сборка и та же последовательность (C); данные не меняются.

## Расхождения с отчётом аудита

- DP-02: `ADDED_COLUMNS` не мёртвый шим, а описанная процедура добавления колонки в bronze
  (`OPERATIONS.md:178-184`, тест `test_bronze_cdc_ingest.py:221-224`). Удаление меняет процесс:
  не взято; если владелец хочет убрать, это отдельное решение с правкой OPERATIONS.
- DP-02: `noqa: UP017` есть и в `test_maintenance.py` (6 строк, Python 3.10 образа): без файлов
  `SPARK_TESTS` в `per-file-target-version` ruff даёт 6 ошибок (копия), `git grep` отчёта не пуст.
- DP-01: номера сдвинуты (compose `:206-207`, у AR-07 `:204-205`). `work/DP/edit.py.txt` не
  удаляет `CATALOG_WAREHOUSE` у Spark (условие про `S3_BUCKET`); набор 7 сервисов тот же.
  Контейнеров пересоздаётся 6: у one-shot `spark-silver` его нет, env берут `make silver` и DAG.
  Сборка образа по регламенту B, а не C.
- QA-07, часть про `test_check_dashboards.py`, ведёт P07 (README, раздел 4).
- AR-10 перенесён сюда из P12 при сведении 18.11: это правка кода `streaming/`, а образ Spark
  собирается в этом пакете. Отчёт AR не назвал два теста, которые ждут «ADR-021» в тексте
  отказа; оркестратор сверил строки тестов и текст ADR-025 (`DECISIONS.md:720-724`).

## Итог

Исполнено 20.11.2026 одной сессией на Opus (оркестратор). Коммиты: `b18aefe` (строка ADR-005 и
индекс, «ок» владельца на текст), `6020b64` (шаги 2-8 и правки по ревью, 35 файлов). Решения:
рутина сессии «да», В-03 «да», `iceberg_maintenance` не паузить, `airflow/dags` править вне окна
03:00-04:00 UTC (аргумент `/task`); шаг 9 по «ок» на точный текст. Код и тесты: `implementer`
(4 брифа: А слой JDBC и DP-05, В Java 17, QA-07, DP-04, DP-06, Б шаги 4, 5, 5а, круг ревью);
документы: `docs-writer`; ревью: `reviewer`, два круга; `git mv` ранбука, Markdown, живой стек:
оркестратор.

| Критерий | Проверка | Результат |
|---|---|---|
| Вход | grep «Входа» 1, цитаты 2-8, живые пробы | 106 строк в 15 файлах; цитаты на месте, compose сдвинут на +1; у Trino 4 ключа `^(CATALOG_\|META_)`, не 3 (см. отклонения) |
| grep «Входа» 1 без DECISIONS | `git grep -n -E "$PAT" -- ':!docs/planning' ':!docs/HANDOFF.md' ':!docs/NEXT_SESSION.md' ':!DECISIONS.md'` | 4 строки `tests/unit/test_spark_settings.py:9-16`: тесты на отказ шага 2 (см. отклонения) |
| Тесты пакета | `uv run pytest tests/unit/test_{compose,spark_settings,dags,airflow_env,contracts}.py tests/unit/test_{maintenance,spark_jvm}.py -q` | `346 passed, 10 skipped` (ревью, круг 2) |
| Тесты на отказ | красные до правки | test_compose `4 failed`, test_spark_settings `2 failed`, test_maintenance `6 failed`, test_silver_upsert `2 failed` (лог merge и пустой снапшот; оркестратор повторил на копии с `silver_upsert.py` из HEAD: красные и по `-k`, и в полном файле), test_spark_jvm ошибка сбора; мутации: без `dropTempView` `['opm_batch_0', 'opm_batch_1']`, без `"unavailable"` и без `shop.reviews` тесты контрактов красные, `check (price >= 0)` -> `assert 3 == 4`, `type X = int` в conftest -> ruff |
| grep мёртвого кода | `git grep -n -E 'opm_starting_offsets\|noqa: UP017' -- ':!docs/planning'` | пусто (без исключения совпадает только текст пакета и отчёта DP) |
| ADR в отказе | `grep -c 'ADR-021, ADR-005' streaming/spark_jobs/maintenance.py`; `grep -c 'ADR-025' tests/unit/test_maintenance.py` | `0`; `2` |
| `make check`, `make dags-check` | | `2117 passed, 149 skipped`; `5 dags import, timeouts, retry budget, force removal and the maintenance switch checked` |
| `make test-spark` | до коммита и на новом образе | `249 passed`, 0 skipped (оба раза) |
| compose | `config -q`; `config --hash '*'` до и после из корня репо | rc 0; другие ровно `airflow-api-server airflow-dag-processor airflow-scheduler oltp-replayer spark-bronze spark-orders-per-minute spark-silver trino` |
| Ревью | `reviewer` | круг 1 «принять с замечаниями (2 средних, 5 низких)», круг 2 «принять с замечаниями (2 низких)» |
| Verify | цикл §5 перед коммитом и в шаге 9 | `verify ok` оба раза, 7 таблиц `rows ok keys ok values ok` |
| CI | `gh run list` | `b18aefe` и `6020b64` `success` |
| Образ | `docker inspect -f '{{.Image}}'` bronze и opm против `docker image inspect -f '{{.Id}}' lakehouse/spark:dev` | оба `sha256:28604e90...`, равно Id тега (до `94bda0b9`, `9b41b55b`) |
| env | `env \| cut -d= -f1 \| grep -c -E "^(CATALOG_(TYPE\|JDBC_\|DB\|WAREHOUSE)\|META_)"` у bronze, opm, trino, scheduler | `0 0 0 0` (до `5 5 3 5`); по шаблону пакета `0 0 1 0`: `CATALOG_MANAGEMENT` из образа Trino |
| jar | `ls /opt/spark/jars \| grep -c postgresql` в bronze | `0` (до `1`) |
| Свойства | `$properties` bronze и 9 таблиц silver до и после в scratchpad | 83 строки, `diff` пуст (с `current-snapshot-id` тоже) |
| Стек после | `make connector-status`; `docker ps`; лог opm | `RUNNING` у коннектора и задачи; все `(healthy)`; `StateSchemaNotCompatible` 0; Trino `-J-Xmx2g`; `silver_upsert` 19:02 и `dq_checks` 19:01 `success` на новом env |
| Алерты | `curl -s 127.0.0.1:9090/api/v1/alerts` | 19:02 шесть `ContainerRestarting` от пересоздания; 19:18:15 UTC `firing` 0, 20 контейнеров `(healthy)` |

Отклонения от пакета:
- grep «Входа» 1 не пуст: шаг 2 требует тест `"catalog_type" not in Settings.model_fields` и тест с
  `CATALOG_TYPE=jdbc` в env, они совпадают с шаблоном. Ревью: приемлемо.
- Шаблон env «Готово, когда» ловит `CATALOG_MANAGEMENT` из образа Trino (было 4, а не 3): после
  правки `1`. Проверено суженным шаблоном (строка таблицы), `0` четыре раза.
- «Через 5 минут 0 firing» недостижимо: `ContainerRestarting` смотрит `changes(...[15m])`, и каждое
  пересоздание и стоп scheduler в цикле verify зажигают его на 15 минут. Проверка через 16 минут.
- `make start` пересобрал образ (`--build`) уже собранным кэшем: `Created` тот же
  (18:53:48 UTC), Id сменился (`281e2183` -> `28604e90`, хранилище containerd, ловушка из
  «Открыто» HANDOFF); `make test-spark` шёл на `281e2183` той же сборки.
- `silver_upsert`: MERGE при `valid == 0` пропускается, потому что тест показал пустой снапшот на
  батче из одних битых событий (условие шага 5).
- Тест `tests/unit/test_dags.py` (`test_bronze_orphans_always_go_to_the_metadata_location`) ждал
  `ADR-021` в том же отказе, что шаг 5а: ожидание сменено на `ADR-025` (не назван в пакете).
- Снятие пауз в порядке `dbt_build dq_checks silver_upsert` (§5), а не как в тексте шага 9.
- Сверх пакета по ревью: `tests/unit/conftest.py` в `per-file-target-version` (образ грузит его на
  3.10); `java_binary` берёт `$JAVA_HOME/bin/java`, как `spark-class`; тест «каждый CHECK
  миграций разобран».

Риски и что осталось (ревью, не исправлено):
- Подсчёт CHECK ищет `check (` с пробелом: `check(x >= 0)` без пробела тест не видит (низкое,
  после второго круга; правка `r"check\s*\("`).
- `DECISIONS.md:196` длиной 114 символов: исторический абзац ADR-005, заменён только путь ранбука.
- `docker/data` (пустой каталог root от снятого mount) владелец удалил 20.11 (`ls -ld` -> нет); строки
  `CATALOG_TYPE`, `CATALOG_DB` в `.env` ничем не читаются, удалить по желанию.
