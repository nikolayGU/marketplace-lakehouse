# 10. Спека: неделя 5, stateful job, CI, сверка значений, обслуживание Iceberg

> Статус: закрыт, неделя 5 закрыта 23.10.2026, W5-T05b закрыта 29.10.2026 по спеке 14; решения W5-D* действуют. Исторический документ: не исполнять как задачу. Действующие правила: `AGENTS.md`; бэклог: `docs/planning/14-closeout-spec.md`; индекс: `docs/planning/README.md`.

Версия 0.1, 23.10.2026. Решения раздела 2 приняты исполнителем 23.10 (владелец делегировал исполнение недели, «делай все сам»; решения W5-D1..D15 он увидит в диффе и в ADR-024 и ADR-025). Формат по `06-spec-standard.md`, структура как у `09-w4-spec.md`. Исходные задачи в `01-roadmap.md` (неделя 5 и список «Спека недели 5 обязана закрыть»), архитектура в `00-mini-architecture-review.md` (§6 RAM, §8 сценарии). Сверено 23.10: код `streaming/spark_jobs/*`, `airflow/dags/*`, `docker/compose.yaml`, `Makefile`, `.github/workflows/ci.yml`, `scripts/chaos/lib.sh`, живой стек (read-only запросы Trino, листинг MinIO, `gh api`), документация Spark 3.5.6, Iceberg (latest), Trino (current), docker/build-push-action, hadolint (context7), `pyspark==3.5.9` из `.venv`. Что не проверено, помечено «не проверено» с командой проверки или оформлено шагом «проверить первым».

## 1. Цель и границы

Цель недели: в проекте есть настоящий stateful job с watermark, state и поздними событиями, показанными SQL; CI гоняет Spark-тесты с Iceberg без skipped и собирает образы; smoke проходит весь путь с чистого клона на сэмпле; сверка источник - silver - gold идёт по значениям, а не только по количеству; обслуживание Iceberg описано политикой и впервые выполнено на живых таблицах.

Состояние на входе (23.10):

- W4 не закрыта. В рабочем дереве не закоммичены W4-T03..T06b: `airflow/dags/lakehouse/metrics.py`, `observability/grafana/dashboards/{pipeline-health,infra}.json`, `alerts.yml`, `alerts_test.yml`, `scripts/obs/check_dashboards.py`, chaos 5, 6, 8 (`git status --short`, 23.10). W5-T01b и W5-T04 правят дашборд и `lakehouse/metrics.py`: они стартуют после коммитов W4. W5-T02 и W5-T03 от W4 не зависят.
- CI: один job `lint-and-test` (`.github/workflows/ci.yml`). `uv sync --group dev` без `--locked` (`:19`). Образ Spark собирается, но в нём ничего не запускается (`:33-34`). Комментарий о hadolint, образе Airflow и smoke (`:39-40`). Последние запуски зелёные, 1m23-1m46 (`gh run list`, 23.10).
- Тесты с `needs_iceberg` пропускаются там, где нет `/opt/spark/jars/iceberg-spark-runtime-*` (`tests/unit/test_silver_upsert.py:41-48`, `test_iceberg_sink.py:17-22`, `test_iceberg_demo.py:17-22`). В трёх файлах 23 строки с `needs_iceberg` (с определениями). Здесь лежат тесты MERGE, карантина и пропуска эпохи. На runner `uv run pytest` их пропускает; `make test-spark` гоняет их в `lakehouse/spark:dev` (`Makefile:137-144`), образ захардкожен, `pip install -q pytest jsonschema` без версий.
- Пять Dockerfile: `streaming/`, `airflow/`, `oltp/`, `docker/connect/`, `observability/container-exporter/` (`find . -name 'Dockerfile*'`).
- Stateful job нет. Позднее событие по `purchase_ts` взять неоткуда: `REPLAY_LATE_RATIO` сдвигает только UPDATE `delivered` (`oltp/replayer/replay.py:197-205`, `settings.py:31-35`), INSERT заказа приходит в порядке `order_purchase_timestamp` (`replay.py:156-160`, расписание по `due_ts`). На 720x (порция) 5 минут event time это 0.4 с реального времени, батч bronze в 20 с покрывает 4 виртуальных часа; на 2880x, 16 часов.
- Bronze (Trino, 23.10): 527 файлов данных, 43 MB, медиана 16 509 байт, 27 партиций, 148 снапшотов; в `metadata_log_entries` 101 запись, в MinIO 122 файла `metadata.json`, 534 parquet против 527 в `$files`, 299 avro (`mc ls --recursive`). Silver: `orders` 28 файлов данных и 4 delete-файла, 25 снапшотов; `order_items` и `payments` по 9 файлов и 20 снапшотов. Gold: `fct_orders` 29 снапшотов, `mart_daily_sales` 13 снапшотов и 22 файла (`CREATE OR REPLACE` на каждый прогон dbt).
- `iceberg_maintenance`: daily, только `optimize` восьми таблиц silver через Trino в pool `lake_writers` (`airflow/dags/iceberg_maintenance.py:21-34`). Bronze, gold, `expire_snapshots`, `remove_orphan_files` не трогались ни разу. ADR об этой политике нет: пишет W5-T05a (ADR-025).
- `reconcile` (`scripts/chaos/lib.sh:153`, `scripts/reconcile_sql.py`) сверяет Postgres и silver по количеству, md5 набора ключей и суммам decimal; значения остальных колонок и gold не сверяются. `dq_checks` (`airflow/dags/dq_checks.py:70-92`) сравнивает только количество строк.
- Реплей: бюджет W5 по D2 W3 до 15 виртуальных дней; потрачено в W4 по HANDOFF 11 ч 54 мин на 23.10.

Входит: W5-T01a, T01b, T02, T03, T04, T05a, T05b. За владельцем: «ок» на то, что в AGENTS.md в списке запретов (разделы карточек «Blast radius»), гейт Spark Operate после W5-T01 (`02-learning-gates.md:24`), чтение diff перед коммитом.

Не входит: README-витрина, дашборд по gold (W6), Alertmanager (W4-D6), снятие запрета на `expire_snapshots` bronze (ADR-021, раздел 7), `dbt build` в smoke.

## 2. Решения до старта

Решения принял исполнитель 23.10 по рекомендации. Карточки ссылаются на них по ID.

