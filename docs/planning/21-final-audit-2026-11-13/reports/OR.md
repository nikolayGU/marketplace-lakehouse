# OR. Оркестрация и DQ

Дерево: HEAD `a8c1d49` плюс незакоммиченные правки владельца (не тронуты). Только чтение: файлы,
`airflow dags list`, `list-runs`, `list-import-errors`, `tasks states-for-dag-run`, `pools list`,
select в Trino, GET к Prometheus, точечный pytest. Копии и пробы: `<scratchpad>/audit/OR-work/`.

## Оценки

- Data engineer: 4 из 5. Один писатель silver держится в трёх местах, задачи идемпотентны, сверка
  по значению всех колонок; минус окно ложного красного в `dq_checks` (OR-01, OR-03) и неверный
  диагноз пропавшей строки с составным ключом (OR-02).
- SRE: 4 из 5. Состояния «нет вердикта» и счётчики прогонов вместо мигающего красного, лог красного
  прогона называет таблицу и ключи; минус `merge_pending` может послать дежурного ждать merge,
  который строку не принесёт (OR-02), и красный после сна хоста без причины в логах задач
  (описано в `OPERATIONS.md:718-723`).

## Сильные стороны

- Один писатель silver: фиксированное имя контейнера merge, второй старт получает 409
  (`airflow/dags/silver_upsert.py:56`); `make silver` отказывает при живом scheduler или контейнере
  merge (`Makefile:95-113`); полный `verify` отказывает при scheduler (`scripts/verify.sh:34-44`);
  `optimize` в том же пуле `lake_writers` (`airflow/dags/iceberg_maintenance.py:54`). Тесты
  `test_dags.py:1173-1180`, `make dags-check` в CI (`.github/workflows/ci.yml:143`).
- Сверка по значению: отпечаток строки одинаково строится в Postgres и Trino
  (`airflow/dags/lakehouse/reconcile.py:220-244`), пары тянутся только при расхождении
  (`reconcile.py:485-504`); сторона Postgres исполняется на настоящем Postgres в CI с
  `FAIL_ON_SKIP` (`tests/unit/test_reconcile_postgres.py`, `ci.yml:62-67`). Живьём сейчас: 13 серий
  `lakehouse_dq_reconcile_values_differing`, `reconcile_gold_compared` 1, `gmv_compared` 1 (GET
  `/api/v1/query`).
- «Нет вердикта» как состояние: покой (`lakehouse/checks.py:19-31`), стоящий CDC
  (`checks.py:61-78`), счётчики прогонов без сравнения и с устаревшим gold в Variable
  (`dq_checks.py:55-81`), по ним алерты `SilverGoldNotCompared` и `GoldStaleAtRest`
  (`observability/prometheus/alerts.yml:119-133`).
- Действия класса C выключены по умолчанию: expire и compaction только при булевом `true`
  (`lakehouse/maintenance_commands.py:23-26`), orphans dry run и DAG на паузе
  (`iceberg_orphans.py:36`; `airflow dags list`: `iceberg_orphans | True`); тесты
  `test_dags.py:802-920`.
- Бюджет таймаутов: все попытки задачи помещаются в `dagrun_timeout`, проверка AST на хосте
  (`test_dags.py:1062-1097`) и DagBag в образе в CI (`Makefile:174-196`).
- Поведенческий стенд для `dq_checks`: DAG грузится с заглушками Airflow, клиентов и Variable
  (`test_dags.py:240-395`), около 60 сценарных тестов. Прогон области:
  `uv run --no-sync pytest tests/unit/test_dags.py tests/unit/test_reconcile*.py tests/unit/test_dq_metrics.py tests/unit/test_maintenance.py -q`:
  `334 passed, 65 skipped in 2.27s`.
- `verify` отказывает быстро и с верной причиной: три пробы Trino, каталога и MinIO
  (`scripts/chaos/lib.sh:57-105`), тесты на заглушках (`tests/unit/test_verify_script.py`).

## Старый бэклог

