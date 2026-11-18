# P03. Хуки: guard целевого вида, уровни гейта, база Stop-хука, settings
Статус: не начат. Оркестратор на Opus или новее, запуск из корня:
`/task docs/planning/21-final-audit-2026-11-13/P03-harness-hooks.md`; хуки применяет владелец.

## Цель

Guard ловит обычные формы записи в lake и потери работы, не отказывает на чтении и данных, тесты
хука краснеют на сломанном guard и идут в процессе; гейт коммита требует столько проверок, сколько
доказывает правка; Stop-хук не блокирует ход из-за чужой правки; settings дают второй слой.

## Находки пакета

| ID | серьёзность | суть | где подробности |
|---|---|---|---|
| HG-01 | высокая | `update/delete/insert/merge` в `lake.bronze/silver/gold` через Trino: allow | `reports/HG.md`, HG-01 |
| HG-02..HG-04 | средняя | `DROP PUBLICATION`; `stop airflow-scheduler kafka`; `git checkout <ref> -- p`, `switch -f`, `find -delete`: allow | HG-02..HG-04 |
| HG-05..HG-11 | средняя, низкая | ложные отказы: чтение отметки в составной команде, слова в данных, `make check > log`, чтение `agent_state`, `open()` на чтение, `show create`, `exec ... rm`, любой `*.env` | HG-05..HG-11 |
| HG-12, HG-15 | средняя, низкая | 310 строк разбора форм обхода, дубли правил 8083 | HG-12 «Целевой вид», HG-15 |
| HG-13 | средняя | ask-тесты зелёные при сломанном guard (R-02) | HG-13 |
| HG-14 | средняя | 859 подпроцессов, резка исходника в `load_guard` (R-08, R-27) | HG-14; `reports/QA.md` «Цена набора» |
| HS-02 | средняя | полный verify на любой коммит, даже Markdown | `reports/HS.md`, HS-02 |
| HS-03 | средняя | Stop-хук блокирует ход из-за правки до сессии | HS-03 |
| HS-11 | низкая | стартовый хук 81 строка, 20 строк контейнеров | HS-11 |
| HC-01 | средняя (в отчёте высокая) | у guard нет `timeout`, по умолчанию 600 с | `reports/HC.md` |
| HC-04 | средняя | защита отметок и файлов харнесса только хуком | `reports/HC.md`, HG «Кандидаты в permissions» |

## Решения владельца и действия класса C

Одним вопросом в начале сессии (README папки, раздел 5, п. 3). Что выпадает при «нет»:
- В-13 нет: нет `gate_level` и правки `commit_gap`; Stop-хук по-прежнему на любой код; тесты
  `:1007-1017`, `:1511-1517` не меняются; П-3 несёт только HS-03 и HS-11.
- В-14 нет: нет базы сессии (функций в `agent_state.py`, записи в `session_context.py`, ветки в
  `stop_gate.py`); Stop-хук сверяет с HEAD.
- В-15 нет: П-2 несёт только HG-01..HG-11 поверх нынешнего устройства guard; HG-12, HG-15 и
  удаление тестов форм обхода выпадают. HG-13 и HG-14 остаются.
- В-16 нет: П-4 не делается (HC-01, HC-04).
Класс C: применение каждого патча (владелец), цикл verify (раздел 5 `13-harness.md`), коммиты.
Правка `scripts/agent_state.py`: окно подтверждения, кладёт оркестратор одной `cp` из scratchpad.

## Зависимости

- После P02 (закоммичен): `agent_state.py` и `test_agent_hooks.py` общие. P04 после P03.
- От P02 (`3af49bd`, ревью круг 1, низкие): `describe_stamp` считает `tree_hash` до проверки
  файла отметки, без git отсутствующая отметка даёт исключение вместо `none` (сначала проверить
  файл, тест в каталоге без git); докстринг `record_review` назвать форму «Итог. ... не принять».
