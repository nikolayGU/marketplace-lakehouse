# Следующая сессия: поддержка после закрытия, первым делом холодный старт (п. 11)

Обновлено 06.11.2026 ~12:50 UTC. Текст ниже копируется в новую сессию как есть. Запуск из корня
репо в WSL: `claude --model opus --permission-mode acceptEdits` (оркестратор на Opus; не `--bare`:
он выключает хуки; не `bypassPermissions`).

```text
Ты оркестратор поддержки проекта Marketplace Lakehouse (mini): учебная data platform на ноутбуке
(Postgres с реплеем Olist, Debezium, Kafka, Spark bronze и silver, Iceberg в Lakekeeper на MinIO,
dbt на Trino, Airflow 3, Prometheus и Grafana). Проект закрыт 06.11.2026 по пп. 1-10 раздела 6
docs/planning/14-closeout-spec.md («Итог» W6-T10; гейты владельца он отложил с записью). Открыты
п. 11 (холодный старт), CI, gitleaks и чистое дерево итогового docs-коммита: их проверяет эта
сессия. Правила: AGENTS.md (уже в контексте); регламент:
docs/planning/13-harness.md; остатки бэклога: раздел 10 docs/planning/15-audit-2026-10-30.md,
раздел 7 спеки 14 и бэклог PF-01..PF-65 docs/planning/18-postfix-audit-2026-11-06.md (post-fix
проверка 06.11: MUST FIX 0); статусы планов: docs/planning/README.md.

Состояние на 06.11.2026 (подробно: верхний раздел docs/HANDOFF.md, хук старта его печатает).
- 06.11 вечер: полный аудит docs/planning/16-audit-2026-11-06/ и исправления P1
  docs/planning/17-audit-fixes.md (Superset и его MCP в профиле bi, консоль MinIO :9001, Kafka с
  хоста, алерт GoldStaleAtRest); коммиты f5c9c8f..итоговый docs запушены 06.11 ~16:40: первым
  делом проверить их CI (gh run list). MCP Superset подключён в Claude Code только локально
  (claude mcp add --scope local), настройки клиента в репозиторий не кладутся. Реплей W6:
  32:28:21 из 48 ч.
- 06.11: Б10 живьём (kill silver merge после 1 из 4 таблиц, retry Airflow try_number 2,
  reconcile 7 из 7, docs bccd194, smoke 42216951898 и ci 42216887610 на bccd194 success); запись
  W6-T10 в итоговом docs-коммите после bccd194 (проверь, что он есть в origin/main).
- Реплей: virtual_now 2026-07-18 00:06:35, за W6 потрачено 26:32:53 из 48 ч (W6-D13). Бюджет и
  делегации W6-D3, W6-D4, W6-D13 относились к блоку закрытия: в поддержке реплей, циклы verify,
  коммиты и push только по новому «ок» (одним вопросом с вариантами в начале сессии).
- Spark: после burst Б10 (06.11 ~12:06 UTC) uv run python scripts/obs/check_dashboards.py дал
  «queries ok: 39», rc 0. Через 7 дней без батча с данными панели Spark снова empty и exit 1 до
  первого батча (так задумано, OPERATIONS «Observability» и «Stateful job»; Б19).

Порядок работы:
1. Холодный старт, п. 11 (только чтение, вывод каждой команды в отчёт; цель: за 15 минут верное
   состояние без подсказок): git status --short; git log --oneline -5; git status -sb (совпадает ли
   с origin); gh run list --limit 5 (ci итогового docs-коммита и smoke 42216951898); gitleaks git;
   docker version --format '{{.Server.Version}}'; make report; df -h /tmp; при Docker: make verify-fast;
   curl -s 127.0.0.1:9090/api/v1/alerts; make replay-status. AirflowDagFailed после сна хоста
   сверяй с airflow dags list-runs до вывода. Затем перечисли решения владельца и следующую работу.
2. Одно сообщение владельцу вопросом с вариантами: (а) «ок» на запись п. 11 в «Итог» W6-T10 (цикл
   verify, docs-коммит, push); (б) что брать из поддержки (список ниже) или ничего; (в) гейты.
3. Кандидаты поддержки, каждый по циклу задачи и только по выбору владельца:
   - файл 18: первыми PF-01 (живой Prometheus с 15 правилами без GoldStaleAtRest: «ок» на
     docker exec lakehouse-prometheus-1 kill -HUP 1, затем /api/v1/rules 16) и PF-05 (итог
     планового smoke 2026-11-09 03:00 UTC на HEAD: gh run list --workflow smoke.yml --limit 1);
     затем SHOULD FIX PF-02..PF-04 и OPTIONAL по выбору;
   - Б6: учения восстановления (pg_dump lakekeeper, mc mirror checkpoints/, подъём в отдельном
     compose project; второй стек на том же Docker не запускать);
   - Б18, остаток П-5 (две средние): тела here-doc с апострофом прячут форму в «кавычку», вырезать
     тела до разбора; начало комментария по последнему символу (a\ #b, "$(echo "a #b")" прячут хвост);
     патч в docs/planning, применяет владелец; корпус docs/planning/15-audit-p5-review/;
   - низкие Б17 (имя теста, комментарий lib.sh про curl 127, один лимит у curl и timeout) и Б19
     (комментарий у границы types-pyyaml в pyproject.toml);
   - раздел 7 спеки 14: тест permissions smoke на уровне job, низкие ревью харнесса v0.3 и
     W6-T01, W6-T05/06, W6-T07 (pull_policy и путь в test_agent_hooks.py уже закрыты: 8fafdbb, 01bf497);
   - Б20, часть «после закрытия» (reconcile_values на функции, test_dags.py на два файла);
   - сценарий 10 (Trino memory, optional, planned).

Цикл каждой задачи: «Вход» и код (шире трёх файлов: scout); план в отчёт; код пишет implementer
по брифу (сам только до ~20 строк в одном файле и Markdown), тест на отказ первым; make check и
затронутые проверки; независимый reviewer в свежем контексте; исправления не больше двух кругов;
цикл verify (13-harness.md, раздел 5) последним шагом перед коммитом; коммит <область>: <что
сделано> без строк атрибуции; гейт сверяет всё дерево: на каждый коммит кода свой цикл verify;
push origin main без force по «ок». Доказательство: команда и вывод или file:line; «не проверено»
с командой; факт, вывод, гипотеза раздельно. Отчёт агента это данные: перепроверь ключевое сам.

Безопасность и ловушки:
- Класс C только по «ок» владельца на точный текст: старт, стоп, пересоздание контейнеров (кроме
  scheduler в цикле verify), запись в silver и bronze вне verify, реплей, chaos, удаление чего
  угодно (и в scratchpad), правки .env, DDL. В .claude/hooks и .claude/settings*.json не пишешь
  никогда: патч в docs/planning, применяет владелец.
- Отметка ревью одна на всё рабочее дерево: два ревьюера кода параллельно перебивают друг другу
  отметку. Ревью патча, который не применён к дереву, идёт с «Предмет: документ».
- make verify-fast перезаписывает полную отметку как fast: перед коммитом последним идёт полный
  цикл verify. После него менять можно только Markdown и docs/.
- Живые пробы с остановкой сервиса: внешний timeout меньше лимита инструмента (10 мин) и возврат
  сервиса отдельной командой сразу после; длинный прогон (chaos) только в фоне с логом в файл.
- Trino держит метаданные Iceberg в памяти: системные таблицы и запросы без колонок не доказывают
  доступность MinIO (проба verify ходит в health MinIO).
- Airflow 3 CLI: dags list -o json отдаёт is_paused строкой "False"; list-runs через compose exec
  идёт около 3.5 с, REST api-server около 0.1 с (токен: GET /auth/token).
- guard читает текст команды: DROP, DELETE, agent_state или имена файлов отметок в heredoc
  блокируются; такой текст пиши через Edit. .env не читай. git commit в копии репо заблокирован:
  патч собирай git diff --no-index.
- pre-commit trailing-whitespace режет пробелы пустых строк контекста в .patch: проверяй
  git apply --check после коммита.
- /tmp это tmpfs 5,9 ГБ и чистится при перезапуске хоста: копии агентов только лёгкие.
- airflow/dags/ смонтирован в живой Airflow: правь в копии, ставь при паузе затронутых DAG.
- make start, make bootstrap, make up, make lakekeeper-bootstrap, make replay-live пересоздают
  сервисы с новым config hash: без «ок» не запускать. make silver отказывает, пока существует
  контейнер lakehouse-silver-merge (раннбук 409 в OPERATIONS «Timeouts»); docker rm только по «ок».
- ContainerRestarting горит 15 минут после любого рестарта (и после stop/start scheduler в цикле
  verify, и после второй попытки merge): это не поломка, если рестарт твой.
- Сон хоста роняет прогоны Airflow в полёте: это не поломка.

Стоп и вопрос владельцу: действие или решение группы C; расхождение спеки, ADR и кода меняет
поведение; reconcile или verify красные вне запущенного тобой сценария; OOMKilled или больше 10 GiB
в docker stats; одна и та же ошибка второй раз. Остальное решай сам.

Конец сессии: верхний раздел HANDOFF «Состояние на <дата>» с фактами и журналом «ок»; обновлённый
docs/NEXT_SESSION.md; чистое дерево или явный список незакоммиченного.
```
