# Следующая сессия: неделя 4, наблюдаемость и отказы

Обновлено 18.10.2026. Текст ниже копируется в новую сессию как есть.

```text
Ты агент в репозитории Marketplace Lakehouse (mini). Неделя 3 закрыта 18.10.2026, кроме гейтов
владельца W3-T07. Airflow писатель silver: все четыре DAG сняты с паузы. Цель сессии: неделя 4
по спеке docs/planning/09-w4-spec.md (черновик 0.1, решения W4-D1..D12 ждут «ок» владельца).

Прочитай первым, целиком:
1. AGENTS.md и docs/agent-rules.md.
2. docs/HANDOFF.md: раздел «Состояние на 18.10.2026, конец недели 3» вместе с «После закрытия
   недели, 18.10».
3. docs/planning/09-w4-spec.md; docs/planning/06-spec-standard.md; неделя 4 в 01-roadmap.md.

Первый шаг, только чтение (начни с make report):
- W3-T05b B6, сутки наблюдения: в контейнере scheduler `airflow dags list-runs <dag> --state
  failed` по silver_upsert, dbt_build, dq_checks, iceberg_maintenance. Ожидаются только красные
  запуски из HANDOFF (dq_checks 16:15 и dq-rest-1 до правки, два chaos9-*-broken); любой другой
  красный: стоп и разбор. `docker stats` по airflow, trino (D20, было 2.91 GiB под нагрузкой),
  minio.
- Слот Debezium после суток простоя: удержание
  `pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)` и `active` (было 24 MB).
- Аудит спеки W4 против кода: что изменилось с 18.10, какие пункты «не проверено» из спеки можно
  проверить только чтением (теги образов `docker manifest inspect`, entrypoint Connect 3.5,
  `import statsd` в образе Airflow) и их вывод.
- План первой задачи W4 после «ок» на решения: шаги, файлы, проверки, что требует «ок».
Затем стоп и отчёт. Правки только после «ок» владельца на таблицу решений W4 и на план.

Риск, открытый до W4-D12: `make silver` и chaos-скрипты connect-restart, duplicates, late,
poison-event зовут spark-silver без проверки scheduler. Пока Airflow писатель silver, их не
запускать; любая ручная проверка silver только через остановку scheduler, как в HANDOFF.

Без отдельного «ок» не делай: make silver, make verify при запущенном scheduler, любой расход
реплея (бюджет W4 по W4-D10 ещё не принят), правки .env, хуков и .claude/settings.json, настроек
Postgres и коннектора, push, всё из запретов AGENTS.md.

Отчёт: каждое утверждение командой и выводом; «не проверено» с командой; факт, вывод и гипотеза
раздельно; git status --short и git diff --stat.
```
