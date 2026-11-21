# Следующая сессия: приёмка 21.11, три решения владельца

Запуск из корня репо в WSL: `claude --model opus --permission-mode acceptEdits` (не `--bare`:
он выключает хуки; не `bypassPermissions`). Текст ниже копируется в сессию как есть.

```text
Ты оркестратор поддержки Marketplace Lakehouse (mini). Проект заморожен 21.11.2026 тегом v1.0;
после него прошла продуктовая приёмка: docs/planning/22-acceptance-2026-11-21.md. HEAD впереди
v1.0 на коммиты приёмки (только документы). Правила: AGENTS.md (уже в контексте), как исполнять:
docs/planning/13-harness.md.

Холодный старт, только чтение, вывод каждой команды в отчёт:
git status --short; git log --oneline -4; git describe --tags HEAD; git status -sb (совпадает ли
с origin); gh run list --workflow ci.yml --limit 1 и то же с --workflow smoke.yml (conclusion и
headSha против git rev-parse HEAD); gh release view v1.0 --json tagName,isDraft;
docker version --format '{{.Server.Version}}'; при Docker: make verify-fast. Ничего не коммитить.

Первый вопрос владельцу, три решения из «Итога» пакета 22, каждое по «ок» на точный текст:
1. Текст ADR-029 (две замены в DECISIONS.md). После «ок»: правка, make check, ревью, коммит,
   повторная проверка приёмки и итоговый статус READY или NOT READY.
2. Живой прогон остановки и старта всего стенда (OPERATIONS.md, «Daily commands»); после него
   убрать пункт из docs/evidence.md, «Not proven yet».
3. Тег: перенос v1.0 на новый HEAD или новый релиз; smoke на новом HEAD.

«Известные ограничения» HANDOFF это не задачи. Другая работа только новым пакетом по решению
владельца.
```