| ID | статус сейчас (file:line или коммит) | делать / не делать | причина |
|---|---|---|---|
| R-05 | открыт: гейт по водяному знаку `dq_checks.py:278-280`, `reconcile.py:167,171-176` | делать (OR-01) | окно ложного красного посреди `dbt_build` подтверждено разбором зависимостей dbt |
| R-06 | открыт: `reconcile.py:414-424` (`first = TABLES[table][0][0]`), `dq_checks.py:174` (`k.split(":")[0]`) | делать (OR-02) | воспроизведено живым select |
| R-09 | открыт `docker/airflow/airflow.env:19` | не делать (часть OR) | scheduler и dag-processor стартуют после healthy api-server (`compose.yaml:604-606`, `634-636`), миграция не параллельна первой; часть `make help` у IN |
| R-25 | открыт `dq_checks.py:418-438`, `dbt_build.py:28` | не делать | задача идёт 5 с (18:30:03.67-18:30:08.89 13.11), seed одна таблица; показывает `dbt source freshness` |
| R-26 | открыт `scripts/chaos/lib.sh:254-274` (4 exec на таблицу) | не делать | около 15 с на verify, проект замораживается; склейка ответов добавляет риск ложного зелёного в сверку |
| R-42 | открыт | делать частично (OR-04) | `dq_checks.py`, `clients.py`, `silver_upsert.py`: да; построители SQL `reconcile.py`: нет |
| PF-20 / F-12 | открыт: `dbt_build.py:27` пул `gold_writers`, merge `silver_upsert.py:66` пул `lake_writers` | не делать в коде, строка в OPERATIONS (OR-05) | нужен `dbt_build` дольше ~4.5 мин при замерах 20-40 с; следующий build исправляет |
| PF-21 / F-13 | открыт: пары source-silver не перечитывают позицию CDC (`dq_checks.py:252-275`), `silver_matches_postgres` не читает её вовсе (`:138-163`) | делать (OR-03) | ложный красный при первой записи пачки |
| PF-22 / F-14 | открыт: `lakehouse/sql.py:98-103`, вызовы `iceberg_maintenance.py:59-63`, `iceberg_orphans.py:40-46` | не делать | `__dbt_tmp` у `mart_daily_sales` таблица (макрос dbt-trino: `delete+insert` с `unique_key` даёт table), но список строится только в ручном прогоне с флагом; итог красная mapped-задача, данные не трогаются |
| PF-10 | открыт: `silver_upsert.py:54-69`; провайдер 4.5.9 тянет образ при отсутствии (`docker.py:497-501`); `lakehouse` на Docker Hub чужой пользователь, репозитория `lakehouse/spark` нет (HTTP 404) | не делать | описано в `OPERATIONS.md:1224-1225`, нужен удалённый локальный образ и захват имени |
| PF-32 | открыт: `lib.sh:219-227` без теста семантики | не делать (решает QA) | SQL верен, живьём 0; риск только при правке, проект замораживается |
| F-11 | открыт `reconcile.py:171-176` (без `reviews`) | закрывается OR-01 | `SILVER_UPDATED` уходит |
| F-01, F-03 | закрыты: `GoldStaleAtRest` (`alerts.yml:130-133`), счёт `dq_checks.py:357-376` | закрыто | |
| Б15 | закрыт для GMV (`dq_checks.py:191-193,322-327,384-392`; тесты `test_dags.py:1193-1312`); часть про пары source-silver = PF-21 | делать (OR-03) | |
| Б20 | закрыт: `sql.postgres_rows` переименован (`sql.py:38`), литерал 7 таблиц проверяет `test_verify_script.py:346` | закрыто | остаток «по желанию» в OR-04 |
| 14 разд. 7, п. 17 (`bronze_caught_up` против Kafka) | открыт `lib.sh:204-208` | не делать | отставание Debezium даёт красный `reconcile`, не зелёный |
| 14 разд. 7, ветка `rows[0][0] is None` | открыт `dq_checks.py:122` (`coalesce` в `sql.py:18`) | не делать | защитная ветка, вреда нет |
| 14 разд. 7, тест expire | закрыт `test_maintenance.py:455-457` (`deleted_manifest_lists_count`) | закрыто | |
| R-08 (часть OR) | открыт `test_dags.py:827-831` (подстрока исходника) | к QA | поведенческая замена: загрузить `iceberg_orphans.py` заглушками как `DqChecks` и вызвать `gold_orphan_commands({"dry_run": False})` |
| R-45 (AST-двойник dags-check) | `test_dags.py:1000-1180` | не делать | быстрая проверка на хосте без Docker, DagBag только в CI |
| R-40 (часть OR) | `airflow.env:32-34`, `settings.py:54-56,65` | решает DP/IN | при удалении JDBC-слоя убрать и эти строки с `test_dags.py:63-90` |

