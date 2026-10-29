# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

## Только для Claude Code

- Плагины и триггеры: `docs/planning/03-agent-tooling.md`, раздел «Плагины агента» в `docs/agent-rules.md`; версии и флаги инструментов сначала через `context7`, не по памяти.
- Модели и роли: основная сессия Opus; поиск `Explore` (Haiku), анализ `scout` (Sonnet, effort medium), код `implementer` (Sonnet), ревью `reviewer` (Opus). Сканеры только читают; `model` при вызове не переопределять. Цикл задачи: `/task <ID карточки | фраза>`.
- `superpowers`: спеки и планы в `docs/planning/` на русском; без коммита после каждого шага, без worktrees, `finishing-a-development-branch`, `subagent-driven-development`, `executing-plans` и `requesting-code-review` (цикл задают роли и `/task`).
- Хуки и разрешения в `.claude/settings.json` меняются только с «ок» владельца.

## Точечные проверки

- Один тест: `uv run pytest tests/unit/test_dags.py::<имя> -q`.
- Spark-тесты на хосте пропускаются (нет JVM); один файл в образе:
  `make test-spark SPARK_TESTS=test_silver_upsert.py`.
- Одна модель dbt: `cd dbt && uv run dbt build --profiles-dir . --target dev --select <модель>`
  (нужен `make start`, пишет в `lake.gold`).
- Корни импорта как в образах (`pythonpath` в `pyproject.toml`): `replayer` из `oltp/`,
  `spark_jobs` из `streaming/`, `lakehouse` из `airflow/dags/`.

## Где что

- Поток данных и откуда берётся exactly-once: `ARCHITECTURE.md`.
- `make verify`: `scripts/verify.sh`; `reconcile`: `scripts/chaos/lib.sh` и `scripts/reconcile_sql.py`.
