# 02. Learning gates

Версия 1.0, 19.09.2026. Гейт закрывает этап: без него этап не считается сделанным, даже если код работает. Read и Explain делаются без AI (AI потом проверяет ответы). Operate делается руками в терминале. Modify: владелец ставит задачу AI, проверяет результат и объясняет, почему изменение сработало.

Ответы записываются в `LEARNING.md` (публично, по-английски, коротко) и при желании подробнее в `docs/interview-notes.md`.

---

## Kafka (неделя 1)

| Тип | Задание | Как проверить |
|---|---|---|
| READ | Найти в compose и в скрипте регистрации коннектора: число партиций, retention, `KAFKA_HEAP_OPTS`, где хранятся `connect-offsets`, `connect-configs`, `connect-status`. Объяснить, почему Spark не появляется в `kafka-consumer-groups.sh --list` | Показать команды и вывод |
| EXPLAIN | Что такое партиция, зачем key=PK, что гарантирует ordering, где at-least-once, что такое offset и consumer group, чем replay отличается от reprocess, что происходит при retention меньше простоя consumer | Рассказать за 5 минут без подсказок, AI задаёт 5 уточняющих вопросов |
| OPERATE | Остановить kafka-connect на 5 минут, посмотреть `pg_replication_slots`, запустить, убедиться через offsets, что события догнаны и не потеряны. Прочитать топик с `--from-beginning`, найти один UPDATE и объяснить before/after | Скриншот или вывод в заметках |
| MODIFY | Поставить AI задачу: увеличить число партиций `oltp.shop.orders` с 3 до 6 без потери данных и объяснить, почему ordering по ключу после этого меняется для новых событий. Второй вариант: добавить таблицу `reviews` в `table.include.list` и убедиться, что snapshot для неё сработал | Diff прочитан, эффект проверен |

## Spark Structured Streaming (неделя 2)

| Тип | Задание | Как проверить |
|---|---|---|
| READ | Найти в `bronze_cdc_ingest`: trigger, checkpoint location, `startingOffsets`, `maxOffsetsPerTrigger`, как парсится envelope. Найти в `silver_upsert`: `AvailableNow`, `foreachBatch`, ключ dedup, условие MERGE | Показать строки |
| EXPLAIN | Micro-batch модель; что лежит в checkpoint (offsets, commits, state); чем `AvailableNow` отличается от `ProcessingTime` и `Once`; почему MERGE делается в `foreachBatch`, а не в streaming sink; что такое watermark и зачем state; что происходит при kill посреди батча; что такое shuffle и где он в silver job | Рассказать, AI задаёт вопросы про restart |
| OPERATE | Убить spark-bronze посреди батча (`make chaos-spark-kill`), поднять, проверить SQL-запросом, есть ли дубли в bronze, и найти в `snapshots.summary` epochId; доказать отсутствие дублей в silver. Открыть Spark UI, найти stage с shuffle в silver job, назвать число partitions. После W5-T01: прогнать late event внутри и за пределами watermark и показать разницу в `silver.orders_per_minute` | Вывод SQL, скриншот UI |
| MODIFY | Поставить AI задачу: уменьшить `maxOffsetsPerTrigger` вдвое и trigger до 10 с; предсказать, что случится с batch duration и числом файлов в bronze, потом проверить по метрикам и `files` metadata table | Предсказание vs факт записаны |

## Iceberg (неделя 2)

| Тип | Задание | Как проверить |
|---|---|---|
| READ | Найти свойства таблиц `silver.orders` (format-version, write.delete.mode, partition spec), путь к metadata в MinIO, содержимое `snapshots`, `files`, `history` metadata tables | Показать |
| EXPLAIN | Что такое snapshot и manifest; как работает time travel; чем CoW отличается от MoR и почему orders на MoR; почему hidden partitioning лучше директорий Hive; что такое small files problem и как её лечит compaction; почему Iceberg + checkpoint дают идемпотентность записи | Рассказать |
| OPERATE | `SELECT ... FOR VERSION AS OF` в Trino до и после chaos; `rollback_to_snapshot`; посчитать число файлов до и после `rewrite_data_files` | Вывод |
| MODIFY | Самому (не AI) добавить колонку `sales_channel` в `silver.orders` и контракт, после `REPLAY_SCHEMA_EVOLUTION_AT` убедиться, что старые строки NULL, новые заполнены, а bronze не менялся | Diff руками, проверка SQL |

## dbt (неделя 3)

| Тип | Задание | Как проверить |
|---|---|---|
| READ | Найти `sources.yml`, incremental-конфиг `mart_daily_sales`, макрос, тест `relationships` | Показать |
| EXPLAIN | Зачем staging views, чем `merge` отличается от `delete+insert` и `append`, что такое `is_incremental()`, как dbt строит lineage, почему тесты в CI работают только как `parse`, а `build` нужен Trino | Рассказать |
| OPERATE | Сломать тест (`make chaos-break-dbt-test`), увидеть в Airflow, починить, перезапустить | Лог |
| MODIFY | Поставить AI задачу: добавить `mart_category_returns` с тестом и docs, проверить, что incremental не пересчитал историю | Diff, `dbt run` дважды |

## Airflow (неделя 3)

| Тип | Задание | Как проверить |
|---|---|---|
| READ | Найти в DAG: schedule, Asset-зависимость `dbt_build` от `silver_upsert`, retries, `catchup`, как DockerOperator запускает spark-silver | Показать |
| EXPLAIN | Почему стрим не оборачивается в DAG; что такое Asset-driven scheduling в Airflow 3; зачем отдельный dag-processor; что случится, если `silver_upsert` идёт дольше 5 минут (`max_active_runs`) | Рассказать |
| OPERATE | Остановить scheduler на 20 минут, запустить, объяснить, какие запуски произошли и почему | Лог |
| MODIFY | Поставить AI задачу: перевести `dq_checks` на запуск по Asset после `silver_upsert` вместо расписания | Diff, граф в UI |

## Observability (неделя 4)

| Тип | Задание | Как проверить |
|---|---|---|
| READ | Найти, откуда берётся каждая панель «Pipeline health»: exporter, метрика, PromQL | Таблица panel → metric |
| EXPLAIN | Чем lag отличается от freshness; почему kafka-exporter не видит Spark; что такое gauge/counter/histogram; почему алерт на «нет батча 5 минут» лучше, чем на «контейнер жив» | Рассказать |
| OPERATE | Выполнить chaos 6 (коннектор мёртв) и chaos 8 (dbt test), показать, какие алерты сработали и через сколько | Скриншоты |
| MODIFY | Поставить AI задачу: добавить метрику `quarantine_rows_total` и алерт на неё, проверить chaos 7 | Алерт срабатывает |

## Итоговый гейт (неделя 6)

Мок-собеседование с AI, 45 минут: system design «спроектируй CDC-пайплайн из OLTP в lakehouse с exactly-once семантикой на выходе», затем 20 быстрых вопросов по Kafka, Spark, Iceberg, DQ. Критерий: ответы без подглядывания в репо, каждый ответ с примером из проекта.
