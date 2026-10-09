# 08. План недели 3: задачи для агентов-исполнителей

Версия 1.0, 09.10.2026. План уровня кода к спеке `07-w3-spec.md`. Спека отвечает «что и почему», план отвечает «какой файл, какой код, какая команда, какой вывод». План рассчитан на исполнителя без контекста прошлых сессий, в том числе на модель попроще: развилки закрыты, код дан целиком, у каждого шага есть проверка и правило «что делать, если не так».

Что проверено при подготовке плана, 09.10.2026:

- Весь код плана механически применён к копии `origin/main` (c52d5cc) в порядке задач. После каждой задачи зелёные `ruff`, `mypy`, `pytest` (в конце 145 passed, 62 skipped), `yamllint`, `sqlfluff` по миграциям и по dbt, `dbt parse`, `docker compose config`, `bash -n` всех скриптов; итоговое дерево совпало с эталонной копией.
- SQL всех моделей dbt выполнен только на чтение по живому silver через Trino 483. Числа совпали со спекой: `fct_orders` 94 406 = живые строки `silver.orders`, `dim_customers` 91 259, заказов без живых позиций 765, удалённых позиций 40; `sum(gmv)` витрин 12 845 420.13 = GMV по D8 прямо из silver.
- Образ Airflow из W3-T04 собран (`apache/airflow:3.3.2-python3.12`, 3.47 GB); версии пакетов в нём те, что в плане. Все четыре DAG импортируются через `BundleDagBag` Airflow 3.3.2 без ошибок, секреты Spark не попадают в сериализованный DAG.
- Поведение dbt-core 1.10.23, dbt-trino 1.10.4, sqlfluff 4.3, Airflow 3.3.2 (`config.yml`, CLI, DockerOperator 4.5.9, task SDK), Trino 483 сверено по исходникам и документации этих версий, где можно, запуском.

Не проверено, поэтому стоит в живых шагах (часть B каждой задачи): всё, что пишет в lake и в Airflow на живом стеке; views в Lakekeeper; DockerOperator через сокет; события Asset; память scheduler под `dbt build`; числа на дату выполнения.

## 1. Как пользоваться

Владелец:

1. Решения раздела 3 приняты 09.10.2026; новое решение или смена принятого записывается туда же до старта задачи.
2. Запускает задачи по порядку раздела 6: одна задача, один исполнитель, промпт из раздела 10.
3. Принимает задачу по отчёту (раздел 11) и командам «Готово, когда», даёт «ок» на коммит.

Исполнитель: читает этот README целиком, затем файл своей задачи, и работает по протоколу раздела 4.

## 2. Состояние на входе, 09.10.2026

- `origin/main` = c52d5cc. PR #1 из облачной сессии сделал W3-T00 шаг 6 (`REPLAY_DATA=raw|sample` через `Settings`) и W3-T04 шаг 4 (ключ Fernet в `make secrets`). Проверено: `make lint` зелёный, `make test` 120 passed и 62 skipped (только Spark-тесты без JVM), пять новых тестов проходят.
- Локальный `main` сведён с `origin/main` 09.10 (`git pull --rebase`): c52d5cc, над ним коммит спеки W3 и коммит этого плана. Проверка: `git merge-base --is-ancestor c52d5cc HEAD && echo ok`.
- Живой `.env`: `AIRFLOW_FERNET_KEY` длиной 32 (заменяется до первого старта Airflow в W3-T04), `REPLAY_DATA` нет (значит `raw`), `AIRFLOW_API_SECRET_KEY` и `DOCKER_GID` нет (добавляются в W3-T04).
- Стек: запущены `core` без реплеера и `trino`; последний коммит bronze 2026-10-08 04:35 UTC; silver равен Postgres; схемы `gold` нет; список soft-deleted таблиц Lakekeeper пуст.
- Реплей: `virtual_now` 2026-07-11 09:58, осталось около 72 виртуальных дней; бюджет W3 по D2 10 дней.

## 3. Решения до старта

Приняты владельцем 09.10.2026: D1-D13 по рекомендациям таблицы раздела 2 спеки, D14 и D15 по рекомендациям ниже. Там, где D14, D15 и уточнения ниже расходятся с текстом спеки, главнее они. Маркер `DECISION_DATE` в задачах это 2026-10-09. Новые решения, найденные при подготовке плана:

