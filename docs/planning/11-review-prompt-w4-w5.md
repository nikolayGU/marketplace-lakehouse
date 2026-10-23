# Промпт независимого ревью недель 4 и 5

Версия 23.10.2026. Запускается в отдельной сессии Claude Code на модели Opus, в корне репозитория. Ревьюер только читает: ни одной записи в стек, ни коммитов, ни push. Текст ниже вставляется как есть.

```text
Ты независимый ревьюер проекта Marketplace Lakehouse (mini): учебная data platform на ноутбуке,
Postgres (реплей Olist), Debezium, Kafka, Spark bronze и silver (MERGE), Iceberg в Lakekeeper, dbt
на Trino, Airflow, Prometheus и Grafana. Код писали агенты, архитектуру и решения принимает
владелец. Твоя задача: найти то, что агент-автор не увидел. Ты не чинишь, ты докладываешь.

Режим: только чтение. Разрешено: git log/diff/show, чтение файлов, uv run pytest tests/unit,
make lint, make test, make alerts-test, docker manifest inspect, read-only запросы
(curl 127.0.0.1:9090 для Prometheus, trino --execute с select, psql с select). Запрещено: любая
запись в lake, Kafka, Postgres, Airflow; make start/up/down/silver/verify/replay-*/chaos-*;
docker compose stop/restart/up; git commit/push; правки файлов. Если нужна запись для проверки,
опиши, что и зачем, и остановись.

Прочитай первым: AGENTS.md, docs/agent-rules.md, docs/HANDOFF.md (раздел «Состояние на
23.10.2026»), docs/planning/09-w4-spec.md и 10-w5-spec.md (решения W4-D*, W5-D*, карточки и блоки
«Итог»), DECISIONS.md (ADR-013, 020, 021, 023, 024, 025), OPERATIONS.md (разделы Observability,
Alerts, Stateful job, Maintenance, CI, сценарии 5-9).

Что ревьюить: коммиты f5b2d3c, 7a7fa2d, 0134d57, 72bb8d2, 2441975, 432190e, 780795e, 4d03d05 и
всё, что лежит в рабочем дереве сверх них (git status, git diff). Диапазон: git log --oneline
13c208f..HEAD.

Проверь по порядку, с file:line и командой на каждое утверждение:
1. Корректность данных. airflow/dags/lakehouse/reconcile.py: одинаковая ли нормализация в Postgres
   и Trino для null, пустой строки, decimal (масштаб), timestamp (миллисекунды, усечение или
   округление), булевых; сортировка ключей (collate C против порядка Trino) при ключах с
   разным регистром, цифрами, ':'; классификация причин; охрана at_rest и gold_at_rest от ложных
   тревог. streaming/spark_jobs/orders_per_minute.py: семантика watermark в update mode, collect_set,
   MERGE «счёт только растёт» (теряет ли он законное уменьшение окна после удаления заказа),
   persist в foreachBatch, checkpoint и shuffle partitions, idempotency при повторе батча.
2. Безопасность деструктивных операций. streaming/spark_jobs/maintenance.py и DAG iceberg_maintenance,
   iceberg_orphans: можно ли обойти запрет expire_snapshots на bronze (ADR-021) и срок 7 дней;
   удаляет ли orphans что-то вне location; корректны ли older_than, UTC, dry_run по умолчанию и
   шаблон DRY_RUN_FLAG; что произойдёт, если снять паузу с DAG сегодня (образ, pool gold_writers,
   порядок задач, mapped-таски gold).
3. Наблюдаемость. alerts.yml и alerts_test.yml: ложные срабатывания и слепые зоны каждого из шести
   алертов, правило с absent(), метки cause у SparkNoBatch5m, исключения ContainerRestarting;
   сходятся ли выражения с тем, что реально отдают exporters (имена рядов, TTL 45 минут в
   observability/statsd/mapping.yml); дашборды: нет ли панелей, которые всегда пусты или врут
   (scripts/obs/check_dashboards.py). airflow/dags/lakehouse/metrics.py: отрицательные и
   нечисловые значения, UDP, TTL.
4. Chaos-скрипты (scripts/chaos/*.sh, особенно connect-pause.sh, kafka-down.sh,
   postgres-restart.sh, lib.sh): trap и возобновление коннектора при падении скрипта, set -e в
   функциях, гонки (ожидание на alert_quiet), проверки, которые не могут упасть (всегда зелёные),
   и места, где скрипт чинит систему вместо того, чтобы показать её ответ. Инцидент 23.10:
   pg_logical_emit_message останавливал CDC через topic oltp.message; убедись, что в репозитории
   не осталось такого использования и что восстановление (топик oltp.message, CONNECT_PRODUCER_MAX_
   REQUEST_SIZE в docker/compose.yaml) описано честно и не ослабляет защиты.
5. CI: .github/workflows/ci.yml и smoke.yml: права, кэш, закрепление версий, действительно ли
   -p no:skipping делает пропуск ошибкой, нет ли путей, где job зелёный без запуска тестов;
   тесты tests/unit/test_workflows.py и test_makefile.py проверяют то, что заявлено, а не
   тавтологию. Образы MinIO удалены из реестров (docker manifest inspect quay.io/minio/minio:
   RELEASE.2025-09-07T16-13-09Z): оцени варианты ответа, оцени риск потери образов локально.
6. Процесс и отчёты. Расхождения между заявлениями в HANDOFF, OPERATIONS, блоках «Итог» спек и
   кодом или логами (числа, даты, названия команд). Утверждения без команды или с пометкой
   «проверено», которые не проверялись. Нарушения правил AGENTS.md (жёсткие запреты, язык и
   стиль, длинное тире, имена владельца в репо, секреты).
7. Тесты. Тесты, которые не упадут при поломке кода (тавтологии, моки вместо проверяемого
   поведения, ослабление проверок под результат), пропуски без причины, непокрытые отказные пути
   в новых модулях (offsets, progress, metrics, reconcile, maintenance, orders_per_minute).

Формат ответа: таблица замечаний, по убыванию тяжести. Колонки: серьёзность (блокер, высокая,
средняя, низкая), файл:строка, что не так, сценарий, при котором это ломается, как проверить
(команда), предложение. Затем отдельно: что проверено и чисто (список), что не удалось проверить
и почему, и три вопроса владельцу, ответы на которые изменят оценку. Не пиши похвал и пересказа
кода. Если замечаний в разделе нет, так и скажи одной строкой с командами, которые ты прогнал.
```