- До применения П-3 любой коммит требует полного verify: стек поднят для коммитов 1 и 2.

## Вход

1. `guard.py:310-318` только `shop|replay|cdc`, `:331` только DDL; `:270-271`
   `(?![^\n;&|]*airflow-scheduler)`; `:218-224` `checkout\s+(--\s|\.(\s|$))`; `:72` DROP без
   publication; `:166-185` `bends_make_check`; `:113-115` ветка `\bopen\(`; `:325-329` дубли;
   `:931-937` verify до проверки кода; `:1055-1063` проверка при импорте, без `main()`.
2. `stop_gate.py:26-41` `code_changes` против HEAD; `session_context.py:149-162` вывод;
   `.claude/settings.json:27-38` у guard нет `timeout`, `:17-26` deny только секреты.
3. `tests/unit/test_agent_hooks.py:21-44` подпроцесс и `decision()`; `:953-963` fails_closed;
   `:1910-1918` `load_guard` режет исходник по `"\ntry:\n    check(json.load(sys.stdin))"`.
4. Код стека (проверено 13.11): `streaming/` и `contracts/` попадают в Spark только образом
   (`docker/compose.yaml:288-295` build, `streaming/Dockerfile:34,37` `COPY`, у `spark-silver`
   `:410-411` нет монтирования, у `DockerOperator` в `airflow/dags` нет `mounts`);
   смонтированы `airflow/dags` и `dbt` (`compose.yaml:579-580,613-614,640`), `observability`
   (`:662,689-690`). Хостовый `reconcile` читает `contracts/silver` из дерева (`lib.sh:252`).
5. Документация (code.claude.com/docs/en/hooks.md, 13.11): `session_id` в общих полях и в примерах
   входа SessionStart и Stop; `timeout` в секундах, по умолчанию 600, таймаут с
   `onFailure: "block"` блокирует как код 2. permissions.md: `Edit` покрывает все встроенные
   правки и запись редиректом и `tee` в Bash; `./path` от текущего каталога, `/path` от корня
   проекта; Bash-правило не видит `git -C . push`.
6. Замеры «до» (копия в `<scratchpad>/P03/`): корпус `docs/planning/15-audit-p5-review/corpus.json`
   через `work/HG/probe.py.txt` с `GATE_OPEN=1`; `uv run pytest tests/unit/test_agent_hooks.py -q`
   (QA 13.11: 859 за 65 с). Аудит 13.11: прототип в процессе 748 passed, 111 failed (все в тестах
   форм обхода и `test_guard_fails_closed`); корпус HEAD против прототипа `ask -> ask` 3667,
   `deny -> allow` 1209 (все `agent_state` без функции записи), `allow -> ask` 604.

## Границы

- Агент правит: `tests/unit/test_agent_hooks.py` (шаг 1), `tests/unit/test_agent_state.py`,
  `scripts/agent_state.py` (окно). Хуки и `settings.json`: только копия
  `<scratchpad>/P03/repo` (`git init`, `git add -A` без коммита: гейт отказывает на коммит и в
  копии) и патч `git diff` в `docs/planning/21-final-audit-2026-11-13/patches/`.
- Нельзя: `git apply` в репозитории (агенту можно только `git apply --check`), запись в
  `.claude/`, правила и роли (P04).
- `work/HG/*.txt` это отправная точка, не патч: собрать заново, каждое правило с тестом.

## Шаги

