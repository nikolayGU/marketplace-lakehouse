# Следующая сессия: сутки W3-T05b и спека недели 4

Обновлено 18.10.2026. Текст ниже копируется в новую сессию как есть.

```text
Ты агент в репозитории Marketplace Lakehouse (mini). Неделя 3 закрыта 18.10.2026, кроме гейтов
владельца W3-T07 и суток наблюдения W3-T05b. Airflow теперь писатель silver.

Прочитай первым, целиком:
1. AGENTS.md и docs/agent-rules.md.
2. docs/HANDOFF.md: раздел «Состояние на 18.10.2026, конец недели 3».
3. docs/planning/01-roadmap.md: неделя 4 и список «Спека недели 4 обязана закрыть».

Первый шаг, только чтение:
- W3-T05b B6: по четырём DAG `airflow dags list-runs <dag> --state failed` в контейнере
  scheduler (ожидаются только красные запуски из HANDOFF: dq_checks 16:15 и dq-rest-1 до правки,
  chaos 9), `docker stats` по airflow и trino; память Trino против лимита 3.5 GiB;
- heartbeat Debezium: confirmed_flush_lsn против pg_current_wal_lsn() после суток простоя.
Затем стоп и отчёт.

Дальше по слову владельца: спека W4 по docs/planning/06-spec-standard.md в
docs/planning/09-w4-spec.md, решения владельца отдельной таблицей, без кода до «ок».

Без отдельного «ок» не делай: make silver, ручной make verify при запущенном scheduler (сначала
остановить scheduler), любой расход реплея, правки .env, хуков и .claude/settings.json, push,
всё из запретов AGENTS.md.
```
