# 03. Плагины агента: ТЗ

Версия 1.0, 22.09.2026. Какие плагины Claude Code из `claude-plugins-official` стоят в проекте, зачем, и когда агент их вызывает. `CLAUDE.md` имеет приоритет над любым плагином.

## Задача

Агенту нужны пять способностей, которых нет в голом Claude Code или которые там слабее:

1. Ревью диффа до коммита: баги, проглоченные исключения (критично для streaming jobs), качество тестов, типы.
2. Брейншторм и планирование задачи `W<n>-T<nn>` до кода: варианты с trade-offs, план, который владелец утверждает.
3. Проверка актуальности: версии и поведение Spark, Iceberg, Kafka, Debezium, Trino, dbt, Airflow 3 сверяются с документацией нужной версии, а не с памятью модели (правило «факты проверяются» из `CLAUDE.md`).
4. Картина архитектуры: разбор существующего кода и проектирование изменения в его рамках.
5. Актуальность самих инструкций: `CLAUDE.md` и `HANDOFF.md` не расходятся с реальностью.

## Ограничения

- Нельзя ломать правила `CLAUDE.md`: коммит только после «ок», никогда `git push`, одна задача один дифф, архитектуру решает владелец, Modify-гейты владелец делает сам.
- Контекст дорогой: плагин с большим always-on (описания skills в каждом запросе) или с hook на каждый ответ ставится только если окупается.
- Без внешних аккаунтов и токенов, без SaaS, которому уходит код (репо публичный, но `.env` и данные нет).
- Плагины ставятся на уровне проекта (`.claude/settings.json`), чтобы набор был виден в репо и одинаков на любой машине.

## Решение: что ставим

| Плагин | Способность | Что даёт | Always-on, токенов |
|---|---|---|---|
| `context7` | 3 | MCP с документацией конкретной версии библиотеки. Без ключа, remote | 0 |
| `superpowers` | 2, 1 | `brainstorming`, `writing-plans`, `systematic-debugging`, `test-driven-development`, `verification-before-completion`, `requesting-code-review` | ~700 |
| `feature-dev` | 4 | Агенты `code-explorer` и `code-architect`, команда `/feature-dev` | ~250 |
| `pr-review-toolkit` | 1 | `/review-pr`, агенты `silent-failure-hunter`, `pr-test-analyzer`, `type-design-analyzer`, `code-reviewer` | ~2000 |
| `claude-md-management` | 5 | `/revise-claude-md`, skill аудита `CLAUDE.md` | ~180 |

Встроенное, ставить не нужно: `/code-review` (ревью диффа), `/security-review` (перед коммитом), агенты `Plan` и `Explore`.

## Что не ставим и почему

| Плагин | Почему нет |
|---|---|
| `code-review` (плагин) | Дублирует встроенный `/code-review` |
| `security-guidance` | LLM-ревью диффа на каждый Stop: платим на каждом ответе. Секреты уже ловит `gitleaks` в pre-commit и CI, плюс ручной `/security-review` перед коммитом |
| `mattpocock-skills` | Пересекается с `superpowers` (grilling, spec, tdd), always-on ~1600 |
| `pyright-lsp` | Нужен бинарь `pyright` (Node), в проекте уже `mypy` как гейт. Вернуться, если захочется диагностики сразу после правки |
| `data-engineering` / `data` (Astronomer) | Always-on ~6000 и hooks на SessionStart/Stop, заточен под Astro. Пересмотреть на неделе 3 (W3-T04): полезны `authoring-dags`, `testing-dags`, `debugging-dags` |
| `grafana-mcp` | Нужен живой Grafana. Пересмотреть на неделе 4 (W4-T01) |
| `streaming-skills-plugin` (Confluent) | Про Confluent Cloud, Flink, Java-клиенты. Schema Registry отложен ADR-012. Документацию Kafka даёт `context7` |
| `altimate-code` | Делегирует dbt во внешний CLI-агент, лишний слой |
| `commit-commands` | Умеет push и PR, `CLAUDE.md` это запрещает |
| `github` MCP | Нужен токен, `gh` CLI хватает |

## Когда агент вызывает (триггеры)

| Ситуация | Что вызывать |
|---|---|
| Новая задача из роадмапа, есть выбор реализации | `superpowers:brainstorming`, варианты владельцу, ждать выбора. Спеки и планы кладутся в `docs/planning/`, на русском, не в `docs/superpowers/` |
| Задача больше одного файла | `superpowers:writing-plans`, план показать до кода |
| Нужна картина существующего кода | агент `feature-dev:code-explorer`, для проектирования `feature-dev:code-architect` |
| Упоминается версия, флаг, конфиг, API Spark/Iceberg/Kafka/Debezium/Trino/dbt/Airflow/MinIO | `context7`: `resolve-library-id`, потом документация нужной версии. Не нашлось, тогда WebFetch официальной доки |
| Баг, падение job, странное поведение пайплайна | `superpowers:systematic-debugging` до любых правок |
| Пишется код с тестами | `superpowers:test-driven-development`: тест на отказ (дубль, late, невалидный JSON) первым |
| Перед словами «готово» | `superpowers:verification-before-completion` плюс проверки из раздела «После каждого изменения» `CLAUDE.md` |
| Дифф готов, до просьбы об «ок» на коммит | `/code-review`; для Spark/streaming/Python кода ещё `pr-review-toolkit:silent-failure-hunter` и `pr-test-analyzer`; перед коммитом `/security-review` |
| Конец недели, обновление `HANDOFF.md`, правила разошлись с практикой | `/revise-claude-md` (правки `CLAUDE.md` только с «ок» владельца) |

## Конфликты с `CLAUDE.md` и как они решены

- `superpowers` предлагает коммитить после каждого шага, worktrees и завершение ветки с merge/push. В проекте: коммит только после «ок», без push, без worktrees, работа в `main` маленькими коммитами.
- `superpowers:brainstorming` пишет спеки в `docs/superpowers/specs/`. В проекте: `docs/planning/`, на русском.
- Ни один skill не делает Modify-гейт за владельца.

## Где зашито

- `.claude/settings.json`: `enabledPlugins` и маркетплейс, ставится командой `claude plugin install <name>@claude-plugins-official --scope project`.
- `CLAUDE.md`, раздел «Плагины агента»: короткая таблица триггеров со ссылкой сюда.
- Память агента: ссылка на этот файл.

## Проверка

```bash
claude plugin list          # пять плагинов, enabled, scope project
cat .claude/settings.json   # enabledPlugins содержит все пять
```

В новой сессии: `/review-pr`, `/feature-dev`, `/revise-claude-md` видны в меню, в `/mcp` есть `context7` в статусе connected.