## Находки «делать»

### OR-01 [средняя] Сверка silver-gold открывается посреди `dbt_build`: ложный красный
Где: `airflow/dags/dq_checks.py:277-280`; `airflow/dags/lakehouse/reconcile.py:167,171-176,407-411`
Факт: гейт `gold_ready = gold_at_rest(GOLD_UPDATED, SILVER_UPDATED)` смотрит только водяной знак
`fct_orders`. `fct_order_items` ссылается на `fct_orders` (`dbt/models/marts/fct_order_items.sql`,
`ref('fct_orders')`), значит строится после него и после его тестов. Покой при идущем `dbt_build`
возможен и признан в коде: «one run that sees it stale at rest can still be the build on its way»
(`alerts.yml:127-128`). При `PARALLELISM=2` (`airflow.env:6`) задачи `dq_checks` в минуту :00/:15/:30/:45
стоят в очереди за merge и попадают после `remember_snapshot` (пример 13.11 18:30: `reconcile_values`
начался в 18:30:08.9, через 8 с после старта прогона).
Чем плохо: в окне между коммитом `fct_orders` и коммитом `fct_order_items`, `dim_*` гейт открыт, а
эти таблицы старые: `ValueError: values differ at rest ... silver_gold fct_order_items ... missing on
the right`, `AirflowDagFailed`, ложный диагноз. Второе: удалённый заказ держит водяные знаки врозь
(комментарий `reconcile.py:178-180`), gold не сравнивается до следующей живой правки
(`OPERATIONS.md:850`); `SILVER_UPDATED` без `reviews` (F-11).
Правка: гейт пар silver-gold по снапшотам: `gold_ready = gold_stale(SILVER_DATA_CHANGED,
GOLD_REBUILT) is False`; запросы снапшотов вынести перед парами (сейчас `dq_checks.py:357-376`, после
них); ошибка запроса снапшотов закрывает гейт, задача красная с этой ошибкой после отправки
вердиктов source-silver (как сейчас). `GOLD_UPDATED` и `MART_UPDATED` оставить для гейта GMV и
`mart_behind`; `SILVER_UPDATED` и его ветку в заглушке (`test_dags.py:369-370`) убрать. Тесты на
отказ первыми: (1) `dq.at_rest(); dq.silver_changed=3000.0; dq.gold_rebuilt=2000.0;
dq.gold_differs=True` при равных водяных знаках: красного нет, `reconcile_gold_compared` 0 (сейчас
`ValueError`); (2) `dq.gold_updated="2026-09-30 00:00:00"` при `silver_changed=1000 < gold_rebuilt=2000`:
сравнение есть, `reconcile_gold_compared` 1 (сейчас 0). Переписать через снапшоты
`test_dags.py:553,647,1432`; `:1379,1460` проверяют, что сбой запроса снапшотов красный и не прячет
разницу source-silver. Документы: `OPERATIONS.md:669-670`, `:850` (убрать «deleted order»),
комментарий `alerts.yml:110-112`.
Проверка: `uv run pytest tests/unit/test_dags.py -q` (новые тесты красные до правки); после
применения ближайший прогон `airflow dags list-runs dq_checks` success; GET
`query=lakehouse_dq_reconcile_gold_compared` 1 в покое.
Размер: M; класс B, правка живого DAG при паузе `dq_checks`; смена условия проверки требует «ок»
владельца (ревьюер подтверждает, что это не ослабление).
Старый ID: R-05, F-11

