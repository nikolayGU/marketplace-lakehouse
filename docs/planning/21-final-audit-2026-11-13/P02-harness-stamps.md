# P02. Отметки гейта: fast не затирает full, разбор «вернуть», интерпретатор проекта
Статус: не начат. Оркестратор на Opus или новее, запуск из корня:
`/task docs/planning/21-final-audit-2026-11-13/P02-harness-stamps.md`.

## Цель

Отметки гейта коммита перестают давать ложный зелёный («вернуть» вне формата) и лишний цикл
verify (`verify-fast` затирает `full`); verify ставит отметку дереву на момент старта и не падает
на отметке; `agent_state.py` с хоста идёт через Python окружения проекта. Хуки в пакете не правятся.

## Находки пакета

| ID | серьёзность | суть | где подробности |
|---|---|---|---|
| HS-01 | средняя | `make verify-fast` после `make verify` на том же коде затирает `full` | `reports/HS.md`, HS-01 |
| HS-04 | средняя | `Итог. Вердикт: вернуть`, `Вердикт - вернуть`, `Предмет: план и код` оставляют прежнее «принять» | HS-04 |
| HS-05 | средняя | `agent_state.py tree` не говорит, какой код покроет отметка ревью (только код; правила пишет P04) | HS-05 |
| HS-06 | низкая | `describe_stamp` пишет `stale`, когда гейт считает отметку покрывающей | HS-06 |
| HS-07 | низкая | `verify.sh` ставит отметку дереву на конец прогона, а не на старт | HS-07 |
| HS-08 | низкая | `dbt/models/docs.md` (блоки `{% docs %}`) считается не кодом | HS-08 |
| HS-12 | низкая | два теста `session_context` зовут docker хоста | HS-12 |
| IN-03 | средняя | отметка verify и `make check` идут через системный `python3` (нужен 3.11) | `reports/IN.md`, IN-03 |

## Решения владельца и действия класса C

- Решений В-n у пакета нет (README, раздел 3).
- Окно подтверждения: замена `scripts/agent_state.py` (одна команда `cp` из scratchpad, см. шаг 2).
- Цикл verify перед коммитом по `docs/planning/13-harness.md`, раздел 5: класс A только при трёх
  условиях раздела, иначе «ок» на точный текст. Коммит после «ок» на diff.

## Зависимости

- Ни от чего. P03 строит свой патч на дереве после коммита P02: `scripts/agent_state.py` и
  `tests/unit/test_agent_hooks.py` правят оба пакета. Пока P02 не закоммичен, P03 не начинать.
- P07 (QA-08) меняет параметры медленных проб в `tests/unit/test_verify_script.py`: P07 берёт файл
  после P02.
- Нужен поднятый стек: гейт до P03 требует полного verify на любой коммит.

## Вход

Сверить цитатой; номер сдвинулся: искать по цитате; не подтвердилось: шаг не делать, записать в
«Итог».

1. `scripts/agent_state.py:120-129` `write_stamp` пишет `fast` в тот же `.verify-stamp`;
   `:153-157` `describe_stamp` знает только `fresh`/`stale`; `:160-161`
   `not path.endswith(".md") and not path.startswith("docs/")`; `:71-75` хвост поля `r"\b.*"`;
   `:204-217` `_read_report` видит строку только по голове `Вердикт:`;
   `:25` `from datetime import UTC`.
2. `scripts/verify.sh:67` `python3 "$ROOT/scripts/agent_state.py" stamp "$mode" "$ROOT"`;
   `scripts/report.sh:14` `python3 scripts/agent_state.py show`; `Makefile:157`
   `@python3 scripts/agent_state.py check "$(CURDIR)"`; образец: `scripts/bootstrap.sh:18`
   `.venv/bin/python`; CI и smoke создают окружение `uv sync --locked --group dev`
   (`.github/workflows/ci.yml:50`, `smoke.yml:37`).
