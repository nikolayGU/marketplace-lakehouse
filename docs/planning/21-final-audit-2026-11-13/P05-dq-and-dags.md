# P05. DQ: гейт silver-gold по снапшотам, позиция CDC, диагноз по ключу, тесты проводки DAG
Статус: не начат. Оркестратор Opus по `13-harness.md`: `/task docs/planning/21-final-audit-2026-11-13/P05-dq-and-dags.md`.

## Цель

`dq_checks` не краснеет ложно посреди `dbt_build` и при записи в источник во время проверки,
диагноз пропавшей строки смотрит весь ключ, проводку `silver_upsert` и фильтр живых строк
сверки ловят тесты. Два коммита: дефекты и тесты, затем упрощение без смены поведения (OR-04).

## Находки пакета

| ID | серьёзность | суть | где подробности |
|---|---|---|---|
| OR-01 | средняя | гейт пар silver-gold по водяному знаку одной `fct_orders`: ложный красный посреди `dbt_build` | `reports/OR.md`, OR-01 |
| OR-02 | средняя | поиск в bronze и quarantine по первой колонке составного ключа: ложный `merge_pending` | `reports/OR.md`, OR-02 |
| OR-03 | средняя | пары source-silver и счёт строк не перечитывают позицию CDC: ложный красный | `reports/OR.md`, OR-03 |
| OR-04 | низкая | упрощение `dq_checks.py`, `clients.py`, `silver_upsert.py` без смены поведения | `reports/OR.md`, OR-04 |
| QA-02 | средняя | `max_active_runs`, пул, `outlets`, порядок задач `silver_upsert` без теста (W1, W2, W4, W5 зелёные) | `reports/QA.md`, QA-02 |
| QA-04 | низкая | silver-сторона сверки по значениям без `_is_deleted` проходит набор (R1) | `reports/QA.md`, QA-04 |
| QA-05, часть | низкая | подстрочные `test_dags.py:827-831` (T3 ложный красный), `test_reconcile.py:40-45` (T1 зелёная) | `reports/QA.md`, R-08 |

## Решения владельца и действия класса C

- **В-04** (рекомендация «да»), два условия проверки. При «нет» шаги 2 и 3 не делать; шаг 6
  (коммит 1) исполнять без их тестов и мутаций и без строк «Готово» об OR-01 и OR-03
  (`SILVER_UPDATED`, `gold_compared`): OR-02, QA-02, QA-04, QA-05 от решения не зависят. В
  «Итог» тогда строка для P11: окна ложного красного остаются, описать их в OPERATIONS. Условия:
  (1) OR-01, гейт пар silver-gold с водяного знака на снапшоты; (2) OR-03, расхождение
  source-silver при сдвиге позиции CDC за время проверки даёт «in flight» вместо красного, как уже
  у GMV (`dq_checks.py:191-193`): настоящее расхождение краснеет на следующем тихом прогоне,
  стоящий CDC ловит `CdcStalledSourceWrites`.
- Класса C нет. Пауза и снятие паузы `dq_checks`, `silver_upsert`: особый случай класса B
  (`13-harness.md`, раздел 2). Полный `make verify` по разделу 5 там же; не выполнены его три
  условия: это C и отдельное «ок».
- Сверх В-n, в первом вопросе сессии (коммит 2): снятие паузы `iceberg_maintenance` это C. Либо
  DAG на паузе на время правки `airflow/dags/lakehouse/clients.py` и снятие по «ок», либо
  правка и коммит вне окна 03:00-04:00 UTC при пустом `list-runs iceberg_maintenance --state
  running`. Без ответа: второй вариант, как в «Границах».

## Зависимости

- P05 ни от чего не зависит. P09 идёт после P05: комментарий гейта в `alerts.yml`.
- P08 идёт после P05: общий файл `tests/unit/test_superset_bundle.py`, шаг 5 (QA-05) переносит
  оттуда `output_columns` в `tests/unit/dbt_sql.py`.
