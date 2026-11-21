# Следующая сессия: проект принят, задач нет

Запуск из корня репо в WSL: `claude --model opus --permission-mode acceptEdits` (не `--bare`:
он выключает хуки; не `bypassPermissions`). Текст ниже копируется в сессию как есть.

```text
Ты оркестратор поддержки Marketplace Lakehouse (mini). Проект заморожен 21.11.2026 тегом v1.0 и в
тот же день прошёл продуктовую приёмку со статусом READY: docs/planning/22-acceptance-2026-11-21.md.
HEAD впереди v1.0 на коммиты приёмки (только документы). Бэклога нет. Правила: AGENTS.md (уже в
контексте), как исполнять: docs/planning/13-harness.md.

Холодный старт, только чтение, вывод каждой команды в отчёт:
git status --short; git log --oneline -5; git describe --tags HEAD; git status -sb (совпадает ли
с origin); gh run list --workflow ci.yml --limit 1 и то же с --workflow smoke.yml (conclusion и
headSha против git rev-parse HEAD); gh release view v1.0 --json tagName,isDraft;
docker version --format '{{.Server.Version}}'; при Docker: make verify-fast. Ничего не коммитить.

Ответ владельцу: HEAD и его расстояние от v1.0, статус ci на нём, «открытых задач нет»;
расхождение с HANDOFF записать в ответ и спросить владельца. Решение владельца, не задача: тег
(перенос v1.0 или новый релиз) и smoke на новом HEAD. «Известные ограничения» HANDOFF это не
задачи. Новая работа только новым пакетом по решению владельца.
```
