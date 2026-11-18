# P04. Правила агентов: один канон, роль `auditor`, HANDOFF и NEXT_SESSION, тест документов
Статус: не начат. Сессия Opus: `/task docs/planning/21-final-audit-2026-11-13/P04-harness-rules.md`

## Цель

Каждое правило агентов в одном файле без противоречий; аудит ролью `auditor`; документы агентов
в бюджетах байт под тестом; HANDOFF и NEXT_SESSION дают состояние, а не журнал.

## Находки пакета

| ID | Серьёзность | Суть | Где подробности |
|---|---|---|---|
| HR-01 | средняя | одни правила в 4-6 файлах, формулировки разошлись | `reports/HR.md`, «Матрица правил», HR-01 |
| HR-02 | средняя | аудит на `general-purpose` вне регламента, модель оркестратора не закреплена | HR-02 |
| HR-03 | средняя | HANDOFF 106 788 Б журнала, NEXT_SESSION 14 705 Б | HR-03, «Цена контекста» |
| HR-04 | средняя | 13-harness 34 774 Б, история и ID закрытых блоков внутри | HR-04 |
| HR-05 | средняя | документы харнесса не покрыты тестом | HR-05 |
| HR-06, PF-63 | низкая | `/security-review`, `/revise-claude-md` ни разу не исполнялись | HR-06 |
| HR-08 | низкая | память агента: устаревшее и дубли | HR-08, «Правила, которые живут только в памяти» |
| HR-09 | низкая | `/task` не знает пакетов и рутины сессии | HR-09 |
| HS-05, HS-09, HS-10 | средняя, низкая | одно ревью кода за раз; копия без коммита; отметку пишет только `reviewer` | `reports/HS.md` |
| HC-02, HC-03, HC-06, HC-07 | средняя, низкая | два пути записи вердикта; версия и перезапуск; глоб `mcp__*`; headless | `reports/HC.md` |
| PF-23 | средняя | в регламенте нет запуска `dbt_build` после паузы | «Вход» 5 |
| PF-62 | низкая | имя из пути домашнего каталога в HANDOFF и файле 12 | «Вход» 6 |

## Решения владельца и действия класса C

Одним вопросом в начале сессии (README папки, раздел 5, п. 3):
- В-17 роль `auditor` и «Opus или новее»; В-18 рутина сессии в `AGENTS.md`; В-19
  `docs/agent-rules.md` только правила кода, без `/security-review` и `/revise-claude-md`,
  плагин `claude-md-management` выключен; В-20 разделы HANDOFF до 13.11 и журнал «ок» до 06.11
  дословно в архив. Рутина этой сессии: циклы verify, коммит после гейта, push без force.
- В-20 включает разделы исполненных пакетов, если HANDOFF после переноса больше 20 480 Б (их
  «Итог» остаётся в файлах пакетов); В-27 это правка памяти агента (шаг 8).
- При «нет» (отказ записать в «Итог»): В-17: `auditor.md` не создавать, тест
  `test_auditor_role_reads_on_opus` не писать, в §1 регламента одной строкой остаётся практика
  аудита на `general-purpose` с Opus; В-18: рутину в `AGENTS.md` не писать, `:83` без оговорки;
  В-19: требования `/security-review` и `/revise-claude-md` остаются, бюджет `agent-rules.md`
  в тест не включать, шаг 7 не делать; В-20: перенос не делать, бюджеты HANDOFF и
  NEXT_SESSION в тест не включать; В-27: шаг 8 не делать.
- Файлы правил (A, C, R, H, `.claude/agents/`, `.claude/skills/`) получают окно guard: весь
  новый текст (diff из копии в scratchpad) показать владельцу одним блоком до первой правки,
  «ок» на блок; текст изменился: новый показ. `.claude/settings.json`: только патч (шаг 7).

## Зависимости

