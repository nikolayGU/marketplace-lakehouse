# HS. Харнесс: отметки и гейты

Дерево аудита: HEAD `a8c1d49` плюс правки владельца (`.github/workflows/ci.yml`,
`tests/unit/test_workflows.py`, `OPERATIONS.md`, `docs/HANDOFF.md`, `docs/NEXT_SESSION.md`),
рабочее дерево `5201ce73...` (`python3 scripts/agent_state.py tree .`). В репозитории ничего не
менялось. Опыты: копия `HS-work/copy` (файлы `git ls-files -co --exclude-standard` плюс копия `.git`)
и pytest-пробы `HS-work/test_hs_probes.py` (22 passed) и `HS-work/test_hs_old_items.py` (4 passed);
каждая проба утверждает ТЕКУЩЕЕ поведение, зелёная проба значит подтверждённую находку. Пробы
делают `git commit` во временных репозиториях pytest так же, как фикстуры `tests/unit`.

Отказы guard во время аудита (не обходились, записаны): (1) первая команда `git ls-files ...; git
check-ignore -v ... <имена трёх отметок>; grep ... Makefile` получила deny «writes a gate stamp by
hand» (чтение со словами имён отметок в составной команде, известный пункт 14 §7, строки 730-733);
(2) `cd <scratchpad>/copy && git init && git add -A && git commit` получила deny «git commit without
a full make verify on this working tree»: гейт сверяет отметки основного репо и для коммита в чужом
репозитории (HS-09). Побочный эффект: одна команда `agent_state.py tree .` ушла в основной репо
(сбой `cd` в копию до её создания); она только читает рабочее дерево, но пишет loose-объекты в
`.git/objects`, как каждый вызов хука.

## Оценки

- QA (тесты харнесса): 4 из 5. 151 тест `test_agent_state.py` за 5.9 с и 88 тестов хуков отметок за
  11.2 с; 3 из 3 мутаций в копии красные; минус: две пробы старых дыр (HS-04) и тесты
  `session_context` на docker хоста (R-08).
- Тимлид, нанимающий: 4 из 5. Гейт «verify, check, ревью по id дерева» редок и убедителен, живые
  доказательства есть; минус: цена одного коммита (полный цикл verify с паузой DAG) видна в журнале.
- Руководитель (цена владения в режиме редкой поддержки): 2 из 5. Любой коммит, даже Markdown,
  требует поднятого стека 16 GB и полного verify; Stop-хук блокирует ход из-за чужой правки.
- Архитектор: 3 из 5. Отметка verify привязана к рабочему дереву, а verify проверяет запущенные
  образы; связь «дерево проверено» и «код проверен» нигде не названа (HS-02, разрыв с продом).

## Сильные стороны

- Хэш дерева через одноразовый индекс: не зависит от staging, включает неотслеживаемые, исключает
  игнорируемые: `scripts/agent_state.py:105-112`; тесты `test_tree_hash_follows_content_not_staging_or_commits`,
  `test_tree_hash_ignores_gitignored_files`.
- `make check` ставит отметку только дереву, которое не менялось во время прогона, и без переменных
  make и pytest: `scripts/agent_state.py:273-287`; тесты `test_agent_state.py:802-834`.
- Вердикт ревью привязан к id дерева, который ревьюер напечатал в начале, проверен как объект tree;
  правка кода после него не записывается: `scripts/agent_state.py:240-270`; мутация «убрать отказ
  при вернуть» в `guard.py:943` даёт 2 failed (`test_commit_of_code_is_refused_after_a_return_verdict`,
  `test_a_late_return_without_a_tree_closes_the_gate_an_accept_opened`).
- Отказоустойчивость: Stop-хук не зацикливает сессию (`stop_gate.py:45-51`, мутация
  `stop_hook_active` даёт failed `test_stop_gate_lets_the_turn_end`), `review_stamp.py` никогда не
  блокирует (`:35-39`), guard закрыт при сбое (`settings.json:35`, `guard.py:1055-1062`). Вне git:
  stop_gate выходит 0 с причиной, guard даёт окно (проба H7).
