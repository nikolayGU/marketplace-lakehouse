# Следующая сессия: закрытие W5 (T05b), починка пути с чистого клона, затем W6

Обновлено 23.10.2026. Текст ниже копируется в новую сессию как есть.

```text
Ты агент в репозитории Marketplace Lakehouse (mini). Недели 4 и 5 выполнены почти целиком:
W4-T01..T06 и W5-T01..T05a закоммичены (см. docs/HANDOFF.md, раздел «Состояние на 23.10.2026»),
CI на GitHub зелёный (4 job: lint-and-test, hadolint, spark-tests без skipped, airflow-image).
Владелец делегировал исполнение («делай все сам»), но деструктивные ступени и решения по
инфраструктуре идут с отдельным «ок» (запреты AGENTS.md).

Прочитай первым, целиком:
1. AGENTS.md и docs/agent-rules.md.
2. docs/HANDOFF.md: раздел «Состояние на 23.10.2026» и «Открытые вопросы».
3. docs/planning/10-w5-spec.md: карточка W5-T05b и раздел 7; docs/planning/09-w4-spec.md: итоги
   карточек W4-T03..T06b.
4. DECISIONS.md: ADR-023, ADR-024, ADR-025; OPERATIONS.md: «Maintenance», «Stateful job», сценарии 5-9.

Первый шаг, только чтение: make report; docker ps; make verify-fast (silver должен равняться
Postgres); curl -s 127.0.0.1:9090/api/v1/alerts (не должно гореть ничего, кроме остатка
ContainerRestarting в первые 15 минут после рестартов); gh run list --limit 5.

Что делать, по порядку:
1. Путь с чистого клона сломан: образы MinIO (quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z и
   quay.io/minio/mc:RELEASE.2025-08-13T08-35-41Z) удалены из реестров (docker manifest inspect:
   no such manifest), workflow smoke.yml упал на их загрузке (run 40003292011). Локально образы в
   кэше и в /home/gusev/lakehouse-image-backup/minio-images.tar; docker image prune не делать.
   Подготовь варианты с ценой ошибки (сборка MinIO из исходников по тегу релиза в docker/minio/
   Dockerfile, закреплённый по sha; замена S3-слоя) и ADR, реализуй выбранное после «ок» владельца,
   затем gh workflow run smoke.yml --ref main и добейся зелёного.
2. W5-T05b, лестница деструктивных процедур из W5-D13 (ADR-025), каждая ступень с отдельным «ок»
   владельца и числами до и после: песочница lake.demo, silver.sellers expire, остальные silver и
   gold, dry run orphans по всем таблицам, реальный orphans. Перед снятием паузы с
   iceberg_maintenance: образ lakehouse/spark:dev уже содержит maintenance.py (собран 23.10);
   запуск за 03:30 выполнит expire_silver, expire_gold и compact_bronze, поэтому паузу снимать
   только после ступеней 2-3. iceberg_orphans остаётся на паузе до решения владельца.
3. Гейты владельца (ты не отвечаешь за них, напомни): W4-T07 (Operate chaos 6 и 9 с временами из
   OPERATIONS; Modify: quarantine_rows_total и алерт), W3-T07 (dbt и Airflow), Spark Operate после
   W5-T01 (make watermark-demo и watermark-live), W1-T08, W2-T08.
4. Открытые находки, которые просят решения (HANDOFF, «Открытые вопросы»): heartbeat.action.query
   против алерта по удержанному WAL; SparkNoBatch5m не ловит цикл рестартов драйвера при остановке
   Kafka; dq_checks краснеет «silver differs at rest», когда Kafka или коннектор стоят; сон ноутбука
   (сутки B6 не засчитаны).
5. Затем W6 по docs/planning/01-roadmap.md: README как карта и ARCHITECTURE.md с диаграммой, дашборд
   по gold (W6-T01), interview-notes. Спека W6 по docs/planning/06-spec-standard.md.

Без отдельного «ок» не делай: blast radius из AGENTS.md (expire_snapshots, remove_orphan_files,
rewrite_data_files bronze, DROP, DELETE, TRUNCATE, rm -rf, удаление checkpoint, тома, retention
Kafka, pg_replication_slot_advance), настройки Postgres и коннектора Debezium, правки .env, хуков
и .claude/settings.json, реплей сверх бюджета (W4-D10 5 дней и W5-D14 3 дня; на 23.10 вместе потрачено 3 д 18 ч,
`virtual_now` 2026-07-16 21:33, осталось 22 293 события), push (разрешён владельцем 23.10 для рабочих коммитов, не для force).
Не используй pg_logical_emit_message в сценариях: Debezium публикует эти записи в topic
oltp.message и на 1 MB останавливает CDC (инцидент 23.10, ADR-023).

Перед каждым коммитом: поставить silver_upsert на паузу, дождаться конца запусков, остановить
scheduler, make verify, запустить scheduler, снять паузу (скрипт: см. HANDOFF). Отметка verify
привязана к дереву: после make verify ничего не править до коммитов.

Отчёт: каждое утверждение командой и выводом; «не проверено» с командой; факт, вывод и гипотеза
раздельно; git status --short и git diff --stat.
```