- После P02 и P03; хуки в A и H §5 описать по коду на момент исполнения. P03 применён
  (`grep -c 'def main' .claude/hooks/guard.py` -> 1, «Итог» P03): уровни гейта В-13, база
  Stop-хука В-14, `timeout` и `permissions` В-16 по docstring `guard.py`, `commit_gap`,
  docstring `stop_gate.py`, `.claude/settings.json`; правило «в сообщении коммита нет `make
  check` и имён отметок» не писать, если guard не читает сообщение. P03 отказан или отложен
  (README, раздел 3): хуки как сейчас (`AGENTS.md:37-55`, `13-harness.md:219-232`), правило о
  словах в сообщении в §5.
- P02: `verify-fast` не затирает полную отметку (HS-01): строку «полный verify последним» не
  писать, иначе она в §5; `agent_state.py tree` печатает покрытые пути (HS-05): `reviewer.md`
  ссылается на вывод. P01: починка CI закоммичена; чужой незакоммиченный код: стоп и вопрос.
- От P02 (`3af49bd`): `tree` печатает id в stdout и строку покрытия в stderr; в строку `Дерево:`
  шаблона (`reviewer.md`, 13-harness §4) идёт только id из stdout, иначе отметка отзывается.
  `AGENTS.md:33` «пишут `.verify-stamp` (tree id рабочего дерева)»: отметка ставится дереву на
  старте verify, `verify-fast` оставляет покрывающий `full`, сбой отметки не роняет verify.

## Вход

Сверить первым, строки искать по цитате:
1. `wc -c AGENTS.md CLAUDE.md docs/agent-rules.md docs/planning/13-harness.md docs/HANDOFF.md
   docs/NEXT_SESSION.md` -> 13.11: 12262, 1865, 12003, 34774, 106788, 14705.
2. Расхождения (матрица: `reports/HR.md`, «Матрица правил»; сверены 13.11, снять все):
   `AGENTS.md:83` «не переносится» против рутины `NEXT_SESSION.md:56-58`; `03-agent-tooling.md:
   17,48,67` «никогда push» против `AGENTS.md:73`; `CLAUDE.md:12` против `AGENTS.md:51-53`
   (агент не пишет, патч); `13-harness.md:13-14` «Других ролей не заводить» против аудитов на
   `general-purpose`; `:18` `"model"` в `settings.local.json` (`grep -c '"model"'` -> 0);
   `AGENTS.md:119` (`model` не трогать только сканерам) против `13-harness.md:14` (всем);
   `agent-rules.md:76` и `03:57` `Plan` вне ролей; `agent-rules.md:51` blast radius без push,
   `:56` области, `:65` `LEARNING.md`, `:68` шире `AGENTS.md:128-131`; `agent-rules.md:78-79`,
   `03:32,41,62-63` мёртвые `/security-review`, `/revise-claude-md`; `settings.local.json:45-46`
   выключает `context7` (приходит коннектором claude.ai) и `claude-md-management`;
   `06-spec-standard.md:34-36,52,53-54,124` (`CLAUDE.md`, `.superpowers/`, «Мелочи»);
   `SKILL.md:14-17,21-22,32-33`; `scout.md:28` (`10-w5-spec.md`); закрытые блоки
   `13-harness.md:3-4,23,43,60,124,180,192,196,268-271,337`; два списка стартовых команд
   `13-harness.md:266-267` и `NEXT_SESSION.md:50-55`; `NEXT_SESSION.md:1,17,76-89,123-125`;
   `HANDOFF.md:3,463,584-585`; `AGENTS.md:10-15`; `docs/planning/README.md:12,21`.
3. Номера §1-§7 13-harness не менять (`guard.py:1043` «section 5», `agent_state.py:241`
   «section 4», `SKILL.md` §1-§7). Хук старта `session_context.py:96-121` берёт первый
   `## Состояние` HANDOFF до `###` или `##`, первую строку NEXT_SESSION и первый абзац блока text.
4. Отметку пишет только `agent_type == "reviewer"` (`review_stamp.py:31`), путями
   `PostToolUse SubagentHandback` (auto mode) и `SubagentStop` (`.claude/settings.json:40-61`);
   `test_agent_state.py:518-523` держит в `reviewer.md` «только слова вердикта» и «следующей
   строкой».
