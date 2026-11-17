# P14. Заморозка: `docs/harness.md`, гигиена документов, чистка `docs/planning`, GitHub, приёмка
Статус: не начат. Сессия Opus: `/task docs/planning/21-final-audit-2026-11-13/P14-freeze.md`

## Цель

Последний пакет. Процесс показан публично по-английски; ссылки, тире и имена держит тест в `make
check`; в `docs/planning` нет применённых патчей и рабочих файлов; GitHub без лишней ветки, Wiki и
Projects; тег `v1.0` на финальном коммите с зелёными `ci` и `smoke`; критерий README папки,
раздел 7, выполнен и проверен холодным стартом.

## Находки пакета

| ID | Серьёзность | Суть | Где подробности |
|---|---|---|---|
| HR-07 | низкая | «How it was built» застыла на 29.10, процесс только по-русски | `reports/HR.md`, HR-07 и «Харнесс как часть портфолио» |
| DC-20 | низкая | проверки ссылок, тире и имён разовыми скриптами, не в `make check` | `reports/DC.md`, DC-20 |
| DC-09 | средняя | 5 применённых `.patch` и корпус ревью guard в `docs/planning` | DC-09, «Судьба спорных путей» |
| DC-10 (остаток) | низкая | имя из пути домашнего каталога в файлах корпуса | DC-10 |
| DC-11 | низкая | 4 строки с длинным тире | DC-11 |
| DC-21 | низкая | слитая ветка, пустые Wiki и Projects, нет релиза | DC-21 |

## Решения владельца и действия класса C

Одним вопросом в начале сессии:
- В-21 `docs/harness.md`; В-10 `git rm` патчей и текстов корпуса; В-11 GitHub; В-23 `reports/`
  оставить, `work/` удалить. Рутина сессии: циклы verify, коммиты после гейта, push без force.
- В-10 покрывает патчи, тексты корпуса (`corpus-result-v1..v4.txt`, 808 176 Б), `probe.py.txt`
  (имя в пути, строка 11) и, если P03 применён (разбор форм обхода удалён), `corpus.json` и
  `normal.json` (546 435 Б): тогда каталог удаляется целиком. P03 не применён: два json остаются
  набором регрессий guard.
- Сверх В-n: (а) текст заметок релиза (5 строк, ниже); (б) social preview из скриншота Superset
  вручную в Settings: по желанию владельца.
- При «нет» строка «Готово» закрывается записью отказа в «Итог»: В-21: `docs/harness.md` не
  писать, раздел evidence «How it was built» только обновить числами; В-10: файлы остаются,
  индекс помечает их историей; В-11: шаги GitHub не делать; В-23: `work/` остаётся.
- Окно guard на текст: `AGENTS.md` (строка о том, где публичные документы говорят об агентах) и
  `.claude/agents/docs-writer.md:16-17`: добавить `docs/harness.md`. Показ одним блоком до правки.
- Класс C, по «ок» владельца на точный текст (каждая команда отдельно, окно guard ожидаемо):
  - `gh api -X DELETE repos/{owner}/{repo}/git/refs/heads/w3-fernet-replay-data`
  - `gh repo edit --enable-wiki=false --enable-projects=false`
  - `gh workflow run smoke.yml --ref main` (на финальном коммите Б, шаг 9)
  - `gh release create v1.0 --target <sha коммита Б> --title "v1.0" --notes-file
    <scratchpad>/release-notes.md --latest`
  - `docker exec lakehouse-superset-1 rm /tmp/review_probe.py` (H-8 реестра: проба ревьюера
    13.11 в контейнере, только чтение; сначала `docker exec lakehouse-superset-1 ls -l
    /tmp/review_probe.py`, нет файла: пункт закрыт без действия)
  - `git push origin main` без force: по рутине сессии.

## Зависимости

- После P01..P13: у каждого «Итог» или отказ в README папки, раздел 3. P03 решает судьбу
  `corpus.json` (выше). P04: архивы HANDOFF и 13-harness уже в `docs/planning/archive/`, имена в
  HANDOFF и `12-review-w4-w5.md:55` сняты. P10: тест или шаблон R-66 для приёмки. P13: строка
  README «How it was built» (В-09); ссылку свести на `docs/harness.md`.
- Гейт коммита по 13-harness §5, как он действует на момент исполнения (после P03 уровни В-13).