### OR-02 [средняя] Диагноз пропавшей строки с составным ключом смотрит только первую колонку
Где: `reconcile.py:414-424` (`first = TABLES[table][0][0]`, `k.split(':')[0]`), `reconcile.py:427-444`,
`dq_checks.py:174`
Факт: для `order_items`, `payments`, `reviews` поиск в bronze и quarantine идёт по `order_id`
(`review_id`). Живая проба: SQL из `bronze_lookup_sql('order_items', ['da2b5ed33ae5068005e9d2c43e7a3de1:9'])`
(позиции 9 в silver нет, select count 0) вернул `da2b5ed33ae5068005e9d2c43e7a3de1`
(`<scratchpad>/audit/OR-work/r06_old.sql`).
Чем плохо: строка, которой нет нигде, получает `merge_pending` («bronze has it»), если у заказа есть
другая позиция; дежурный ждёт merge, который строку не принесёт, `OPERATIONS.md:673` обещает
верную причину.
Правка: искать по всему ключу через колонку `key` (JSON ключа Debezium, `bronze_cdc_ingest.py:52`):
`concat_ws(':', json_extract_scalar(x.key, '$.c1'), ...) = t.id`, массив из полных ключей; в
quarantine `coalesce(x.key, x.payload)` (у 4 живых строк quarantine `key` null и payload не JSON,
`json_extract_scalar` даёт NULL, запрос проходит). `_explain` сравнивает полный ключ: `k in ids`.
Тест на отказ первым в `test_reconcile.py`: для `order_items` и ключа `X:2` SQL содержит
`'$.order_item_id'` и литерал `'X:2'`; для `orders` один `'$.order_id'`; отказ на небезопасном ключе
сохраняется (`test_reconcile.py:165-169`).
Проверка: `uv run pytest tests/unit/test_reconcile.py tests/unit/test_dags.py -q`; живой select
нового SQL (`<scratchpad>/audit/OR-work/r06_new.sql`, ключи `...:9` и `...:1`) возвращает только `...:1`, 2.0 с, как
старый.
Размер: S; класс B (пауза `dq_checks`).
Старый ID: R-06

### OR-03 [средняя] Пары source-silver не перечитывают позицию CDC: ложный красный при старте пачки
Где: `dq_checks.py:252-275` (позиция читается до пар, после них только для GMV, `:191`);
`dq_checks.py:138-163` (`silver_matches_postgres` позицию не читает)
Факт: `at_rest` смотрит покой bronze 5 мин (`checks.py:27-31`), а запись в источник после
`cdc_progress` ещё не в bronze. Окно 13.11 18:30: `cdc_progress` 00.66-01.26, чтение Postgres в
`reconcile_values` 08.9-17.6, в `silver_matches_postgres` 08.4-09.6 (`tasks states-for-dag-run`).
Чем плохо: первая запись пачки реплея в это окно даёт «silver differs from Postgres at rest» и
`AirflowDagFailed` при здоровом конвейере. Порядок: около 1-2% пачек, начатых в случайный момент.
Правка: в `reconcile_values` после цикла пар перечитать `_cdc_position()`; при сдвиге отбросить
вердикты и gauge source-silver, напечатать `in flight: the source or the slot moved during the run`,
`reconcile_in_flight` 1 (GMV уже пропускается сам). В `silver_matches_postgres` читать позицию до
счётов Postgres и после счётов silver; при сдвиге исход `in_flight`. Счётчик записей PG17 сбрасывается
при простое бэкенда, для первой записи после тишины сразу; это сужает окно, а не закрывает его
(записать в docstring). Тесты на отказ первыми на стенде `DqChecks`: флаг расхождения пары
`orders` плюс `cdc_moves_after = reconcile.fingerprint_sql_postgres("orders")`: красного нет
(сейчас `ValueError`); `postgres_counts={"orders": 11}` плюс `cdc_moves_after = sql.source_rows("orders")`:
красного нет; без сдвига оба красные, как сейчас.
Проверка: `uv run pytest tests/unit/test_dags.py -q`; ближайший прогон `dq_checks` success.
Размер: S; класс B (пауза `dq_checks`); вместе с OR-01 одним пакетом (один файл).
Старый ID: PF-21, остаток Б15