- Разбор путей `-z --no-renames` без кавычек и с переносом кода в `docs/` или `.md`:
  `agent_state.py:169-184`, 8 тестов `test_agent_state.py:141-251`.
- Живые доказательства: отметка ревью, записанная хуком сегодня, `accept-with-notes
  2026-11-13T12:27:28Z b3aa4e31...` (файл отметки ревью, дерево = HEAD плюс `ci.yml` и
  `test_workflows.py`, `git diff --stat HEAD b3aa4e31`), совпадает с HANDOFF:24-25 «reviewer
  принять с замечаниями»; живой отказ гейта HANDOFF:409; инцидент HANDOFF:215 (отметка ревью легла
  на дерево с чужим кодом) показывает, что хук работал в сессии 05.11.
- Стартовый хук находит стек по метке каталога compose, а не по имени проекта, и называет упавшие
  контейнеры с restart-политикой (инцидент 27.10 и 30.10): `session_context.py:17-20,56-93`.

## Старый бэклог

| ID | статус сейчас | делать / не делать | причина |
|---|---|---|---|
| R-08 (часть HS) | открыт: `test_agent_hooks.py:1165-1187` два теста `session_context` зовут docker хоста (самые медленные в выборке, 0.46 и 0.41 с) | делать (HS-12) | дёшево, тест не зависит от хоста |
| R-08 (`test_agent_state.py:518-523`) | открыт, тест по подстроке роли | не делать | требование и есть текст роли |
| R-27 (часть HS) | тесты отметок и гейтов: 151 за 5.9 с, 88 за 11.2 с | не делать в HS | основное время у guard, область HG |
| Б11 | закрыт П-3 30.10; остаток: ремарка «(не блокируют)» в строке вердикта всё ещё отзывает (проба F3), роль запрещает её `reviewer.md:54-57`, тест `test_agent_state.py:518` | не делать | после 30.10 в журналах отзывов нет (`grep -i revoked docs/HANDOFF.md` пусто) |
| Б12 | закрыт: `stop_gate.py:26-41`, тест `test_stop_gate_lets_markdown_edited_after_a_verify_end_the_turn` | закрыт | |
| 14 §7, п. 23 гейт по индексу | открыт по решению: проба H3, коммит застейдженного непроверенного кода при чистом рабочем дереве `allow` | не делать | правило «один verify, один коммит», частичные коммиты в поддержке редки |
| 14 §7, v0.3 средняя «вернуть вне формата» | открыт: `Итог. Вердикт: вернуть`, `Вердикт - вернуть`, `Предмет: план и код` оставляют прежнее «принять» (проба `test_hs_old_items.py`, 3 из 3) | делать (HS-04) | ложный зелёный гейта |
| 14 §7, закрывающий текст «Вердикт: принять» без дерева отзывает | открыт (проба: `return`) | не делать | отказ закрытый, цена один проход |
| 14 §7, guard на составной команде с чтением отметки (строки 730-733) | открыт, воспроизведён сегодня (отказ 1 выше) | делать, в пакете HG | ложный отказ на чтении |
| 14 §7, `make check > log` и «make check» в сообщении коммита | вне HS | передать HG | `guard.py:172-185` |
| Память `verify-fast-overwrites-full-stamp`, NEXT_SESSION:92-93 | открыт (проба F1) | делать (HS-01) | |
| NEXT_SESSION:90-91 два ревьюера кода перебивают отметку | открыт, тест закрепляет «позднее побеждает» `test_agent_state.py:738-744` | делать правилом (HS-05) | |

## Находки «делать»