3. `tests/unit/test_agent_state.py:798` ждёт рецепт `python3 scripts/agent_state.py check`;
   `:107-112` `test_describe_stamp` ждёт окончание `stale`; `:738-744` «позднее ревью побеждает».
4. `tests/unit/test_agent_hooks.py:1165-1187`: `test_session_context_reports_state_goal_and_stamp`
   и `test_session_context_survives_missing_docs` без `fake_docker` (он в `:1190`).
5. `tests/unit/test_verify_script.py:88-163`: фейковый корень без git и без `.venv`; фейк docker
   `:29-63` отвечает Kafka отказом, ни один тест не доходит до отметки.
6. Пробы аудита утверждают ТЕКУЩЕЕ поведение. Скопировать в `<scratchpad>/P02/`
   `work/HS/test_hs_probes.py.txt` и `test_hs_old_items.py.txt` без `.txt`, `<repo>` заменить на
   корень, прогнать `uv run pytest <scratchpad>/P02/test_hs_*.py -q -s`: 26 passed (на 13.11 так).
   Вывод сохранить: это «до».

## Границы

- Менять: `scripts/agent_state.py` (через окно), `scripts/verify.sh`, `scripts/report.sh`,
  `Makefile` (только строка `check`), `tests/unit/test_agent_state.py`,
  `tests/unit/test_agent_hooks.py` (новые тесты HS-01, HS-08 и два теста HS-12),
  `tests/unit/test_verify_script.py`.
- Нельзя: `.claude/` (хуки и роли), `scripts/chaos/lib.sh` (см. «Расхождения»), правила и
  документы агентов (это P04), README (это P13). Тесты не ослаблять; изменённые ожидания перечислены
  в шагах поимённо.
- Живой стек: только цикл verify раздела 5 регламента.

## Шаги

1. Тесты на отказ первыми (`implementer`, файлы тестов в репозитории). Прогнать, сохранить вывод:
   каждый новый тест красный на HEAD. Имена и утверждения:
   - `test_a_fast_verify_keeps_a_full_stamp_that_covers_the_tree`: `full`, правка `NOTES.md`,
     `write_stamp(repo, "fast")`, режим остаётся `full` (переворот пробы F1);
   - `test_a_fast_verify_replaces_a_full_stamp_of_older_code`: `full`, правка `job.py`, `fast`;
   - `test_a_fast_verify_replaces_a_full_stamp_whose_tree_is_gone`: в отметке id чужого дерева;
   - `test_write_stamp_uses_the_given_tree`, `test_write_stamp_refuses_an_id_that_is_no_tree`,
     `test_cli_stamps_the_given_tree` (`stamp fast <root> <tree>`);
   - `test_record_review_revokes_on_a_verdict_line_out_of_format`, параметры `Итог. Вердикт:
     вернуть`, `Вердикт - вернуть`: после «принять» по дереву отметка `return` (переворот форм 1-2
     `test_hs_old_items`);
   - `test_a_subject_line_with_two_subjects_revokes`: `Предмет: план и код` после «принять» даёт
     `return` (форма 3); `Предмет: план` по-прежнему не трогает отметку
     (`test_a_review_of_a_plan_or_a_document_leaves_the_stamp` без правки);
   - `test_cli_tree_lists_the_code_paths_it_covers`: stdout ровно id дерева, stderr
     `covers code changed since HEAD: job.py`; без правок `covers no code changed since HEAD`;
   - `test_describe_stamp_says_covers_after_a_markdown_edit` (переворот H6) и
     `test_describe_stamp_counts_the_code_paths_of_a_stale_stamp`;
   - `test_markdown_under_dbt_is_code` (`dbt/models/docs.md` в `code_changes`; переворот H1 для
     dbt) и `test_markdown_of_the_agent_roles_stays_no_code` (`.claude/agents/x.md`, HS-N8);
   - в `test_agent_hooks.py`: `test_commit_after_full_then_fast_verify_is_allowed` (все три
     отметки, `write_stamp(repo, "fast")`, `COMMIT` даёт allow) и
     `test_stop_gate_blocks_an_edit_of_a_dbt_docs_block`.
   Изменённые ожидания (правило меняется, не ослабляется): `test_describe_stamp` ждёт
   `stale (code changed: 1 path)`; `test_make_check_runs_lint_and_test_through_run_check` ждёт
   слова `uv run python scripts/agent_state.py check "<REPO>"`.