### OR-04 [низкая] R-42: упрощение без смены поведения
Где и что:
- `dq_checks.py:55-81`: `count_gold_run` и `count_stale_run` в одну `_count_runs(variable, grows)`
  (`count_gold_run(c)` = `_count_runs(GOLD_NOT_COMPARED_RUNS, not c)`, `count_stale_run(s)` =
  `_count_runs(GOLD_STALE_RUNS, bool(s))`), около -12 строк.
- `dq_checks.py:140-146` и `:222-225`: одно чтение покоя `_resting()`, около -4.
- `dq_checks.py:307-321`: вердикт `dim_customers` функцией `reconcile.count_verdict(pair, table,
  left, right)`, около -8.
- `dq_checks.py:1-18`: docstring без ID карточек (часть R-66, см. OR-05).
- `lakehouse/clients.py:27-40`: `postgres_value` через `postgres_rows` (одна строка подключения),
  около -10.
- `silver_upsert.py:54-69`: `DockerOperator(task_id="merge", container_name=..., command=...,
  outlets=..., **spark_job_kwargs(LAKE_WRITERS_POOL))`; `spark_task.py:16-27` даёт ровно те же 9
  аргументов (image, network, env, private env, `2g`, `mount_tmp_dir`, `force`, pool, xcom), около -8.
Не делать: построители SQL `reconcile.py` (17 функций, `order by` в парах): выигрыш около 10 строк,
сторона Trino нигде не исполняется в тестах, а заглушка `DqChecks` сверяет запросы по тексту тех
же построителей, поэтому ошибка «gold читает silver» прошла бы набор (ложный зелёный); `order by`
закреплён `test_reconcile_postgres.py:219`. Ключи в `settings.SILVER_KEYS` и `reconcile.TABLES`:
оба сверены с контрактами (`test_dags.py:93-99`, `test_reconcile.py:26`), `reconcile.py` обязан
остаться без зависимостей. Профиль dbt `ci` равен `dev` (`dbt/profiles.yml`), решает GB.
Проверка равенства: до правки сохранить вывод всех построителей `reconcile` и `sql` в файл
scratchpad, после правки сравнить (пусто); тесты области без правок тестов:
`uv run pytest tests/unit/test_dags.py tests/unit/test_reconcile*.py tests/unit/test_dq_metrics.py tests/unit/test_maintenance.py -q`
дают те же `334 passed, 65 skipped`; `make dags-check` в CI зелёный (проверяет `auto_remove` и
`container_name` merge).
Размер: S-M; класс B, пауза `silver_upsert` (дождаться конца идущего merge) и `dq_checks`.
Старый ID: R-42, остаток Б20

### OR-05 [низкая] Документы области расходятся с кодом
Где и правка:
- `airflow/README.md:10` и `OPERATIONS.md:627`: строка `dq_checks` называет только дубли ключей и
  счёт строк; добавить сверку по значению source-silver и silver-gold, GMV против источника, красный
  при сбое запроса снапшотов и freshness.
- `OPERATIONS.md:598`: «pool lake_writers, 1 slot» -> два пула `lake_writers` и `gold_writers`
  (`Makefile:127-131`).
- `scripts/verify.sh:2`: «Bronze holds every Kafka record exactly once» -> «no Kafka offset twice and
  no gap between the lowest and the highest one, up to Kafka's end offsets» (`lib.sh:196-227` не
  смотрит начало партиции).
- PF-20 строкой в разделе Airflow OPERATIONS: `dbt_build` и merge не исключают друг друга;
  build дольше около 4 мин может увидеть merge посреди и упасть на relationships; следующий build
  исправляет.
- ID карточек в коде области (R-66, чтобы пакет DC не правил те же файлы): `dq_checks.py:5,6,10,17,214`;
  `reconcile.py:1-2`; `settings.py:25,43,86`; `metrics.py:1`; `maintenance_commands.py:25`;
  `silver_upsert.py:1`; `dbt_build.py:1,4`; `iceberg_maintenance.py:1,12`; `iceberg_orphans.py:1`;
  `docker/airflow/airflow.env:4,11,20` (оставить правило и номер ADR).