### HS-01 [средняя] `make verify-fast` затирает полную отметку
Где: `scripts/agent_state.py:120-129` (`write_stamp` пишет `fast` в тот же файл), `scripts/verify.sh:67`,
гейт `.claude/hooks/guard.py:931-935` (нужен именно `full`).
Факт: проба F1: после всех трёх отметок коммит `allow`; `write_stamp(repo, "fast")` на том же дереве;
коммит `deny: git commit without a full make verify on this working tree`. Сейчас в репо отметка
verify `fast 2026-11-13T12:17:02Z b3aa4e31...`. Stop-хук и регламент (`13-harness.md:192-193`, раздел 8
п. 1) сами просят `verify-fast`, поэтому затирание штатное.
Чем плохо: второй полный цикл verify (пауза трёх DAG, стоп scheduler, merge) ради коммита, код не
менялся (29.10 W6-T02, память агента).
Правка: в `write_stamp` при `mode == "fast"`: прочитать текущую отметку verify; если она `full` и
покрывает текущее дерево (свежая или с неё менялись только Markdown и `docs/`), оставить её и
напечатать в stderr `kept the full verify stamp of <time>: it covers this tree`. Иначе писать `fast`.
Тесты первыми: `test_a_fast_verify_keeps_a_full_stamp_that_covers_the_tree` (full, правка `.md`,
fast: режим `full`), `test_a_fast_verify_replaces_a_full_stamp_of_older_code` (full, правка `.py`,
fast: режим `fast`), в `test_agent_hooks.py` `test_commit_after_full_then_fast_verify_is_allowed`.
Проверка: `uv run pytest tests/unit/test_agent_state.py tests/unit/test_agent_hooks.py -q -k "fast"`
зелёный; на HEAD новые тесты красные.
Размер: S; класс A; `scripts/agent_state.py` с окном подтверждения, тесты агент.
Старый ID: память агента, NEXT_SESSION:92-93.

### HS-02 [средняя] Полный verify на каждый коммит, в том числе Markdown и код вне стека
Где: `guard.py:931-937` (verify всегда, до проверки `code_changes`), `stop_gate.py:29`,
`13-harness.md:219-221,228-232`.
Факт: проба F2: правка только `docs/a.md`, без отметки `deny ... a full make verify`; с отметкой
`fast` тоже `deny`. HANDOFF:17 «полный цикл verify перед каждым коммитом кода ... verify ok трижды» за
одну карточку; HANDOFF:20-28: починка CI (`.github/workflows/ci.yml` и тест) ждёт цикла verify.
Факт: verify проверяет запущенные образы и смонтированные каталоги, а не рабочее дерево: у
`spark-silver` `image: lakehouse/spark:dev` без монтирования `streaming/` (`docker/compose.yaml:410-411`),
код `streaming/` и `contracts/` попадает только в образ (`streaming/Dockerfile:35-37`); смонтированы
`airflow/dags`, `dbt`, `observability` (`docker/compose.yaml:579-580,662,689-690`).
Чем плохо: в режиме поддержки стек обычно не поднят; правка README или CI требует стека 16 GB и
паузы DAG, хотя verify про эти файлы ничего не доказывает. Для `streaming/` полный verify без
пересборки образа даёт ложное «проверено».
Правка (решение владельца, см. ниже): в `scripts/agent_state.py` функция `needs_stack(path)`:
ложь для `tests/`, `.github/`, `.claude/`, `.pre-commit-config.yaml`, `.yamllint`, `.sqlfluff`;
истина для всего прочего кода (консервативно). Гейт `commit_gap`: нет кода против HEAD:
пусто (Markdown и `docs/` коммитятся без отметок); код только вне стека: `make check` и ревью; код
стека: ещё `verify` любого режима; изменения в `streaming/` или `contracts/`: `full`, и в
`13-harness.md` §5 строка «перед полным verify пересобрать образ spark (`make up --build`), иначе
verify проверяет старый код». Stop-хук просит `verify-fast` только для кода стека. По желанию:
`git commit ... -- <пути>`, где все пути Markdown или `docs/`, гейт пропускает (коммит документов
при чужой правке кода в дереве, проба F2b).
Тесты первыми: `test_markdown_only_commit_needs_no_stamp`, `test_ci_and_tests_commit_needs_check_and_review_only`,
`test_stack_code_commit_needs_a_verify`, `test_streaming_commit_needs_a_full_verify`,
`test_stop_gate_ignores_code_outside_the_stack`.
Проверка: те же тесты; проба F2 из `HS-work/test_hs_probes.py` после правки красная.
Размер: M; `agent_state.py` агент (окно), `guard.py` и `stop_gate.py` патч владельцу; решение
владельца; правка `13-harness.md` §5 и `AGENTS.md` (строки «Хуки», «make verify пишет отметку») с окном.
Старый ID: нет (связано с 13-harness §5 «Docker недоступен»).