5. PF-23: `airflow/dags/dbt_build.py:15` `schedule=[Asset(SILVER_ASSET_NAME)]`; событие при паузе
   теряется (`16-audit-2026-11-06/FINDINGS_REGISTER.md:61-80`: `created_dagruns: []`,
   `manager.py:354 if not ref.dag.is_paused`); правило есть в `OPERATIONS.md:637-645`, в
   13-harness нет (`:50-54`, `:203-209`).
6. PF-62: `git grep -n -i -I "$(basename "$HOME")" -- docs/HANDOFF.md
   docs/planning/12-review-w4-w5.md` -> HANDOFF 276, 284, 528, файл 12 строка 55 (в 276 и 12:55
   не в форме пути `/home/<имя>/`). Значение не печатать.
7. Журнал «ок» `HANDOFF.md:495-578`: `grep -cE '^\| [0-9]{2}\.[0-9]{2}' docs/HANDOFF.md` -> 80;
   строки 06.11 и новее: 499-520; разделы до 13.11: от `## Состояние на 10.11.2026, вечер` до
   строки перед `### Журнал «ок»`.

## Границы

- Можно: файлы правил из «Решений», новый `auditor.md`, HANDOFF, NEXT_SESSION, новые файлы
  `docs/planning/archive/`, `git mv` файла 03, `06-spec-standard.md`, `12-review-w4-w5.md:55`,
  `docs/planning/README.md`, новый `tests/unit/test_agent_docs.py`, память агента (шаг 8).
- Нельзя: `.claude/hooks/`, `.claude/settings*.json` (только патч), код стека, OPERATIONS и
  публичные документы (P11, P13), `docs/harness.md` (P14). Правку владельца и записи аудита
  13.11 в HANDOFF и NEXT_SESSION не терять. Живой стек: только цикл verify.

## Шаги