| ID | Вопрос | Рекомендация | Альтернатива | Цена ошибки |
|---|---|---|---|---|
| D14 | Повторная загрузка seed. dbt-trino 1.10.4 на каждом `dbt seed` и `dbt build` делает DROP и CREATE таблицы seed (`trino__reset_csv_table`), а не TRUNCATE, как написано в D13 | Макрос проекта `dbt/macros/trino__reset_csv_table.sql` возвращает поведение dbt-core: TRUNCATE и INSERT, DROP только при `--full-refresh`. Dispatch проверен 09.10: берётся макрос проекта; TRUNCATE Iceberg-коннектор Trino 483 поддерживает | Исключить seed из `dbt build` (`--exclude resource_type:seed`) и грузить отдельной целью `make dbt-seed` | Каждый `dbt build` оставляет в Lakekeeper soft-deleted копию `category_translation` на 7 дней, и DoD W3-T01 «в soft-deleted нет ничего из gold» не выполняется уже со второго прогона |
| D15 | К какому штату относится заказ в `mart_daily_sales` | По всем его позициям, включая удалённые; в `unknown` только заказы, у которых позиций не было никогда (735 на 09.10). Отменённый до отгрузки заказ и его отменённый GMV остаются в штате продавца, в одной строке | По живым позициям, как в тексте W3-T02 шаг 2 (в `unknown` 765) | Альтернатива разносит один отменённый заказ по двум строкам (`canceled_orders` в `unknown`, `canceled_gmv` в штате продавца), а продавцу не засчитываются отмены до отгрузки |

D7 остаётся в силе и при D15: пересчёт целой даты нужен любому изменению задним числом, а тест полного пересчёта остаётся главным сторожем витрины.

Уточнения спеки: факты, проверенные 09.10, решения не требуют.

1. sqlfluff 4.3 не меняет templater во вложенном `.sqlfluff` («Templater cannot be set in a .sqlfluff file in a subdirectory of the current working directory»). `dbt/.sqlfluff` остаётся, но `make lint` и CI запускают sqlfluff для dbt из каталога `dbt/`.
2. dbt-core 1.10.23 включает `require_generic_test_arguments_property`: аргументы generic-тестов пишутся под `arguments:`, иначе предупреждения об устаревании.
3. dbt-trino печатает предупреждение про SSL на каждом подключении; `flags: require_certificate_validation: true` при http его убирает и больше ничего не меняет. `send_anonymous_usage_stats: false`: иначе dbt пишет `.user.yml` в каталог профилей, а в Airflow он read-only.
4. `greatest()` в Trino возвращает null, если null хотя бы один аргумент, поэтому `fct_orders.updated_at` собран через `coalesce`.
5. Тест аномалии платежей (W3-T03) исключает статусы `canceled` и `unavailable`: по всем заказам расхождений 1 045, по остальным 287. У отменённых позиции удалены или их не было, а платежи остались.
6. `apache/airflow:3.3.2` собран на Python 3.13; план берёт `3.3.2-python3.12`, Python хоста и CI. Провайдер docker уже входит в образ.
7. Без общего `AIRFLOW__API__SECRET_KEY` UI не показывает логи задач: scheduler отдаёт их по токену, подписанному этим ключом, а без значения каждый процесс придумывает свой. Новая переменная `.env` `AIRFLOW_API_SECRET_KEY`.
8. Сокет Docker на хосте `root:docker`, gid 1001, а образ Airflow работает как `50000:0`: permission denied известен заранее. `group_add: ["${DOCKER_GID:-0}"]` только у scheduler, где LocalExecutor выполняет задачи; новая переменная `.env` `DOCKER_GID`. Api-server сокет не использует.
9. Новые DAG стартуют на паузе (`dags_are_paused_at_creation=True`), а запуск DAG на паузе остаётся в очереди: снятие паузы отдельный явный шаг.
10. Задачи LocalExecutor живут процессами в контейнере scheduler с лимитом 600 MB, поэтому `AIRFLOW__CORE__PARALLELISM=2`; память под `dbt build` меряется в W3-T05a, при OOM стоп.
11. `query_max_memory` в Trino 483 есть, но не виден в `SHOW SESSION`; `SET SESSION query_max_memory = '1MB'` работает и роняет join с `Query exceeded distributed user memory limit of 1MB` (optional chaos 10).