### HS-03 [средняя] Stop-хук блокирует ход из-за чужой незакоммиченной правки
Где: `stop_gate.py:26-41` (`code_changes` против HEAD), докстринг `stop_gate.py:2` и
`AGENTS.md` («останавливает конец хода с изменённым кодом»).
Факт: копия текущего дерева без отметки: `{"decision": "block", "reason": "Code changed
(.github/workflows/ci.yml, tests/unit/test_workflows.py) ..."}` за 0.12 с; проба F5 то же на
синтетике. Сессия аудита код не меняла.
Чем плохо: каждый конец хода любой сессии с чужой правкой в дереве стоит лишнего хода агента
(`verify-fast` или «не проверено»); поведение расходится с докстрингом «a turn that changed code».
Правка: базовое дерево сессии. `session_context.py` на SessionStart пишет id дерева в
`$(git rev-parse --git-path claude-base-<session_id>)` (каталог `.git`, рабочее дерево и хэш не
меняются), только если файла ещё нет (resume и compact не сдвигают базу); файлы старше 7 дней
удаляет. `stop_gate.py`: при наличии базы проверяемые пути `_code_diff(base, current)` вместо
`code_changes`; без базы прежнее поведение. Функции чтения и записи базы в `agent_state.py`.
Тесты первыми: `test_stop_gate_ignores_code_changed_before_the_session`,
`test_stop_gate_blocks_code_changed_in_the_session`, `test_a_resumed_session_keeps_its_base`,
`test_stop_gate_without_a_base_behaves_as_before`.
Проверка: тесты; живьём: новая сессия при грязном `ci.yml` заканчивает ход без блока.
Размер: M; хуки патчем владельцу, `agent_state.py` агент (окно); не проверено, что `session_id`
приходит в SessionStart и Stop (сверка HC).
Старый ID: нет.

### HS-04 [средняя] «Вернуть» вне формата роли оставляет прежнее «принять» в силе
Где: `scripts/agent_state.py:71-75` (хвост поля `\b.*`: `Предмет: план и код` читается как `план`),
`:204-217` (строка без `Вердикт:` в начале не замечается), докстринг `:247-249` обещает «never leaves
an earlier accepting verdict in force».
Факт: `HS-work/test_hs_old_items.py`: после «принять» по дереву `Итог. Вердикт: вернуть` и
`Вердикт - вернуть` дают `nothing recorded: no verdict line`, `Предмет: план и код` даёт
`nothing recorded: not a review of code (план)`; отметка остаётся `accept`.
Чем плохо: ложный зелёный гейта коммита: ревьюер вернул, коммит проходит.
Правка: строка, где есть слово «вердикт» и любое слово вердикта, но нет годной строки, считается
испорченной (`garbled verdict`, отзыв); в строке предмета наличие `код` среди слов значит код.
Тесты первыми: три формы выше дают `return`; `Предмет: план` по-прежнему не трогает отметку.
Проверка: `uv run pytest tests/unit/test_agent_state.py -q -k "verdict or subject"`.
Размер: S; `agent_state.py` агент (окно), тесты агент.
Старый ID: 14-closeout-spec §7 (ревью v0.3, круг 1, средняя).