| ID | Вопрос | Рекомендация | Альтернатива | Цена ошибки | Статус |
|---|---|---|---|---|---|
| W5-D1 | Что читает `orders_per_minute`: Kafka или bronze | Kafka, топик `oltp.shop.orders`, свой checkpoint `checkpoints/orders_per_minute`, `startingOffsets=earliest`, `failOnDataLoss=true`. Stateful операция живёт на самом потоке, событие для демо публикуется в топик так же, как в `scripts/chaos/late.sh`. Читать bronze значило бы ещё один долгоживущий читатель Iceberg-таблицы с тем же дефектом, что у silver: подготовка стартует со снапшота, который видел запрос (apache/iceberg#18000), и обходит все хранимые снапшоты (#16940, ADR-021), а bronze коммитит каждые 20 с | Iceberg streaming read bronze, как silver | Читатель bronze навсегда закрепляет запрет `expire_snapshots` на bronze, и каждый его триггер опрашивает историю из 148+ снапшотов. Kafka хранит 24 ч: простой job дольше суток роняет его по `failOnDataLoss` (как bronze, OPERATIONS «Bronze ingest»); таблица производная, восстановление через сброс checkpoint с «ок» (ADR-024) | принято исполнителем 23.10 |
| W5-D2 | Где крутится job | Отдельный сервис compose `spark-orders-per-minute`, профиль `stateful`, образ `lakehouse/spark:dev` (`pull_policy: never`, собирает `spark-bronze`), команда `["orders_per_minute"]`, лимит 1792M, `SPARK_DRIVER_MEMORY=1g`, метрики на `:4041` внутри сети `lake` (Prometheus job `spark-orders-per-minute`), UI на `127.0.0.1:4043`. Зависимости от сервисов `core` с `required: false`, как у `obs`. `make start` не меняется. Новый сервис, поэтому ADR-024 | Второй `StreamingQuery` в драйвере `spark-bronze` (ноль новых сервисов) | Второй запрос в драйвере bronze связывает отказы: ошибка stateful запроса или OOM уводит с собой CDC-приём в `core`. Отдельный сервис стоит около 0.7 GiB реального RAM (замеряется в T01b) при стоп-правиле W4-D5 в 10 GiB; в покое со всеми профилями было 5.16 GiB (19.10) | принято исполнителем 23.10 |
| W5-D3 | Что считать и как пережить повторы Debezium | Только `op = 'c'` (вставка заказа; снапшотные `r` приходят в порядке скана таблицы, а не времени, и массово отбрасывались бы). Окно `window(purchase_ts, '1 minute')`, `withWatermark('purchase_ts', '5 minutes')`, агрегат `size(collect_set(order_id))`, `outputMode=update`. Повтор одного заказа внутри окна не увеличивает счёт. Spark не поддерживает цепочку stateful операций в update mode (программное руководство Spark 3.5, «Unsupported Operations»), поэтому `dropDuplicatesWithinWatermark` плюс `count` не подходят | `count(*)`: повтор после `docker kill` Connect (253 повтора в chaos 2b) завышает окно | `count(*)` делает таблицу неидемпотентной: повтор доставки меняет результат, что нарушает инвариант AGENTS.md. `collect_set` держит id в state (заказов в минуту порядка 0.1-10): память пренебрежима | принято исполнителем 23.10 |
| W5-D4 | Откуда позднее событие и где его показывать | Две части. Демо `make watermark-demo`: лаб-топик `lab.orders.<run_id>` (1 партиция, `retention.ms=3600000`, создаётся явно, автосоздание выключено), синтетические конверты с вымышленной датой 2000-01-01, тот же код job с `OPM_TRIGGER=available_now` двумя прогонами на одном checkpoint (граница между прогонами это граница батча, поэтому последовательность детерминирована), приёмник `lake.demo.orders_per_minute`. На живом потоке `make watermark-live`: повторная публикация реальной вставки (как chaos 4): старой, за watermark, и самой свежей, внутри. Основной топик получает только реально существовавшие записи, поэтому `bronze_offsets_ok` и `reconcile` не ломаются. `REPLAY_LATE_RATIO` не используется (сдвигает UPDATE, `op = 'u'` в job не читается) | (a) Расширить реплеер: откладывать INSERT заказа. Откладывать надо и все следующие события заказа (иначе UPDATE уходит в пустоту), правка ядра реплеера; задержка в 5 виртуальных минут на 720x это 0.4 с и не пересекает границу батча в 20 с. (b) Синтетические заказы в основной топик: silver получает заказ, которого нет в Postgres, `reconcile` красный | (b) ломает инвариант сверки. (a) без смены границы батча не создаёт позднего события вообще | принято исполнителем 23.10 |
| W5-D5 | Приёмник, триггер, shuffle | Таблица `lake.silver.orders_per_minute (window_start timestamp_ntz, orders bigint, _updated_at timestamp)`, создаёт job через `ensure_table`; контракта в `contracts/silver/` нет (иначе `silver_upsert` создаст и обработает её как таблицу CDC). `foreachBatch`: `MERGE ... when matched and s.orders > t.orders then update`, `when not matched then insert`: повтор батча и повторное чтение дают тот же результат, неполные данные после сброса checkpoint не откатывают счёт. Окно и watermark по `timestamp` в `spark.sql.session.timeZone=UTC` (`timestamp_millis` от миллисекунд конверта), в приёмник каст в `timestamp_ntz`: колонка сравнима с `silver.orders.order_purchase_timestamp` в Trino. Триггер `processingTime` 20 с (`OPM_TRIGGER_SECONDS`). `spark.sql.shuffle.partitions=2` (`OPM_SHUFFLE_PARTITIONS`) | Значения по умолчанию Spark (200 партиций состояния) | 200 партиций state store это до 200 файлов дельт на каждый батч в S3A, значение замораживается в checkpoint (как `silver_shuffle_partitions`), исправление только сбросом checkpoint | принято исполнителем 23.10 |
| W5-D6 | Как запустить Spark-тесты с Iceberg в CI | В CI собирается образ `lakehouse/spark:ci` (buildx, `load: true`), `make test-spark SPARK_IMAGE=lakehouse/spark:ci`. Переменная `SPARK_IMAGE ?= lakehouse/spark:dev`, версии `pytest` и `jsonschema` закреплены по `uv.lock` (тест сверяет). Skipped превращается в отказ флагом `-p no:skipping` в команде внутри образа (в образе есть JVM и jar, поэтому тесты не должны пропускаться ни по какой причине) | Скачать Iceberg jar на runner в `$SPARK_HOME/jars` pip-версии PySpark и гонять `uv run pytest` | Второй путь расходится с образом (другие jar, другой Python 3.12 против 3.10 образа Spark): зелёное в CI не доказывает, что работает `make test-spark` владельца | принято исполнителем 23.10 |
| W5-D7 | Структура CI и кэш слоёв | Четыре параллельных job: `lint-and-test` (как сейчас, `uv sync --locked --group dev`), `hadolint` (матрица по пяти Dockerfile, `failure-threshold: warning`, `.hadolint.yaml` с причиной у каждого `ignored`), `spark-tests`, `airflow-image`. Кэш слоёв `type=gha,mode=max`, отдельный `scope` на образ. Образ Airflow после сборки проверяется запуском (`import`, `dbt --version`). Action-ы: `docker/setup-buildx-action@v4`, `docker/build-push-action@v7`, `hadolint/hadolint-action@v3.5.0` (последние релизы 15-24.09 и 24.08, `gh api` 23.10); существующие `checkout@v4`, `setup-uv@v6`, `gitleaks-action@v2` не меняются | Один job; кэш в реестре GHCR | Один job удлиняет обратную связь до суммы всех шагов; GHCR требует прав на запись пакетов. Лимит кэша GHA 10 GB на репозиторий: два образа около 3 GB (оценка, не проверено: размер кэша в `gh cache list` после первого прогона), `scope` разделяет их ключи | принято исполнителем 23.10 |
| W5-D8 | Когда и что гоняет smoke | `workflow_dispatch` плюс `schedule` раз в неделю (понедельник 03:00 UTC). Шаги: `make secrets`, `REPLAY_DATA=sample` в `.env`, `make bootstrap`, `make replay-burst SECONDS=60`, `make verify`, повторный `make bootstrap` (идемпотентность). `dbt build` не входит | Nightly; `dbt build` в smoke | Nightly на публичном репозитории бесплатен, но красный запуск приходит письмом каждую ночь; расписание отключается через 60 дней без активности в репозитории (не проверено, документация GitHub). `dbt build` добавляет 3-4 минуты и ещё одно звено, которое может покраснеть не по вине пути с клона | принято исполнителем 23.10 |
| W5-D9 | Как сверять значения источника, silver и gold | Отпечаток строки: `md5` от значений всех колонок контракта в каноническом тексте (общий разделитель `chr(31)`, `\N` вместо null, decimal с масштабом контракта, timestamp как миллисекунды от эпохи после усечения до мс). Уровень 1: на каждую таблицу один запрос с `count` и `md5` от отсортированных `ключ:отпечаток` (тот же приём, что в `reconcile_sql.py`, он уже работает на 107 тыс. строк). Расхождение: вторым запросом вытаскиваются пары (ключ, отпечаток) только этой таблицы и сравниваются в Python; в отчёт идут первые 20 ключей и причина. Пары: источник - silver (7 таблиц) и silver - gold (`fct_orders`, `fct_order_items`, `dim_products`, `dim_sellers` по общим колонкам; `dim_customers` только по числу `customer_unique_id`). Витрины сверяются тестом dbt (`assert_mart_daily_sales_matches_full_recompute`), не здесь | Всегда вытаскивать все пары и сравнивать в Python; агрегат по xor хэшей | Пары по 107 тыс. строк каждые 15 минут перегружают Trino, который стоит на 95% лимита; xor требует функций, паритет которых в Postgres и Trino не проверен | принято исполнителем 23.10 |
| W5-D10 | Где живёт сверка и когда считается «в покое» | Задача `reconcile_values` в `dq_checks` (DoD роадмапа), считается только при `checks.at_rest` для пары источник - silver; для пары silver - gold дополнительно нужно, чтобы gold догнал silver: `max(fct_orders.updated_at) >= max(silver.orders._updated_at)`. Иначе задача печатает `in flight, no verdict`, не шлёт gauges и не падает. Порог пересмотра: если суммарное время запросов задачи больше 60 с (замер в шаге 1), задача переезжает в DAG `reconcile_report` `@hourly` с теми же функциями | Задача без охраны каждые 15 минут | Сверка в полёте даёт ложные расхождения (`reconcile` при идущем реплее, OPERATIONS «Airflow»). Ошибка на 60 с: `dq_checks` занимает Trino на четверть каденции | принято исполнителем 23.10 |
| W5-D11 | Чем выполнять `expire_snapshots`, `remove_orphan_files`, `rewrite_*` | Spark-задание `streaming/spark_jobs/maintenance.py` в образе `lakehouse/spark:dev`, запускается DockerOperator из DAG так же, как `merge` (то же окружение, `spark_silver_environment`). Причины: `remove_orphan_files` в Spark умеет `dry_run` и `location`, в Trino нет ни того, ни другого; `rewrite_position_delete_files` есть только в Spark. `optimize` silver остаётся в Trino (D11 W3). Задачи silver в pool `lake_writers`, задачи gold в новом pool `gold_writers` (1 слот), в нём же `dbt_build`, чтобы `CREATE OR REPLACE` и `expire_snapshots` одной таблицы не пересекались | Trino `ALTER TABLE EXECUTE expire_snapshots / remove_orphan_files` | Без `dry_run` первый `remove_orphan_files` вслепую (blast radius). Без отдельного pool `expire_snapshots` gold может проиграть коммит `dbt_build` и упасть | принято исполнителем 23.10 |
| W5-D12 | Политика обслуживания (ADR-025) | Silver: `optimize` daily (как сейчас), `rewrite_position_delete_files` для `orders`, `expire_snapshots` 7 дней при `retain_last=1`, `remove_orphan_files` раз в неделю старше 7 дней, `write.metadata.delete-after-commit.enabled=true` через `PROPERTIES` в `silver_upsert.py`. Gold: `expire_snapshots` 7 дней и `remove_orphan_files` для таблиц, которые вернёт `information_schema.tables where table_type = 'BASE TABLE'`. Bronze: `rewrite_data_files` партиций старше текущих суток daily, свойство `write.metadata.delete-after-commit.enabled` в `ensure_table` bronze, `remove_orphan_files` только в `location` каталога `metadata` (данные bronze не удаляются никогда), `expire_snapshots` запрещён кодом (ADR-021). `lake.silver.orders_per_minute` входит в список silver. 7 дней: Trino требует не меньше (`iceberg.expire-snapshots.min-retention` по умолчанию 7d), time travel глубже недели проекту не нужен, 5-минутные MERGE `silver.orders` без изменений дают до 2016 снапшотов за неделю | 3 дня; хранить снапшоты gold дольше | Короткий срок убирает окно отката ошибки dbt (chaos 9 откатывает витрину по снапшоту). Любой срок меньше 7d Trino отклонит | принято исполнителем 23.10 |
| W5-D13 | Порядок первого запуска деструктивных процедур | Лестница с отдельным «ок» на каждую ступень: (1) `lake.demo` (песочница `make iceberg-demo`), (2) `silver.sellers` (самая маленькая, 2 снапшота) `expire_snapshots`, (3) остальные silver и gold, (4) `remove_orphan_files` с `dry_run=true` по всем таблицам и разбор списка, (5) реальный `remove_orphan_files`. DAG `iceberg_orphans` создаётся на паузе, реальный запуск только с `{"dry_run": false}` в conf после «ок» | Включить DAG целиком после одного «ок» | Одна ошибка в `older_than` удаляет файлы снапшота, который читает silver или dbt: на bronze это неисправимо (Kafka хранит 24 ч) | принято исполнителем 23.10 |
| W5-D14 | Бюджет реплея W5 | До 3 виртуальных дней из 15: T01b две порции по 60 с (около 1 дня), T04 одна порция, T05b одна порция; остальное запас. Потраченное пишется в HANDOFF | 15 дней | Перерасход оставляет Operate-гейты W6 без трафика | принято исполнителем 23.10 |
| W5-D15 | Формулировка гейта в `02-learning-gates.md:24` | Operate-гейт Spark называет `silver.orders_per_minute`; демо позднего события идёт в `demo.orders_per_minute` (`make watermark-demo`), на живой таблице видны счёт и метрика отброшенных строк (`make watermark-live`). Строку гейта правит W5-T01b | Оставить как есть: на живой таблице внутри watermark новую строку взять неоткуда (W5-D4) | Гейт, который нельзя выполнить как написано | принято исполнителем 23.10 |

## 3. Ограничения блока

- `$COMPOSE` означает `docker compose --env-file .env -f docker/compose.yaml` из корня репо, как в `Makefile`.
- Версии: Spark 3.5.9, Iceberg 1.11.0 (`streaming/Dockerfile`), Trino 483, Airflow 3.3.2, Prometheus v3.14.0, Python 3.12 на хосте и в Airflow, 3.10 в образе Spark (код `streaming/` без синтаксиса 3.11+). Поведение сверяется с документацией этих версий.
- Один писатель silver, это Airflow. Ручной `make silver` и полный `make verify` только при остановленном scheduler по процедуре HANDOFF («Что живёт в стеке»). Chaos-скрипты и демо получают silver через `merge_silver`.
- Коммит: `guard.py` требует полный `make verify` этого дерева. Перед каждым коммитом: поставить на паузу `silver_upsert` и `iceberg_maintenance`, дождаться конца запусков, остановить scheduler, `make verify`, запустить scheduler, снять паузу с `silver_upsert`; `iceberg_maintenance` вернуть в то состояние, в каком он был (сейчас на паузе: снятие паузы это ступень лестницы W5-D13).
- Пересборка `lakehouse/spark:dev` меняет образ для `spark-silver` в DAG: следующий merge идёт на новом коде. `make start` пересоздаёт `spark-bronze` при изменившемся образе. Поэтому образ для демо собирается командой `$COMPOSE --profile core build spark-bronze` (без пересоздания контейнера), а `make start` только с «ок», без идущего реплея, после `bronze_caught_up`.
- Реплей только порциями `make replay-burst`, каждая с «ок» владельца, в пределах W5-D14; потраченное в HANDOFF.
- Новый сервис один (`spark-orders-per-minute`, W5-D2). Профили: рабочая комбинация `core+query+orchestrate+obs` плюс `stateful`; стоп-правило W4-D5 (любой `OOMKilled=true` или сумма `docker stats` больше 10 GiB) действует.
- Без «ок» владельца не выполняются: `expire_snapshots`, `remove_orphan_files` (в том числе процедуры DAG), `rewrite_data_files` bronze, любая запись в bronze и silver кроме штатных DAG, сброс checkpoint, `DROP` (в том числе `lake.demo` через `make iceberg-demo`, он начинается с `drop table ... purge`), `docker compose down -v`, `rm -rf`, `git push`, правки `.env`, хуков и `.claude/settings.json`. «ок» на одно действие не переносится на следующее. Запуск workflow на GitHub и push тоже только с «ок» (агент не пушит).
- Секреты только `${VAR}` и `.env`; в workflow только `secrets.GITHUB_TOKEN`. Порты на 127.0.0.1.
- Конфиги `.github` и `observability` проходят `yamllint` (`make lint`); каждый файл, который монтирует compose, существует до первого старта.
- Один коммит на карточку, после проверок раздела 6 и «ок» владельца на дифф.

## 4. Карточки

### W5-T02 `ci.yml`: hadolint, `uv sync --locked`, Spark-тесты с Iceberg, образ Airflow, кэш слоёв

**Зачем.** Самые ценные тесты W2 (MERGE, карантин, пропуск эпохи) на runner пропускаются, поэтому зелёный CI не доказывает, что silver работает. Образ Airflow и пять Dockerfile вообще не проверяются.
**Оценка** 4 ч. **Зависит от:** W5-D6, W5-D7. **Область коммита:** `ci`.

**Вход.**
- Факты раздела 1 про `ci.yml`, `Makefile:137-144`, `needs_iceberg`.
- `uv.lock`: `pytest` 9.1.1, `jsonschema` 4.26.0, `pyspark` 3.5.9.
- Версии action-ов на 23.10 (`gh api repos/<repo>/releases/latest`): `docker/setup-buildx-action` v4.4.1, `docker/build-push-action` v7.4.0, `hadolint/hadolint-action` v3.5.0. `build-contexts` в build-push-action принимает `name=path` и передаёт `--build-context` (документация action, context7), нужен buildx не старше 0.8.0.
- Репозиторий публичный (`gh repo view`, 23.10): runner Linux 4 vCPU и 16 GB (не проверено: печатает первый шаг `smoke.yml`, `nproc; free -g; df -h /`).

**Сделать.**
1. Проверить первым:
   - действия живы: `for r in docker/setup-buildx-action docker/build-push-action hadolint/hadolint-action; do gh api repos/$r/releases/latest --jq '.tag_name'; done`; в workflow мажорные теги (`@v4`, `@v7`, `@v3.5.0`).
   - hadolint на пяти Dockerfile: `for f in streaming/Dockerfile airflow/Dockerfile oltp/Dockerfile docker/connect/Dockerfile observability/container-exporter/Dockerfile; do echo "== $f"; docker run --rm -i hadolint/hadolint < "$f"; done` (тег образа по `gh api repos/hadolint/hadolint/releases/latest --jq .tag_name`). Замечание уровня warning и выше исправляется в Dockerfile, если исправление не меняет содержимое слоёв; остальные замечания идут в `.hadolint.yaml` (`ignored`) с комментарием причины у каждого.
   - `-p no:skipping`: `docker run --rm --user root --entrypoint bash -v "$PWD":/repo:ro -e PYTHONPATH=/opt/spark/python:/opt/spark/python/lib/py4j-0.10.9.7-src.zip:/repo/streaming lakehouse/spark:dev -c 'pip install -q pytest==9.1.1 jsonschema==4.26.0 && cd /repo/tests/unit && python3 -m pytest -q -p no:cacheprovider -p no:skipping --rootdir=/tmp test_iceberg_sink.py'` печатает `passed` без `skipped`. Не печатает: стоп, вопрос владельцу (запасной путь - счёт `skipped` в выводе, правка шага 3).
   - `grep -rn 'xfail\|pytest.skip(' tests/unit` пусто (флаг отключает и `xfail`).
2. `Makefile`: `SPARK_IMAGE ?= lakehouse/spark:dev`, `SPARK_TEST_PIP := pytest==9.1.1 jsonschema==4.26.0`; `test-spark` берёт оба; в команду внутри образа добавлен `-p no:skipping`. Первыми тесты в `tests/unit/test_makefile.py`: `make -n test-spark SPARK_IMAGE=lakehouse/spark:ci` содержит `lakehouse/spark:ci` и `-p no:skipping`; закреплённые версии равны версиям `pytest` и `jsonschema` в `uv.lock` (дрейф ловит тест, а не человек).
3. `.github/workflows/ci.yml`: у workflow `concurrency` по `github.ref` с `cancel-in-progress` для pull request, у каждого job `timeout-minutes`; `lint-and-test` как есть, но `uv sync --locked --group dev`, шаг сборки Spark оттуда убран; job `hadolint` (матрица по пяти Dockerfile, `hadolint-action`, `dockerfile: ${{ matrix.dockerfile }}`, `failure-threshold: warning`); job `spark-tests` (checkout, `setup-buildx-action`, `build-push-action` с `context: streaming`, `build-contexts: contracts=contracts`, `tags: lakehouse/spark:ci`, `load: true`, `cache-from: type=gha,scope=spark`, `cache-to: type=gha,mode=max,scope=spark`, затем `make test-spark SPARK_IMAGE=lakehouse/spark:ci`); job `airflow-image` (то же для `context: airflow`, тег `lakehouse/airflow:ci`, `scope=airflow`, затем `docker run --rm --entrypoint python lakehouse/airflow:ci -c "import airflow, trino, psycopg, pydantic_settings"` и `docker run --rm --entrypoint /opt/dbt-venv/bin/dbt lakehouse/airflow:ci --version`). Комментарий в конце файла про hadolint и образ Airflow заменён строкой «smoke: smoke.yml (W5-T03)».
4. `.hadolint.yaml` (если шаг 1 нашёл что игнорировать): `ignored` с комментарием причины у каждого правила.
5. `tests/unit/test_workflows.py`, первым: каждый найденный `find . -name 'Dockerfile'` (кроме `.venv`) есть в матрице job `hadolint`; в `ci.yml` каждый `uses:` из списка `docker/*` и `hadolint/*` имеет мажорный тег, не `latest` и не ветку; в обоих workflow нет `secrets.` кроме `secrets.GITHUB_TOKEN`.
6. Документация: `tests/README.md` (где идут Spark-тесты и как повторить локально), OPERATIONS: подраздел «CI» (job-ы, `make test-spark SPARK_IMAGE=...`, холодная и тёплая сборка с числами из первого зелёного прогона), `streaming/README.md` одной строкой.

**Готово, когда.**
- `make test`, `make lint` зелёные; `uv run pytest tests/unit/test_makefile.py tests/unit/test_workflows.py -q` печатает `passed`.
- `make test-spark SPARK_IMAGE=lakehouse/spark:dev`: последняя строка `N passed`, слова `skipped` нет; `N` записано в описание коммита.
- Тест на отказ: `uv run pytest -p no:skipping tests/unit/test_iceberg_sink.py -q` на хосте без Spark jar печатает `failed` или `error`, не `skipped` (доказывает, что флаг превращает пропуск в отказ).
- После push владельца: `gh run list --workflow ci --limit 1 --json conclusion --jq '.[0].conclusion'` равно `success`; `gh run view <id> --log | grep -E '[0-9]+ passed'` содержит строку Spark-job с тем же `N` без `skipped`; в логе `hadolint` пять успешных прогонов матрицы; время холодного и тёплого прогонов записано в OPERATIONS.

**Ловушки.**
- `docker build` без buildx не умеет `cache-to type=gha`; поэтому `setup-buildx-action` с драйвером `docker-container`, а `load: true` нужен, чтобы `make test-spark` увидел образ в локальном демоне runner.
- Образ Spark использует именованный контекст `contracts`; без `build-contexts: contracts=contracts` сборка падает на `COPY --from=contracts`.
- `pip install` внутри `make test-spark` без версий забирает новый `pytest` в любой день: CI краснеет без изменений в репо. Версии закреплены тестом против `uv.lock`.
- Python образа Spark 3.10, хоста 3.12: код `streaming/` и тесты не должны использовать синтаксис 3.11+ (поэтому тест в образе и нужен).
- Лимит кэша GHA 10 GB: без отдельного `scope` образы вытесняют друг друга.
- `-p no:skipping` отключает и `xfail`: шаг 1 проверяет, что их нет.

**Blast radius и пайплайн.** Нет. Стек, checkpoint, таблицы и DAG не затронуты; push и запуск workflow на GitHub только с «ок».

**Не входит.** Smoke (W5-T03), сборка остальных трёх образов (их проверяет hadolint), повышение версий существующих action-ов (раздел 7).

**Итог 23.10.** `780795e`. Первый прогон на GitHub (run 40002529798) зелёный: `lint-and-test` 89 с, `hadolint` 5 прогонов по 7-15 с, `spark-tests` 258 с (`213 passed`, без skipped, `-p no:skipping`), `airflow-image` 301 с (холодный кэш). Hadolint: замечания уровня warning закрыты inline-комментариями `# hadolint ignore=` с причиной в `streaming/Dockerfile`.

### W5-T03 `smoke.yml`: путь с чистого клона на сэмпле

**Зачем.** `make bootstrap` на сэмпле проверен руками 17.10; CI не знает, сломался ли путь с клона. Kaggle в CI недоступен, поэтому сэмпл (`data/sample`, закоммичен).
**Оценка** 3.5 ч. **Зависит от:** W5-T02 (общие тесты workflow), W5-D8. **Область коммита:** `ci`.

**Вход.**
- `scripts/bootstrap.sh`: `make start`, ожидание здоровья `spark-bronze kafka-connect trino` до 300 с, `make migrate`, `connect/register.sh`, `replay-load` если нет состояния реплея, `verify.sh`, `protect.sh`. Использует `.venv/bin/python`, значит нужен `uv sync`.
- `.env.example:7` `REPLAY_DATA=raw`, комментарий «sample is ... CI smoke»; `Settings.replay_data: Literal["raw", "sample"]` (`oltp/replayer/settings.py`).
- OPERATIONS «Daily commands»: с нуля на сэмпле 4 минуты при собранных образах, повтор 75 с; холодная сборка Spark добавляет около 80 с.
- Реплей берёт 20% сэмпла (2000 заказов): порция 60 с на 720x даёт десятки событий (оценка, не проверено: `make replay-status` после порции в шаге 4 покажет `events_emitted`).

**Сделать.**
1. Первым `tests/unit/test_workflows.py` (общий с W5-T02): у `smoke.yml` есть `workflow_dispatch`, нет `pull_request`, в тексте workflow есть `REPLAY_DATA=sample`, `make verify` и проверка строки `verify ok`.
2. `.github/workflows/smoke.yml`: `on: workflow_dispatch` и `schedule` (`0 3 * * 1`); один job `ubuntu-latest`, `timeout-minutes: 45`, права `contents: read`. Шаги по порядку:
   - checkout; печать `nproc; free -g; df -h /; docker version --format '{{.Server.Version}}'` (подтверждает размер runner, закрывает «не проверено» W5-T02);
   - освобождение диска на одноразовой VM runner: `sudo rm -rf /usr/local/lib/android /usr/share/dotnet /opt/ghc` и `df -h /` (это CI-машина, не рабочий стек);
   - `astral-sh/setup-uv@v6` с `python-version: "3.12"`, `uv sync --locked --group dev`;
   - `make secrets`, затем `sed -i 's/^REPLAY_DATA=.*/REPLAY_DATA=sample/' .env`;
   - `set -o pipefail; make bootstrap 2>&1 | tee bootstrap.log` и `grep -qx 'verify ok' bootstrap.log`;
   - `make replay-burst SECONDS=60`, затем `make verify 2>&1 | tee verify.log` и `tail -1 verify.log` равно `verify ok`;
   - повтор `make bootstrap 2>&1 | tee again.log`: `grep -q 'replay state exists, load skipped' again.log` и `grep -qx 'verify ok' again.log`;
   - `if: failure()`: `$COMPOSE --profile '*' ps -a`, `logs --tail=200` в файл и `actions/upload-artifact` (версия по `gh api repos/actions/upload-artifact/releases/latest`, мажорный тег).
3. Документация: OPERATIONS «CI» дополняется абзацем про smoke (как запустить, `gh workflow run smoke.yml --ref main`, сколько идёт); `tests/README.md` строка про smoke вместо «Integration checks run through ... the smoke workflow».

**Готово, когда.**
- `make lint` зелёный (yamllint по `.github`); `uv run pytest tests/unit/test_workflows.py -q`: `passed`.
- `uv run python -c "import yaml; d = yaml.safe_load(open('.github/workflows/smoke.yml')); print(sorted(d[True]))"` печатает `['schedule', 'workflow_dispatch']` (PyYAML читает ключ `on` как `True`).
- После push и «ок» владельца на запуск: `gh workflow run smoke.yml --ref main`, затем `gh run watch "$(gh run list --workflow smoke.yml --limit 1 --json databaseId --jq '.[0].databaseId')" --exit-status` завершается кодом 0 не позже 45 минут; `gh run view <id> --log | grep -c 'verify ok'` не меньше 3 (bootstrap, verify, повторный bootstrap).
- Размер runner из первого шага записан в OPERATIONS и в строку «не проверено» карточки W5-T02 закрыт.

**Ловушки.**
- `make secrets` кладёт `REPLAY_DATA=raw`; без `sed` bootstrap идёт за Kaggle и падает на загрузке.
- `make start` собирает образы Spark и Connect с нуля (около 400 MB jar Spark; Connect тянет jar JMX с GitHub по контрольной сумме): смоук холодный по определению, поэтому лимит 45 минут и расписание раз в неделю.
- Память: лимиты `core+trino` около 11 GB при 16 GB runner; если OOM-kill, лимиты сервисов не трогаются, запись в OPERATIONS и вопрос владельцу.
- Диск: без очистки образы (Spark, Trino 483, Kafka, Connect, два Postgres, MinIO, Lakekeeper) около 5-7 GB на runner с 14 GB свободных (оценка, не проверено: `df -h /` до и после очистки).
- `schedule` выполняется только на ветке по умолчанию и отключается после 60 дней без активности (не проверено).
- Порт 8000 на runner свободен; `no_other_replayer` в `replay-burst` и `verify` ловит чужой реплеер, на чистой VM его нет.

**Blast radius и пайплайн.** Нет для рабочего стека: всё на одноразовой VM GitHub. `rm -rf` в шаге очистки диска относится к VM runner. Запуск на GitHub только с «ок».

**Не входит.** `dbt build` в smoke (раздел 7), сборка Airflow-профиля, проверка алертов.

**Итог 23.10.** `780795e`. Запуск `gh workflow run smoke.yml --ref main` (run 40003292011) упал на первом шаге bootstrap: образы MinIO удалены из quay.io (`no such manifest`, остальные 11 образов проекта на месте). Runner: 4 vCPU, 15 GB RAM, диск 145 GB (свободно 86 GB). Остальные шаги не проверены. Нужен ADR на замену или сборку MinIO (см. HANDOFF).

### W5-T01a Job `orders_per_minute`, тесты, демо позднего события

**Зачем.** Без watermark, state и позднего события вопрос про Structured Streaming остаётся теорией (ADR-017). Карточка даёт код и детерминированное демо: событие внутри watermark меняет окно, за ним отбрасывается, повтор не задваивает.
**Оценка** 4 ч. **Зависит от:** W5-D1, W5-D3, W5-D4, W5-D5, W5-T02 (тесты сразу идут в CI). **Область коммита:** `stream`.

**Вход.**
- `streaming/spark_jobs/bronze_cdc_ingest.py:126-136` (опции Kafka-источника), `:121` (listener), `:143` (триггер); `silver_upsert.py:313-325` (`foreachBatch` и `availableNow`), `contracts.py` (`MIN_EPOCH_MS`, `MAX_EPOCH_MS`); `catalog.py:build_session`; `settings.py` (`Settings`).
- Конверт заказа: `tests/fixtures/envelopes/orders_c.json` (`after.order_id`, `after.order_purchase_timestamp` в миллисекундах от эпохи, `op = "c"`).
- Spark 3.5: окно по `timestamp` и `withWatermark` до агрегата; в update mode строка с окном, закрытым watermark, отбрасывается; `numRowsDroppedByWatermark` и `numRowsTotal` есть в `StateOperatorProgress`, `eventTime['watermark']` в ISO UTC (документация 3.5.6, context7 23.10; `.venv/bin/python -c "from pyspark.sql.streaming.listener import StateOperatorProgress as S; print([a for a in dir(S) if a.startswith('numRows')])"` печатает `numRowsDroppedByWatermark`, `numRowsRemoved`, `numRowsTotal`, `numRowsUpdated`, 23.10, pyspark 3.5.9). Цепочка stateful операций в update mode не поддерживается: отсюда `collect_set` (W5-D3).
- Не проверено: что `collect_set` допустим в потоковой агрегации Spark 3.5.9 и что `numRowsDroppedByWatermark` считает отброшенные окна, а не входные строки. Проверяет первый тест шага 2.

**Сделать.**
1. `settings.py`: `opm_source_topic = "oltp.shop.orders"`, `opm_target = "lake.silver.orders_per_minute"`, `opm_checkpoint = ""` (пусто означает `<checkpoint_root>/orders_per_minute`), `opm_watermark = "5 minutes"`, `opm_trigger: Literal["processing", "available_now"] = "processing"`, `opm_trigger_seconds = 20`, `opm_starting_offsets = "earliest"`, `opm_shuffle_partitions = 2`; в `tests/unit/test_spark_settings.py` строка про значения по умолчанию.
2. Тесты первыми, `tests/unit/test_orders_per_minute.py` (`needs_java` для потока, `needs_iceberg` для приёмника; источник потока это каталог JSON-файлов с `maxFilesPerTrigger=1` и `availableNow`, каждый файл один батч; у файлов разные `mtime`, иначе порядок не детерминирован):
   - событие внутри watermark: батч 1 заказы в 10:00:10, 10:04:30, 10:10:20; батч 2 заказ в 10:07:40 (окно 10:07 закрывается в 10:08, watermark 10:05:20): появляется окно 10:07 со счётом 1;
   - событие за watermark: тот же батч 2 содержит заказ в 10:04:50 (окно 10:04 закрылось в 10:05, раньше 10:05:20): счёт окна 10:04 остаётся 1, `numRowsDroppedByWatermark` в прогрессе батча 2 не меньше 1;
   - повтор `order_id` внутри окна не меняет счёт (повторная вставка заказа 10:10:20);
   - строка, не являющаяся конвертом (`not json at all`), `op = 'u'`, `op = 'r'`, пустой `order_id`, `order_purchase_timestamp` вне `[MIN_EPOCH_MS, MAX_EPOCH_MS]` не попадают в счёт и не роняют запрос;
   - приёмник: `upsert` двух одинаковых батчей оставляет счёт тем же; батч с меньшим счётом окна не уменьшает его;
   - `describe(progress)` печатает `progress batch=<id> watermark=<iso> state_rows=<n> dropped=<n> input_rows=<n>`.
   Ожидание `state_rows` после батча 2: 2 (окна 10:07 и 10:10, окна 10:00 и 10:04 вытеснены). Если Spark даёт другое число, фиксируется фактическое и объяснение в ADR-024; расхождение с цифрами выше не повод править тест под результат без разбора.
3. `streaming/spark_jobs/orders_per_minute.py`: `parse_orders(kafka)` (конверт: `op`, `after.order_id`, `after.order_purchase_timestamp`; фильтры шага 2; `purchase_ts = timestamp_millis(...)`), `windowed_counts(events, delay)` (`withWatermark`, `groupBy(window(...))`, `size(collect_set('order_id'))`, `window.start` в `timestamp_ntz`), `ensure_table`, `upsert(batch, batch_id, target)` по W5-D5, `describe`, `main`. Сессия: `spark.sql.session.timeZone=UTC`, `spark.sql.shuffle.partitions` из настроек до старта запроса. Источник Kafka: `subscribe`, `startingOffsets`, `failOnDataLoss=true`, `maxOffsetsPerTrigger` как у bronze. Режим `available_now` печатает `describe` по `recentProgress` после завершения. Зависимость `to_bronze`/конверта: схема конверта берётся из `bronze_cdc_ingest.ENVELOPE`, не копируется.
4. `scripts/demo/watermark.sh` и цели `make watermark-demo` и `make watermark-live`. Режим `lab` реплеер не проверяет, потому что не трогает Postgres; `run_id=$(date -u +%Y%m%d%H%M%S)`, топик `lab.orders.$run_id` создаётся `kafka kafka-topics.sh --create --partitions 1 --replication-factor 1 --config retention.ms=3600000`; батч 1 (3 конверта, заказы `demo-$run_id-1..3`, дата 2000-01-01) публикуется `kafka-console-producer.sh --sync`; прогон 1: `$COMPOSE --profile core run --rm --no-deps -e OPM_SOURCE_TOPIC=... -e OPM_TARGET=lake.demo.orders_per_minute -e OPM_CHECKPOINT=s3a://${S3_BUCKET}/checkpoints/orders_per_minute_demo/$run_id -e OPM_TRIGGER=available_now spark-silver orders_per_minute`; батч 2 (заказ внутри, заказ за watermark, повтор заказа 3); прогон 2 с теми же параметрами; затем SQL из Trino и сверка с ожидаемыми строками; последняя строка `ok: inside watermark updated, outside dropped, duplicate counted once`; при различии скрипт печатает его и завершается кодом 1. Режим `live` описан в W5-T01b.
5. `SPARK_TESTS` в `Makefile` получает `test_orders_per_minute.py`; `run-job.sh` не меняется.
6. Образ для демо: `$COMPOSE --profile core build spark-bronze` (без пересоздания контейнеров).
7. Документация: `streaming/README.md` (job, настройки `OPM_*`), docstring модуля с семантикой watermark (почему `update`, почему `collect_set`, почему `r` не читается), OPERATIONS «Stateful job» пишет W5-T01b.

**Готово, когда.**
- `make test`: новые тесты зелёные или пропущены (на хосте без JVM) без ошибок; `make lint` зелёный.
- `make test-spark SPARK_TESTS=test_orders_per_minute.py`: `N passed`, 0 skipped, `N` не меньше 8.
- `make watermark-demo` печатает ровно четыре строки результата `select window_start, orders from demo.orders_per_minute where window_start < timestamp '2000-01-02' order by 1`: окна 10:00 со счётом 1, 10:04 со счётом 1, 10:07 со счётом 1, 10:10 со счётом 1; строка `progress batch=... dropped=1` для батча с поздними событиями; последняя строка `ok: ...`.
- Повтор `make watermark-demo` (новый `run_id`) даёт те же четыре строки: приёмник идемпотентен.
- `select count(*) from silver.orders_per_minute` в Trino падает с `does not exist`: живой job в этой карточке не запускался; `select count(*) from silver.quarantine` до и после `make watermark-demo` один и тот же.

**Ловушки.**
- Watermark применяется к батчу по значению предыдущего батча. Внутри одного батча порядок событий не важен, поэтому позднее событие в демо стоит строго в следующем прогоне.
- Окно отбрасывается, когда его конец не позже watermark, а не когда само событие старше watermark: события в тестах подобраны с запасом около 20 с.
- `spark.sql.shuffle.partitions` замораживается в checkpoint при первом запуске: 200 партиций state store это сотни файлов на каждый батч в S3A, исправляется только сбросом checkpoint.
- Файловый источник в тесте читает файлы по `mtime`: без разных `mtime` оба файла попадают в один батч, и тест не видит позднего события.
- Конверт Debezium в `before`/`after` содержит поле `order_purchase_timestamp` числом (миллисекунды): `timestamp_millis` на значении вне диапазона бросает исключение, поэтому фильтр по границам из `contracts.py` до преобразования.
- Лаб-топик не подпадает под `subscribePattern` bronze (`oltp\.shop\..*`): bronze его не читает. Удаление топика это отдельный «ок».
- `ensure_table` проверяет колонки и падает, если таблица не совпадает; приёмник не в `contracts/silver/`, чтобы `silver_upsert` его не подхватил.
- Пересборка `lakehouse/spark:dev` меняет образ для следующего `merge`; `make test-spark` перед сборкой обязателен.

**Blast radius и пайплайн.** Новый код и демо-таблица `lake.demo.orders_per_minute` (`create table if not exists`, без `drop`). Checkpoint демо в `checkpoints/orders_per_minute_demo/<run_id>`, одноразовые каталоги без удаления. Bronze, silver, offsets Kafka и DAG не затронуты. Новый топик `lab.orders.<run_id>` создаётся, удаление только с «ок». Сборка образа без пересоздания контейнеров.

**Не входит.** Долгоживущий сервис, метрики, дашборд (W5-T01b); сверка со `silver.orders` на живом потоке (W5-T01b).

**Итог 23.10.** `2441975`. Тесты первыми, 10 тестов `test_orders_per_minute.py` без skipped в образе. **Расхождение со спекой:** Spark отбрасывает позднюю строку по watermark предыдущего батча, поэтому событие за watermark в батче, который двигает watermark, ещё принимается; демо идёт тремя прогонами, а не двумя. `collect_set` допустим. `foreachBatch` обязан делать `persist` (без него `dropped=3` на одну позднюю строку и `state_rows=8` на 3 окна). `make watermark-demo`: четыре окна по 1, `dropped=1`, повтор не задваивает.

### W5-T01b Сервис `spark-orders-per-minute`, метрики state и watermark, живая проверка

**Зачем.** Job должен работать на живом потоке и быть виден на дашборде: сколько строк в state, где watermark, сколько отброшено. Это ответ на «как вы мониторите stateful стрим» (ADR-013).
**Оценка** 3.5 ч. **Зависит от:** W5-T01a, коммиты W4 (дашборд, `prometheus.yml`), W5-D2, W5-D14; «ок» на запуск сервиса и две порции реплея. **Область коммита:** `stream`.

**Вход.**
- `streaming/spark_jobs/metrics.py`: `PrometheusListener` с метриками на `query`, `onQueryProgress` читает `progress.sources`; тесты `tests/unit/test_metrics_listener.py` (SimpleNamespace вместо событий).
- `docker/compose.yaml`: `spark-bronze` (`:265-322`, healthcheck по `spark_streaming_last_batch_timestamp` `:306-317`), `spark-silver` (`:328-365`, `profiles: [jobs]`, `pull_policy: never`).
- Профиль `obs` ссылается на сервисы `core` через `depends_on` с `required: false` (W4-T01a): так проект остаётся валидным без `core`.
- `observability/prometheus/prometheus.yml` (jobs, W4-T01a), `scripts/obs/check_dashboards.py` (W4-T04), дашборд `pipeline-health.json`.

**Сделать.**
1. ADR-024 «Stateful job `orders_per_minute`» в `DECISIONS.md` и строка индекса: W5-D1, D2, D3, D4, D5 (источник Kafka и почему не bronze, `collect_set`, `op = 'c'`, `update` и upsert с защитой, shuffle 2, сервис, лаб-топик), ограничения (watermark в event time; на ускорении реплея 5 минут это доли секунды реального времени; допускается ли перекос партиций, см. DoD).
2. Тесты первыми, `tests/unit/test_progress.py` и дополнения `test_metrics_listener.py`: `watermark_seconds({"watermark": "1970-01-01T00:00:00.000Z"})` равно 0; ISO с дробной частью и без неё; ключа `watermark` нет (пустой `eventTime`): метрика не меняется; `state_rows` суммирует операторы; отрицательных и нечисловых значений нет; `numRowsDroppedByWatermark` увеличивает счётчик на разницу, не на накопленное значение (в прогрессе оно по батчу).
3. `streaming/spark_jobs/progress.py` без импорта pyspark (как `offsets.py`): `watermark_seconds(event_time: Mapping[str, str] | None) -> float | None`, `state_totals(operators) -> tuple[int, int]` (строк в state, отброшено watermark). `metrics.py`: gauge `spark_streaming_state_rows{query}`, gauge `spark_streaming_watermark_timestamp_seconds{query}`, counter `spark_streaming_late_rows_dropped_total{query}`; `onQueryProgress` выставляет их из `progress.stateOperators` и `progress.eventTime`; у bronze (без состояния) метрики не появляются. Docstring модуля обновлён.
4. `docker/compose.yaml`: сервис `spark-orders-per-minute` по W5-D2: `profiles: [stateful]`, `image: lakehouse/spark:dev`, `pull_policy: never`, `command: ["orders_per_minute"]`, окружение как у `spark-bronze` плюс `OPM_*` со значениями по умолчанию в compose (`${OPM_WATERMARK:-5 minutes}` и т.д., `.env` не правится), `METRICS_PORT: "4041"`, порт `${BIND_IP}:4043:4040`, healthcheck как у bronze, `depends_on` на `kafka`, `lakekeeper-bootstrap`, `minio-init` с `required: false`, `deploy.resources.limits.memory: 1792M`, `restart: unless-stopped`, `logging: *logging`. `prometheus.yml`: job `spark-orders-per-minute` (`spark-orders-per-minute:4041`).
5. Дашборд `pipeline-health.json`: панели `spark_streaming_state_rows{query="orders_per_minute"}`, `spark_streaming_watermark_timestamp_seconds{query="orders_per_minute"} * 1000` (тип time), `increase(spark_streaming_late_rows_dropped_total{query="orders_per_minute"}[1h])`, `sum(rate(spark_streaming_input_rows_total{query="orders_per_minute"}[5m]))`; `scripts/obs/check_dashboards.py` проходит.
6. Проверить первым после старта: `make up PROFILE=stateful` с «ок» (bronze не перезапускается: образ уже собран шагом W5-T01a), `$COMPOSE --profile stateful ps` показывает `healthy` не позже 2 минут; `docker stats --no-stream lakehouse-spark-orders-per-minute-1` записан; `curl -s 127.0.0.1:9090/api/v1/targets` содержит job `spark-orders-per-minute` в состоянии `up` после `docker kill -s HUP lakehouse-prometheus-1`.
7. `scripts/demo/watermark.sh live` (цель `make watermark-live`): предусловия как в `late.sh` (`no_other_replayer`, `connector_running`, `service_healthy spark-orders-per-minute`); `bronze_caught_up`; из `silver.orders_per_minute` берётся максимальный `window_start` `M`; из bronze вставка (`op = 'c'`) заказа с `order_purchase_timestamp` не позже `M - 1 hour` (за watermark) и вставка с самым большим `order_purchase_timestamp` (внутри); обе читаются из Kafka по partition и offset и публикуются заново (`kafka-console-consumer` и `kafka-console-producer --sync`, как в `late.sh`); после каждой ждёт одного батча (рост `spark_streaming_input_rows_total` в `docker compose exec spark-orders-per-minute curl -s localhost:4041/metrics`); печатает сумму `orders` и число отброшенных до и после; код 1, если на событии за watermark сумма изменилась, а отброшенных не стало больше ровно на 1; код 1, если на событии внутри сумма изменилась.
8. Живая проверка с «ок» на порцию: `make replay-burst SECONDS=60` (запомнить `virtual_now before` как `T0`, округлить вверх до минуты), `bronze_caught_up`, `merge_silver`, сумма `lag` по запросу `orders_per_minute` равна 0, затем SQL из DoD.
9. Документация: OPERATIONS: раздел «Stateful job» (что читает, как запустить `make up PROFILE=stateful`, как остановить, как сбросить checkpoint с «ок» и почему сброс безопасен, таблица метрик, как читать `late_rows_dropped`), строки в «Profiles» (профиль `stateful`, замер `docker stats`) и «Ports» (4043); `docs/runbooks/spark-stalled.md` одной строкой про второй job; `02-learning-gates.md:24` по W5-D15; ADR-013 одной фразой про state и watermark.

**Готово, когда.**
- `make test`, `make lint`, `make test-spark` зелёные.
- `$COMPOSE --profile '*' config -q`: код 0; `$COMPOSE --profile stateful config -q` без `--profile core`: код 0 (работает благодаря `required: false`).
- `curl -s 127.0.0.1:9090/api/v1/query --data-urlencode 'query=spark_streaming_watermark_timestamp_seconds{query="orders_per_minute"}'` возвращает один ряд, значение не 0 после первой порции.
- После порции (`T0` из шага 8) в Trino:
  ```sql
  with s as (select date_trunc('minute', order_purchase_timestamp) m, count(*) c
             from silver.orders where not _is_deleted and order_purchase_timestamp >= timestamp '<T0>' group by 1),
       o as (select window_start m, orders c from silver.orders_per_minute where window_start >= timestamp '<T0>')
  select count(*) from s full join o on s.m = o.m where s.c is distinct from o.c
  ```
  печатает `0`, и `curl -s 127.0.0.1:9090/api/v1/query --data-urlencode 'query=spark_streaming_late_rows_dropped_total{query="orders_per_minute"}'` равно 0. Не ноль: стоп, это находка (перекос партиций сильнее watermark на ускоренном реплее), она записывается в ADR-024, а `OPM_WATERMARK` пересматривается решением владельца; DoD при этом не подгоняется.
- `make watermark-live` печатает `ok:`, показывает отброшенных `+1` на событии за watermark и `+0` на событии внутри, сумма `orders` до и после равна.
- Перезапуск сервиса: `$COMPOSE --profile stateful restart spark-orders-per-minute`, в логе `Resuming at batch N`, после догона тот же запрос из первого пункта выше даёт `0` (checkpoint и state переживают рестарт).
- `bash -c '. scripts/chaos/lib.sh && bronze_offsets_ok'` код 0 после `watermark-live` (повторная публикация добавила записи с новыми offset); `make reconcile` без расхождений при остановленном scheduler.
- Замер: `docker stats --no-stream` сервиса записан в OPERATIONS, сумма по всем контейнерам меньше 10 GiB.

**Ловушки.**
- Повторная публикация реальной вставки попадает и в bronze, и в silver: MERGE её отбрасывает по `_last_lsn` (как chaos 4), `lsn_repeats_last_hour` в `dq_checks` вырастет на 1. Это ожидаемо, записать в OPERATIONS.
- Пока Prometheus не перечитал конфиг, job не виден: нужен `HUP`.
- Контейнер `spark-orders-per-minute` не стартует, если `lakehouse/spark:dev` ещё не собран (`pull_policy: never`); образ собирает `make start` или `build spark-bronze`.
- Метрики state и watermark появляются после первого батча с данными; на пустом топике `eventTime` пуст.
- Watermark живёт в виртуальном времени заказов, а не в часах реального: панель показывает дату событий, `time() - watermark` не имеет смысла.
- `failOnDataLoss=true`: простой сервиса дольше 24 ч роняет запрос и ведёт к циклу рестартов Docker, как у bronze; выход это сброс checkpoint с «ок» (таблица производная: счёт не уменьшается из-за защиты MERGE, шаг в OPERATIONS).
- Лимит памяти сервиса 1792M взят оценкой, не замером; по `docker stats` шага 6 лимит поправляется в этом же коммите.

**Blast radius и пайплайн.** Новый долгоживущий контейнер читает Kafka, пишет `silver.orders_per_minute` и свой checkpoint; Kafka-offsets bronze и checkpoint silver не затронуты. Две порции реплея около 1 виртуального дня из W5-D14. Запуск сервиса и порции с «ок». Сброс checkpoint сервиса (в OPERATIONS) в blast radius, с «ок».

**Не входит.** Алерт на `orders_per_minute` без батча (раздел 7), чтение из bronze, метрика карантина (Modify-гейт W4).

**Итог 23.10.** `2441975`. Сервис `spark-orders-per-minute` (профиль `stateful`) healthy за 90 с, 495 MiB в покое, 842 MiB при чтении топика с начала. После порции 60 с: 164 окна, 0 расхождений с `count(*)` по `silver.orders` поминутно, 194 заказа с каждой стороны, `late_rows_dropped_total` 0. `make watermark-live`: старый заказ отброшен один раз (`0 -> 1`), свежий `1 -> 1`, сумма 819. После рестарта продолжил с checkpoint, сверка 0. Сумма памяти контейнеров 8.2 GiB. Правка гейта (W5-D15) внесена в `02-learning-gates.md`.

### W5-T04 Сверка источник - silver - gold по значениям

**Зачем.** `reconcile` ловит потерянную строку и неверную сумму, но не ловит изменённый статус или дату при совпадающем количестве. Отчёт с отпечатком строки и причиной расхождения превращает «данные верны» из утверждения в проверку.
**Оценка** 5 ч. **Зависит от:** W5-D9, W5-D10; коммиты W4-T03 (`lakehouse/metrics.py`) и W4-T04 (дашборд). **Область коммита:** `orchestrate`.

**Вход.**
- `scripts/reconcile_sql.py`: запросы Postgres и Trino на таблицу из `contracts/silver/*.json`, `md5` отсортированных ключей, суммы decimal. `lib.sh:153` `reconcile`.
- `airflow/dags/dq_checks.py:70-92` `silver_matches_postgres`, `:31-35` `export` через `metrics.send`; `lakehouse/checks.py` (`at_rest`, `count_differences`), `lakehouse/settings.py` (`SILVER_KEYS`, `SOURCE_TABLES`), `lakehouse/clients.py` (`trino_rows`, `postgres_value`).
- Контракты в образ Airflow не монтируются (только `airflow/dags` и `dbt`, `docker/compose.yaml` раздел `orchestrate`): список колонок живёт в коде DAG-пакета, и тест сверяет его с `contracts/silver/*.json`, как `SILVER_KEYS`.
- Gold: `fct_orders` (1 строка на живой заказ, `updated_at`), `fct_order_items` (удалённые позиции остаются с `is_deleted`), `dim_products`, `dim_sellers` (живые строки silver), `dim_customers` (грейн `customer_unique_id`, производная); `dbt/models/marts/*.sql`.
- ADR-020: timestamp в silver с точностью до миллисекунды, decimal через `double` на проводе (`decimal.handling.mode=double`).

**Сделать.**
1. Проверить первым, только чтение, результат в описание коммита: для каждой из 7 таблиц отпечаток из шага 3 вычисляется в Postgres и в Trino на живых данных и совпадает (`make reconcile` до этого зелёный при остановленном реплее и догнавшем silver). Расхождение на колонке: стоп, нормализация этой колонки пересматривается (decimal через `double`, миллисекунды). Время Trino-запросов всех пар суммарно записано: больше 60 с означает перенос в DAG `reconcile_report` (W5-D10) и тот же код.
2. Тесты первыми, `tests/unit/test_reconcile.py`: колонки отпечатка равны колонкам контракта по именам и типам (7 таблиц); пара silver - gold ссылается на существующие колонки моделей (текст моделей `dbt/models/marts/*.sql`); `diff_keys` на словарях: ключ только слева, только справа, у обоих с разным отпечатком, одинаковые; `classify`: ключ расхождения есть в карантине даёт `quarantined`, есть в bronze без silver даёт `merge_pending`, нигде нет даёт `unknown`; `gold_at_rest` ложно, пока `max(fct_orders.updated_at)` меньше `max(silver.orders._updated_at)`; отпечаток строки с `null` и с пустой строкой различается; в запрос не попадает значение, не прошедшее проверку идентификатора (имена таблиц и колонок только из словарей модуля).
3. `airflow/dags/lakehouse/reconcile.py` без импорта `airflow`: `VALUE_COLUMNS`, `GOLD_PAIRS`, `row_hash_sql_postgres(table)`, `row_hash_sql_trino(table, schema)`, `fingerprint_sql_*` (count и `md5` от отсортированных `ключ:отпечаток`), `pairs_sql_*` (ключ, отпечаток для разбора), `diff_keys`, `classify`, `gold_at_rest`. Каноническая нормализация по W5-D9: `coalesce(cast(x as varchar), '\N')`, decimal с масштабом контракта, timestamp как миллисекунды (`date_trunc('milliseconds', ...)` в Postgres, `date_diff('millisecond', timestamp '1970-01-01 00:00:00', ...)` в Trino), разделитель `chr(31)`.
4. `dq_checks.py`: задача `reconcile_values` рядом с остальными. Внутри: `at_rest` (те же запросы, что в `silver_matches_postgres`); не в покое: печатает `in flight, no verdict`, шлёт `lakehouse.dq.reconcile_in_flight` 1, выходит; в покое: отпечатки по 7 таблицам Postgres и silver, по 4 парам silver - gold (если `gold_at_rest`), count для `dim_customers`; расхождение: `pairs_sql_*` только для этой таблицы, `diff_keys`, `classify`, первые 20 ключей и причина в лог; gauges: `lakehouse.dq.reconcile_rows{layer,table}`, `lakehouse.dq.reconcile_keys_missing{pair,table,side}`, `lakehouse.dq.reconcile_values_differing{pair,table}`, `lakehouse.dq.reconcile_in_flight` 0, `lakehouse.dq.reconcile_verdict_timestamp_seconds`; задача падает, если в покое есть расхождение, после отправки gauges. Строки `dq reconcile_<имя>=<значение>` в лог, как у остальных.
5. `observability/statsd/mapping.yml` уже сводит `lakehouse.dq.*` в `lakehouse_dq_$1` с `ttl: 45m`; новые имена отдельных правил не требуют. Проверить ряды (DoD).
6. Дашборд `pipeline-health.json`: таблица «Сверка» (`lakehouse_dq_reconcile_values_differing`, `lakehouse_dq_reconcile_keys_missing`, строки по слоям), stat «сверка в полёте» и «возраст вердикта» (`time() - lakehouse_dq_reconcile_verdict_timestamp_seconds`); `scripts/obs/check_dashboards.py` проходит.
7. Документация: OPERATIONS «Airflow» (задача, что значит красная `reconcile_values`, как читать причину) и «Observability» (ряды); `docs/runbooks/` не добавляется, красная задача разбирается по OPERATIONS; ADR-020 одной фразой про отпечаток по миллисекундам.

**Готово, когда.**
- `make test`, `make lint` зелёные; `uv run pytest tests/unit/test_reconcile.py -q`: `passed`.
- DAG виден: `$COMPOSE exec airflow-scheduler airflow dags list-import-errors` пусто; `airflow tasks list dq_checks` содержит `reconcile_values`.
- В покое после догона silver и dbt: `bash -c '. scripts/chaos/lib.sh && run_dag dq_checks w5-t04-$(date -u +%H%M%S)'` код 0; `task_log dq_checks <run_id> reconcile_values` содержит по строке на каждую из 7 таблиц и 4 пары silver - gold со значением `values_differing=0` и `keys_missing=0`.
- `curl -s 127.0.0.1:9090/api/v1/query --data-urlencode 'query=sum(lakehouse_dq_reconcile_values_differing)'` равно 0; `count(lakehouse_dq_reconcile_rows)` равно 19 (7 таблиц источника, 7 silver, 5 gold: `fct_orders`, `fct_order_items`, `dim_products`, `dim_sellers`, `dim_customers`).
- В полёте (сразу после `make replay-burst SECONDS=60`, до догона): задача `reconcile_values` зелёная, `in flight, no verdict` в логе, `lakehouse_dq_reconcile_in_flight` равно 1.
- Время запросов задачи записано в OPERATIONS; не больше 60 с либо задача перенесена по W5-D10.
- Тест на отказ: негативный путь (расхождение значений при равном количестве, причина расхождения) покрыт юнит-тестами `diff_keys` и `classify` на подмене клиентов Trino и Postgres. Живое расхождение не создаётся: запись в источник уходит в CDC и в silver.
- Дашборд: `uv run python scripts/obs/check_dashboards.py` печатает `panels ok: <n>`, код 0.

**Ловушки.**
- Сверка в полёте даёт ложные расхождения (OPERATIONS «Airflow», `at_rest=False`); без охраны задача красная на каждой порции.
- Gold отстаёт от silver на время `dbt_build` после `merge`; без `gold_at_rest` пара silver - gold красная после каждой порции.
- Нормализация: `decimal` приходит через `double` (ADR-020), timestamp усечён до миллисекунд; сравнение сырых текстов даст расхождения там, где данные равны. Шаг 1 это проверяет.
- `string_agg` и `array_join` от 107 тыс. пар `ключ:отпечаток` это 7-10 MB текста на запрос: память Trino на 95% лимита, поэтому при росте времени запроса вынос в отдельный DAG, а не рост лимита.
- Имена таблиц и колонок подставляются в SQL: только из словарей модуля (внешних значений нет), тест это проверяет.
- Gauges живут 45 минут (TTL): если сверка весь час «в полёте», ряды `reconcile_values_differing` пропадут; панель «возраст вердикта» нужна именно поэтому.
- `dim_customers` нельзя сверить по значениям: адрес берётся от последнего заказа (грейн `customer_unique_id`), сверяется число.

**Blast radius и пайплайн.** Чтение Trino и Postgres, отправка UDP. Таблицы, checkpoint, offsets не затронуты. DAG перечитывается за минуту; перезапуск Airflow не нужен. Порция реплея одна (около 12 виртуальных часов) для проверки «в полёте», с «ок».

**Не входит.** Сверка витрин по значениям (тест dbt), алерт на расхождение (красная задача уже поднимает `AirflowDagFailed`), host-версия отпечатка в `make reconcile` (раздел 7), метрика карантина.

**Итог 23.10.** `0134d57`. Отпечатки Postgres и Trino совпали на 7 таблицах и 4 парах silver-gold; в `dq_checks` 12 вердиктов за 7 с; 19 рядов `lakehouse_dq_reconcile_rows`; «в полёте» после порции 20 с: `in flight, no verdict`. Живое расхождение не создавалось (юнит-тесты `diff_keys`, `classify`, `compare`). Панели «Сверка» на `pipeline-health`.

### W5-T05a Политика обслуживания: ADR-025, задание `maintenance`, DAG

**Зачем.** Silver и gold копят снапшоты и файлы, bronze копит мелкие файлы и `metadata.json` (122 файла в MinIO против 101 записи в логе, 23.10), и ничего из этого не чистится. Карточка пишет политику и код; деструктивные запуски в W5-T05b.
**Оценка** 4 ч. **Зависит от:** W5-D11, W5-D12, W5-D13. **Область коммита:** `lake`.

**Вход.**
- Факты раздела 1 про файлы и снапшоты; `iceberg_maintenance.py:21-34`; `iceberg_demo.py` (`now_literal`: `CALL` принимает только литералы); `lakehouse/settings.py` (`SPARK_SILVER_ENV`, `spark_silver_environment`, `LAKE_WRITERS_POOL`); `silver_upsert.py:41-42` (`PARTITIONS`, `PROPERTIES`), `converge_layout`.
- Процедуры Iceberg (документация, context7 23.10): `expire_snapshots(table, older_than, retain_last, stream_results, ...)`, `remove_orphan_files(table, older_than, location, dry_run, ...)` (по умолчанию `older_than` 3 дня, `prefix_mismatch_mode=ERROR`, `equal_schemes` `s3a,s3n` равны `s3`), `rewrite_position_delete_files(table, options, where)` (опции `min-input-files` 5, `target-file-size-bytes` 64 MB), `rewrite_data_files(table, where, options)`. Свойства: `write.metadata.delete-after-commit.enabled` (по умолчанию false), `write.metadata.previous-versions-max` (100); при `false` файлы, выпавшие из лога, остаются навсегда и убираются только `remove_orphan_files`.
- Trino 483: `expire_snapshots(retention_threshold)` требует не меньше `iceberg.expire-snapshots.min-retention` (7d по умолчанию); в `remove_orphan_files` нет `dry_run`.
- ADR-005 (b): у Lakekeeper `push-s3-delete-disabled: false`; в песочнице `lake.demo` `expire_snapshots` через HadoopFileIO удалил 22 файла данных, 43 манифеста, 22 списка манифестов.
- ADR-021: `expire_snapshots` на bronze ломает чтение silver (apache/iceberg#18000).
- Не проверено: учитывает ли Lakekeeper (коммит и запись `metadata.json` делает он) `write.metadata.delete-after-commit.enabled`; проверяется шагом 1.

**Сделать.**
1. Проверить первым, на песочнице `lake.demo` (ошибка не касается bronze и silver):
   - свойство метаданных: на таблице `lake.demo.orders` (после `make iceberg-demo`, с «ок», он начинается с `drop table ... purge`) `alter table lake.demo.orders set tblproperties ('write.metadata.delete-after-commit.enabled' = 'true', 'write.metadata.previous-versions-max' = '5')`, затем 10 коммитов `insert`; сравнить число записей `select count(*) from demo."orders$metadata_log_entries"` (не больше 6) с числом файлов `metadata.json` в `warehouse/demo/orders-*` по `mc ls --recursive` (команда с `quay.io/minio/mc:RELEASE.2025-08-13T08-35-41Z` в сети `${COMPOSE_PROJECT_NAME}_lake`, как в шаге листинга 23.10). Равны: Lakekeeper удаляет метаданные, свойство работает. Файлов больше: свойство не работает, метаданные чистит только `remove_orphan_files` в `location` каталога `metadata` (шаг 5 остаётся без изменений, в ADR-025 записывается факт).
   - `remove_orphan_files` с `dry_run => true` на `lake.demo.orders` печатает список без ошибки префиксов; `prefix_mismatch_mode` оставить `ERROR`.
2. Тесты первыми, `tests/unit/test_maintenance.py` (чистые функции, без JVM): `expire_snapshots` для таблицы с префиксом `lake.bronze.` бросает ошибку с `ADR-021`; срок меньше 7 дней для silver и gold отклоняется; `remove_orphan_files` для bronze без `location`, заканчивающегося на `/metadata`, отклоняется; `older_than` формируется литералом `TIMESTAMP '...'` в UTC; в `lake.demo.` допустим любой срок; сводка результата процедуры печатается JSON-строкой одной строкой на вызов; ошибка на одной таблице не останавливает остальные, итоговый код 1.
3. `streaming/spark_jobs/maintenance.py` и пересылка аргументов в `streaming/run-job.sh` (`"${@:2}"` после имени задания): подкоманды `expire`, `rewrite-position-deletes`, `rewrite-data`, `orphans` с таблицами аргументами; `orphans` по умолчанию `--dry-run`, реальное удаление только флагом `--no-dry-run`; сессия через `build_session`, `spark.sql.session.timeZone=UTC`. Ограничения шага 2 в коде, не только в DAG.
4. `silver_upsert.py`: `PROPERTIES` получает для всех таблиц `write.metadata.delete-after-commit.enabled = true` (`converge_layout` применит на следующем прогоне, метаданные); тест в `test_silver_upsert.py` для `ensure_table`. `bronze_cdc_ingest.py`: тот же приём в `ensure_table` (`alter table ... set tblproperties`, метаданные, checkpoint не затрагивается), тест в `test_bronze_cdc_ingest.py`. Применение к живому bronze это пересоздание контейнера: в T05b.
5. `airflow/dags/lakehouse/settings.py`: `GOLD_WRITERS_POOL = "gold_writers"`, `MAINTENANCE_TABLES` (silver: восемь таблиц `SILVER_KEYS` плюс `orders_per_minute`), `RETENTION_DAYS = 7`; `sql.py`: `GOLD_BASE_TABLES` (`select table_name from lake.information_schema.tables where table_schema = 'gold' and table_type = 'BASE TABLE'`); `Makefile` `airflow-init` создаёт pool `gold_writers` 1 слот; `dbt_build.py`: `pool=GOLD_WRITERS_POOL` у задачи, тест в `test_dags.py` (pool задачи равен `gold_writers`).
6. `iceberg_maintenance.py` (daily, 03:30, `max_active_runs=1`): существующий `optimize` без изменений (Trino, `lake_writers`); затем `rewrite_position_deletes` для `silver.orders` (DockerOperator, `maintenance rewrite-position-deletes silver.orders`, `lake_writers`); затем `expire_silver` (`maintenance expire --days 7 <таблицы silver>`, `lake_writers`); `expire_gold` (список из `GOLD_BASE_TABLES`, `gold_writers`, `retries=2`, `retry_delay=5m`); `compact_bronze` (`maintenance rewrite-data lake.bronze.cdc_events --before-today`, `lake_writers`). Новый DAG `iceberg_orphans` (`@weekly`, воскресенье 04:00, создаётся на паузе общим правилом, `params={"dry_run": True}`): `maintenance orphans` по таблицам silver и gold, и `lake.bronze.cdc_events --location-suffix metadata`; реальное удаление только при `dry_run = false` в conf. Окружение контейнера через `spark_silver_environment`, `mem_limit="2g"`, `auto_remove="success"`, как у `merge`.
7. Документация: ADR-025 «Maintenance policy» (таблица слой / операция / срок, W5-D11, W5-D12, W5-D13, результат шага 1, bronze без сжатия хранилища: `rewrite_data_files` без `expire_snapshots` не освобождает место, старые файлы остаются в снапшотах), строка индекса; OPERATIONS: «Airflow» (таблица DAG, pool `gold_writers`) и новый раздел «Maintenance» (что делает, как запустить dry-run, как читать вывод), таблица «what deletes files» дополняется процедурами; `docs/agent-rules.md` и `AGENTS.md` не меняются (запреты уже перечислены).

**Готово, когда.**
- `make test`, `make lint`, `make test-spark` зелёные; новые тесты `passed`.
- `airflow dags list-import-errors` пусто; `airflow dags list` содержит `iceberg_orphans` в состоянии paused; `airflow pools list` содержит `gold_writers` с 1 слотом.
- Запрет в коде: `docker compose --profile core run --rm --no-deps spark-silver maintenance expire lake.bronze.cdc_events` (только после сборки образа, без запуска процедуры) завершается кодом 1 и строкой с `ADR-021` до создания сессии Spark; число снапшотов в `lake.bronze."cdc_events$snapshots"` до и после одно и то же.
- `maintenance orphans --dry-run silver.sellers` (чтение) печатает JSON-строку с `dry_run: true` и числом кандидатов; `select count(*) from silver.sellers` до и после равно.
- Результат шага 1 (метаданные убираются или нет) записан в ADR-025 числами.

**Ловушки.**
- `remove_orphan_files` с `older_than` короче 3 дней удаляет файлы незавершённых коммитов (стрим пишет данные до коммита): минимум 7 дней, и это проверяет код.
- Bronze в `location` данных нельзя: после `expire_snapshots` невозможного bronze никогда не пересоздаётся (Kafka хранит 24 ч, ADR-005 (b)); код отклоняет `orphans` bronze без `/metadata`.
- Метаданные Lakekeeper пишет сам: свойство удаления метаданных может не работать (шаг 1); без этого рост `metadata.json` bronze (около 4 300 в сутки при непрерывном потоке) идёт мимо политики.
- `expire_snapshots` и `dbt_build` на gold: `CREATE OR REPLACE` и очистка одной таблицы конфликтуют по коммиту; поэтому общий pool `gold_writers`, и `dbt_build` теперь занимает слот: два запуска dbt подряд ждут друг друга (`max_active_runs=1` и так).
- `rewrite_data_files` bronze создаёт снапшот `replace`; Iceberg streaming read silver такие пропускает (ADR-010: «a replace snapshot, which no stream reads»), но `bronze_has_new_snapshot` увидит новый id и запустит пустой merge и затем `dbt_build` по Asset. Это лишний прогон, не ошибка.
- `rewrite_data_files` в Spark по умолчанию собирает всё: условие `--before-today` ограничивает партиции прошлыми сутками, чтобы не конфликтовать с текущими коммитами стрима.
- Свойство `write.metadata.*` через `dbt-trino` для gold недоступно (в `properties` Trino его нет): метаданные gold убирает только `iceberg_orphans`.
- `MERGE` без изменённых строк коммитит снапшот `silver.orders` (HANDOFF): без `expire` их до 2016 за неделю.

**Blast radius и пайплайн.** Код и DAG, ничего не выполняется. `dbt_build` меняет pool: его запуск может ждать слот, если идёт maintenance gold. Запрет `expire_snapshots` bronze зашит в код. Все процедуры `expire_snapshots`, `remove_orphan_files`, `rewrite_data_files` bronze выполняются только в W5-T05b и каждая с «ок». Пересоздание `spark-bronze` для свойства метаданных только в T05b.

**Не входит.** Живые запуски (W5-T05b), снятие запрета на bronze (раздел 7), переход на S3FileIO.

**Итог 23.10.** `432190e` (код агентом-исполнителем, проверено основной сессией). `maintenance.py` с правилами до создания сессии Spark: `expire` на bronze отказывает с `ADR-021` (проверено: код 1, Spark не стартует), `orphans` по умолчанию dry run. Свойство метаданных проверено на `lake.demo.meta_probe`: Lakekeeper чистит `metadata.json` (6 записей, 6 файлов при `previous-versions-max` 5). Сухой прогон `orphans` по `bronze/metadata`: 21 кандидат (122 файла против 101 записи). Побочное: DAG `iceberg_maintenance` подхватил код раньше образа, просроченный запуск 03:30 успел выполнить `optimize` и упал на `rewrite_position_deletes` (нет `maintenance.py` в образе); запуск закрыт вручную, образ пересобран, DAG на паузе. Pool `gold_writers` создан.

### W5-T05b Первые живые запуски: компактация, `expire_snapshots`, `remove_orphan_files`, демо до и после

**Зачем.** Политика, которая ни разу не выполнялась, не доказана. Карточка идёт по лестнице W5-D13 с «ок» на каждую ступень и записывает числа до и после.
**Оценка** 3 ч. **Зависит от:** W5-T05a, W5-D13, W5-D14. **Область коммита:** `lake`.

**Вход.**
- База 23.10: bronze 527 файлов, 43 MB, 27 партиций, 148 снапшотов, 122 `metadata.json` в MinIO; `silver.orders` 28 файлов данных и 4 delete-файла, 25 снапшотов; `silver.sellers` 2 снапшота; `fct_orders` 29 снапшотов; `mart_daily_sales` 13 снапшотов и 22 файла. Числа в карточке переснимаются перед стартом.
- `make iceberg-demo`: компактация `lake.demo.orders` 21 файл в 1, `expire_snapshots` до одного снапшота (OPERATIONS «Daily commands», HANDOFF 08.10).
- Таблица «what deletes files» в OPERATIONS «Lakekeeper».

**Сделать.**
1. Перед стартом, только чтение: `bash -c '. scripts/chaos/lib.sh && bronze_caught_up && bronze_offsets_ok'`, `make verify-fast` при остановленном scheduler (или `reconcile`), числа базы записываются в отчёт сессии. Реплеер не играет.
2. Ступень 1, «ок»: `make iceberg-demo`; в вывод записаны файлы до и после компактации и число снапшотов до и после `expire_snapshots`; затем `docker compose --profile core run --rm --no-deps spark-silver maintenance expire --days 7 lake.demo.orders` проверяет сам вызов задания на песочнице: код 0 и JSON-строка с `deleted_data_files_count`.
3. Ступень 2, «ок»: bronze. (a) «ок» на пересоздание `spark-bronze` (свойство метаданных из W5-T05a): без реплея, после `bronze_caught_up`, `TRINO_XMX=2g make start`; в логе `Resuming at batch N`, `show tblproperties lake.bronze.cdc_events` в Trino содержит `write.metadata.delete-after-commit.enabled`. (b) «ок» на первую компактацию: вручную `docker compose --profile core run --rm --no-deps spark-silver maintenance rewrite-data lake.bronze.cdc_events --before-today` при паузе `silver_upsert`, дождавшемся конца запуске и остановленном scheduler (процедура HANDOFF для ручных записей); DAG `iceberg_maintenance` сам включается после этой ступени снятием паузы. До и после: `select count(*) from bronze."cdc_events$files" where partition.ingest_ts_day < current_date`, число снапшотов, `count(*)` и `max(kafka_offset)` по `bronze.cdc_events`.
4. Ступень 3, «ок»: `silver.sellers` `maintenance expire --days 7 silver.sellers` (2 снапшота: ничего не должно исчезнуть, а сам вызов проходит); затем остальные таблицы silver и `orders_per_minute`; затем gold. До и после по каждой таблице: `select count(*) from <t>`, число снапшотов, число файлов, живая проверка `reconcile`.
5. Ступень 4, «ок»: `airflow dags trigger iceberg_orphans` с `dry_run: true` (по умолчанию); список кандидатов разбирается: ожидаемые это файлы старше 7 дней, не входящие ни в один снапшот. Для bronze в списке только каталог `metadata`; 7 лишних parquet bronze (534 против 527, 23.10) процедура не смотрит и не удаляет, их судьба за владельцем (раздел 7). Любой кандидат моложе 7 дней: стоп.
6. Ступень 5, «ок»: реальный запуск `airflow dags trigger iceberg_orphans --conf '{"dry_run": false}'`; до и после число файлов в `mc ls --recursive` по каждой таблице, `count(*)`, `reconcile`.
7. Порция реплея с «ок» (`make replay-burst SECONDS=60`), затем штатный `silver_upsert`, за ним `dbt_build`, затем зелёный `reconcile_values` в `dq_checks`: подтверждение, что после обслуживания конвейер идёт.
8. Документация: OPERATIONS «Maintenance» с таблицей до и после (числа, дата), ADR-025 с фактическими числами, HANDOFF (потрачено реплея, что запущено), расписание: `iceberg_orphans` остаётся на паузе до решения владельца о недельном автозапуске (раздел 7).

**Готово, когда.**
- Bronze: число файлов партиций старше текущих суток после компактации не больше одной десятой числа до (ожидание: 527 до, около 27 после; записано число); `count(*)` и `max(kafka_offset)` по `bronze.cdc_events` равны до и после; `bronze_offsets_ok` код 0; `make verify-fast` (или `reconcile` при остановленном scheduler) `7 из 7 ok`.
- Для каждой таблицы silver и gold: `select count(*) from <t>` равно до и после `expire_snapshots`; `select count(*) from <t>."$snapshots" where committed_at < current_timestamp - interval '7' day` не больше 1 (единственный старый снапшот это текущий); `reconcile` ok.
- `iceberg_orphans` в режиме `dry_run`: файлов-кандидатов в `data/` bronze 0 (список в логе); реальный запуск: число `metadata.json` bronze в MinIO упало с 122 (23.10) и не больше `previous-versions-max + 1`, если свойство работает (шаг 1 W5-T05a), иначе число записано как факт.
- `make iceberg-demo` печатает падение файлов в 10 раз и больше (ожидание: 21 до, 1 после).
- `docker compose ps`: контейнеры без новых перезапусков кроме согласованного пересоздания `spark-bronze`; `silver_upsert` после снятия паузы зелёный, следующий `dq_checks` зелёный.
- Для спеки: время каждой процедуры записано в OPERATIONS.

**Ловушки.**
- `expire_snapshots` на Lakekeeper с HadoopFileIO удаляет файлы немедленно (ADR-005 (b)): отката нет, поэтому лестница.
- Лишний merge и `dbt_build` после компактации bronze (replace-снапшот) ожидаемы.
- Компактация bronze и ручной Spark при работающем scheduler это второй писатель; поэтому пауза `silver_upsert` и остановка scheduler по процедуре HANDOFF.
- Расписание хранения: `iceberg_orphans` включать нельзя, пока владелец не прочитал dry-run.
- Партиция bronze, куда ещё идёт стрим (текущие сутки), не компактируется: цифра «в 10 раз» только для партиций прошлых суток.
- Если нужно откатить свойство метаданных bronze: `alter table ... unset tblproperties` это DDL вне `ensure_table`, только с «ок».

**Blast radius и пайплайн.** Максимальный в неделе: `expire_snapshots` (silver, gold), `remove_orphan_files` (все слои, bronze только `metadata/`), `rewrite_data_files` (bronze), пересоздание `spark-bronze`, пауза и остановка Airflow на время ручной компактации. Bronze `expire_snapshots` не выполняется никогда (ADR-021). Checkpoint bronze и silver не удаляются, offsets Kafka не меняются. Каждая ступень лестницы с отдельным «ок»; порция реплея около 12 виртуальных часов из W5-D14.

**Не входит.** Снятие запрета на `expire_snapshots` bronze, автозапуск `iceberg_orphans`, переход на S3FileIO (раздел 7).

**Итог 23.10.** Не выполнена: ступени лестницы с `expire_snapshots`, компактацией bronze и реальным `remove_orphan_files` ждут «ок» владельца. Сделано только чтение и сухие прогоны (см. W5-T05a).

## 5. Порядок и коммиты

| # | Задача | Область | Зависит от |
|---|---|---|---|
| 1 | W5-T02 `ci.yml` | `ci` | W5-D6, W5-D7 |
| 2 | W5-T03 `smoke.yml` | `ci` | 1, W5-D8 |
| 3 | W5-T01a job, тесты, демо | `stream` | 1, W5-D1..D5, W5-D14 |
| 4 | W5-T01b сервис, метрики, живая проверка | `stream` | 3, коммиты W4, W5-D2 |
| 5 | W5-T04 сверка по значениям | `orchestrate` | коммиты W4-T03 и W4-T04, W5-D9, W5-D10 |
| 6 | W5-T05a политика и код обслуживания | `lake` | W5-D11..D13; параллельно 5 |
| 7 | W5-T05b живые запуски | `lake` | 6, 5 (для шага 7) |
| 8 | HANDOFF, итоги W5, потраченный бюджет реплея, `docker stats` | `docs` | все |

Сумма оценок 27 ч (4 + 3.5 + 4 + 3.5 + 5 + 4 + 3) против 19 ч роадмапа. Если неделя не влезает, режется в таком порядке: первой ступень 6 лестницы W5-T05b (реальный `remove_orphan_files` остаётся dry-run), затем панели дашборда в W5-T01b и W5-T04, затем повторный `bootstrap` в smoke; задачи W5-T01 (обязательна, ADR-017), W5-T02 и сверка по значениям не режутся. Если задача превысила оценку вдвое, остановиться и записать в `DECISIONS.md` вариант «упростить или вырезать».

## 6. Проверки для каждой задачи

- `make lint`, `make test`; для `stream` и `lake` ещё `make test-spark` (после W5-T02 с `SPARK_IMAGE`); для compose `$COMPOSE --profile '*' config -q` и `$COMPOSE --profile stateful config -q` без `core`; для DAG `airflow dags list-import-errors` пусто; для дашбордов `uv run python scripts/obs/check_dashboards.py`; для правил `make alerts-test` (не меняются).
- Первый тест на отказ: повтор заказа в окне, событие за watermark, мусорный конверт, `expire_snapshots` bronze, срок короче 7 дней, расхождение хэша строки при совпадающем количестве, пропуск Spark-теста в CI.
- Живой старт, а не только `config`: сервис `healthy`, target Prometheus `up`, ряды существуют, `find observability -type d -name '*.y*ml'` пусто.
- Влияние на checkpoint, таблицы Iceberg, offsets, реплей и DAG пишется явно; запись в bronze и silver, перезапуск `spark-bronze`, `expire_snapshots`, `remove_orphan_files`, порция реплея только с «ок».
- Полный `make verify` перед коммитом при остановленном scheduler (раздел 3).
- Ревью диффа по разделу «Плагины агента» в `docs/agent-rules.md`, коммит после «ок» владельца без строк атрибуции.

## 7. Замечено и не входит в W5

Кандидаты на решение владельца:

- Запрет `expire_snapshots` на bronze (ADR-021, apache/iceberg#18000 открыт). Пути, не проверенные: `async-micro-batch-planning-enabled`, сброс checkpoint silver после expire (blast radius). Пока bronze растёт снапшотами навсегда (148 за месяц, при непрерывном потоке 4 300 в сутки), компактация только уменьшает число файлов, не место.
- Автозапуск `iceberg_orphans` еженедельно: включить после чтения dry-run (W5-D13).
- Алерт на отсутствие батча у `orders_per_minute` (аналог `SparkNoBatch5m`): правила W4 фиксированы, новый алерт это решение; метрика `spark_streaming_last_batch_timestamp{query="orders_per_minute"}` уже есть.
- Отпечаток значений в `make reconcile` и `make verify` на хосте: сейчас значения сверяет только `dq_checks`; перенос даёт тот же контроль в chaos-сценариях и `bootstrap`, ценой второй реализации нормализации (контракты есть на хосте, в Airflow нет).
- `dbt build` в smoke (3-4 минуты), `workflow_dispatch` с параметром профиля.
- Повышение существующих action-ов: `actions/checkout` v4 против v7.0.1, `astral-sh/setup-uv` v6 против v10.3.2, `gitleaks/gitleaks-action` v2 против v3.0.0 (`gh api`, 23.10): после обновления major проверить Node-версию runner.
- S3FileIO и vended credentials в Lakekeeper (HANDOFF): после перехода от `push-s3-delete-disabled: false` зависит работа `expire_snapshots` и `remove_orphan_files` (ADR-005 (b)); политика ADR-025 пересматривается.
- `REPLAY_LATE_RATIO` остаётся для UPDATE `delivered`; позднее событие по `purchase_ts` в самом реплеере (отложенный INSERT с каскадом на следующие события заказа) нужен только если демо на лаб-топике признают недостаточным.
- Чтение гейта Spark Operate владельцем: текст `02-learning-gates.md:24` правится в W5-T01b по W5-D15.
- Лимит памяти нового сервиса и Trino на 95% лимита (W4 §7): ADR-024 записывает замер после первого дня работы.