## 4. Протокол исполнителя

До первого шага:

1. `git status --short` пуст, ветка `main`, HEAD содержит c52d5cc и коммит предыдущей задачи из раздела 6.
2. Прочитаны `CLAUDE.md`, этот README и файл задачи. Спека `07-w3-spec.md` открывается там, где шаг ссылается на решение Dn.
3. Блок «Вход» задачи выполнен, вывод совпал. Не совпал: стоп.

Во время работы:

4. Шаги идут по порядку, без пропусков. Чекбоксы отмечаются в отчёте, файл плана не правится.
5. Код переносится как есть. «Файл целиком» создаёт или перезаписывает файл. «Найти / Заменить на» меняет ровно один фрагмент: если он не найден или найден дважды, файл менялся после плана, это стоп. Однострочный фрагмент заменяется внутри строки, многострочный целиком.
6. После каждого шага выполняется его проверка. Вывод не совпал: таблица «Если не так» задачи; нужной строки нет: стоп.
7. Ничего сверх плана: ни файлов, ни зависимостей, ни правок соседнего кода. Замеченное идёт в отчёт.
8. Заглавные маркеры в тексте документации (`FRESH_MINUTES`, `DECISION_DATE` и подобные) заменяются только значениями из своего прогона. Перед отчётом этот поиск пуст: `git grep -nE 'FRESH_|DECISION_DATE|AIRFLOW_STATS|AIRFLOW_IMAGE_SIZE|CHAOS9_' -- . ':!docs/planning'`.

Стоп-условия, общие для всех задач:

- Любое действие из blast radius `CLAUDE.md`: `DROP`, `DELETE` или `TRUNCATE` руками, `docker compose down -v`, `make nuke`, удаление тома, checkpoint или каталога, `expire_snapshots`, `remove_orphan_files`, `rm -rf`, снятие `protected`. Разрешены только служебные DROP, DELETE и TRUNCATE самого dbt в `lake.gold` (D13, D14).
- Нужно изменить файл, которого нет в списке «Файлы» задачи.
- Проверка падает после двух попыток исправить строго по плану.
- Нужна зависимость, сервис, профиль, порт или переменная `.env`, которых задача не называет.
- Живой вывод расходится с ожидаемым сильнее, чем допускает задача.
- Шаг тратит реплей сверх бюджета задачи.

При стопе ничего не откатывается молча: отчёт по разделу 11 с командой, выводом и гипотезой.

Никогда: `git push`, коммит без «ок», `git commit --amend` чужого коммита, `git reset --hard`, `git rebase`, строки атрибуции в сообщении коммита, имена владельца и работодателей в репо, длинное тире.

После шагов: проверки раздела «Готово, когда», отчёт, коммит только после «ок» владельца, сообщение коммита из задачи, файлы добавляются по списку, не `git add -A`.

Облачная сессия (Claude Code в браузере, Codex и подобные) выполняет только часть A и сдаёт работу веткой и PR, как PR #1. Часть B она не выполняет и не изображает: в описании PR строка «часть B не выполнялась». Заглавные маркеры остаются на месте, их заполняет часть B.

## 5. Где выполнять и кому

| Часть | Что нужно | Кто справится |
|---|---|---|
| A. Код и статические проверки | git, uv, Python 3.12, docker CLI для `docker compose config` (демон не нужен) | любая среда, в том числе облачная; модель уровня Sonnet, код дан целиком |
| B. Живая проверка | WSL2, Docker, поднятый стек, данные | только локально; исполнитель, который останавливается при расхождении; диагностика сбоя (`superpowers:systematic-debugging`) за сильной моделью или владельцем |

## 6. Порядок задач