### HS-05 [средняя] Отметка ревью накрывает чужой код в дереве; параллельные ревьюеры
Где: отметка одна на всё дерево (`agent_state.py:269`), ревьюер смотрит diff брифа
(`reviewer.md:3,14-15`); `test_agent_state.py:738-744` закрепляет «позднее побеждает».
Факт: HANDOFF:215 «отметка ревью П-5 как кода легла на дерево с непроверенным кодом Б17»; проба H4:
«вернуть», затем «принять» по тому же дереву от второго ревьюера: коммит `allow`. Правило «одно ревью
кода за раз» только в NEXT_SESSION:90-91.
Чем плохо: код без ревью проходит гейт вместе с проверенным.
Правка: `agent_state.py tree <root>` печатает в stderr `covers code changed since HEAD: <пути>`;
`reviewer.md`: строка «Дерево» значит «я просмотрел каждый путь этого списка; путь вне брифа:
назвать его в отчёте или «вернуть»»; `13-harness.md` §4: «одно ревью кода за раз».
Тест первым: `test_cli_tree_lists_the_code_paths_it_covers`.
Проверка: тест; `python3 scripts/agent_state.py tree .` в текущем дереве называет `ci.yml` и
`test_workflows.py`.
Размер: S; `agent_state.py`, `reviewer.md`, `13-harness.md` с окном подтверждения.
Старый ID: NEXT_SESSION:90.

### HS-06 [низкая] Описание отметки «stale» там, где гейт считает её покрывающей
Где: `agent_state.py:153-157`, вызовы `session_context.py:124-128`, `scripts/report.sh:13-16`.
Факт: сегодня старт сессии печатает `Verify stamp: fast at 2026-11-13T12:17:02Z, stale`, хотя от
дерева отметки менялись только Markdown (`git diff --stat HEAD b3aa4e31` два файла кода, оба в
отметке); проба H6: `full ..., stale | commit: allow`.
Чем плохо: агент запускает лишний `verify-fast` или считает коммит закрытым.
Правка: `describe_stamp` печатает `fresh`, `covers (only Markdown and docs/ changed since)` или
`stale (code changed: N paths)`.
Тест первым: `test_describe_stamp_says_covers_after_a_markdown_edit`.
Размер: S; `agent_state.py` с окном.
Старый ID: нет.

### HS-07 [низкая] `verify.sh` ставит отметку дереву на момент конца, а не начала
Где: `scripts/verify.sh:67` (`write_stamp` считает дерево в конце), ожидание до `VERIFY_WAIT=900` с
(`:54-56`) плюс merge.
Факт: чтение кода; `run_check` сравнивает дерево до и после (`agent_state.py:277-286`), verify нет.
Чем плохо: правка кода параллельным агентом во время verify получает отметку как проверенная.
Правка: в начале `tree=$(python3 "$ROOT/scripts/agent_state.py" tree "$ROOT")`, в конце
`stamp "$mode" "$ROOT" "$tree"`; `write_stamp(root, mode, tree=None)` пишет данный id. Правка
после старта тогда не покрыта, гейт попросит новый verify.
Тесты первыми: `test_write_stamp_uses_the_given_tree`; в `test_verify_script.py` подделка docker
меняет файл посреди прогона, отметка равна дереву старта.
Размер: S; `verify.sh` и тесты агент, `agent_state.py` с окном.
Старый ID: нет.

### HS-08 [низкая] `dbt/models/docs.md` считается не кодом
Где: `agent_state.py:160-161` (`not path.endswith(".md") and not path.startswith("docs/")`).
Факт: `dbt/models/docs.md` содержит 7 блоков `{% docs %}`, на них ссылаются `_marts.yml:23,41,43,66`
и `_core.yml:19` (`doc('gmv')`); проба H1: после всех отметок правка `docs.md` даёт Stop `end` и
коммит `allow` без check и ревью. CI запускает `make dbt-parse` (`ci.yml:60`).
Чем плохо: сломанный блок docs проходит гейт, CI красный.
Правка: `.md` не код только вне `dbt/`. `.claude/**.md` оставить не кодом (правка роли без
ревью-прохода; единственный тест на роль по подстроке).
Тест первым: `test_markdown_under_dbt_is_code`.
Размер: S; `agent_state.py` с окном.
Старый ID: нет.

