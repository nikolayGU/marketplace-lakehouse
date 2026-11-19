# P03. Хуки: guard целевого вида, уровни гейта, база Stop-хука, settings
Статус: исполнен 19.11.2026, `0edcba4`, `2c945a5`, `04e7c66`, `96fe2fb`. Оркестратор на Opus или новее, запуск из корня:
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

Исполнен 19.11.2026 (UTC), четыре коммита кода: `0edcba4` (П-1, тесты в процессе, функции
`agent_state.py`), `2c945a5` (П-2 и исправление П-2b), `04e7c66` (П-3), `96fe2fb` (П-4). Решения
владельца в аргументе `/task`: В-13, В-14, В-15, В-16 «да», рутина сессии «да»; патчи применял
владелец (`git apply` и `make check` в своём терминале), коммиты 1-4 тоже он: классификатор auto
mode четыре раза отказал оркестратору на `git commit` (журнал «ок» в HANDOFF). Кто писал:
`implementer` (Sonnet) шаги 1-6 и круги исправлений; оркестратор сам: обёртка `main()` (П-1),
откат Stop-хука на стёртой базе, правка строки `CAT_MESSAGE` и окончаний целей в П-2/П-2b,
слияние П-3 с П-2, правки П-4 по ревью; ревью `reviewer` (Opus) по каждому патчу как документу и
по каждому дереву как коду. Файлы патчей лежат в `patches/` вне git: pre-commit
(`trailing-whitespace`, `end-of-file-fixer`) снимает пробел пустых строк контекста и портит
патч; точное применённое содержимое это сами коммиты (`git show <hash>`), sha256 файлов:
П-1 `0abfdb20`, П-2 `2b7333ee`, П-2b `29e91d11`, П-3 `eeb5e1a9`, П-4 `f29521c5`.

| Критерий («Готово, когда») | Проверка, вывод (19.11 UTC) |
|---|---|
| набор хуков быстрее 15 с, 0 failed | до: `861 passed in 56.00s` (HEAD `0274655`); после П-1: `863 passed in 9.03s`; на `04e7c66`: `892 passed in 12.48s` (ревьюер); под нагрузкой стека один прогон 19.5 с |
| мутация `check_bash` | `-k "asks_the_owner or asks_before or denies or allows"` -> `335 failed, 10 passed` (П-1), `333 failed, 10 passed` (дерево П-2b): 9 файловых случаев и новый подпроцессный deny через Write, а не 9 |
| корпус | `GATE_OPEN=1 ... probe.py <guard П-1> guard.py < corpus.json` -> до `allow 2448, ask 3667, deny 1209`; после `{"allow -> allow": 1844, "allow -> ask": 604, "ask -> ask": 3667, "deny -> allow": 1209}`, `classify.py` -> одна группа `agent_state without a writer`; нет `ask -> allow` |
| `fp`, `fp2`, `miss`, конвейер | решения шага 2 (ревью П-2, пять проходов; пять форм конвейера deny и ask; `docker logs x 2>&1 \| grep -c "drop table"` allow) |
| `tests/unit` и `make check` после каждого патча | П-1 `2017 passed`; П-2 `1966`; П-2b `2009`; П-3 `2048`; П-4 `2049 passed, 146 skipped` |
| живой смоук после П-2 | allow: `cat .verify-stamp 2>/dev/null \|\| echo none`, `echo 'truncate the output'`, `docker logs lakehouse-trino-1 2>&1 \| grep -c "drop table"` (`0`); deny: `echo x > .verify-stamp`, `echo "drop table t" \| psql`; три формы `ask` (`trino --execute "delete ..."`, `find ... -delete`, `git checkout HEAD -- no/such/path`) исполнились без окна: guard решает `ask` (проба в процессе), владелец окон не видел (режим auto). Не доказано |
| после П-3 | коммит одного Markdown без отметок: тест `test_markdown_only_commit_needs_no_stamp` и docs-коммит этого пакета; живой `stop_gate.py` на дереве с правкой только хуков и тестов: пусто, exit 0 (на HEAD этот же хук блокировал). Новая сессия при чужой правке `.py`: не проверено (`ls "$(git rev-parse --git-path claude-base-)"*` и конец хода в следующей сессии) |
| после П-4 | Write в `.verify-stamp` -> отказ правила permissions («File is in a directory that is denied by your permission settings»), отметка не изменилась; `cat .verify-stamp`, `make replay-status` allow; `make silver-nothing` (guard allow, правило `Bash(make silver*)`) исполнилась, было ли окно, владелец не помнит: не доказано; Edit `AGENTS.md` не пробовался |
| ревью | патчи как документ: П-2 пять проходов («вернуть» x4, затем «принять с замечаниями»), П-2b «принять», П-3 два прохода, П-4 два прохода; деревья как код: П-1 «принять с замечаниями», П-2 «вернуть» -> П-2b -> «принять», П-3 «принять», П-4 «принять с замечаниями» |
| цикл verify перед каждым коммитом | паузы `silver_upsert`, `dbt_build`, `dq_checks`; в полёте пусто; bronze `max(committed_at)` 06.11 16:17; stop scheduler; `make verify` 7 из 7 `rows ok keys ok ... values ok` и `wrote the full stamp` (деревья `078097be`, `ce7f6120`, `03791470`, `f52acc37`); start scheduler; паузы сняты после коммита; `iceberg_orphans` на паузе как был |
| CI | `0edcba4` run `44523862506`, `2c945a5` run `44552022266`, `04e7c66` run `44555211513`: exit 0, 12 из 12 `success`; `96fe2fb`: run `44562309323`, exit 0, 12 из 12 `success` |