1. П-1 `patches/p03-1-guard-main.patch` (только `guard.py`: `def main()` и
   `if __name__ == "__main__": main()`, как `work/HG/step1-main.diff.txt`). Неизменённые тесты:
   859 passed. Владелец применяет (команды ниже). Затем `implementer` в `test_agent_hooks.py`:
   - HG-13: `decision()` первой строкой `if "guard.py failed" in result.stdout: return "crash"`;
     `test_guard_fails_closed` ждёт `crash` (меняется смысл, не ослабление).
   - HG-14: `GUARD` импортом через `importlib.util.spec_from_file_location`; `run_guard(event,
     root)` подменяет `GUARD.ROOT` и `sys.stdin`, ловит `SystemExit`, отдаёт `CompletedProcess`;
     `bash()` и `hook("guard.py")` через него; `load_guard` заменить импортом и
     `monkeypatch.setattr`. Подпроцессом оставить три теста: deny (код 2, stderr), ask (JSON),
     мусор на stdin (`crash`). Образец: `work/HG/tests-inprocess-proto.diff.txt`.
   - Если В-13 или В-14 «да»: в `scripts/agent_state.py` функции шагов 3 и 4 с тестами в
     `test_agent_state.py` (хуки их ещё не зовут, набор зелёный).
   Мутация в копии: первая строка `check_bash` бросает исключение; `-k asks_the_owner` даёт 0
   passed (до правки 100 passed). Ревью кода, цикл verify, коммит 1.
2. П-2 `patches/p03-2-guard.patch` (`guard.py` и `test_agent_hooks.py` одним патчем: новые тесты
   красные на guard П-1). Сначала тесты в копии, прогон красный, затем guard.
   - Ask-формы (allow на HEAD): 12 строк `work/HG/miss.json.txt:2-13`. Правила: HG-01
     `\b(insert\s+into|update|delete\s+from|merge\s+into)\s+"?(lake\.)?"?(bronze|silver|gold)"?\.`;
     HG-02 `drop` в правиле публикаций; HG-03 исключение только для единственной цели
     `(?!\s+airflow-scheduler\s*(?:$|[;&|\n]))`; HG-04
     `checkout\b[^\n;&|]*\s(--|-f|--force|\.)(\s|$)`,
     `switch\b[^\n;&|]*\s(-f|--force|--discard-changes)\b`, `\bfind\b[^\n;&|]*\s-delete\b`.
     Остаётся allow:
     `$COMPOSE stop airflow-scheduler && make verify && $COMPOSE start airflow-scheduler`.
   - Allow-формы (deny или ask на HEAD, по `work/HG/fp.json.txt` и `fp2.json.txt`): HG-05
     `fp.json.txt:2-7`; HG-06 `fp.json.txt:8-17,19-20,30-31` и `fp2.json.txt:4-5,7,11`; HG-07
     `fp.json.txt:21,24`; HG-08 `:26-27`; HG-09 `fp2.json.txt:2-3`; HG-10 `fp.json.txt:28-29,35`;
     HG-11 `fp.json.txt:39`, `fp2.json.txt:8-9`. Окно и отказ остаются (HG «не делать»):
     `fp.json.txt:33-34,36-38,41,59`, `fp2.json.txt:6`. Запреты-двойники остаются: `echo x >
     .verify-stamp`, `test -f .verify-stamp || touch .verify-stamp`, `python3 -c "from
     scripts.agent_state import write_stamp"`, `echo X=1 >> .env`, `python3 -c "open('AGENTS.md',
     'w')"` (ask).
   - Тест конвейера (новый, аудит прототипа его не видел): слово из данных чтения проверяется,
     если после чтения в том же конвейере стоит команда не-чтение. Прежние решения сохраняются:
     `echo "drop table shop.orders" | psql -d shop` deny, `echo 'truncate shop.orders' | psql`
     deny, `echo "update shop.orders set x = 1" | psql` ask, `echo 'git push origin main' | bash`
     ask, `echo 'docker compose down' | bash` ask; `docker logs x 2>&1 | grep -c "drop table"`
     allow. Прототип даёт allow на первые пять: исполнитель обязан это закрыть.
   - Тест времени в процессе: 5 команд по 8-16 KB (длинный `echo`, `grep` по 2000 файлам, 2000
     `ls` через `;`, 1000 звеньев `echo | `, `git log` с 2500 путями) решаются быстрее 1 с каждая.
     Форму `curl x:8083/ ` x1300 не брать: 2.3 с и на HEAD, и в прототипе (HG-n6, «не делать»).
   - При В-15 «да» guard целевого вида по `reports/HG.md` «Целевой вид» (что оставить, удалить,
     упростить; `work/HG/slim-proto.diff.txt`); удалить и сократить тесты по списку там же;
     докстринг начать с границы HG-15; комментарии оставшегося кода не срезать (около 750 строк).
     При «нет»: HG-01..HG-11 поверх нынешнего кода.
   Проверки в копии: полный `tests/unit`; корпус (ниже); мутации по одной в `is_read`,
   `without_data`, `writes_stamp`, исключении scheduler: тест-копия краснеет. Ревью патча как
   `документ`, владелец применяет, ревью кода по дереву, цикл verify, коммит 2.