### HS-09 [низкая] Гейт коммита срабатывает на коммит в копии в scratchpad
Где: `guard.py:1038-1044` (любой `git commit` в тексте, отметки `ROOT`).
Факт: отказ 2 этой сессии; проба H5 `deny ... a full make verify, make check and a reviewer verdict`.
Чем плохо: ревьюер или аудитор с `git init` в копии получает отказ; бриф этого аудита предлагал
именно так.
Правка (без кода): в `13-harness.md` §3 и `reviewer.md` строка «в копии `git init` и `git add -A`
без коммита; базу брать из `cp -a .git`». Патч guard не нужен.
Размер: S; документы с окном.
Старый ID: нет.

### HS-10 [низкая] Правило «отметку пишет только `reviewer`» живёт только в памяти агента
Где: `review_stamp.py:31` (`agent_type == "reviewer"`); память `model-split-preference.md`
(«not reviewer when no tree verdict is wanted»); в `13-harness.md` §4 и `AGENTS.md` этого нет.
Правка: `13-harness.md` §4: «Отметку пишет только роль `reviewer` (`agent_type`); аудит и ревью
без вердикта по дереву: `general-purpose` на Opus, отметку не трогает. После отчёта: `python3
scripts/agent_state.py show review .`. Ревьюер упёрся в `maxTurns: 100` (`reviewer.md:6`): SendMessage
«отчёт по сделанному», хук запишет его вердикт».
Размер: S; документы с окном.
Старый ID: нет.

### HS-11 [низкая] Стартовый хук: 81 строка, около 2 тыс. токенов
Где: `session_context.py:131-162`.
Факт: прогон 0.54 с; 7918 байт, 843 слова, 81 строка (`HS-work/session_context.txt`). По оценке
(кириллица 2.3, прочее 3.5 символа на токен): коммиты около 325, HANDOFF около 1070, NEXT_SESSION
около 295, 20 строк контейнеров около 275 токенов; всего около 2060.
Чем плохо: HANDOFF агент и так читает по `AGENTS.md`; 20 строк «Up (healthy)» без сигнала.
Правка: контейнеры одной строкой `20 running, 20 healthy` плюс только нездоровые и упавшие;
коммиты `%h %<(72,trunc)%s`; три отметки по строке через исправленный `describe_stamp` (HS-06).
HANDOFF и NEXT_SESSION оставить: это холодный старт. Экономия около 500 токенов.
Тест первым: `test_session_context_lists_only_unhealthy_containers` на `fake_docker`.
Размер: S; патч владельцу.
Старый ID: нет.

### HS-12 [низкая] Тесты `session_context` зовут docker хоста
Где: `tests/unit/test_agent_hooks.py:1165-1187`.
Правка: `fake_docker` или `PATH` без docker в обоих тестах.
Проверка: `uv run pytest tests/unit/test_agent_hooks.py -q -k session_context` при `PATH` без docker
тот же результат.
Размер: S; тесты агент.
Старый ID: R-08.

### HS-13 [низкая] `.claude/settings.local.json`: мусорные и широкие разрешения
Где: `.claude/settings.local.json:12-41` (одноразовые `echo "... rc=$?"`, `mkdir` scratchpad другой
сессии `:14`, `curl` hub.docker.com `:38-41`), широкие `Bash(docker compose *)` `:13`,
`Bash(git commit *)` `:34`, `Bash(uv run *)` `:11`; `enabledPlugins` выключает `context7` `:45`
при правиле `CLAUDE.md` «версии через context7» (MCP Context7 доступен коннектором claude.ai).
Чем плохо: между guard и записью в стек нет второго слоя: `docker compose down` без окна, если guard
пропустит форму.
Правка: владелец удаляет одноразовые строки и широкие `docker compose *`, `git commit *`; файл
локальный, вне git.
Размер: S; только владелец.
Старый ID: нет.

## Находки «не делать»

