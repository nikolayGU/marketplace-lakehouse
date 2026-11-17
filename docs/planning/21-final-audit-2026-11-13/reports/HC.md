# HC. Соответствие документации Claude Code (конспект отчёта claude-code-guide, 13.11.2026)

Локальный CLI 2.1.306. Страницы: code.claude.com/docs/en/{hooks,hooks-guide,settings,permissions,sub-agents,skills,memory,sandboxing,headless,tools-reference}.md

## Статус конфигурации
- Все события хуков и matcher в .claude/settings.json документированы: PreToolUse (matcher по имени инструмента), SubagentStop (matcher по agent_type), Stop и SessionStart без matcher.
- PostToolUse matcher SubagentHandback: инструмент существует только в auto mode (v2.1.271+). Вне auto mode вердикт приходит через SubagentStop (last_assistant_message). Регламент описывает один путь.
- onFailure: "block" документирован (v2.1.295+): без него сбой хука (код не 0 и не 2, таймаут, мусор) пропускает действие. Стоит. timeout не задан: по умолчанию 600 с.
- guard: deny через stderr + exit 2, ask через hookSpecificOutput.permissionDecision: актуально. stop_gate {"decision":"block"}: актуально. session_context additionalContext: актуально.
- Поля agent_type, last_assistant_message, stop_hook_active, tool_input.message/command/file_path документированы.
- Frontmatter ролей (name, description, disallowedTools, model, maxTurns, effort, color) и skill (argument-hint, disable-model-invocation, $ARGUMENTS) документированы. Проектный Explore переопределяет встроенный: документировано.
- `mcp__*` (глоб) в disallowedTools у Explore: не документировано.
- .claude/settings.local.json не в git (.gitignore:20): правильно. В нём мёртвые allow-правила с `\\(` и путями scratchpad прошлой сессии.
- CLAUDE.md с @AGENTS.md: документировано; импорт не уменьшает контекст; рекомендация до 200 строк на файл.
- 13-harness.md:315-317 «документация версии 2.1.306»: это версия CLI, не документации; «подхватывается без перезапуска» верно с исключениями (первый файл в новом каталоге agents, --add-dir).

## Что можно отдать permissions
Порядок: хук exit 2 раньше правил; затем deny, ask, allow. Bash-правила «не граница безопасности» (документация).
- Да (deny): Read/Edit секретов; Edit(./.verify-stamp|.check-stamp|.review-stamp); Edit(./.claude/hooks/**), Edit(./.claude/settings.json). Edit-правила покрывают Write и редиректы, но не cp, sed -i, python.
- Да (ask): Edit(./AGENTS.md), Edit(./CLAUDE.md), Edit(./.claude/agents/**), Edit(./.claude/skills/**), Edit(./docs/agent-rules.md).
- Частично: Bash(git push *) ask, Bash(git push --force*) deny (git -C обходит); Bash(make replay-*), Bash(make silver) ask; Bash(docker compose down *) ask.
- Нет: гейт git commit (зависит от отметок), SQL DROP/TRUNCATE/DELETE внутри psql/trino, слот репликации, stamp CLI, make check с флагами: только хук.

## Что стоит взять
- sandbox (bubblewrap, socat; docker compose в excludedCommands): слой ОС; меняет settings, только владелец. Для закрытого проекта: не обязательно.
- поле `if` у хука: фильтр best-effort, логику guard в него не переносить.
- headless claude -p: --bare выключает хуки; ask без человека равен отказу.

## Находки
- HC-01 [высокая по отчёту; по факту средняя] нет timeout у guard: зависший хук держит каждый Bash/Write/Edit до 600 с. Правка: "timeout": 30 у guard (settings, патч владельцу).
- HC-02 [средняя] два пути записи отметки ревью (SubagentHandback только в auto mode, иначе SubagentStop); отказ классификатора в auto mode даёт отсутствие отметки. Правка: описать в регламенте.
- HC-03 [средняя] 13-harness.md:315-317 формулировка про версию и перезапуск: переписать с датой и исключениями.
- HC-04 [средняя] защита отметок и файлов харнесса только хуком: добавить нативные permissions.deny/ask (список выше). Settings, патч владельцу.
- HC-05 [низкая] мёртвые allow в .claude/settings.local.json:4-41: удалить (владелец, /permissions).
- HC-06 [низкая] mcp__* в disallowedTools Explore не подтверждён: проверить на живом Explore или перечислить явно.
- HC-07 [низкая] на будущее: в CI не --bare; ask в headless это отказ. Строка в регламент.

Не проверено: поведение guard при сбое вне try на 2.1.306; глоб mcp__*; классификатор auto mode.