- P10 (ID карточек в `airflow/`) после: новые и переписанные строки P05 пишутся без ID.

## Вход

Сверить первым шагом (строки `a8c1d49`; после других пакетов искать по цитате):
- `airflow/dags/dq_checks.py:278-280`: `gold_updated = ...GOLD_UPDATED`,
  `silver_updated = ...SILVER_UPDATED`, `gold_ready = reconcile.gold_at_rest(...)`.
- `dbt/models/marts/fct_order_items.sql:20`: `{{ ref('fct_orders') }}`, строится после него.
- `airflow/dags/lakehouse/reconcile.py:186-217`: `GOLD_REBUILT_TABLES`, `SILVER_DATA_CHANGED`,
  `GOLD_REBUILT`, `gold_stale`; `dq_checks.py:357-376`: снапшоты только для `gold_stale_runs`.
- `reconcile.py:419-420`: `first = TABLES[table][0][0]`, `k.split(':')[0]`; `dq_checks.py:174`:
  `{k for k in shown if k.split(":")[0] in ids}`.
- `dq_checks.py:252` `cdc_at_start` до пар; после пар позиция читается только в GMV (`:191`);
  `silver_matches_postgres` (`:138-163`) её не читает.
- `reconcile.py:299`: `where = " where not _is_deleted" if live_only else ""`.
- `airflow/dags/silver_upsert.py:35` `max_active_runs=1`, `:66` `pool=LAKE_WRITERS_POOL`,
  `:67` `outlets=[Asset(SILVER_ASSET_NAME)]`,
  `:78` `snapshot >> merge >> remember_snapshot(snapshot)`; `Makefile:128` `lake_writers 1`.
- Trino: `select source_table, max(key) from lake.bronze.cdc_events group by 1` -> JSON ключа,
  `{"order_id":"...","order_item_id":1}`, у `reviews` `{"review_id":"...","order_id":"..."}`.
- Импорты: `lakehouse/reconcile.py` берёт только `dq_checks.py`; `lakehouse/clients.py` берут
  `dq_checks`, `silver_upsert`, `iceberg_maintenance`, `iceberg_orphans`.
- База (13.11): `uv run --no-sync pytest` по `tests/unit/` `test_dags.py test_reconcile.py
  test_reconcile_sql.py test_reconcile_postgres.py test_dq_metrics.py test_maintenance.py
  test_superset_bundle.py test_check_dashboards.py -q` -> `393 passed, 65 skipped`.

## Границы

- Менять: `airflow/dags/dq_checks.py`, `airflow/dags/lakehouse/reconcile.py`; в OR-04 ещё
  `lakehouse/clients.py`, `airflow/dags/silver_upsert.py`; тесты `test_dags.py`,
  `test_reconcile.py`, `dbt_sql.py`, `test_superset_bundle.py` (только перенос `output_columns`).
- Нельзя: построители SQL `reconcile.py` (`_trino`, `_postgres`, `fingerprint_*`, `pairs_*`,
  `gold_*_sql_trino`): Trino-сторона в тестах не исполняется, заглушка сверяет запросы текстом тех
  же построителей, рефакторинг дал бы ложный зелёный (`reports/OR.md`, OR-04). Не трогать
  `SILVER_KEYS`, `TABLES`, `gold_at_rest` (нужен GMV), `iceberg_*.py`, OPERATIONS, `alerts.yml`.
- Живой стек: `airflow/dags/` живой, порядок `13-harness.md`, раздел 2, особый случай (пауза,
  правка, `make test`, `make dags-check`, ревью, цикл verify, коммит, снятие паузы последним).
  Коммит 1: пауза `dq_checks`. Коммит 2: пауза `silver_upsert` и `dq_checks`;
  `iceberg_maintenance` не паузить (снятие паузы `iceberg_*` это C): `clients.py` править, когда
  `list-runs iceberg_maintenance --state running` пуст и до 03:30 UTC далеко (DAG зовёт только
  неизменный `trino_rows`). Пауза: `$COMPOSE exec -T airflow-scheduler airflow dags pause <dag>`,
  затем `list-runs <dag> --state running` пуст. Docker не запущен: `airflow/dags/` не править.