2. `scripts/agent_state.py` (`implementer` пишет копию `<scratchpad>/P02/agent_state.py` и гоняет
   тесты в копии репозитория `<scratchpad>/P02/repo`; в репозиторий файл кладёт оркестратор одной
   командой `cp <scratchpad>/P02/agent_state.py scripts/agent_state.py`, окно подтверждения,
   владелец жмёт «да»; подагент на окне останавливается, `13-harness.md`, раздел 3):
   - `write_stamp(root, mode, tree=None)`: `tree` по умолчанию `tree_hash(root)`, данный id
     проверить `_is_tree`, иначе `ValueError`. При `mode == "fast"`: если в `.verify-stamp` режим
     `full` и `_code_diff(root, full.tree, tree)` пуст, отметку не трогать и вернуть
     `kept the full verify stamp of <written_at>: it covers this tree`; `CalledProcessError`
     (дерево отметки пропало) значит писать `fast`. Возвращает строку о том, что сделано.
   - CLI: `stamp fast|full <root> [<tree>]`; строку от `write_stamp` в stderr. `stamp check`
     прежний. Строку `usage` обновить.
   - `tree <root>`: id в stdout; в stderr `covers code changed since HEAD: <пути через запятую>`
     по `code_changes(root)` (больше 20: первые 20 и `and N more`) или
     `covers no code changed since HEAD`.
   - `describe_stamp`: `<mode> at <time>, fresh` |
     `, covers (only Markdown and docs/ changed since)` | `, stale (code changed: N path[s])` |
     `, stale (the stamped tree is gone)`.
   - `_is_code`: `.md` не код только вне `dbt/`: `not (path.endswith(".md") and not
     path.startswith("dbt/")) and not path.startswith("docs/")` или равное по смыслу.
   - `_read_report`: строка, у которой нет головы ни одного поля, но есть слово `вердикт` (любой
     регистр, разметка вокруг) и любое слово из `VERDICTS`, добавляет `verdict` в `garbled`
     (отзыв, `return`). Строка предмета, где названо больше одного из `код|план|документ`, это
     `garbled subject` (отзыв). Докстринг `record_review` дополнить этими случаями.
   Проверка: `uv run pytest tests/unit/test_agent_state.py -q`, `uv run ruff check scripts`,
   `uv run mypy`.