3. HS-02, если В-13 «да». `scripts/agent_state.py` (в коммите 1): `gate_level(path)` возвращает
   `none` для `_is_code` ложь (Markdown вне `dbt/`, всё в `docs/`); `full` для `streaming/`,
   `contracts/`; `check` для `tests/`, `.github/`, `.claude/`, `.pre-commit-config.yaml`,
   `.yamllint`, `.sqlfluff`, `scripts/agent_state.py`; `verify` для прочего (консервативно).
   `gate_need(paths)` максимум уровней; `uncovered(root, stamp, current, floor)` пути с уровнем не
   ниже `floor`, изменённые с дерева отметки (`CalledProcessError` значит всё). `write_stamp`
   (HS-01) считает покрытие тем же правилом с `floor="verify"`. Тест на каждую границу:
   `test_gate_level_of_each_path_class` с параметрами `README.md` none, `docs/x.py` none,
   `dbt/models/docs.md` verify, `.claude/agents/r.md` none, `tests/unit/t.py`,
   `.github/workflows/ci.yml`, `.claude/hooks/guard.py`, `.yamllint`, `scripts/agent_state.py`
   check, `airflow/dags/x.py`, `dbt/models/x.sql`, `scripts/verify.sh`, `Makefile`,
   `docker/compose.yaml`, `uv.lock`, `dbt/.sqlfluff` verify, `streaming/spark_jobs/x.py`,
   `contracts/silver/orders.json` full; `test_a_move_out_of_streaming_keeps_the_full_level`.
   П-3 `guard.py`: `commit_gap` по `gate_need` путей против HEAD: `none` пусто; `check` и выше:
   `make check` и вердикт (покрытие `floor="check"`); `verify`: отметка verify любого режима,
   `floor="verify"`; `full`: режим `full` или `make verify && ... git commit`. `stop_gate.py`
   блокирует только пути уровня `verify` и выше. Тесты: `test_markdown_only_commit_needs_no_stamp`
   (переворот пробы F2), `test_ci_and_tests_commit_needs_check_and_review_only`,
   `test_stack_code_commit_needs_a_verify`, `test_streaming_commit_needs_a_full_verify`,
   `test_a_tests_edit_after_a_verify_keeps_it_covering`,
   `test_stop_gate_ignores_code_outside_the_stack`.
   Меняются по решению: `test_docs_after_a_fast_verify_do_not_open_the_commit` (`:1007`),
   `test_commit_chained_after_a_full_verify_is_allowed` (`:1016-1017` на чистом дереве allow),
   `test_only_docs_changed_needs_a_full_verify_and_nothing_else` (`:1511`).
4. HS-03, если В-14 «да». `agent_state.py`: `remember_session_base(root, session_id)` пишет
   `tree_hash` в `git rev-parse --git-path claude-base-<id>`, только если файла нет, и удаляет такие
   файлы старше 7 дней; `session_base(root, session_id)`; id вне `[A-Za-z0-9_-]{1,128}` базы не
   даёт. П-3: `session_context.py` зовёт запись на любом `source` (`resume` и `compact` базу не
   двигают), сбой не роняет хук; `stop_gate.py` с базой берёт пути `_code_diff(base, current)`, без
   базы прежнее. Тесты: `test_stop_gate_ignores_code_changed_before_the_session` (переворот F5),
   `test_stop_gate_blocks_code_changed_in_the_session`, `test_a_resumed_session_keeps_its_base`,
   `test_stop_gate_without_a_base_behaves_as_before`,
   `test_a_session_id_with_a_slash_writes_no_base`.