## Шаги

Код пишет `implementer` по брифу (`13-harness.md`, раздел 3), тест на отказ первым.
1. **Пауза** `dq_checks` (Границы), вывод `list-runs` в «Итог».
2. **OR-01, гейт по снапшотам.** Тесты на отказ на стенде `DqChecks` (`test_dags.py:239-395`):
   - `dq.at_rest(); dq.silver_changed, dq.gold_rebuilt = 3000.0, 2000.0; dq.gold_differs = True`:
     без исключения, `reconcile_gold_compared` 0 (на HEAD `ValueError`);
   - `dq.at_rest(); dq.gold_updated = "2026-09-30 00:00:00"` (снапшоты 1000 < 2000):
     `reconcile_gold_compared` 1 (на HEAD 0).
   Правка `reconcile_values`, после пар source-silver и проверки шага 3:
   - `gold_ready = gold_stale(_epoch(SILVER_DATA_CHANGED), _epoch(GOLD_REBUILT)) is False`, оба
     запроса один раз, до пар silver-gold;
   - сбой этих запросов: гейт закрыт, `reconcile_gold_compared` 0, вердикты source-silver
     печатаются и уходят, Variables `dq_gold_not_compared_runs`, `dq_gold_stale_runs` и их gauge
     не меняются, задача красная этой ошибкой (при расхождении source-silver `ValueError`
     «values differ at rest» с хвостом «the gold snapshot check failed as well»);
   - `GOLD_UPDATED` читают шаг GMV (`_compare_gmv`, до `MART_UPDATED`) и блок `mart_behind`;
     `stale = mart_behind or <итог gold_stale>`, снапшоты второй раз не запрашиваются;
   - `SILVER_UPDATED` (`reconcile.py:171-176`) удалить; комментарий `:178-185` без «deleted order
     leaves the watermarks apart»; docstring `reconcile_values` по новой логике.
   Прототип при написании пакета уронил ровно 8 тестов; переписать так:

   | тест `test_dags.py` | правка | почему не слабее |
   |---|---|---|
   | `test_gmv_is_not_compared_while_gold_is_behind_silver` (:553) | «gold позади» через `silver_changed, gold_rebuilt = 3000.0, 2000.0` | тот же сценарий и исход |
   | `test_gold_behind_silver_counts_one_more_run_without_gold` (:647) | так же | то же |
   | `test_a_comparison_that_fails_does_not_reset_the_count`, параметр `GOLD_UPDATED` (:701) | заменить на `SILVER_DATA_CHANGED`; `("trino", reconcile.GOLD_UPDATED)` добавить в `test_a_failing_gmv_step_sends_the_finished_verdicts_then_fails_the_run` (:1193) | строже: сбой знака больше не теряет готовые вердикты |
   | `test_a_failing_metadata_query_keeps_the_verdicts_and_the_count_then_fails` (:1379, 2 параметра) | ждать вердикт `source_silver`/`orders` в `dq.sent`, `reconcile_gold_compared` 0, обе Variables прежние | красный и отправка готовых вердиктов те же |
   | `test_a_value_difference_and_a_failing_metadata_query_are_both_reported` (:1460) | расхождение source-silver (флаг заглушки `source_differs`, шаг 3) | те же утверждения о сообщении |
   | `test_gmv_is_still_compared_when_cdc_did_not_move_during_the_task` (:1264) | чтений позиции 3 | строже |
   | `test_the_cdc_position_is_read_before_the_comparisons_and_again_before_the_gmv` (:1297) | 3 чтения: до первой пары; после последней пары и до первого запроса silver-gold; между `MART_UPDATED` и GMV Postgres | строже |

   Ещё: ветку `SILVER_UPDATED` заглушки (`:369-370`) удалить; комментарии `:1354`, `:1433`
   переписать без водяного знака; в `:1246` добавить параметр из трёх чтений
   `[(10, "0/10"), (10, "0/10"), later]` (чтение перед GMV остаётся покрыто); комментарий
   параметра `[cdc_reread]` (`:1189`) поправить: теперь падает чтение после пар.
   `test_gold_at_rest_*` (`test_reconcile.py:119`) остаётся.
