# CLAUDE.md

Версия 1.0, 19.09.2026. Правила для любого агента (Claude Code, Cursor) в этом репозитории.

## Что за проект

Marketplace Lakehouse (mini): учебная, но production-like Data Platform на ноутбуке 16 GB (WSL2 + Docker Compose). Реальный датасет Olist воспроизводится через PostgreSQL как OLTP-трафик, Debezium снимает CDC в Kafka, Spark Structured Streaming пишет bronze в Iceberg, второй Spark job (`AvailableNow` + `MERGE`) строит silver, dbt на Trino строит gold, Airflow 3 оркестрирует только batch, Prometheus + Grafana наблюдают. Код пишет AI, владелец проектирует, ревьюит, оперирует и объясняет.

## Порядок чтения перед любой задачей

1. `docs/HANDOFF.md`: текущее состояние и следующий шаг (появится после первой недели).
2. `docs/planning/00-mini-architecture-review.md`: архитектура и обоснования, приоритет над любыми другими описаниями.
3. `docs/planning/01-roadmap.md`: задачи `W<n>-T<nn>` с DoD.
4. `DECISIONS.md`: принятые ADR. Код, противоречащий ADR, не пишется, сначала новый ADR.
5. `OPERATIONS.md`: профили, порты, что можно запускать одновременно.

Сначала изучить архитектуру и существующий код, потом менять.

## Принципы

- Маленькие изменения: одна задача из роадмапа, один diff, один коммит. Не рефакторить соседний код «заодно».
- Не менять контракты (`contracts/`, схемы silver, имена топиков, имена таблиц, `.env` переменные) без явной причины и без записи в `DECISIONS.md`.
- Не переписывать работающий код без причины. Если что-то кажется некрасивым, но работает и покрыто тестом, оставить и предложить владельцу отдельно.
- KISS и YAGNI: ни абстракций «на будущее», ни сервисов «пригодится». Новый сервис только через ADR.
- Архитектурные решения принимает владелец. Агент предлагает варианты с trade-offs и ждёт выбора.
- Факты проверяются: версии, флаги, поведение инструментов сверяются с документацией (`WebFetch`) или запуском. Не угадывать.

## После каждого изменения

- Запустить соответствующие тесты: `make lint`, `make test` для Python; `dbt parse` и `dbt build --select <model>` для dbt; `docker compose config` для compose; `sqlfluff lint` для SQL.
- Если изменение касается compose, Dockerfile, SQL, конфигов: показать, как проверить вручную (команда и ожидаемый вывод).
- Проверить влияние на пайплайн: что будет с checkpoint, с существующими таблицами Iceberg, с offsets, с DAG. Если ответ «нужно удалить checkpoint или таблицу», написать это явно и ждать «ок».
- Обновить документацию, если изменилось поведение: `OPERATIONS.md`, `DECISIONS.md`, docstring контракта.

## Правила кода

- Python 3.12, `uv`, `ruff` (lint + format), типизация везде (`mypy`-совместимо), `pytest`. Конфиг только через env (`pydantic-settings`), без хардкода хостов и портов.
- Комментарии только там, где имя не объясняет поведение (ключ dedup, условие MERGE, семантика watermark). Без комментариев-паддинга, без пересказа кода. Docstring короткий и только на публичных функциях с неочевидной семантикой.
- SQL: `sqlfluff`, lowercase ключевые слова, CTE вместо вложенных подзапросов, в dbt только `{{ ref() }}` и `{{ source() }}`.
- Spark: PySpark, `local[2]`, явные схемы из `contracts/`, никаких `inferSchema`.
- Тесты вместе с кодом в одном коммите. Тест проверяет поведение, включая отказы (дубли, late, невалидный JSON).

## Правила compose и инфраструктуры

Каждый сервис в `docker/compose.yaml` имеет: `profiles`, `healthcheck` с реальной проверкой, `restart: unless-stopped`, `logging: *logging`, `deploy.resources.limits.memory`, для JVM явный `-Xmx` через env, `depends_on` с `condition: service_healthy`, порты только на `127.0.0.1`. Образы закреплены тегом, не `latest`.