5. HS-11 в П-3: контейнеры одной строкой `N running, M healthy` и строки только нездоровых
   (`unhealthy`, `health: starting`); коммиты `%h %<(72,trunc)%s`; три отметки
   (`describe_stamp` verify, check, review). Тест
   `test_session_context_lists_only_unhealthy_containers`; меняются ожидания трёх тестов
   `:1235-1404` о списке запущенных. HANDOFF и NEXT_SESSION остаются.
6. П-4 `patches/p03-4-settings.patch`, если В-16 «да»: `"timeout": 30` у guard; `permissions.deny`
   плюс `Edit(/.claude/hooks/**)`, `Edit(/.claude/settings.json)`,
   `Edit(/.claude/settings.local.json)`, `Edit(/.verify-stamp)`, `Edit(/.check-stamp)`,
   `Edit(/.review-stamp)`; `ask`: `Edit(/AGENTS.md)`, `Edit(/CLAUDE.md)`,
   `Edit(/docs/agent-rules.md)`, `Edit(/docs/planning/13-harness.md)`,
   `Edit(/scripts/agent_state.py)`, `Edit(/.claude/agents/**)`, `Edit(/.claude/skills/**)`,
   `Bash(git push *)`, `Bash(git rebase *)`, `Bash(git reset --hard*)`, `Bash(make silver*)`,
   `Bash(make nuke*)`, `Bash(make bootstrap*)`, `Bash(make replay-*)`, `Bash(make chaos-*)`,
   `Bash(make down*)`, `Bash(docker compose down*)`, `Bash(gh pr create*)`,
   `Bash(gh workflow run*)`, `Bash(docker push*)`. Секреты остаются в guard (Bash-формы,
   `.env.example`). Тест `test_settings_give_the_guard_a_timeout_and_a_second_layer`; прежние
   `test_settings_*` зелёные.

Порядок патчей и команды владельца (из корня, в своём терминале, не через агента):

```bash
P=docs/planning/21-final-audit-2026-11-13/patches
git apply --check $P/p03-1-guard-main.patch && git apply $P/p03-1-guard-main.patch && make check
```

То же для `p03-2-guard.patch`, `p03-3-gates.patch`, `p03-4-settings.patch`, строго по порядку и
только после коммита предыдущего шага. Хук живой сразу после `git apply`, поэтому `make check` в
той же строке. Между патчами агент: ревью кода по дереву, живой смоук (ниже), цикл verify и
коммит. Каждый патч собирается заново из копии дерева после предыдущего коммита.

## Готово, когда

- [ ] `uv run pytest tests/unit/test_agent_hooks.py -q --durations=3` -> 0 failed, время меньше 15 с (до: записано во «Вход»)
- [ ] мутация `check_bash` в копии, `-k "asks_the_owner or asks_before or denies or allows"` -> зелёные только 9 случаев `test_guard_denies_every_file_tool_on_a_gate_stamp` (файловые инструменты; аудит 13.11: 335 failed, 9 passed)
- [ ] корпус: `GATE_OPEN=1 CLAUDE_PROJECT_DIR=$PWD python3 <scratchpad>/P03/probe.py <копия guard HEAD> .claude/hooks/guard.py < docs/planning/15-audit-p5-review/corpus.json | tail -1` -> нет `ask -> allow`; `deny -> allow` только `agent_state` без функции записи (`work/HG/classify.py.txt`)
- [ ] `fp.json`, `fp2.json`, `miss.json` и формы конвейера шага 2 -> решения из шага 2
- [ ] `uv run pytest tests/unit -q` и `make check` -> зелёные после каждого патча
- [ ] живой смоук после П-2 (агент выполняет, владелец на окно отвечает «нет»): ask `trino --execute "delete from lake.silver.orders where 1 = 0"`, `find <scratchpad>/empty -name x -delete`, `git checkout HEAD -- no/such/path`; deny `echo x > .verify-stamp`, `echo "drop table t" | psql`; allow `cat .verify-stamp 2>/dev/null || echo none`, `echo 'truncate the output'`, `docker logs lakehouse-trino-1 2>&1 | grep -c "drop table"`
- [ ] после П-3: коммит одного Markdown без отметок allow; новая сессия при чужой правке `.py` заканчивает ход без блока
- [ ] после П-4: Write в `.verify-stamp` отказ; Edit `AGENTS.md` окно; `cat .verify-stamp` allow
- [ ] вердикт `reviewer` по каждому патчу как `документ` и по дереву после применения; «Итог», README папки, HANDOFF