3. **OR-03, позиция CDC.** Флаг заглушки `source_differs`: отпечаток Trino `orders` "10 other",
   пары Trino `[["key", "changed"]]`, пары Postgres `[("key", "original")]`. Тесты на отказ:
   - `source_differs` и `dq.cdc_moves_after = reconcile.fingerprint_sql_postgres("orders")`:
     `reconcile_values` без исключения, `reconcile_in_flight` 1 (на HEAD `ValueError`);
   - `dq.postgres_counts = {"orders": 11}` и `dq.cdc_moves_after = sql.source_rows("orders")`:
     `silver_matches_postgres` печатает «in flight» (на HEAD `ValueError`);
   - без сдвига оба красные (контроль, зелёный и сейчас).
   Правка: после цикла пар `_cdc_position()` ещё раз; сдвиг: вердикты и gauge `reconcile_rows`
   source-silver отброшены, `reconcile_in_flight` 1, строка `in flight: the source or the slot
   moved during the run`, GMV не сравнивается; сбой этого чтения: то же и красный этой ошибкой
   после отправки. `silver_matches_postgres`: позиция до счётов Postgres и после счётов silver,
   сдвиг превращает `red` в `in_flight`. В docstring: счётчик записей PG17 обнуляется при простое
   бэкенда, окно сужается, но не закрыто.
4. **OR-02, весь ключ.** В `_lookup` выражение `K`: `json_extract_scalar(x.key, '$.<c1>')` для
   ключа из одной колонки, `concat_ws(':', json_extract_scalar(x.key, '$.<c1>'), ...)` для
   составного; в массив идут полные ключи. Bronze (SQL дословно, переносы любые):
   ```sql
   select id from unnest(array['<k1>', ...]) as t(id) where exists (select 1
   from lake.bronze.cdc_events x where x.source_table = '<table>' and <K> = t.id)
   ```
   Quarantine: `lake.silver.quarantine x where x.topic = 'oltp.shop.<table>'`, в `K`
   `coalesce(x.key, x.payload)` вместо `x.key`. `_explain`: `{k for k in shown if k in ids}`.
   Тесты первыми: в `test_reconcile.py` для `order_items` и `["X:2"]` SQL обоих поисков содержит
   `'$.order_item_id'` и `'X:2'`, для `orders` и `["X"]` есть `'$.order_id'`, отказ на
   небезопасном ключе (`:165`) прежний; в `test_dags.py` пара `order_items`: Postgres
   `{"X:1", "X:9"}`, silver пуст, bronze отвечает `[["X:1"]]`: в сообщении `X:9 (unknown)` и
   `X:1 (merge_pending)` (на HEAD оба `unknown`).