| # | Файл | Карточка | Коммит | Зависит от | A, ч | B, ч |
|---|---|---|---|---|---|---|
| 1 | `T00-clean-clone.md` | W3-T00 путь с чистого клона | `infra: make start, bootstrap, verify and replay-burst` | D1, D2 | 1 | 2 |
| 2 | `T01-dbt-core.md` | W3-T01 dbt: проект, staging, ядро | `dbt: project, staging and core models` | D3-D6, D13, D14 | 1.5 | 1 |
| 3 | `T02-dbt-marts.md` | W3-T02 витрины | `dbt: marts and incremental daily sales` | 2, D7, D8, D15 | 1 | 1 |
| 4 | `T03-dbt-quality.md` | W3-T03 DQ-тесты, docs, глоссарий | `dbt: source anomaly tests, docs and glossary` | 3 | 1 | 0.5 |
| 5 | `T04-airflow-image.md` | W3-T04 образ Airflow, профиль `orchestrate` | `orchestrate: airflow image, env and pool` | D9, D12 | 1 | 1.5 |
| 6 | `T05a-dags-silver-dbt.md` | W3-T05, коммит 1 | `orchestrate: silver_upsert and dbt_build dags` | 1-5, D10, D13 | 1.5 | 1.5 |
| 7 | `T05b-dags-dq-maintenance.md` | W3-T05, коммит 2 | `orchestrate: dq_checks and iceberg_maintenance dags` | 6, D11 | 1 | 1 и сутки наблюдения |
| 8 | `T06-chaos-dbt.md` | W3-T06 chaos 9, optional chaos 10 | `dbt: chaos 9, a failing dbt test in airflow` | 7 | 0.5 | 0.5 |
| 9 | `close-week.md` | итоги W3, HANDOFF, бюджет реплея | `docs: week 3 handoff` | 1-8 | 0.5 | 0 |

Гейты W3-T07 (dbt и Airflow) делает владелец, план их не содержит. W3-T04 от W3-T01..T03 не зависит; в одном рабочем дереве задачи всё равно идут по таблице, иначе якоря «Найти» в общих файлах (`Makefile`, `OPERATIONS.md`, `DECISIONS.md`) не проверены на другой порядок.

## 7. Имена, на которые опираются задачи