## Не входит

- Тексты правил (`AGENTS.md` «Хуки», `13-harness.md` §3-5, `reviewer.md`): P04, в том числе
  запись решения о порядке «коммит, CI, сборка образа» (см. «Расхождения»). Чистка `settings.local.json` (В-22): владелец.
- `git commit -- <пути>` для коммита документов при чужом коде (проба F2b), гейт по индексу (H3),
  квадратичный `HTTP_WRITE` (HG-n6), остальное «не делать» из `reports/HG.md` и `reports/HS.md`.

## Риски и откат

- Неверный патч guard блокирует работу агента: при сбое импорта каждый Bash, Write и Edit
  отклоняется (`onFailure: "block"`), агент откатить не может. Владелец в своём терминале:
  `git apply -R docs/planning/21-final-audit-2026-11-13/patches/<патч>` или
  `git checkout -- .claude/hooks/guard.py`.
- В процессе `GUARD.ROOT` подменяется, а шаблоны с `IN_REPO` скомпилированы при импорте с путём
  репозитория: тест с абсолютным путём во временном корне держать подпроцессом.
- Уровни гейта доверяют пути: правка `docker/` проходит с `verify-fast`, хотя без пересоздания
  контейнеров verify её не доказывает (так и сейчас).

## Расхождения с отчётом аудита

- Прототип guard ослабляет обычные формы, которых нет в корпусе: пять форм конвейера шага 2 из
  deny или ask стали allow (проба 13.11). Вывод HG «мягче только `agent_state` без записи» верен
  только для корпуса.
- В `work/HG/` есть `commit.json.txt`, `ev_*.json.txt` и `gen_long.py.txt` (он создаёт
  `long.json`); нет `normal-out` и каталогов `t_*`, на которые ссылается HG.md; формы теста
  времени заданы в шаге 2. Длинная форма 8083 нарушает «быстрее 1 с».
- Прототип убрал комментарии и докстринги оставшегося кода; 709 строк отчасти за счёт этого.
- HC пишет правила как `Edit(./...)`: по документации это от текущего каталога; в пакете `/`.
  Документация разрешает отрицание `!` для таких правил, но секреты остаются в guard по брифу.
- HS-02 подтверждён по коду, с оговоркой: `contracts/silver` читает и хостовый `reconcile`.
- `13-harness.md`, раздел 2, B: образ `lakehouse/spark:dev` собирают только из чистого дерева на
  HEAD после CI, а отчёт HS-02 требовал полного verify незакоммиченного `streaming/` после
  пересборки: порядок не сходится. Решено при сведении 18.11 (README папки, В-13): уровень
  `full` это полный verify дерева, как сейчас (шаг 3); новый код Spark до коммита доказывает
  `make test-spark`, живую проверку после сборки образа из HEAD ведёт пакет с этим кодом (P06).
  P04 записывает это в раздел 5 регламента.
- HS-03: `session_id` подтверждён документацией; живым событием не проверен.

## Итог