## Правила безопасности

- Секреты только в `.env` (генерируется `make secrets`, в `.gitignore`). В репо только `.env.example` с плейсхолдерами. В коде, compose, workflows только `${VAR}`.
- Ни один порт на `0.0.0.0`.
- Перед коммитом: `gitleaks`, нет `.env`, нет данных из `data/raw`, нет имён владельца и работодателей. Репозиторий публичный.
- Действия из списка blast radius требуют явного «ок» владельца, молчание не «ок»: `docker compose down -v`, `make nuke`, удаление checkpoint или volume, `DROP`, `DELETE`, `TRUNCATE`, `expire_snapshots`, `remove_orphan_files`, изменение retention Kafka, `rm -rf`.

## Правила коммитов

- Формат: `<область>: <что сделано>`. Области: `oltp`, `cdc`, `stream`, `lake`, `dbt`, `orchestrate`, `obs`, `ci`, `docs`, `infra`.
- Коммит только после явного «ок» владельца на diff. Никогда `git push`, `git commit --amend` чужого коммита, `git reset --hard`.

## Understanding-гейты

Владелец закрывает каждый этап гейтами Read / Explain / Operate / Modify (`docs/planning/02-learning-gates.md`). Агент не делает Modify-гейт за владельца: если просят «сделай» то, что помечено как гейт владельца, агент называет файл и функцию, даёт подсказку или тест, но не готовый код. На «объясни» агент объясняет полностью, с trade-offs, и задаёт 2-3 встречных вопроса для проверки понимания.

## Языки и стиль

- Общение с владельцем и `docs/planning/` на русском. Код, README, `ARCHITECTURE.md`, `OPERATIONS.md`, `DECISIONS.md`, `LEARNING.md`, docstring, имена файлов, сервисов, топиков, таблиц на английском.
- Без длинного тире (em dash, en dash) нигде: запятая, двоеточие, точка или слово «это».
- Без канцелярита и без формулировок «важно отметить», «данный», «в рамках». Коротко, как staff-инженер коллеге.
- В репо нет имён владельца, названий работодателей, упоминаний, что текст писал AI.

## Плагины агента

Стоят на уровне проекта (`.claude/settings.json`), обоснование и полный список триггеров в `docs/planning/03-agent-tooling.md`. Правила этого файла выше любого skill.

- Версия, флаг, конфиг или API Spark, Iceberg, Kafka, Debezium, Trino, dbt, Airflow, MinIO: сначала `context7` (документация нужной версии), не память.
- Задача с выбором реализации: `superpowers:brainstorming`, затем `superpowers:writing-plans`. Спеки и планы в `docs/planning/` на русском, не в `docs/superpowers/`, и без коммита до «ок».
- Разобраться в существующем коде или спроектировать изменение: агенты `feature-dev:code-explorer`, `feature-dev:code-architect`.
- Баг или падение job: `superpowers:systematic-debugging` до правок. Код с тестами: `superpowers:test-driven-development`, первым тест на отказ.
- Дифф готов: `/code-review`, для Python и Spark ещё `pr-review-toolkit:silent-failure-hunter` и `pr-test-analyzer`, перед коммитом `/security-review`. Перед «готово»: `superpowers:verification-before-completion`.
- Конец недели или правила разошлись с практикой: `/revise-claude-md`, правки только с «ок».
- Из `superpowers` не применяются: коммит после каждого шага, worktrees, `finishing-a-development-branch` (merge, push, PR).

## Когда не уверен

- Проверить документацию или запустить и посмотреть вывод.
- Если проверить нельзя сейчас: написать «не уверен, предлагаю эксперимент: <команда, что ожидаем>» и остановиться.
- Если решение меняет архитектуру: остановиться, предложить варианты, ждать выбора владельца.
