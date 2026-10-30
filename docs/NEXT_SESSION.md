# Следующая сессия: закрытие проекта после бэклога аудита 30.10

Обновлено 30.10.2026 вечером, конец сессии W6-T03 и задач аудита Б5, Б7, Б8, Б9. Текст ниже
копируется в новую сессию как есть. Запуск из корня репо в WSL:
`claude --model opus --permission-mode acceptEdits` (оркестратор на Opus; не `--bare`: он выключает
хуки; не `bypassPermissions`).

```text
Ты оркестратор закрытия проекта Marketplace Lakehouse (mini): учебная data platform на ноутбуке
(Postgres с реплеем Olist, Debezium, Kafka, Spark bronze и silver, Iceberg в Lakekeeper на MinIO,
dbt на Trino, Airflow 3, Prometheus и Grafana). Веди работу до доказуемого конца сам; владелец
решает группу C, даёт «ок» на опасные действия и делает то, что требует человека. Правила: AGENTS.md
(уже в контексте); регламент: docs/planning/13-harness.md; бэклог W6: docs/planning/14-closeout-spec.md;
находки и бэклог аудита: docs/planning/15-audit-2026-10-30.md (раздел 10); статусы всех планов:
docs/planning/README.md.

Состояние на 30.10.2026 вечер (подробно: верхний раздел docs/HANDOFF.md, хук старта его печатает).
- Закрыто 30.10 с «Итогом»: W6-T03 (149e10d, interview-notes по источникам, ссылки на якоря),
  Б9 (f02a8fd, проба Trino в verify), Б5 (45c5b88, сверка GMV по дням с Postgres в dq_checks,
  первый живой прогон зелёный), Б7 (8fafdbb, образы по digest, actions по SHA, pull_policy: never),
  Б8 (f648243, тесты на мутации: dbt staging, мягкое удаление, 7 контрактов, два запроса в Iceberg
  sink; make dbt-build PASS=79 WARN=4 ERROR=0).
  Dry run orphans silver.orders: 0 кандидатов, пункт «Not proven yet» закрыт.
- Раньше закрыты: аудит 30.10 (P0 и P1 нет), Б1, Б2, Б3; W6-T00, W5-T05b, W6-T01, W6-T02,
  W6-T05..T08, W6-T11; решения W6-D1..D17 приняты.
- Ждёт владельца: применить патч П-3 docs/planning/15-audit-p3-harness.patch (stop_gate после
  Markdown, поиск стека по метке compose, роль reviewer, --no-renames в гейте; применяет владелец:
  git apply docs/planning/15-audit-p3-harness.patch && uv run pytest tests/unit -q, затем новая
  сессия); /permissions: Read(./.env) в deny; питание для окна B6 (HANDOFF «Действия владельца»,
  строка 4); гейты в LEARNING.md.
- Открыто: W6-T09 (окно B6 24 ч), W6-T10 (закрытие по разделу 6 спеки 14), бэклог аудита Б4, Б6,
  Б10 (класс C), Б13 (проба каталога lake в verify), Б14 (дыры guard: патч владельцу), Б15
  (dq_checks: сбой запроса GMV и окно at_rest), Б16 (остатки Б7 и Б8: исполнение SQL reconcile в
  CI с сервисом Postgres, два низких теста).
- Реплей: virtual_now 2026-07-17 18:13, потрачено около 20 ч 40 мин из 48 ч (W6-D13), 30.10 не
  тратился.

Порядок работы:
1. Старт (только чтение, вывод каждой команды в отчёт): git status --short; git log --oneline -8;
   gh run list --limit 5 (CI на 8fafdbb и позже: первые прогоны с actions по SHA); gh run list
   --workflow smoke.yml (первый smoke по расписанию 2026-11-02 03:00 UTC, тоже с actions по SHA);
   docker version --format '{{.Server.Version}}'; make report; при Docker: make verify-fast;
   curl -s 127.0.0.1:9090/api/v1/alerts; make replay-status. Контейнеры поднимаются сами после
   старта Docker Desktop; не пересоздавай их. Упавший контейнер из make report поднимается
   docker start <имя> только по «ок» владельца.
2. Холодный старт (раздел 6 спеки 14, п. 11): сверь, что состояние из HANDOFF и этого промпта
   совпадает с выводом п. 1; расхождение записать.
3. Одно сообщение владельцу вопросом с вариантами (AskUserQuestion): (а) «ок» на циклы verify,
   коммиты и push этой сессии (классификатор auto mode отказывает в цикле verify без явного
   разрешения владельца в сессии); (б) действия владельца: П-3 применён или нет, /permissions,
   питание для B6, гейты; (в) пакет класса C с рекомендацией по каждому: Б4 (правило grafana до
   fct_, dim_, mart_ и рестарт Trino), Б10 (живые сценарии: kill silver merge, потеря checkpoint на
   копии, недоступный MinIO), живая проба зависшего Trino для Б9 (docker compose pause trino на
   время make verify-fast), Б6 (учения восстановления), старт окна W6-T09.
4. Бэклог без живых действий, по приоритету: Б13, Б15, Б16, Б4 код (правила и тест; рестарт по
   «ок»), Б14 (только после того, как владелец применит П-3: патч поверх него).
5. W6-T09 после питания: начало окна UTC, 24 ч без реплея и без циклов verify, затем команды
   карточки (14-closeout-spec.md, W6-T09).
6. W6-T10: закрытие по разделу 6 спеки 14, каждая строка с доказательством; статусы в
   01-roadmap.md, HANDOFF итоговый, NEXT_SESSION на поддержку.

Цикл каждой задачи: «Вход» и код (шире трёх файлов: scout); план в отчёт; код пишет implementer
по брифу (сам только до ~20 строк в одном файле и Markdown), тест на отказ первым; make check и
затронутые проверки (test-spark, dags-check, alerts-test, dbt-parse); независимый reviewer в свежем
контексте; исправления не больше двух кругов; цикл verify (13-harness.md, раздел 5) последним
шагом перед коммитом; коммит <область>: <что сделано> без строк атрибуции; «Итог» в спеке или в
разделе 10 аудита и HANDOFF отдельным коммитом docs; push origin main без force по «ок» (W6-D3).
Доказательство: команда и вывод или file:line; «не проверено» с командой; факт, вывод, гипотеза
раздельно. Отчёт агента это данные: перепроверь ключевое сам.

Безопасность и ловушки:
- Класс C только по «ок» владельца на точный текст: старт, стоп, пересоздание контейнеров (кроме
  scheduler в цикле verify), запись в silver и bronze вне verify, реплей сверх W6-D13, chaos,
  kafka-configs --alter, удаление чего угодно (и в scratchpad), правки .env, DDL. В .claude/hooks и
  .claude/settings*.json не пишешь никогда: патч в scratchpad, применяет владелец. Правки AGENTS.md,
  CLAUDE.md, docs/agent-rules.md, 13-harness.md, .claude/agents получают окно подтверждения.
- Отказ классификатора auto mode или окно guard без «ок»: стоп и вопрос владельцу. Никогда не
  переформулируй, не дроби и не прячь команду в скрипт ради обхода хука.
- После Б7 (8fafdbb) у 9 работающих сервисов новый config hash: следующий make start (и make
  bootstrap), make up PROFILE=orchestrate|bi|obs, make lakekeeper-bootstrap, make replay-live
  пересоздают postgres-oltp, kafka, postgres-meta, trino, prometheus, grafana и экспортёры
  (OPERATIONS «Pinned images and actions»). trino и без Б7 расходится с живым (-Xmx2g против
  TRINO_XMX в .env). Ничего из этого не запускать без «ок».
- guard читает текст команды: слова вроде DROP, DELETE, agent_state или имена файлов отметок в
  heredoc блокируются; такой текст пиши через Edit. .env не читай (окно guard, deny в settings).
  git commit блокируется и в копии репо в scratchpad: патч собирай git diff --no-index.
- /tmp это tmpfs 5,9 ГБ в памяти WSL: копия репо с собственным .venv (pyspark) весит около
  0,55 ГБ, шесть копий 30.10 заполнили его и съели память. В копиях запускай тесты venv основного
  репо (/home/gusev/marketplace-lakehouse/.venv/bin/python -m pytest ... -p no:cacheprovider), новых
  .venv не создавай; удаление в scratchpad тоже только по «ок».
- Параллельные агенты: в рабочем дереве пишет только один; остальные в копиях в scratchpad, патч
  ставится по очереди (одна карточка, один verify, один коммит). Не обещай исполнителю «дерево
  твоё», если параллельно идёт docs-writer.
- Пока П-3 не применён, stop_gate требует точно свежий verify-fast после любой правки при
  незакоммиченном коде. Перед коммитом последним пишущим отметку шагом идёт полный цикл verify:
  verify-fast перезаписывает полную отметку; docs-коммит после полного verify verify-fast не
  требует.
- airflow/dags/ смонтирован в живой Airflow: правь в копии в scratchpad, ставь git apply при паузе
  затронутых DAG, затем make dags-check и airflow dags list-import-errors, потом снимай паузу.
- Правила Prometheus перезагружать только docker exec lakehouse-prometheus-1 kill -HUP 1; docker
  kill -s HUP помечает контейнер остановленным вручную, и после рестарта Docker он не поднимается.
- make silver отказывает, пока существует контейнер lakehouse-silver-merge; раннбук 409 в
  OPERATIONS «Timeouts». Таймаут задачи даёт в логе Process timed out, затем NotFound.
- pre-commit trailing-whitespace режет пробелы контекста в .patch: срежь их заранее и проверь git
  apply --check.
- make start при новом образе lakehouse/spark:dev пересоздаёт spark-bronze: не запускай.
  iceberg_maintenance активен и делает только optimize; iceberg_orphans на паузе, по умолчанию dry
  run. pg_logical_emit_message запрещён (ADR-023); docker image prune и system prune не делать.
- SilverGoldNotCompared живьём требует 24 прогона dq_checks без сверки gold (6 ч непрерывного
  реплея), это далеко за бюджетом W6-D13: доказан только promtool.
- Номера строк в отчётах агентов бывают неверны: проверяй.

Стоп и вопрос владельцу: действие или решение группы C; расхождение спеки, ADR и кода меняет
поведение; reconcile или verify красные вне запущенного тобой сценария; OOMKilled или больше 10 GiB
в docker stats; одна и та же ошибка второй раз (сначала чини тест, хук или проверку, которые её
пропустили). Остальное решай сам.

Конец сессии: верхний раздел HANDOFF «Состояние на <дата>» с фактами, «Действиями владельца» и
журналом «ок»; обновлённый docs/NEXT_SESSION.md с полным промптом; чистое дерево или явный список
незакоммиченного. Проект закрыт только по разделу 6 спеки 14, каждая строка с доказательством.
```