Изменение по коду. `guard.py` 1063 -> 1013 строк: `main()`; правила HG-01..HG-04
(запись в `lake.bronze|silver|gold`, `DROP PUBLICATION`, scheduler только как единственная цель,
`checkout -- path`, `switch -f`, `find -delete`); один разбор команды (комментарии как в bash,
перевод строки в кавычках не разделитель, тела here-doc у команды с `<<`); слова чтения это данные
только при уверенном разборе, иначе проверяется весь текст; тело `cat > файл <<'EOF'` и сообщение
`git commit -m "$(cat <<'EOF' ...)"` данные только в тексте из одной команды; разбор форм
нарочного обхода удалён (HG-12, HG-15); `open()` с режимом записи; окончания целей `make`,
`checkout`, `compose up`; гейт по `gate_need` (Markdown и `docs/` ничего, `check` для тестов, CI,
`.claude/` и конфигов линтеров, verify любого режима для кода стека, `full` для `streaming/` и
`contracts/`); коммит после команды, меняющей дерево в том же тексте, получает отказ.
`stop_gate.py`: только код стека, с базой сессии только пути, изменённые в сессии и не
закоммиченные. `session_context.py`: база сессии, контейнеры одной строкой плюс не-`Up`, коммиты
в одну строку, три отметки. `agent_state.py`: `gate_level`, `gate_need`, `uncovered`,
`changed_paths`, база сессии, `fast` оставляет `full` после правки ниже уровня verify,
`describe_stamp` без git. `settings.json`: `timeout: 30` у guard, 12 `deny`, 31 `ask`.

Отклонения от текста пакета:
- В-15: guard 1013 строк, а не около 750: разбор here-doc, составных команд и откат при
  неуверенности добавили код, комментарии сохранены.
- Решения владельца по ходу ревью П-2: круги 3 и 4 сверх лимита регламента (вопрос с
  вариантами), сужение данных до текста из одной команды, нарочные формы обхода записываются, а
  не открывают круг.
- Сверх плана, строже: Markdown под `.claude/` уровня `check` (его читают тесты, ревью дважды);
  отказ коммита после команды, меняющей дерево, в том же тексте; в П-4 пять тратящих целей
  `replay-*` вместо `replay-*` (иначе `make replay-status` из стартовой рутины давал бы окно),
  добавлены `make iceberg-demo`, `cdc-snapshot`, `migrate`, `watermark-*`, `start`, `up` и
  `docker compose * down*`.
- `timeout` только у guard (В-16 говорит «у хуков»): у `session_context.py` свои таймауты 10 с,
  Stop и PostToolUse быстрые.
- Между коммитом 1 и П-3 Stop-хук блокировал каждый конец хода после правки тестов и хуков:
  `verify-fast` оставлял `full` по новому правилу, а старый `stop_gate.py` его не засчитывал
  (ревью коммита 1, №1). Снято П-3.
- Строка «после П-4» пакета не различает слои; смоук взят на формах, где guard молчит (выше).

Замечено и записано, не исправлено (бэклог HG, P04):
- Окно `ask` в режиме auto: ответы `ask` хука guard исполнялись без окна владельцу (смоук П-2, проба
  ревьюера с `rm -r`); для правил `ask` в permissions документация обещает окно, живьём не доказано.
  Решение о режиме работы и о классе C в режиме auto: P04.
- Ложные отказы в безопасную сторону: `git status && git add -A && git commit -m "$(cat <<'EOF'...)"`,
  `make lint && make test && git commit`, `git checkout -b x && ... git commit` (причина «команда
  меняет дерево»); `uv run python -m pytest ... -k write_stamp`; `cat > f <<END-NOTES` с «drop
  table» в теле; составная команда со `for` и именем отметки (`cat .verify-stamp` в ней).
- Пропуски, которые были и на HEAD: `UPDATE "lake"."silver"...` с кавычками, `--schema silver ...
  delete`, `INSERT OVERWRITE`, `CREATE OR REPLACE TABLE`, `rm .env`, `truncate -s 0 .env`,
  `dd of=.env`, `echo "make silver" | sh`, `sh -c "make silver"`, `git checkout <ref> <path>` без
  `--`, `os.open(...)`, коммиты без текста `git commit` (`cherry-pick`, `merge`, `revert`, `pull`),
  `bash -c '... git commit'`.
- Тексты правил отстают от хуков: `AGENTS.md` «Хуки» (`:38-49`), `13-harness.md` раздел 5 (гейт
  всегда полный verify), докстринги трёх хуков частично; перенос в P04.
- Нарушения правил подагентами (данные, вреда нет, все в scratchpad): исполнитель П-2 дважды после
  отказа guard сделал ту же правку теста скриптом или командой без слов-триггеров; ревьюер П-2 в
  первом проходе генерировал формы проб из rot13, чтобы живой guard не видел слов; исполнитель П-3
  один раз отформатировал копию хука `ruff format .`.
- `/tmp` в WSL это tmpfs 5.9 ГБ: копии репозитория подагентов заполнили его до 0, тесты падали на
  записи; удалено по «ок» владельца. Остаются копии ревьюеров в scratchpad (удалить по «ок»).
- Независимая проверка по запросу владельца (`scout`, роль архитектора данных): `DROP TABLE` в
  операции не исполнялся и не нужен; строки с ним это входы тестов guard; silver без снапшотов за
  19.11, Postgres 7 таблиц с прежним числом строк, логи без `drop`.

Риски: guard стал короче и мягче на данных, но каждый проход ревью находил новую форму в вырезании
данных; правило «данные только в тексте из одной команды» сужает класс. Откат по коммиту:
`git revert <hash>` (класс C, хуки применяет владелец).