## Вход

Сверить первым, строки искать по цитате:
1. `git ls-files docs/planning | grep -E '\.patch$'` -> 5 файлов, `wc -c` вместе 167 819:
   `13-harness-guard.patch`, `15-audit-p1-harness.patch`, `15-audit-p3-harness.patch`,
   `15-audit-p4-harness.patch`, `15-audit-p5-harness.patch`. `git ls-files
   docs/planning/15-audit-p5-review` -> 7: `corpus-result-v1..v4.txt`, `corpus.json` (список из
   7 324 форм), `normal.json` (57), `probe.py.txt`.
2. Где текст файла останется в истории (последний коммит, который его менял, равен коммиту
   добавления: `git log --format=%h -1 -- <путь>`): guard-патч `5ca361a`, p1 `e66531b`, p3
   `149e10d`, p4 `2fb9c6b`, p5 и весь каталог корпуса `7e5af85`. Применены в `5ca361a`,
   `8577de1`, `90c64b2`, `164d837`, `7e5af85`.
3. Входящие ссылки (команда одной строкой): `git grep -n -E '13-harness-guard\.patch|
   15-audit-p[0-9]-harness\.patch|15-audit-p5-review|corpus-result|probe\.py\.txt' -- .
   ':!docs/planning/15-audit-p5-review'` -> только текст в обратных кавычках, ни одной
   Markdown-ссылки: `docs/planning/README.md:20,23-27` (обновить),
   `15-audit-2026-10-30.md:193,354,358,412,416,422`, `18-postfix-audit-2026-11-06.md:122`, архивы
   HANDOFF и 13-harness после P04 (история, не трогать). Код не ссылается: `git grep -n
   'corpus\|p5-review\|\.patch' -- tests scripts .claude Makefile` -> пусто.
4. Длинные тире: `git grep -n -I -P '[\x{2013}\x{2014}]'` -> `20-superset-dashboard.md:41`
   (U+2014), `:44`, `:51`, `:52` (U+2013); в папке 21 нет.
5. Имена: `git grep -n -i -I "$(basename "$HOME")"` -> после P04 только `corpus-result-v3.txt`
   (7 строк) и `probe.py.txt:11` (форма scratchpad `-home-<имя>-`). Разрешённые пути:
   `/home/nonroot/` (`docker/compose.yaml:247`, `04-w2-spec.md:127`, `05-w2-plan.md:2132`),
   `/home/user/` (`tests/unit/test_agent_hooks.py:882`), заглушка `/home/<имя>/`
   (`14-closeout-spec.md:723,725`). Значение имени в отчёт не печатать.
6. Ссылки: копия `work/DC/check_docs.py.txt` в scratchpad, `python3 -I <копия> . links` ->
   13.11: `links checked: 259, github-relative: 15, broken: 1`, единственная в
   `docs/planning/08-w3-plan/T00-clean-clone.md:361` (DC-N3: не чинить). В копии режим `dashes`
   испорчен (`"-" in line`, символы потеряны): логику тире писать заново через `U+2013`,
   `U+2014`. `work/OB/check_md_links.py.txt` считает `../../actions/runs/<id>` битыми (16 на
   13.11): правило GitHub-относительных ссылок брать из `check_docs.py`.
7. GitHub: `gh repo view --json hasWikiEnabled,hasProjectsEnabled` -> `true`, `true`;
   `git branch -r` -> `origin/main`, `origin/w3-fernet-replay-data`; `gh pr list --state all` ->
   PR 1 `w3-fernet-replay-data` MERGED, squash `c52d5cc` в `main`; `git diff --stat
   origin/w3-fernet-replay-data c52d5cc` -> пусто; релизов и тегов 0.
8. `docs/evidence.md:287-348` «How it was built»: числа 27-29.10 (`:314-316`), «60 turn limit»
   (`:340`); `README.md:13-15` строка о процессе (P13 могла перенести).

## Границы

- Можно: `tests/unit/test_docs_hygiene.py` (новый), `docs/harness.md` (новый), `docs/evidence.md`
  (раздел «How it was built»), `README.md` (только ссылка на `docs/harness.md`),
  `docs/planning/20-superset-dashboard.md` (4 строки), `git rm` по списку шага 3,
  `docs/planning/README.md`, файлы папки 21 (README, «Итог» P14), HANDOFF, NEXT_SESSION; с окном
  `AGENTS.md` и `docs-writer.md` (одна строка каждый).