5. **QA-02, QA-04, QA-05: только тесты**, зелёные на HEAD, красные на мутациях:
   - `test_dags.py`: `dag_keywords("silver_upsert.py", "dag")`: `max_active_runs` 1, `catchup`
     False; пул merge это `pool=LAKE_WRITERS_POOL` **или** `**spark_job_kwargs(LAKE_WRITERS_POOL)`
     (оба вида, OR-04 тест не трогает); `outlets` `[Asset(SILVER_ASSET_NAME)]`; `schedule`
     `dbt_build` `[Asset(SILVER_ASSET_NAME)]`; рёбра `("snapshot", "merge")`,
     `("merge", "remember_snapshot")` через `dependency_edges` (`:860`), `names()` понимает
     `ast.Call`; `"pools set lake_writers 1"` в Makefile рядом с проверкой `:783`.
   - `test_reconcile.py`: `"where not _is_deleted"` в `fingerprint_sql_trino(t)` и
     `pairs_sql_trino(t)` для 7 таблиц; в `gold_silver_sql_trino(g)` ровно у пар с `live_only`.
   - `test_dags.py:827-831` заменить поведением: `iceberg_orphans.py` грузится с заглушками
     `airflow.sdk` (`dag`, `task`) и `DockerOperator` (`partial(...).expand(...)`), окружение
     `SPARK_SILVER_ENV` через `monkeypatch.setenv`, `trino_rows` -> `[["orders_daily"]]`; тело
     `gold_orphan_commands({"dry_run": False})` равно `[gold_orphans_command("orders_daily",
     {"dry_run": False})]` с `--no-dry-run`, с `None` `--dry-run`.
   - `test_reconcile.py:40-45`: `output_columns` из `test_superset_bundle.py:111` в
     `tests/unit/dbt_sql.py` (импорт в обоих файлах); `gold_name` входит в `output_columns(модели)`.
6. **Проверки, коммит 1.** `make check`; `make dags-check`; мутации в копии дерева в scratchpad
   (тексты `work/QA/mutations.json.txt`, `mutations2.json.txt`, тесты из копии через venv репо):
   W1, W2, W4, W5, R1, T1 `RED`, T3 `GREEN`, своя O1 (`params or {}` -> `{}` в
   `iceberg_orphans.py`) `RED`. Живой select (Готово). `reviewer`: код плюс вопрос «не ослаблено ли
   условие» по таблице «Расхождения». Цикл verify, коммит
   `airflow: dq_checks gates gold on snapshots, rechecks cdc, looks up whole keys`; снятие паузы.
7. **OR-04, коммит 2.** До правки: вывод всех построителей `reconcile` и `sql` по всем таблицам в
   файл scratchpad, счёт тестов области. Правка по `reports/OR.md`, OR-04: `_count_runs`,
   `_resting()`, `reconcile.count_verdict`, `postgres_value` через `postgres_rows` (пустой ответ:
   тот же `ValueError("no row from: ...")`), merge через `**spark_job_kwargs(LAKE_WRITERS_POOL)` с
   явными `task_id`, `container_name`, `command`, `outlets` (`public_env`, `os` убрать). Тесты не
   менять; мутация W2' (`spark_job_kwargs(LAKE_WRITERS_POOL)` -> `GOLD_WRITERS_POOL`) `RED`.
   Ревью, verify, коммит `airflow: shared helpers in dq_checks and the merge task`.

## Готово, когда

- [ ] `uv run pytest tests/unit/test_dags.py tests/unit/test_reconcile.py -q` -> без `failed`;
      новые тесты шагов 2-4 записаны красными до правки (вывод в «Итог»)
- [ ] `grep -rn "SILVER_UPDATED" airflow tests` и `grep -rn 'split(":")\[0\]' airflow/dags` -> пусто
- [ ] мутации -> W1, W2, W4, W5, R1, T1, O1 `RED`, T3 `GREEN`; после коммита 2 W2' `RED`
- [ ] `make check` -> exit 0; `make dags-check` -> `5 dags import, timeouts, retry budget, force
      removal and the maintenance switch checked: [...]` с 5 DAG
- [ ] SQL `reconcile.bronze_lookup_sql('order_items', [<da2b...e1>:9, <da2b...e1>:1])` файлом в
      `$COMPOSE exec -T trino trino --catalog lake --execute` -> одна строка `...:1`
      (ключ `da2b5ed33ae5068005e9d2c43e7a3de1`, позиции 9 нет нигде)
- [ ] OR-04: вывод построителей до и после равен (`diff` пуст), счёт тестов как после коммита 1
- [ ] `reviewer` «принять» (с замечаниями) на каждый коммит; `make verify` -> `verify ok`
- [ ] после снятия пауз `$COMPOSE exec -T airflow-scheduler airflow dags list-runs dq_checks` ->
      ближайший прогон `success`; в покое GET `query=lakehouse_dq_reconcile_gold_compared` -> 1

