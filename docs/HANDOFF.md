# HANDOFF

Обновляется в конце каждой недели. Читать первым в каждой сессии.

## Состояние на 19.09.2026

- Неделя 0: планирование закрыто, код не написан.
- Скелет репо: README, ARCHITECTURE, OPERATIONS, DECISIONS, LEARNING, CLAUDE.md, compose-скелет
  с профилями и лимитами, Makefile, CI-скелет, контракт envelope, конфиг коннектора.
- Ничего не запускалось. Теги образов не проверены pull'ом.

## Следующий шаг

W1-T01 и W1-T02 из `docs/planning/01-roadmap.md`: `uv`, `ruff`, pre-commit, затем
`docker compose pull` для профиля `core` и фиксация реальных тегов (особенно MinIO, ADR-004).

## Правки после внешнего ревью 19.09

- Bronze объявлен at-least-once по контракту; отсутствие дублей гарантирует silver; идемпотентность Iceberg-sink по epochId проверяется экспериментом (chaos 1), результат в ADR-007.
- Stateful job `orders_per_minute` обязателен (W5-T01, ADR-017).
- Каталог: JDBC в `postgres-meta` для недели 1, Lakekeeper как should-have с лимитом 3 часа (W2-T09, ADR-005).
- Superset в optional; витрины через Grafana + Trino datasource.
- Обязательных chaos-сценариев 8, два optional.

## Открытые вопросы

См. `docs/planning/00-mini-architecture-review.md` §10.