Проверка: `grep -n -E 'W[0-9]-[TD][0-9]|MODEL-|\bD1[0-9]\b|chaos [0-9]' airflow docker/airflow -r`
пуст; `grep -n 'pool lake_writers, 1 slot' OPERATIONS.md` пуст; ссылки Markdown целы (скрипт DC).
Размер: S; класс A (документы), B для docstring в DAG (пауза не нужна: меняется текст, но файл
перечитывается, поэтому вместе с OR-01..04).
Старый ID: PF-20 (текст), R-66 (часть)

## Находки «не делать»

| ID | что | почему не делать |
|---|---|---|
| OR-N1 | DAG `probe_echo` в базе Airflow без файла (`dags details`: `is_stale True`, разбор 2026-10-18) | скрыт как stale, удаление пишет в Airflow (C), читатель репозитория его не видит |
| OR-N2 | Пулы создаёт отдельный `make airflow-init`; без них задачи с пулом молча ждут до `dagrun_timeout` | шаг описан (`OPERATIONS.md:598`), стенд живой; комментарий правит OR-05 |
| OR-N3 | gauge `lakehouse_dq_dbt_source_freshness_exit_code` в покое всегда 1 (живьём 1), его не читает ни алерт, ни панель | вместе с R-25: дешёвая демонстрация `dbt source freshness`, красный только при runtime error |
| OR-N4 | Сверка gold не трогает производные деньги `fct_orders` (`items_value`, `payment_value`) | gold-тест `dbt/tests/assert_payments_match_order_value.sql`, GMV по дням против источника; новая пара это новый функционал |
| OR-N5 | Красный после сна хоста: все задачи `skipped`, причина только в логе scheduler (прогоны 11-10 18:45, 11-07 00:15, 11-05 05:15) | описано `OPERATIONS.md:718-723`; ранбук и annotations алертов у OB (R-67) |

## Разрыв с продом

- LocalExecutor, `PARALLELISM=2`, один scheduler в лимите 900M, задачи делят его память; нет HA.
- Взаимоисключение через пулы одного Airflow и глобальное имя контейнера Docker, а не через
  распределённую блокировку или оптимистичные коммиты с ретраем.
- Сверка только в покое: при непрерывной нагрузке source-silver не сравнивается, сигнал только через
  6 ч (`SilverGoldNotCompared`); в проде сравнение по зафиксированному снапшоту и LSN или выборочное.
- Своя DQ-библиотека вместо фреймворка с реестром проверок и историей результатов.
- Алерты только `warn` в Prometheus: нет Alertmanager, маршрутизации, дежурства и annotations.
- `catchup=False` везде, пропущенное событие Asset у паузы `dbt_build` возвращается рукой.
- Секреты в env-файле Airflow, UI без входа, у scheduler `docker.sock`.
- Expire снапшотов silver и gold только по ручному флагу: метаданные растут при обычной работе.

## Не проверено

- R-05 и PF-21 живьём не воспроизводились (нужна запись в источник или прогон в окне `dbt_build`);
  вывод из кода, времён задач 13.11 18:30 и комментария `alerts.yml:127-128`. Проверит: тесты
  OR-01 и OR-03 на стенде `DqChecks`.
- Что вторая `airflow db migrate` берёт глобальную блокировку (R-09):
  `docker compose ... exec -T airflow-scheduler python -c "import inspect, airflow.utils.db as d; print('create_global_lock' in inspect.getsource(d.upgradedb))"`.
- Память scheduler при одновременных `dbt build` и `dbt source freshness`: пик 14 дней 675 MiB из
  900 (`max_over_time(docker_container_memory_usage_bytes{name=~".*airflow-scheduler.*"}[14d])`), swap
  не виден; совпадения двух процессов не искал.
- Для DP: в bronze нет первой половины offsets каждой партиции (sellers p0: bronze 1053..2105,
  конец Kafka 2106; Kafka earliest равен latest, записей в топиках нет); `bronze_offsets_ok` этого
  не видит по построению. Причина не разбиралась.
- `make dags-check` не запускался (бриф); `tests/unit/test_verify_script.py` не запускался.
- `spark-orders-per-minute` пересоздан примерно за 7 мин до начала аудита (`docker ps`: Up 7 minutes,
  остальные 10 ч); не моя область, причину не смотрел.