3. `scripts/verify.sh` (`implementer`). После разбора режима (`:22-27`):
   `python="$ROOT/.venv/bin/python"`, `tree=$("$python" "$ROOT/scripts/agent_state.py" tree "$ROOT"
   2>/dev/null) || tree=""`. Строку `:67` заменить: при непустом `tree` вызвать
   `"$python" ... stamp "$mode" "$ROOT" "$tree"`; при пустом `tree` или ненулевом коде напечатать в
   stderr `verify: the working tree was not stamped (<причина>); the checks above passed`.
   Затем `echo "verify ok"`, код 0. Комментарий `:14` привести к правде (отметка дерева на старте,
   сбой отметки не роняет verify).
   Почему сбой отметки не роняет verify: verify доказывает данные, отметка это доказательство для
   харнесса. Гейт коммита закрыт без отметки (fail-closed), поэтому пропущенная отметка проявится
   отказом коммита с причиной, а не ложным зелёным; пользователь без git (ZIP) или без `.venv`
   получает `verify ok` вместо traceback в публичной команде. Stop-хук без отметки один раз просит
   verify (как сейчас).
   Тесты первыми в `test_verify_script.py`: режим фейка «здоровый стек» (переменная окружения
   фейка, например `STACK=healthy`): `exec -T kafka` печатает `oltp.shop.orders:0:5`; запрос
   Trino с `max(kafka_offset) + 1` печатает ту же строку; с `having count(*)` печатает `0`; с
   `count(distinct source_table)` печатает `7` и, если задан `EDIT_FILE`, дописывает в него
   строку; любой иной `psql` и Trino печатают `1 x`. Корень: `git init` и коммит, `.gitignore` с
   тремя отметками, копии `verify.sh`, `lib.sh`, `agent_state.py`, симлинки `reconcile_sql.py` и
   `contracts` как `tests/unit/test_reconcile_shell.py:48-49`, `.venv/bin/python` симлинк на
   `sys.executable`. Тесты (режим `--no-merge`):
   - `test_verify_stamps_the_tree_it_started_on`: `EDIT_FILE=<root>/job.py`; итог `verify ok`,
     дерево в `.verify-stamp` равно `tree_hash` до запуска и не равно текущему (HS-07);
   - `test_verify_is_ok_when_the_tree_cannot_be_stamped`: корень без `git init`; код 0, последняя
     строка stdout `verify ok`, stderr содержит `was not stamped`, `.verify-stamp` нет (IN-03);
   - `test_verify_runs_agent_state_with_the_project_python`: в тексте `verify.sh`, `report.sh`,
     `Makefile` нет `python3` в одной строке с `agent_state`.
4. `scripts/report.sh:14`: `"$root/.venv/bin/python" scripts/agent_state.py show ...`
   (`|| echo unreadable` остаётся). `Makefile:157`: `@uv run python scripts/agent_state.py check
   "$(CURDIR)"` (как цели `secrets` и `hooks`; в скриптах принят `.venv/bin/python`).
   `implementer`; проверка:
   `uv run pytest tests/unit/test_report.py tests/unit/test_agent_state.py -q`.
5. HS-12 (`implementer`): в двух тестах `test_agent_hooks.py:1165-1187` подложить `fake_docker`
   (пустые `running`, `stopped`, `rows`) через `tmp_path_factory` и `monkeypatch`; утверждения
   те же.
6. Проверки: `make check`; пробы из «Вход» п. 6 снова: красными должны стать ровно
   `test_f1_fast_after_full_downgrades_the_stamp`,
   `test_h6_describe_says_stale_for_a_stamp_that_covers`,
   `test_h1_markdown_read_by_tools_is_not_code[dbt/models/docs.md]`; `test_hs_old_items.py`
   печатает `return` для форм 1-3 и прежний `return` для формы 4. Остальные пробы (F2, F2b, F3,
   F5, H2..H5, H7, H1 для `.claude`) прежние: их переворачивает P03 или они «не делать».
7. Ревью: `reviewer`, предмет `код`, diff и раздел «Готово, когда» этого файла. Исправления по
   `13-harness.md`, раздел 4. Затем цикл verify (раздел 5) и коммит
   `harness: fast verify keeps a covering full stamp, out-of-format verdicts revoke, verify stamps
   its start tree with the project python`.

## Готово, когда