1. Тест на отказ (`implementer`), `tests/unit/test_agent_docs.py`:
   `test_agent_documents_fit_their_byte_budget` (AGENTS 8192, CLAUDE 2048, agent-rules 6144,
   13-harness 15360, HANDOFF 20480, NEXT_SESSION 4096); `test_roles_set_model_turns_no_agent`
   (frontmatter ролей); `test_auditor_role_reads_on_opus` (`model: opus`; `Agent`, `Edit`,
   `NotebookEdit` запрещены); `test_agents_md_lists_the_roles` (пары `` `имя` (Модель `` в
   `AGENTS.md` равны `name`, `model`); `test_rule_files_have_no_long_dash` (U+2013, U+2014 в
   правилах, ролях, skill, HANDOFF, NEXT_SESSION); `test_rule_paths_exist` (обратные кавычки,
   начало `docs/`, `.claude/`, `scripts/` в A, C, R, H, N, SKILL; пропуск `<`, `*`, `{`, `|`,
   `$`; хвост `:N-M` отрезать; явный список упомянутых несуществующих путей с причиной);
   `test_harness_names_no_closed_block` (`W6-D(3|4|13|15)|W6-T0[23]|W5-D13`);
   `test_handoff_starts_with_state_section`. Прототип 13.11: красны 5 бюджетов (кроме CLAUDE),
   `auditor.md`, путь `docs/superpowers/` (`agent-rules.md:75`), закрытые ID; зелёное остальное.
2. Канон (текст пишет оркестратор в копии в scratchpad; показ владельцу одним блоком). Целевой
   вид: `reports/HR.md`, «Целевой вид». Обязательное:
   - `AGENTS.md` до 8 192 Б: «Читать первым» 3 пункта (верх HANDOFF; NEXT_SESSION;
     `DECISIONS.md`, `OPERATIONS.md`, `docs/planning/README.md`); хуки 5 строк по ветке P03;
     в «Цикл» рутина сессии (В-18: одно «ок» в начале сессии на циклы verify, коммиты после
     гейта, push без force; класс C вне списка поимённо; запись в журнал «ок»), `:83` с
     оговоркой о ней; роли 6, `model` при вызове не переопределять никому; основная сессия
     «Opus или новее, `--model` при запуске»; публичные документы: «всё на английском вне
     `docs/planning/`, HANDOFF, NEXT_SESSION и файлов правил» (без перечня с `LEARNING.md`).
   - `CLAUDE.md` до 1 536 Б: импорт; плагины 5 строк (context7 плагином или коннектором
     claude.ai; триггеры `superpowers` из `agent-rules.md:74-80` без `/security-review`,
     `/revise-claude-md`, `Plan`); точечные проверки; «Где что». Уходят `:9` и `:12`.
   - `docs/agent-rules.md` до 5 120 Б: принципы, после изменения, правила кода, compose (с «ни
     одного порта на `0.0.0.0`»), гейты понимания, когда не уверен; остальное в A или C.
   - `13-harness.md` до 15 360 Б, версия 1.0, §1-§7 без закрытых ID. §1: шесть ролей, без
     `settings.local.json`; HC-03 «правки хуков и ролей подхватываются без перезапуска, кроме
     первого файла в новом каталоге `agents` и `--add-dir` (документация Claude Code, 13.11.2026,
     CLI 2.1.306); после правки ролей `/agents`». §2: цикл verify класс A «по рутине сессии»
     вместо W6-D4, «ADR-025» вместо W5-D13, «рутина» вместо W6-D3/D13; отказ классификатора на
     цикл verify снимает вопрос, где цикл расписан и названы коммиты; «синкани гит» = `git pull
     --rebase` только по просьбе (C). §3: узкие брифы под `maxTurns`, при упоре SendMessage
     «отчёт по сделанному»; HS-09 «в копии `git init`, `git add -A` без коммита, база `cp -a
     .git`, патч `git diff --no-index`»; `trailing-whitespace` в `.patch`, `/tmp` это tmpfs. §4:
     HS-05 «одно ревью кода за раз»; HS-10 «отметку пишет только `reviewer`, аудит: `auditor`»;
     HC-02 два пути записи, после отчёта отдельной командой `python3 scripts/agent_state.py show
     review .`, отметки нет: SendMessage тому же ревьюеру повторить строки вердикта. §5: гейт по
     ветке P03 (уровень `full` это полный verify дерева; новый код Spark до коммита доказывает
     `make test-spark`; образ собирается после коммита и CI), строки P02, PF-23 (шаг 3), запуск из `:339-340` плюс HC-07 («headless `claude -p`:
     `ask` без человека равен отказу; в CI агент не запускается»). §8 в шаблон NEXT_SESSION, §9
     заменён тестом, §10-§11 дословно в `docs/planning/archive/13-harness-history.md`.
   - `.claude/agents/auditor.md` по `reports/HR.md`, HR-02: `model: opus`, `disallowedTools:
     Agent, Edit, NotebookEdit`, `maxTurns: 100`, запись только в scratchpad, отчёт по
     `00-audit-prompt.md` §6, вердикт по дереву не пишет. `scout.md:28`: версии из
     `docker/compose.yaml` и `pyproject.toml`. `reviewer.md`: HS-05 («строка «Дерево» значит,
     что просмотрен каждый путь кода этого дерева; путь вне брифа назвать или «вернуть»»), HS-09;
     фразы «Вход» 4 сохранить. `SKILL.md` (HR-09): шаг 0 вопрос о рутине, если в журнале «ок»
     нет записи за сегодня; шаг 1 принимает путь к файлу пакета; «если спека не делегировала»
     -> «вне рутины сессии».
   - `06-spec-standard.md:34-36,52,53-54,124`: `AGENTS.md` вместо `CLAUDE.md`, без
     `.superpowers/`, «HANDOFF, «Открыто»» вместо «Мелочи», формат пакета `00-audit-prompt.md` §8;
     `git mv docs/planning/03-agent-tooling.md docs/planning/archive/`; индекс `:12`, `:21`.
3. PF-23 в 13-harness: §2 B, особый случай `airflow/dags/`: «пауза одного `dbt_build` при
   работающем `silver_upsert` теряет события Asset: после снятия паузы `airflow dags trigger
   dbt_build` один раз (OPERATIONS, «Airflow»)»; §5 цикл: снимать паузы в порядке `dbt_build
   dq_checks silver_upsert`, затем, если gold старше silver (`GoldStaleAtRest`), trigger один
   раз. Вывод по коду (`silver_upsert.py:45-71`: `make silver` не пишет Variable, первый прогон
   после паузы сам выпускает событие), живьём не проверено.
4. PF-62 (Edit): HANDOFF три строки (путь домашнего каталога -> `~/`, `pytest-of-<имя>` ->
   `pytest-of-<user>`), `12-review-w4-w5.md:55` имя в команде -> `<фамилия>`. Затем копия
   HANDOFF в scratchpad и дословный перенос в `docs/planning/archive/HANDOFF-2026-10-27-to-
   2026-11-10.md` (шапка 2 строки: что и откуда): разделы и строки журнала из «Вход» 7 с
   заголовком таблицы. Остаются: разделы с 13.11
   (записи аудита и P01-P03), «Открыто», `## Журнал «ок»` (06.11 и новее), `## История` со
   ссылками на оба архива; «прежнее из раздела 10.11 ниже» -> архив; `:3`, `:463`, `:584-585`
   переписать. Больше 20 480 Б: решение (а).
5. NEXT_SESSION шаблоном до 4 096 Б: строка запуска (`claude --model opus --permission-mode
   acceptEdits`, не `--bare`); блок ```` ```text ````, первый абзац: проект закрыт, бэклог
   `docs/planning/21-final-audit-2026-11-13/README.md`, раздел 4; правила `AGENTS.md`;
   стартовые команды одним списком (`13-harness.md:266` и `NEXT_SESSION.md:50-55`); первый
   вопрос владельцу (рутина, пакет, тексты класса C); конец сессии. Правку владельца
   (`NEXT_SESSION.md:64-67`) и запись аудита, если актуальны, в HANDOFF «Открыто». Ловушки без
   копии в OPERATIONS (`ImageManifestDescriptor`, `memory.swap` в cgroup) строкой в «Открыто»
   для P11 со ссылкой `git show <hash>:docs/NEXT_SESSION.md`.
6. HC-06 (живой агент): `Explore` с задачей «перечисли имена всех своих инструментов, ничего не
   исполняй». Есть `mcp__`: в `explore.md` вместо `disallowedTools` список `tools:` только из
   инструментов чтения (`Read`, `Bash`, поиск, если он есть в списке), в тот же показ текста;
   нет: строка в 13-harness §1 «глоб `mcp__*` проверен <дата>».
7. Патч владельцу (В-19): `.claude/settings.json` `"claude-md-management@claude-plugins-official":
   false` и этот плагин в кортеже `tests/unit/test_agent_hooks.py:1734-1738` (тест краснеет без
   settings). Копия по дереву после P03, `git diff --no-index`, файл в scratchpad; владелец:
   `git apply <файл> && make check`.
8. Память (по «ок», оркестратор; `~/.claude/projects/<каталог проекта>/memory/`): удалить
   `harness-proposal-2026-10-27.md` (патч в `5ca361a`), `mcp-settings-stay-local.md`
   (`.gitignore:21-22`, `OPERATIONS.md:546`), `verify-fast-overwrites-full-stamp.md` (правило в
   §5 или снято P02); править `cloud-sessions-and-git-sync.md` («never push» -> push по «ок»),
   `agent-plugins.md` (выключенные плагины, ссылка на `CLAUDE.md`), `model-split-preference.md`
   (предпочтение владельца; аудит -> `auditor`), `owner-delegates-week-execution.md` (рутина в
   `AGENTS.md`, делегации история), `laptop-sleep-breaks-airflow.md` (команда `wevtutil`, ссылка
   на OPERATIONS), `executor-plan-format.md` (история, формат пакета §8); оставить
   `no-ai-coauthor-in-commits.md`, `email-in-git-history-accepted.md`, `obsidian-daily-notes.md`;
   `MEMORY.md` до 1 229 Б. В отчёт: список и `wc -c`.
9. `make check`; `reviewer` (предмет `код`); не больше двух кругов; гейт и цикл verify по §5;
   коммит `infra: agent rules in one place, auditor role, handoff history archived, agent docs
   test`; push по рутине.

## Готово, когда

- [ ] `uv run pytest tests/unit/test_agent_docs.py -q` -> все passed; в лёгкой копии без `Agent`
      в `scout.md` -> 1 failed.
- [ ] `wc -c` шести файлов «Вход» 1 -> не больше 8192, 2048 (цель 1536), 6144 (цель 5120),
      15360, 20480, 4096.
- [ ] `grep -rn 'security-review\|revise-claude-md' AGENTS.md CLAUDE.md docs/agent-rules.md
      docs/planning/13-harness.md .claude/` -> пусто; `grep -l 'не переносится'` по A, C, R, H,
      NEXT_SESSION -> только `AGENTS.md`.
- [ ] Перенос: куски из копии шага 4 и из архива в два файла scratchpad, `wc -l` равны,
      `git diff --no-index --exit-code <копия> <архив>` -> пусто (оба куска); `grep -cE '^\|
      [0-9]{2}\.[0-9]{2}'` по HANDOFF и архиву в сумме -> 80 плюс строки после 13.11.
- [ ] `python3 .claude/hooks/session_context.py` -> новый верх HANDOFF и абзац шаблона;
      `git grep -n -i -I "$(basename "$HOME")" -- docs/HANDOFF.md docs/planning/archive
      docs/planning/12-review-w4-w5.md` -> пусто.
- [ ] В `docs/planning/13-harness.md` есть каждая строка шага 2 и шага 3: `grep -c` по словам
      `dbt_build` (PF-23: запуск после паузы, счёт больше, чем до правки), `claude -p` (HC-07),
      `SubagentStop` (HC-02), `git init` (HS-09), `auditor` (HS-10, при В-17 «да») -> каждое
      не меньше 1; `grep -c '21-final-audit' .claude/skills/task/SKILL.md` -> не меньше 1 (HR-09).
- [ ] Память (В-27): файлов из списка шага 8 нет, в `MEMORY.md` нет их строк.
- [ ] `/agents` -> 6 ролей, `auditor` на Opus; итог HC-06 записан; после патча владельца
      `uv run pytest tests/unit/test_agent_hooks.py -q` зелёный.
- [ ] `make check` зелёный; `reviewer` «принять» или «принять с замечаниями»; коммит прошёл
      гейт; `git status --short` без файлов пакета.

## Не входит

- Хуки и `agent_state.py` (P02, P03); OPERATIONS (P11); `docs/harness.md` и строки о нём в A и
  `docs-writer.md` (P14); перевод `docs/planning` (HR-N1); тест дублей (HR-N5); В-22.

## Риски и откат

- Окно на файл правил отклонено: файл не трогать, остальное делать, запись в «Итог». Перенос
  теряет строку: ловят `git diff --no-index` и счёт журнала; откат Edit из копии шага 4, после
  коммита `git revert <hash>` по «ок». Бюджет не влезает без потери обязательного: стоп, вопрос.

## Расхождения с отчётом аудита

- HR-05: на дереве 13.11 пары ролей в `AGENTS.md` зелёные, зато красны бюджеты `AGENTS.md`
  (12 262) и `agent-rules.md` (12 003), которых отчёт не назвал.
- HANDOFF 276 и `12-review-w4-w5.md:55`: имя не в форме `/home/<имя>/`, шаблон пути не ловит.
- PF-23: цикл verify снимает паузу со всех трёх DAG, и первый `silver_upsert` сам выпускает
  событие; потеря реальна при паузе одного `dbt_build` и в гонке порядка снятия пауз.
- HC-06: `mcp__*` в запретах роли в интерфейсе не доказывает действие глоба. DC-10:
  в `00-audit-prompt.md:234` пути домашнего каталога уже нет.

## Итог

Заполняет исполнитель по разделу 6 `docs/planning/13-harness.md`.
