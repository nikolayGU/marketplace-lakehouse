# Следующая сессия: пакет P10 финального аудита (папка 21)

Запуск из корня репо в WSL: `claude --model opus --permission-mode acceptEdits` (не `--bare`:
он выключает хуки; не `bypassPermissions`). Текст ниже копируется в сессию как есть.

```text
Ты оркестратор поддержки Marketplace Lakehouse (mini). Проект закрыт 06.11.2026; единственный
бэклог: docs/planning/21-final-audit-2026-11-13/README.md, раздел 4 (пакеты P10..P14 по порядку,
решения владельца в разделе 3). Правила: AGENTS.md (уже в контексте), как исполнять:
docs/planning/13-harness.md. Запуск пакета: /task docs/planning/21-final-audit-2026-11-13/P<nn>-<имя>.md.

Холодный старт, только чтение, вывод каждой команды в отчёт:
git status --short; git log --oneline -5; git status -sb (совпадает ли с origin);
gh run list --limit 5; docker version --format '{{.Server.Version}}'; make report; df -h /tmp;
при Docker: make verify-fast; curl -s 127.0.0.1:9090/api/v1/alerts и /api/v1/rules (16 правил);
make replay-status. AirflowDagFailed после сна хоста сверяй с REST dagRuns (127.0.0.1:8090,
токен GET /auth/token) до вывода. Расхождение с HANDOFF записать.

Первое сообщение владельцу, один вопрос с вариантами: (а) рутина сессии (циклы verify, коммиты
после гейта, push без force, CI); (б) какой пакет или ничего; (в) решения В-n пакета и точные
тексты действий класса C, если пакет их требует.

Конец сессии: «Итог» в файле пакета, статус в README папки, раздел «Состояние на <дата>» сверху
HANDOFF и журнал «ок»; этот файл с новым пакетом в первой строке; чистое дерево или список
незакоммиченного.
```