- [ ] вывод шага 1 до правки: каждый новый тест `FAILED`, сохранён в «Итог»
- [ ] `uv run pytest tests/unit/test_agent_state.py tests/unit/test_agent_hooks.py tests/unit/test_verify_script.py tests/unit/test_report.py -q` -> `passed`, 0 failed
- [ ] `grep -nE 'python3.*agent_state' scripts/verify.sh scripts/report.sh Makefile` -> пусто
- [ ] `python3 scripts/agent_state.py tree .` -> одна строка id в stdout, в stderr `covers code changed since HEAD:` со списком
- [ ] в `<scratchpad>/P02/trap/docker` скрипт, который дописывает строку в `<scratchpad>/P02/trap/log` и выходит 1; `PATH=<scratchpad>/P02/trap:$PATH uv run pytest tests/unit/test_agent_hooks.py -q -k "reports_state_goal_and_stamp or survives_missing_docs"` -> 2 passed, файла `log` нет
- [ ] пробы аудита: красные ровно три теста из шага 6
- [ ] `make check` -> зелёный; `python3 scripts/agent_state.py show check .` -> `check at ..., fresh`
- [ ] вердикт `reviewer` «принять» или «принять с замечаниями» по дереву
- [ ] цикл verify: `make verify` -> последняя строка `verify ok`; затем `make verify-fast` -> в stderr `kept the full verify stamp`; `python3 scripts/agent_state.py show verify .` -> `full at ..., fresh`
- [ ] коммит прошёл гейт; «Итог» ниже, статус в README папки, верх HANDOFF

## Не входит

- Правила о покрытии ревью и «одно ревью кода за раз» (HS-05, текст), HS-09, HS-10: P04.
- Уровни гейта, база Stop-хука, стартовый хук (HS-02, HS-03, HS-11): P03.
- Хостовые инструменты в README «Requirements» (IN-03, п. 3): P13 вместе с DC-19; не делать
  здесь.
- `python3 -c` со стандартной библиотекой в `scripts/chaos/*.sh` и `Makefile:119`: версия не важна.
- Хуки сами идут под системным `python3` (`.claude/settings.json`) и импортируют `agent_state.py`:
  на хосте агента нужен Python 3.11 или новее. Это требование харнесса, не публичной команды.

## Риски и откат

- Хуки импортируют `agent_state.py` на каждом вызове: ошибка в нём ломает `stop_gate.py`,
  `session_context.py` и гейт коммита (`guard.py` ловит сбой и спрашивает владельца). Поэтому файл
  кладётся в репозиторий только после зелёных тестов в копии. Откат: владелец
  `git checkout -- scripts/agent_state.py` (для агента это класс C).
- Новый разбор вердикта отзывает чаще: прозаическая строка со словом «вердикт» и словом вердикта
  отзывает отметку. Это закрытая сторона, цена один проход ревью.
- Сохранённый `full` после `fast`: держится, только пока код не менялся (тот же `_code_diff`, что
  у гейта), иначе пишется `fast`.

## Расхождения с отчётом аудита

- IN-03 называет `scripts/chaos/lib.sh:252` (`python3 reconcile_sql.py`). Не меняется:
  `reconcile_sql.py` нарочно только стандартная библиотека и проверяется запуском `-I -S`
  (`tests/unit/test_reconcile_sql.py:121`); синтаксис его и `airflow/dags/lakehouse/reconcile.py`
  разобран как 3.10 (`ast.parse(..., feature_version=(3, 10))`, 13.11). Замена на `.venv` сломала бы
  фейк `tests/unit/test_chaos_silver_kill.py:157-166`, где `.venv/bin/python` изображает реплеер.
  3.11 нужен только `agent_state.py` (`from datetime import UTC`), поэтому меняются его вызовы.
- `Makefile:157` переводится на `uv run python`, а не `.venv/bin/python`: так устроены
  остальные цели.
- HS-04 предлагал «`код` среди слов предмета значит код»: тогда `Предмет: документ, не код` с
  «принять» открыл бы гейт. Взят закрытый вариант: два предмета в строке отзывают.
- HS-07 и IN-03 предлагали тест «по образцу существующих проб»: существующие пробы до отметки не
  доходят (`test_verify_script.py:29-63`), нужен режим «здоровый стек» из шага 3.
- IN-03, п. 3 (хостовые инструменты в README): при сведении 18.11 отдан P13 вместе с DC-19.
- Во время сверки guard отказал на `python3 -c` с `ast.parse` по трём файлам, среди которых
  `agent_state.py` («writes a gate stamp by hand»): живой случай HG-08. Проверка повторена без
  этого файла; для `agent_state.py` хватает строки `:25`.

## Итог