- Цели Makefile: `start` (W3-T00), `up` с отказом на `core`, `bootstrap`, `verify`, `replay-burst SECONDS=<n> [SPEED=720]`, `replay-live`; `dbt-build` (W3-T01), `dbt-docs` (W3-T03); `airflow-init` (W3-T04); `chaos-break-dbt-test`, `chaos-trino-memory` (W3-T06, общая цель `chaos-%`).
- Функции `scripts/chaos/lib.sh`: `service_healthy`, `bronze_offsets_ok`, `virtual_now` (W3-T00); `airflow_cli`, `dag_run_state`, `run_dag` (W3-T04). Существующие: `trino`, `trino_value`, `psql_value`, `wait_until`, `run_silver`, `healthy`, `replay_burst`, `no_other_replayer`, `bronze_caught_up`, `bronze_offsets_report`, `reconcile`, `lsn_duplicates_since`.
- dbt: проект `marketplace`, профиль `lakehouse`, targets `dev`, `ci`, `chaos_low_memory`; всё пишется в `lake.gold`. Модели: `stg_{orders,order_items,payments,reviews,customers,sellers,products}`, `int_orders_enriched`, `int_daily_sales`, `fct_orders`, `fct_order_items`, `dim_customers`, `dim_products`, `dim_sellers`, `mart_daily_sales`, `mart_delivery_sla`, `mart_seller_performance`. Seed `category_translation`. Макросы `safe_divide`, `trino__reset_csv_table`. Generic-тест `unique_combination`. Переменные: `payments_mismatch_error_if`, `delivered_before_carrier_error_if`, `products_without_category_error_if`, `untranslated_categories_error_if`, `chaos_break_test`.
- Airflow: образ `lakehouse/airflow:dev`; dbt `/opt/dbt-venv/bin/dbt`, проект `/opt/dbt` (read-only), `--target-path /tmp/dbt/target --log-path /tmp/dbt/logs`. DAG `silver_upsert`, `dbt_build`, `dq_checks`, `iceberg_maintenance`. Asset `lake.silver`. Variable `silver_upsert_last_bronze_snapshot`. Pool `lake_writers`, 1 слот. Пакет `airflow/dags/lakehouse/`: `settings`, `checks`, `sql`, `clients`.
- `.env`: `REPLAY_DATA` (PR #1), `AIRFLOW_API_SECRET_KEY` и `DOCKER_GID` (W3-T04, новые), `AIRFLOW_ADMIN_PASSWORD` удалён из `.env.example` (D12).

## 8. Ограничения на всю неделю

- Версии: dbt-core 1.10.23 и dbt-trino 1.10.4 (`uv.lock`), Trino 483, Lakekeeper 0.13.6, Airflow 3.3.2 на Python 3.12. Поведение сверяется по документации этих версий, не по памяти.
- `$COMPOSE` в задачах это `docker compose --env-file .env -f docker/compose.yaml`, из корня репо.
- Реплей только порциями `make replay-burst`, в пределах бюджета D2 (W3 до 10 виртуальных дней); потраченное каждая задача пишет в отчёт.
- Профили: `make start` (`core` без реплеера и `trino`); с W3-T04 ещё `orchestrate`, и тогда `TRINO_XMX=2g` перед каждым `make start`. Все профили сразу не поднимаются.
- Один писатель silver: при снятом с паузы `silver_upsert` ручные `make silver` и `make verify` запрещены.
- JDBC-строки в `iceberg_catalog` не трогать, Spark с `CATALOG_TYPE=jdbc` не запускать.
- dbt без пакетов (`dbt deps` не нужен): встроенные тесты и свои в `dbt/tests/`.
- SQL lowercase, CTE, только `ref()` и `source()`; порты только на 127.0.0.1; секреты только через `${VAR}`.
- Один коммит на задачу (W3-T05 два), после проверок и «ок» владельца.

## 9. Review Focus

Режимы отказа, которые спека подразумевает, а юнит-тесты не ловят; у каждого есть живая проверка в задаче-владельце.

1. Повторный `dbt build` без новых данных не оставляет новых soft-deleted таблиц `gold`, кроме `mart_daily_sales__dbt_tmp` (D13, D14). W3-T01 B, W3-T02 B: список deleted-tabulars до и после.
2. Изменение заказа задним числом (доставка или отмена через дни после покупки) пересчитывает его старую дату: тест полного пересчёта после порции реплея. W3-T02 B.
3. Ручной `make silver` или `make verify` при работающем Airflow даёт второго писателя одного checkpoint. `verify` отказывается при запущенном scheduler; проверка в W3-T05a B.
4. Перезапуск Airflow и пустой bronze: `silver_upsert` с Variable от прошлого запуска и без неё; таблицы входов в `test_dags.py` (W3-T05a, W3-T05b), живой рестарт scheduler в W3-T05b B.
5. Память scheduler под `dbt build` (600 MB, parallelism 2): W3-T05a B меряет пик и `OOMKilled`; при OOM стоп и решение владельца.

## 10. Промпт для запуска исполнителя

```text
Ты исполнитель задачи <ФАЙЛ> проекта Marketplace Lakehouse (mini), репозиторий в текущем
каталоге. Владелец принимает решения и коммиты; ты выполняешь план и ничего не решаешь за него.

До первого действия прочитай CLAUDE.md, docs/planning/08-w3-plan/README.md целиком и
docs/planning/08-w3-plan/<ФАЙЛ>. Работай строго по протоколу раздела 4 README: шаги по
порядку, код из плана как есть, после каждого шага его проверка; при расхождении, которого
нет в таблице «Если не так» задачи, остановись и напиши отчёт.

Среда: <облачная, только часть A | локальная, части A и B>.
Не коммить и не пушь. В конце отчёт по разделу 11 README.
```

## 11. Отчёт исполнителя

```text
Задача: <файл>, выполнены части: A | A и B
Итог: готово к ревью | остановлено на шаге <N>
Шаги: A1 ок, A2 ок, ... B1 ок, ...
Проверки «Готово, когда»: команда -> последние строки вывода, по каждой
Замеры: значение, дата, команда (всё, что попало в документацию вместо маркеров)
Реплей: virtual_now до и после, потрачено виртуальных часов
Отклонения от плана: что и почему, или «нет»
Стоп: шаг, команда, вывод, гипотеза (если был)
Blast radius: что затронуто (ожидается: ничего, кроме служебных операций dbt в gold)
git status --short и git diff --stat
Сообщение коммита: из задачи
```