- Нельзя: код стека, хуки, `settings*.json`, `reports/` папки 21, закрытые спеки по существу,
  история git. Живой стек: цикл verify и чтение для приёмки.

## Шаги

1. Тест на отказ первым (`implementer`): `tests/unit/test_docs_hygiene.py`, файлы из `git
   ls-files -z` от корня репо, только UTF-8:
   - `test_no_long_dash_in_tracked_text`: нет `U+2013`, `U+2014`; сейчас красный (Вход 4).
   - `test_no_home_directory_name_in_tracked_files`: (1) шаблон `/home/([a-z_][a-z0-9_.-]*)/`,
     имя не из `{"user", "nonroot", "runner", "root"}`; (2) имя из окружения
     (`Path.home().name`, `getpass.getuser()`), если оно не из этого набора и длиннее 3
     символов: без учёта регистра, в любой форме (`-home-<имя>-`, `pytest-of-<имя>`). Имя в
     тесте не писать; `LICENSE.md` не исключать (там логин, не имя из пути). Сейчас красный
     (Вход 5); в CI работает только (1).
   - `test_relative_links_and_anchors_resolve`: `*.md` вне `docs/planning/`; ссылки со схемой
     пропустить; `../../actions/...` проверить по глубине (`check_docs.py`, `mode_links`); цель
     отслеживается; якорь по правилам GitHub (`slugify`, `anchors`, `strip_code` оттуда же).
     Сейчас зелёный (Вход 6).
   - `test_link_checker_finds_a_broken_link_and_anchor`: функция проверки на файлах в
     `tmp_path` (битая ссылка, битый якорь, верная ссылка) -> ровно 2 находки.
   Проверка: `uv run pytest tests/unit/test_docs_hygiene.py -q` -> 2 failed (тире, имена).
2. DC-11 (оркестратор, Edit): 4 строки `20-superset-dashboard.md` -> дефис или двоеточие.
3. DC-09, DC-10, В-23 (оркестратор): `git rm` пяти `.patch`, `corpus-result-v1.txt`..`v4.txt`,
   `probe.py.txt`; по решению (а) `corpus.json`, `normal.json`. Строки индекса
   `docs/planning/README.md:20,23-27`: «применён в `<коммит>`; файл удалён при заморозке, текст:
   `git show <коммит из Вход 2>:docs/planning/<имя>`». Папка 21: `git rm -r
   docs/planning/21-final-audit-2026-11-13/work` (и `patches/`, если есть и каждый патч применён
   по «Итогу» P03) только после приёмки шага 7 (шаблон R-66 приведён там); упоминания
   `work/` в README папки (таблица состава, раздел 3 В-23, раздел 5 п. 4) перевести на историю git. Проверка: тест шага 1 зелёный.
4. HR-07 (`docs-writer`, бриф по 13-harness §3): `docs/harness.md` на английском до 10 240 Б, без
   имён; разделы и источники чисел по `reports/HR.md`, «Харнесс как часть портфолио» (8 разделов:
   What this is, Diagram, Roles, Action classes, Numbers, What review caught, What did not work,
   Reuse); плюс итоги P02-P04 по их «Итогам»: полная отметка verify не затирается, guard целевого
   вида и уровни гейта (если P03 применён), один канон правил и тест бюджетов, роль `auditor`.
   Диаграмма Mermaid (`.claude/settings.json` как источник хуков); экспорт в `docs/img/` по
   `docs-writer.md:25`, если есть инструмент, иначе запись в «Итог». Каждое число с командой из
   шага 5 и датой UTC. «How it was built» в `docs/evidence.md`: один абзац со ссылкой на
   `docs/harness.md` и числами шага 5 вместо чисел 29.10. README: ссылка ведёт на
   `docs/harness.md`. С окном: строка `AGENTS.md` и `docs-writer.md:16-17` называют
   `docs/harness.md` разрешённым местом.
