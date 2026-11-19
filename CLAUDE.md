# CLAUDE.md

@AGENTS.md

## Плагины

- `context7` (плагин или коннектор claude.ai): версии и флаги стека сначала через него.
- `superpowers`: выбор реализации `brainstorming`, план в `docs/planning/` по-русски; баг
  `systematic-debugging`; код `test-driven-development`; перед «готово»
  `verification-before-completion`.
- Не применяются: коммит после шага, worktrees, `finishing-a-development-branch`,
  `subagent-driven-development`, `executing-plans`, `requesting-code-review`.

## Точечные проверки

- Тест: `uv run pytest tests/unit/test_dags.py::<имя> -q`.
- Spark только в образе: `make test-spark SPARK_TESTS=test_silver_upsert.py`.
- dbt: `cd dbt && uv run dbt build --profiles-dir . --target dev --select <модель>` (нужен
  `make start`, пишет в `lake.gold`).
- Корни импорта (`pyproject.toml`): `replayer` в `oltp/`, `spark_jobs` в `streaming/`,
  `lakehouse` в `airflow/dags/`.

## Где что

Поток и exactly-once: `ARCHITECTURE.md`; verify: `scripts/verify.sh`; `reconcile`:
`scripts/chaos/lib.sh`, `scripts/reconcile_sql.py`.