## Не входит

- Комментарий гейта `observability/prometheus/alerts.yml:110-112`, `:124-128`: P09.
- OPERATIONS про `dq_checks` (`:627`, `:669-670`, `:850` «deleted order», `:703-716`),
  `airflow/README.md:10`, PF-20: P11 и P13 (OR-05). Оставить им в «Итог» строку: «гейт
  silver-gold по снапшотам с <коммит>; сдвиг CDC во время проверки = in flight».
- ID карточек и даты в `airflow/` (R-66): P10, кроме строк, которые P05 переписывает сам.
- `test_trino_access.py:121-123`, `test_superset_import.py:69`, `test_compose.py:167-168`: P07.

## Риски и откат

- Узкое окно ложного красного остаётся: merge закоммитил silver посреди `dbt_build` (PF-20),
  gold закоммичен позже из старого silver, гейт открыт до следующего build (около минуты).
  Старый гейт это окно закрывал. Записать в «Итог» и строку для P11.
- Пока `dq_checks` на паузе, через 30 минут горит `DqChecksStale`: ожидаемо.
- Строка quarantine без ключа, но с JSON в payload больше не находится (было `strpos`); живьём
  таких нет: 4 строки с `key` null и не-JSON payload, новый SQL на них проходит.
- Откат: `git revert` коммита при той же паузе, затем снятие паузы (DAG только читает данные).

## Расхождения с отчётом аудита

- Сверено: все `file:line` OR-01..OR-04, QA-02, QA-04, QA-05 подтверждены цитатой; живой SQL
  OR-02 повторён (1.5 с, ответ `...:1`); пробы в копии: 5 новых тестов красные на HEAD, на новых
  тестах W1, W2, W4, W5, R1, T1, O1 `RED`, T3 `GREEN`. `make dags-check` при написании не
  запускался (вывод взят из `Makefile:174-196`).
- Отчёт: «переписать `:553, 647, 1432`». Прототип OR-01 и OR-03 уронил 8 тестов (таблица шага 2),
  `:1432` не падает. Поведение при сбое запроса снапшотов и при сбое третьего чтения позиции
  отчёт не задавал: здесь задано.
- OR-04: «те же `334 passed, 65 skipped`» после коммита 1 неверно (тестов больше); равенство от
  состояния после коммита 1. Пауза нужна и `silver_upsert`. QA-02: тест пула обязан понимать `**spark_job_kwargs(...)`, мутацию W2 после
  OR-04 заменяет W2'.
- Строгость нового условия по сценариям (для `reviewer` и «ок» В-04):

  | сценарий | старый гейт | новый гейт | сигнал, если новый закрыт |
  |---|---|---|---|
  | gold перестроен после silver, знаки равны | сравнивает | сравнивает | |
  | посреди `dbt_build` | ложный красный | закрыт | `gold_stale_runs` +1 |
  | удалённый заказ, gold перестроен | закрыт навсегда | сравнивает | |
  | коммит silver в `customers`, `products`, `sellers`, `reviews`; gold старый | сравнивает старый gold | закрыт | `GoldStaleAtRest` через 2 прогона |
  | `dbt_build` на паузе или красный | по таблице | закрыт | `GoldStaleAtRest`, `SilverGoldNotCompared`, `AirflowDagFailed` |
  | у gold-таблицы нет снапшота | сравнивает | закрыт | `gold_stale_runs` +1 |
  | сбой запроса снапшотов | сравнивает, красный | не сравнивает, красный | красный прогон |
  | в silver нет коммитов данных | сравнивает | сравнивает | |

  Каждый случай «старый сравнивал, новый закрыт» даёт счёт `gold_stale_runs` или красный: молча
  ничего не прячется.

## Итог