5. Числа снимать в момент исполнения (на дереве перед коммитом А, вывод в «Итог»):
   - коммиты `git rev-list --count HEAD`; даты `git log --reverse --format=%ad --date=short |
     head -1` и `git log -1 --format=%ad --date=short`; области `git log --format=%s | sed
     's/:.*//' | sort | uniq -c | sort -rn`; атрибуции `git log --format=%B | grep -ci
     'co-authored-by'` -> 0;
   - журнал «ок» `grep -chE '^\| [0-9]{2}\.[0-9]{2}' docs/HANDOFF.md
     docs/planning/archive/HANDOFF-*.md` (сумма; 80 на 13.11 до P04);
   - вердикты: `git grep -ohE '«(вернуть|принять с замечаниями)»' -- docs/HANDOFF.md docs/planning
     | sort | uniq -c` (это упоминания, не число ревью; 34 и 73 на 13.11);
   - guard и тесты: `wc -l .claude/hooks/guard.py` (1063 на 13.11), `uv run pytest
     tests/unit/test_agent_hooks.py -q | tail -1` (859 passed на 13.11), `uv run pytest tests/unit
     -q | tail -1`; корпус: 7 324 форм (из `reports/HR.md` или `git show
     7e5af85:docs/planning/15-audit-p5-review/corpus.json`, если каталог удалён);
   - отказы классификатора 7 и упоры в лимит ходов 3: источник `reports/HR.md`, «Трение по
     журналам», плюс записи после 13.11 в HANDOFF.
6. Итоговые документы (оркестратор): `docs/planning/README.md`: каждая спека, план и аудит
   «история», `02` «отложено владельцем 06.11», `13-harness.md` «действует», `06` «справка»,
   папка 21 «исполнено <дата>»; README папки 21: статусы пакетов в разделе 4, «Итог» P14;
   HANDOFF: верх «Состояние: проект заморожен <дата>», журнал «ок» этой сессии; NEXT_SESSION:
   кандидатов нет, ответ холодного старта «открытых задач нет».
7. Приёмка по README папки, раздел 7 (команды в «Готово, когда»), на дереве перед коммитом А.
   Шаблон R-66 (из `work/DC/r66_pattern.txt`): `\b(W[0-9](-[TD][0-9]+[ab]?)?|D[0-9]{1,2}|
   (QA|SEC|REL|DATA|DOC|MODEL|ARCH|AI|PF|F|R)-[0-9]{2}|RT-S[0-9]|[BbБК][0-9]{1,2})\b|[Aa]udit|
   [Ww]eek[ -][0-9]|verified 202|[(, ]202[0-9]-[01][0-9]-[0-3][0-9]\b` (одной строкой).
8. Коммит А: `make check`; `reviewer` (предмет `код`, весь diff, `docs/harness.md` против
   источников чисел); не больше двух кругов; гейт; коммит `docs: process page, docs hygiene test,
   applied patches and audit scratch files removed`; push; `ci` на А зелёный. Затем GitHub: ветка,
   Wiki и Projects (класс C выше), проверка командами «Готово, когда».
9. Коммит Б (только Markdown): «Итог» P14 с числами и run id `ci` коммита А, HANDOFF; push; `ci`
   на Б; `gh workflow run smoke.yml --ref main`; оба success -> `gh release create v1.0 --target
   <sha Б>` с заметками: что это (одна строка), что доказано (сверка 7 из 7, сценарии отказа),
   как запустить (`make bootstrap`), где процесс (`docs/harness.md`), лицензия. После тега
   коммитов нет.
10. Холодный старт: владелец открывает новую сессию по `docs/NEXT_SESSION.md`; за 15 минут она
    называет HEAD (`v1.0`), статус `ci` и `smoke` (success) и «открытых задач нет», ничего не
    коммитит. Расхождение: стоп, решение владельца.

## Готово, когда

- [ ] `grep -l '^Статус: не начат' docs/planning/21-final-audit-2026-11-13/P[0-9][0-9]-*.md` ->
      пусто; `grep -L '^Критерий:' docs/planning/21-final-audit-2026-11-13/P[0-9][0-9]-*.md` ->
      только пакеты с отказом в разделе 3 README папки (и P14 до коммита Б).
- [ ] `gh run list --workflow ci.yml --limit 1 --json conclusion,headSha -q
      '.[0]|[.conclusion,.headSha]|@tsv'` -> `success` и `git rev-parse HEAD`; то же с
      `--workflow smoke.yml`.
