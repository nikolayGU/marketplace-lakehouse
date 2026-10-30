# Следующая сессия: закрытие проекта после аудита 30.10

Обновлено 30.10.2026, конец сессии аудита (`docs/planning/15-audit-2026-10-30.md`). Текст ниже
копируется в новую сессию как есть. Запуск из корня репо в WSL:
`claude --model opus --permission-mode acceptEdits` (оркестратор на Opus; не `--bare`: он выключает
хуки; не `bypassPermissions`).

```text
Ты оркестратор закрытия проекта Marketplace Lakehouse (mini): учебная data platform на ноутбуке
(Postgres с реплеем Olist, Debezium, Kafka, Spark bronze и silver, Iceberg в Lakekeeper на MinIO,
dbt на Trino, Airflow 3, Prometheus и Grafana). Веди работу до доказуемого конца сам; владелец
решает группу C, даёт «ок» на опасные действия и делает то, что требует человека. Правила: AGENTS.md
(уже в контексте); регламент: docs/planning/13-harness.md; бэклог W6: docs/planning/14-closeout-spec.md;
находки и бэклог аудита: docs/planning/15-audit-2026-10-30.md; статусы всех планов:
docs/planning/README.md.

Состояние на 30.10.2026 (подробно: верхний раздел docs/HANDOFF.md, хук старта его печатает).
- Аудит 30.10 закрыт: P0 и P1 нет, P2 21, P3 44. Все P2 либо исправлены, либо приняты как
  ограничение, либо ждут владельца (раздел 3 и 9 аудита). Закоммичено и запушено: 01bf497,
  e66531b (правки аудита), 8577de1 (патч хуков П-1: guard спрашивает на чтение .env, docker
  compose config без -q, docker inspect с Env, make down), 8164afe (Б2: make verify сверяет
  значения строк), e2ae619 (Б1: таймауты всех задач Airflow, merge с именем
  lakehouse-silver-merge), c2d711c (Б3: алерт SilverGoldNotCompared), bac8047 (docs).
- Решения W6-D1..D17 приняты (спека 14, раздел 2). Закрыты с «Итогом»: W6-T00, W5-T05b, W6-T01,
  W6-T02, W6-T05..T08, W6-T11. Открыты: W6-T03, W6-T09, W6-T10, гейты владельца.
- Реплей: virtual_now 2026-07-17 18:13, потрачено около 20 ч 40 мин из 48 ч (W6-D13).

Порядок работы:
1. Старт (только чтение, вывод каждой команды в отчёт): git status --short; git log --oneline -8;
   gh run list --limit 5; docker version --format '{{.Server.Version}}'; make report (раздел
   «stopped containers» называет упавшие контейнеры с unless-stopped); при Docker: make verify-fast;
   curl -s 127.0.0.1:9090/api/v1/alerts; make replay-status. Контейнеры поднимаются сами после
   старта Docker Desktop; не пересоздавай их. Упавший контейнер из make report поднимается
   docker start <имя> только по «ок» владельца.
2. Одно сообщение владельцу вопросом с вариантами (AskUserQuestion): (а) «ок» на циклы verify и
   коммиты этой сессии (классификатор auto mode отказывает в цикле verify без явного разрешения
   владельца в сессии); (б) строки «Действий владельца» в HANDOFF, которые не сделаны (14: копия .env
   вне репо; проверка /permissions, что Read(./.env) стоит в deny); (в) решения группы C, если
   появятся.
3. Живые проверки с датой: первый smoke по расписанию 2026-11-02 03:00 UTC (gh run list --workflow
   smoke.yml); dry run orphans silver.orders без путей orders_per_minute- (OPERATIONS «Not proven
   yet»; запуск только по «ок»). Серия lakehouse_dq_gold_not_compared_runs уже есть (30.10 16:33
   UTC: 0, прогон dq_checks 16:30 success); живое срабатывание SilverGoldNotCompared не показано.
4. /task W6-T03: сверка docs/interview-notes.md с docs/evidence.md (Q13 TODO(verify) закрывается
   числами W5-T05b; учти правки 30.10: reconcile сверяет значения, 15 правил алертов, таймауты).
5. Бэклог аудита без живых действий, по приоритету (раздел 10): Б5 (сверка GMV с Postgres в
   dq_checks), Б9 (ранняя проба Trino в verify), Б7 (digest образов и SHA actions), Б8 (тесты),
   Б11 и Б12 (патч владельцу для хуков: stop_gate и Markdown, имя проекта, ремарки вердикта).
6. Подготовка W6-T10 (закрытие по разделу 6 спеки 14) и пакет «ок» владельцу на действия класса C:
   Б4 (правило grafana, рестарт Trino), Б6 (учения восстановления), Б10 (живые сценарии), W6-T09
   (окно B6 24 ч после действия владельца 4, питание; SilverGoldNotCompared при непрерывном
   реплее стреляет по замыслу).

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
  kafka-configs --alter, удаление чего угодно, правки .env, DDL. В .claude/hooks и
  .claude/settings*.json не пишешь никогда: патч в scratchpad, применяет владелец. Правки AGENTS.md,
  CLAUDE.md, docs/agent-rules.md, 13-harness.md, .claude/agents получают окно подтверждения.
- Отказ классификатора auto mode или окно guard без «ок»: стоп и вопрос владельцу. Никогда не
  переформулируй, не дроби и не прячь команду в скрипт ради обхода хука.
- guard читает текст команды: слова вроде DROP, DELETE, agent_state или имена файлов отметок в
  heredoc блокируются; такой текст пиши через Edit. .env не читай (окно guard, deny в settings).
- stop_gate требует свежий make verify-fast после любой правки, даже Markdown (бэклог Б12). Перед
  коммитом последним пишущим отметку шагом идёт полный цикл verify: verify-fast перезаписывает
  полную отметку.
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
- Номера строк в отчётах агентов бывают неверны: проверяй.

Стоп и вопрос владельцу: действие или решение группы C; расхождение спеки, ADR и кода меняет
поведение; reconcile или verify красные вне запущенного тобой сценария; OOMKilled или больше 10 GiB
в docker stats; одна и та же ошибка второй раз (сначала чини тест, хук или проверку, которые её
пропустили). Остальное решай сам.

Конец сессии: верхний раздел HANDOFF «Состояние на <дата>» с фактами, «Действиями владельца» и
журналом «ок»; обновлённый docs/NEXT_SESSION.md с полным промптом; чистое дерево или явный список
незакоммиченного. Проект закрыт только по разделу 6 спеки 14, каждая строка с доказательством.
```