| ID | что | почему не делать |
|---|---|---|
| HS-N1 | Гейт по индексу (проба H3) | правило «один verify, один коммит» (14 §7); частичные коммиты в поддержке редки |
| HS-N2 | Смягчить слова отмены в скобках (проба F3: «(не блокируют)», «(нет высоких)» отзывают) | роль уже запрещает ремарки в строке, отзывов в журналах после 30.10 нет; ослабление ради редкого случая |
| HS-N3 | Не-Markdown в `docs/` (патчи, `corpus.json`, `probe.py.txt`, png) считается не кодом (проба H2) | ничто в коде, CI и тестах их не читает (`grep -rn "docs/planning"` по `*.py`, `*.yml`, `*.sh`, Makefile: только комментарии) |
| HS-N4 | Закрывающий текст с «Вердикт: принять» без дерева отзывает | закрытый отказ, цена один проход |
| HS-N5 | Отдельная отметка на ревьюера или предмет | сложнее, закрывается правилом HS-05 |
| HS-N6 | `git gc` loose-объектов (`git count-objects -vH`: 3435, 25.32 MiB, их пишет `tree_hash`) | gc сам сработает на 6700, выигрыша нет |
| HS-N7 | Права и подпись файлов отметок (0644, пишет любой процесс) | хук ловит ошибки, обход запрещён правилом (`13-harness.md` §2.1) |
| HS-N8 | `.claude/**.md` считать кодом | правка роли потребовала бы ревью-прохода; роль читает один тест по подстроке |

## Решения владельца

1. HS-02, уровни гейта. Рекомендую «да»: Markdown и `docs/` без отметок; `tests/`, `.github/`,
   `.claude/`, конфиги линтеров: `make check` и ревью; код стека: ещё `verify-fast`; `streaming/` и
   `contracts/`: полный verify после пересборки образа. Цена отказа: каждый коммит в поддержке
   требует стека и цикла с паузой DAG.
2. HS-03, база Stop-хука на старте сессии. Рекомендую «да».
3. HS-13, чистка `settings.local.json`. Рекомендую удалить одноразовые и широкие строки.

Порядок применения: (1) пакет агента: `scripts/agent_state.py` и тесты (HS-01, 04, 05, 06, 07, 08,
части HS-02 и HS-03), `scripts/verify.sh`, тесты HS-12; окно подтверждения на `agent_state.py`;
`make check`, `reviewer`. (2) Патч владельцу из копии: `guard.py` (`commit_gap`), `stop_gate.py`,
`session_context.py` (HS-02, HS-03, HS-11), с тестами; применяет владелец `git apply` и `make check`.
(3) Документы: `13-harness.md` §3-5, `AGENTS.md` «Хуки» и «Команды», `reviewer.md` (HS-02, 05, 09,
10), с окном. HS-02 и HS-03 трогают `stop_gate.py`: один патч.

## Разрыв с продом

- Гейты локальные, по тексту команды в хуках агента; в проде: защита ветки и обязательные проверки
  CI и ревью на сервере.
- Отметки это файлы без подписи; в проде: аттестации сборки (provenance) и статусы проверок в CI.
- Отметка verify связывает рабочее дерево с проверкой запущенных образов; в проде образ собирается
  из коммита, и проверяется именно он.
- Ревью делает модель того же поставщика; в проде: человек-владелец кода (CODEOWNERS).
- Хуки зависят от полей событий Claude Code без закреплённой версии контракта.
- Нет журнала решений гейта; в проде: лог решений с причиной.

## Не проверено

- Каким путём записана сегодняшняя отметка ревью (PostToolUse `SubagentHandback` или `SubagentStop`):
  в репо нет лога хука. Проверка: временный лог события в копии хука (патч владельцу) или сверка HC.
- Приходят ли `session_id` в SessionStart и Stop и `agent_type` в PostToolUse внутри подагента, по
  живому событию (нужно для HS-03); в репо только синтетические события тестов
  (`test_agent_hooks.py:1585-1605`). Сверка: агент HC.
- Приоритет `ask` хука над `allow` из `settings.local.json`: агент HC.
- Гонка HS-07 живьём не воспроизведена, только чтение кода.
- Полное время `tests/unit` и `make check`: области QA и HG.