- [ ] `make check` зелёный; `make verify` -> последняя строка `verify ok`; `curl -s
      127.0.0.1:9090/api/v1/rules | python3 -c 'import json,sys;r=[x for g in
      json.load(sys.stdin)["data"]["groups"] for x in g["rules"] if x["type"]=="alerting"];
      print(len(r),sum(not x.get("annotations",{}).get("runbook_url") for x in r))'` -> `N 0`
      (13.11: `16 16`; `jq` на хосте нет).
- [ ] `wc -c README.md OPERATIONS.md DECISIONS.md` -> не больше 10240, 67584, 40960;
      `grep -c '4 charts\|planned' README.md` -> 0; `head -40 OPERATIONS.md | grep -c '](#'` ->
      не меньше 17 (оглавление); `grep -c '^## ADR-0\(2[7-9]\|30\)' DECISIONS.md` -> 4 (2, если
      в «Итоге» P12 записан отказ на ADR-029 и ADR-030).
- [ ] `uv run pytest tests/unit/test_docs_hygiene.py -q` -> passed; `git grep -n -I -P
      '[\x{2013}\x{2014}]'` -> пусто.
- [ ] R-66: `uv run pytest tests/unit/test_no_history_in_code.py -q` зелёный, если P10 его создал;
      иначе команда `reports/DC.md`, DC-04 с шаблоном шага 7 -> 0 строк.
- [ ] `git ls-files docs/planning | grep -cE '\.patch$'` -> 0; `git ls-files
      docs/planning/15-audit-p5-review | grep -c 'txt$'` -> 0; `git ls-files
      docs/planning/21-final-audit-2026-11-13/work | wc -l` -> 0.
- [ ] `wc -c docs/HANDOFF.md docs/harness.md` -> не больше 20480 и 10240; строки
      `docs/planning/README.md` из шага 6.
- [ ] `gh api 'repos/{owner}/{repo}/branches' --jq '.[].name'` -> `main`; `gh repo view --json
      hasWikiEnabled,hasProjectsEnabled` -> `false`, `false`; `gh release view v1.0 --json
      tagName,isDraft` -> `v1.0`, `false`; `gh release list --limit 1` -> `Latest`;
      `git ls-remote --tags origin v1.0` -> sha коммита Б.
- [ ] Холодный старт шага 10 записан владельцем или в чате сессии.

## Не входит

- Правка содержимого закрытых спек и `reports/`; ссылка `08-w3-plan/T00-clean-clone.md:361`
  (DC-N3); бейдж smoke и GitHub Pages (DC-N8); `.superpowers/` (не отслеживается); переписывание
  истории git (DC-N4); английская шапка `docs/planning/README.md` (P13, если взята).

## Риски и откат

- Тест имён краснеет на чужой машине с коротким или общим именем: набор исключений и порог длины
  в тесте, не ослабление шаблона пути. Тест ссылок краснеет на якоре с символами вне правил
  `slugify`: проверить ссылку на github.com, поправить `slugify` с тестом.
- `git rm` ошибочного файла: до коммита `git restore --staged` и `git checkout -- <путь>` по
  «ок»; после коммита `git show <коммит>^:<путь>`.
- Красный `ci` или `smoke` на Б: тег не ставить, стоп и вопрос владельцу. Тег ошибочный:
  `gh release delete v1.0 --cleanup-tag` только по «ок».

## Расхождения с отчётом аудита

- В копии `work/DC/check_docs.py.txt` режим `dashes` неработоспособен (символы заменены
  дефисом); `work/OB/check_md_links.py.txt` даёт 16 ложных битых ссылок на `actions/runs`.
- DC-10: `00-audit-prompt.md:234` уже без пути; строки HANDOFF и файла 12 снимает P04; в
  `HANDOFF.md:276` и `12-review-w4-w5.md:55` имя не в форме `/home/<имя>/`, поэтому в тесте
  нужна проверка по имени из окружения, одного шаблона пути мало.
- DC-21: ветка слита сквозным squash (`c52d5cc`), поэтому `git branch -r --merged origin/main`
  её не показывает; дерево ветки равно `c52d5cc`, удаление безопасно.
- При сведении 18.11 README папки поправлен: раздел 7 проверяет R-66 тестом из P10 (шаблон в
  шаге 7 остаётся запасным путём), в таблице раздела 4 есть колонка статуса, В-10 покрывает
  `probe.py.txt`, `corpus.json` и `normal.json`.

## Итог

Заполняет исполнитель по разделу 6 `docs/planning/13-harness.md`.
