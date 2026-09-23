# HANDOFF

Обновляется в конце каждой недели или смыслового блока. Читать первым в каждой сессии.

## Состояние на 23.09.2026

Неделя 1 закрыта по коду, неделя 2 начата.

| Задача | Состояние |
|---|---|
| W1-T01..T06 | сделано раньше: скелет, core-профиль, OLTP-схема и реплеер, Debezium, bronze |
| W1-T07 Trino | сделано: профиль `query`, catalog `lake` через JDBC, `select source_table, count(*) from lake.bronze.cdc_events group by 1` работает |
| W1-T08 гейт Kafka | **за владельцем**, `LEARNING.md` пуст |
| W2-T01 контракты silver | сделано: `contracts/silver/*.json`, фикстуры envelope, тесты против `001_schema.sql`, ADR-020 |
| W2-T02 `silver_upsert` | сделано: `make silver`, первый прогон 23.09: все 7 таблиц silver совпадают с Postgres по `count(*)`, суммам и датам; повторный прогон ничего не меняет. ADR-021 |

Что сейчас живёт в стеке:

- Запущены `core` без реплеера и `trino`. Реплеер остановлен на виртуальном времени 2026-06-27, в `replay.schedule` осталось ~49.7k событий.
- Bronze: 518 461 событие, почти всё это incremental snapshot от 22.09 (ADR-019).
- Silver: 7 таблиц `lake.silver.*`, format v2, copy-on-write, без партиций. Checkpoint `s3a://lakehouse/checkpoints/silver_upsert`.
- Каталог `iceberg_catalog` переведён Trino в JDBC schema V1 (колонка `iceberg_type`), см. ADR-005.

Проверки: `make lint`, `make test` (хост без Java, Spark-тесты пропускаются), `make test-spark` (Spark-тесты в образе, включая MERGE на локальном Iceberg).

## Следующий шаг

1. **W2-T03** свойства таблиц: `silver.orders` на merge-on-read (`write.merge.mode`, `write.update.mode`, `write.delete.mode`) и партиция `months(order_purchase_timestamp)`, остальные остаются CoW. Таблицы уже существуют, поэтому через `ALTER TABLE ... SET TBLPROPERTIES` и `ADD PARTITION FIELD` (метаданные, без переписывания и без blast radius), плюс те же свойства в `ensure_table` для чистого старта. Замерить и закрыть ADR-010.
2. **W2-T04** `silver.quarantine`: сейчас невалидные события только считаются в логе (`invalid ... events skipped`, `no contract`). Писать их `MERGE`-ем по `(topic, kafka_partition, kafka_offset)`, чтобы повтор батча не дублировал карантин. Причины: unparsed envelope, unknown op, null key, null в NOT NULL колонке, нет контракта.
3. **W2-T05** chaos 1-4 как `make chaos-*`, после них W2-T06 iceberg demo.
4. Чтобы увидеть живой поток: `make replay-start` на хосте, потом `make silver` несколько раз.

## Решения, которые ждут владельца

- ADR-020 (контракты silver, `timestamp_ntz` с точностью до миллисекунды) записан как proposed.
- ADR-019, дополнение: incremental snapshot не может исправить строку silver, у которой уже есть streamed LSN. Для восстановления после реального провала в Kafka нужна позиция snapshot-чтения в bronze (`source.sequence`), это изменение контракта bronze.
- ADR-021: apache/iceberg#18000. `expire_snapshots` на bronze (W5-T05) сломает AvailableNow-чтение silver. Решить до W5.
- В Docker остались два анонимных тома от одноразовых контейнеров исследования (не проектные данные). Удаление тома в списке blast radius, поэтому не удалены: `docker volume rm 24fddd5f9b3da04014cbf027b837239460bb1cd4c0ac4b425f927bd7f71f88e2 179eb31fb74b947039c3e78e8d9cecf3380fbe6ee0b32db240ee1ee52333924d`.

## Открытые вопросы

См. `docs/planning/00-mini-architecture-review.md` §10.
