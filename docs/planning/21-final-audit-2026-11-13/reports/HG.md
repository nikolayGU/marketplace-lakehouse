# HG. Харнесс: guard.py

Дерево: HEAD `a8c1d49` плюс незакоммиченные правки владельца (не трогались). В репозитории ничего не
менялось. Опыты в `<scratchpad>/audit/HG-work/` (полный путь в конце). Все команды в Bash подавали
запретные слова только файлами.

## Оценки

- Безопасность (харнесс как страховка): 3 из 5. Ядро (гейт коммита, секреты, класс C) верное и
  fail-closed, но есть ложные пропуски в обычной форме (SQL-записи в silver и bronze, `DROP
  PUBLICATION`, `git checkout <ref> -- путь`), а 30% кода ловит только нарочный обход.
- QA (тесты хука): 3 из 5. 859 случаев, но 120 ask-случаев зелёные при полностью сломанном guard
  (R-02 подтверждён мутацией), 859 подпроцессов (66 с), около 400 случаев проверяют формы обхода.
- Тимлид, нанимающий: 2 из 5. 1063 строки и 2236 строк тестов на хук, который по собственному
  регламенту «ловит ошибки, а не обход»: несоразмерность видна за минуту.
- Архитектор: 3 из 5. Граница «текст команды, не песочница» названа (13-harness.md:97-104), но код ей
  не следует: три токенизатора и разбор флагов интерпретаторов.
- Руководитель (цена владения): 2 из 5. Каждая правка guard шла 3-4 прохода ревью (Б14, Б18), ложные
  отказы бьют по рутине (сегодня дважды в этой сессии аудита).

## Сильные стороны

- Fail-closed в двух слоях: любое исключение даёт ask (`guard.py:1055-1062`), падение процесса
  блокирует вызов (`.claude/settings.json`, `"onFailure": "block"`; тест
  `test_settings_wire_the_review_hook_and_make_the_guard_fail_closed`).
- Гейт коммита привязан к хэшу дерева, с исключением Markdown и `docs/` и учётом переноса кода в docs
  (`guard.py:906-945`; тесты `test_agent_hooks.py:1409-1545`, `--no-renames`).
- Строгий ответ из двух текстов (склеенный и исходный) и приоритет deny над упавшей веткой
  (`guard.py:982-996`; тесты 1921-1950).
- Семантическая проверка секретов в обычных формах: `docker inspect` с разбором `--format`,
  `compose config` с флагами-списками, `exec env` (`guard.py:520-631`; 79 случаев теста
  `test_guard_asks_before_a_command_shows_a_secret`, 42 разрешающих).
- Дисциплина регрессий: корпус 7324 форм и требование «мягче 0» против HEAD
  (`docs/planning/15-audit-p5-review/`).
- Список класса C с причиной в окне подтверждения (`guard.py:194-332`) прямо отображает
  `13-harness.md`, раздел 2, C.

## Карта guard.py (HEAD)

Пометка: «ошибка» ловит случайную опасную команду в обычной форме; «обход» ловит только нарочно
изменённую форму; «точность» нужна, чтобы не дать ложное окно.

| Блок | Строки | Что ловит | Правило | Пример | Пометка |
|---|---|---|---|---|---|
| docstring | 1-45 | описание; 27-42 про разбор inline-кода | AGENTS.md «Хуки» | | 16 строк про обход |
| `SECRET_FILE` | 59-61, 965-966 | Write/Edit секретов | «Секреты только в .env» | Write `.env` | ошибка |
| `GIT` | 62-70 | глобальные опции git перед подкомандой | все правила git | `git -C /repo push` | ошибка |
| `FORCE_PUSH` | 71, 1007 | deny | Жёсткие запреты | `git push -f` | ошибка |
| `DROP`, `TRUNCATE`, `DELETE` | 72-74, 1009-1019 | deny | Blast radius | `psql -c "truncate t"` | ошибка; ложные отказы на прозе |
| `SLOT_SKIP`, `LOGICAL_MESSAGE` | 76, 84 | deny | слот, ADR-023 | `pg_drop_replication_slot` | ошибка |
| `SHELL_WRITE_ENV` | 77-82, 1020 | deny записи в `.env` | секреты | `echo X=1 >> .env` | ошибка; ловит любой `*.env` |
| `HARNESS_FILE/DOC`, `STAMP_FILE` | 88-95, 967-977 | файловые инструменты | «Хуки», гейт | Edit `.claude/hooks/guard.py` | ошибка |
| `shell_write`, `SHELL_WRITE_*` | 97-122, 1022, 1045 | cp, sed -i, tee в хуки и правила | «Хуки» | `cp /tmp/g.py .claude/hooks/guard.py` | ошибка; ветка `open(` ловит и чтение |
| `STAMP_NAME` | 125, 1027-1035 | любое упоминание отметки вне чистого чтения | гейт | `touch .verify-stamp` | ошибка, но главный источник ложных отказов |
| `STAMP_CLI` | 126 | `agent_state.py stamp|check` | гейт | | ошибка |
| `SEGMENT` | 130 | `python3 -X 'a;b' -c` | | | обход |
| `LINE_CONTINUATION` и два текста | 132, 982-996 | перенос `\` | | `docker compose ... \` | ошибка (склейка), обход (комментарий с `\`) |
| `WRAPPER_*`, `AFTER_PIPE`, `READS_STDIN`, `INLINE_PYTHON` | 133-165 | код в интерпретатор по пайпу через обёртки | | `echo ... \| nice -n 5 python3` | обход |
| `bends_make_check` | 166-185, 1036-1037 | `make -i check`, переменные | гейт | | избыточно: `run_check` уже снимает `MAKEFLAGS`, `PYTEST_ADDOPTS` (`scripts/agent_state.py:51-58,273-287`, тест `test_agent_state.py:824`) |
| `COMMIT`, `VERIFY_THEN_COMMIT`, `commit_gap` | 190-192, 906-945, 1038-1044 | гейт коммита | 13-harness §5 | `git commit -m x` | ошибка (ядро) |
| `ASK` | 194-332 | 24 правила класса C | 13-harness §2 C | `make silver`, `docker compose down` | ошибка; дубли 325-329 |
| `READERS`, `reads_only` | 334-350, 463-486 | ранний выход для чтения (токенизатор 1) | точность | `grep "drop table" f` | точность |
| `INLINE_CODE` | 359-367, 887 | `.env` вместе с inline-кодом | секреты | `python3 -c "open('.env')"` | ошибка (первая ветка), обход (ветка после пайпа) |
| `shell_words` | 489-517 | слова команд (токенизатор 2) | секреты | | ошибка |
| секреты: `secret_in_segment`, `compose_secret`, `inspect_*`, `prints_environment` | 520-631 | `cat .env`, `compose config`, `inspect`, `exec env` | секреты | | ошибка |
| `Flavor`, `FLAVORS`, `runner_flavor`, `command_start`, `reads_code_from_stdin`, `strip_comments`, `scan_commands` (токенизатор 3), `stdin_code_runners` | 634-879 | stdin интерпретатора, `-o pipefail`, `-s`, `#`, группы после пайпа | | `echo ... \| bash -euo pipefail` | обход (246 строк) |
| `check`, `check_bash` | 960-1052 | маршрутизация | | | |
| запуск | 1055-1063 | без `main()` и `__main__` | | | мешает тестам (R-08, R-27) |

Итог карты: около 310 строк «обход» (130, 133-165 без 132, 363-367 частично, 634-879, 27-42,
1030-1033) и 22 строки избыточного `bends_make_check`. Это совпадает с R-45 (246 строк токенного
разбора плюс окружение).

## Старый бэклог

| ID | статус сейчас | делать / не делать | причина |
|---|---|---|---|
| R-02 | открыт: `tests/unit/test_agent_hooks.py:39-44`; мутация `check_bash` с `raise` первой строкой: 197 passed, из них 100 `test_guard_asks_the_owner`, 11 `test_the_forms_that_asked_before_still_ask`, 6 `test_a_backslash...`, 3 ask-случая `test_forty_odd...` | делать (HG-13) | ложный зелёный набора при сломанном guard |
| R-08 (guard) | открыт: `load_guard` режет по тексту `"\ntry:\n    check(json.load(sys.stdin))"` (`test_agent_hooks.py:1913`); тот же приём в `15-audit-p5-review/probe.py.txt:6` | делать (HG-14) | после `main()` импорт модуля вместо резки |
| R-08 (session_context) | открыт: `test_agent_hooks.py:1165-1187` зовут docker хоста (0.71 с и 0.50 с, самые медленные) | делать, область HS | фейк `fake_docker` уже есть (1190) |
| R-27 (guard) | открыт: `bash()` и `hook("guard.py")` через подпроцесс (`:21-36`), 859 passed за 66.33 с | делать (HG-14) | в процессе 858 passed за 10.0 с (опыт ниже) |
| R-45 | открыт: guard 1063 строки, тесты 2236 | делать (HG-12) | целевой вид ниже: guard около 700, тесты около 1600, покрытие обычных форм то же |
| Б11б | принято владельцем 30.10 (ложное окно `python3 -c` и `.env` в разных частях команды) | не делать | в целевом виде правило шире (интерпретатор и `.env` в одной команде), окно в безопасную сторону |
| Б14 | закрыт `164d837` | не делать | |
| Б18 | закрыт `7e5af85` (П-5); остаток: комментарий по последнему символу, апостроф в теле here-doc, составная команда после пайпа, `perl -MEnglish` ложный ask, `<<` у `INLINE_PYTHON` | не делать | всё это формы обхода; целевой вид удаляет сам механизм, остаток теряет смысл |
| SEC-04 | принято: guard ловит ошибки, не обход (`13-harness.md:97-104`) | не делать | целевой вид приводит код к этому правилу |
| 14 §7: `make check > /tmp/log 2>&1` ложный отказ | открыт: `guard.py:169,178-179` (голый `>` проходит `REDIRECT`, путь становится аргументом); `make check >/tmp/log` проходит | делать (HG-07) | удалить `bends_make_check` |
| 14 §7: «make check» в сообщении коммита | открыт: `guard.py:173` режет без кавычек | делать (HG-06, HG-07) | |
| 14 §7: чтение отметки или `agent_state.py show` в составной команде, heredoc со словами об отметках | открыт: `mkdir -p x && cat .verify-stamp` deny (опыт), `python3 - <<EOF` с `read_stamp` deny | делать (HG-05, HG-08) | случилось в этом аудите |
| 14 §7: гейт коммита по индексу | решено правилом «один verify, один коммит» | не делать | хук не меняется по решению |
| 14 §7: разбор вердикта, закрывающий текст | область HS (`review_stamp.py`) | не здесь | |

## Находки «делать»

### HG-01 [высокая] SQL-записи в bronze, silver и gold проходят без окна

Где: `guard.py:310-318` (только `shop|replay|cdc`), `guard.py:331` (только DDL).
Факт: опыт `miss.json`: `trino --execute "update lake.silver.orders set ... where ..."`,
`delete from lake.silver.orders where ...`, `insert into lake.bronze.cdc_events select ...`,
`merge into lake.silver.orders ...` через `docker compose exec -T trino`: `allow`. Docstring
обещает ask на «silver and other lake writes» (`guard.py:16-17`), AGENTS.md: «make silver и любые
записи в silver и bronze» только с «ок».
Чем плохо: агент «чинит» расхождение `reconcile` правкой silver руками; инвариант сверки и один
писатель silver нарушены без окна.
Правка: правило ASK `\b(insert\s+into|update|delete\s+from|merge\s+into)\s+"?(lake\.)?"?(bronze|silver|gold)"?\.`
с причиной «writes to bronze, silver or gold by hand». Тест на отказ первым: 4 формы выше дают ask.
Проверка: тест-копия: 4 случая `ask`; `test_guard_allows` (51) зелёный.
Размер: S; класс B; патч владельцу (guard), тест агент.
Старый ID: нет.

### HG-02 [средняя] `DROP PUBLICATION` и `DROP SUBSCRIPTION` проходят

Где: `guard.py:72` (`DROP` без publication), `guard.py:314` (только `create|alter`).
Факт: `psql ... -c "DROP PUBLICATION dbz_publication"`: `allow` (опыт `miss.json`).
Чем плохо: Debezium теряет публикацию, CDC встаёт; это настройка коннектора и Postgres (класс C).
Правка: `(create|alter|drop)\s+(publication|subscription)` в правиле 310-318.
Проверка: случай в `test_guard_asks_the_owner` даёт ask.
Размер: S; класс B; патч владельцу.
Старый ID: нет.

### HG-03 [средняя] Остановка scheduler вместе с другим сервисом проходит

Где: `guard.py:270-271`, `(?![^\n;&|]*airflow-scheduler)`.
Факт: `docker compose stop airflow-scheduler kafka` и `... stop airflow-scheduler spark-bronze`:
`allow`. Исключение срабатывает при любом упоминании scheduler в команде.
Чем плохо: остановка Kafka или bronze без окна; ровно та форма, которую агент пишет в цикле verify.
Правка: исключение только для единственной цели: `(?!\s+airflow-scheduler\s*(?:$|[;&|\n]))` сразу
после слова `stop|kill|restart|pause`. Тест: две формы выше ask; `$COMPOSE stop airflow-scheduler
&& make verify && $COMPOSE start airflow-scheduler` по-прежнему allow (`test_agent_hooks.py:863`).
Проверка: обе формы `ask` в прототипе, 863 зелёный.
Размер: S; класс B; патч владельцу.
Старый ID: нет.

### HG-04 [средняя] Потеря незакоммиченной работы обычными формами git и `find -delete`

Где: `guard.py:218-224` (`checkout\s+(--\s|\.(\s|$))`), `guard.py:217`.
Факт: `git checkout HEAD -- airflow/dags/dq_checks.py`, `git checkout main -- .`, `git checkout -f
main`, `git switch -f main`, `find data/checkpoints -name '*.crc' -delete`: `allow`.
Чем плохо: правка карточки или checkpoint теряются без окна (AGENTS.md: blast radius, удаление
checkpoint).
Правка: `checkout\b[^\n;&|]*\s(--|-f|--force|\.)(\s|$)`, `switch\b[^\n;&|]*\s(-f|--force|--discard-changes)\b`,
в правило recursive delete `|\bfind\b[^\n;&|]*\s-delete\b`.
Проверка: 5 случаев ask; `git checkout -b x`, `git checkout main` allow.
Размер: S; класс B; патч владельцу.
Старый ID: нет.

### HG-05 [средняя] Чтение отметки в составной команде получает «writes a gate stamp by hand»

Где: `guard.py:125`, `1027-1035`; `reads_only` 463-486 требует, чтобы вся команда была чтением; в
`READERS` (334) нет `echo`, `printf`, `stat`, `test`.
Факт (опыт `fp.json`, deny на HEAD): `mkdir -p /tmp/s/audit && cat .verify-stamp .check-stamp`
(сегодняшний случай), `cat .verify-stamp 2>/dev/null || echo none`, `cat .verify-stamp; echo ---;
cat .check-stamp`, `stat .verify-stamp`, `test -f .review-stamp && echo yes`, `ls -la .verify-stamp
&& make report`.
Чем плохо: ложный отказ на чтении, которое регламент делает свободным (`test_agent_hooks.py:874`);
агент тратит ход и переформулирует.
Правка: отметка запрещена, только если она названа в простой команде, которая не чтение
(проверка по каждой команде, а не по всей строке); `echo`, `printf`, `stat`, `test`, `[`, `file`,
`du`, `diff`, `pwd`, `true`, `realpath` в `READERS` (запись через `>` по-прежнему отсекается токеном
редиректа).
Проверка: 6 форм allow; 23 случая `test_guard_denies_a_gate_stamp_written_by_hand` deny (в прототипе
так и есть).
Размер: S; класс B; патч владельцу.
Старый ID: 14 §7 (29.10).

### HG-06 [средняя] Правила слов читают данные: сообщение коммита, тело here-doc, echo, шаблон grep

Где: `check_bash` 1006-1052 сверяет весь текст, кроме случая «вся команда только чтение».
Факт (опыт, при открытом гейте): `git commit -m "docs: truncate long lines in the report"` deny
TRUNCATE; `... delete from the table ...` deny DELETE; `... note that git push needs an ok` ask;
`... docker compose down and make down ...` ask; `git commit -m "$(cat <<'EOF' ... drop table ...
EOF)"` deny DROP; `cat > notes.md <<'EOF'` с «DROP TABLE» deny, с «git commit» deny гейтом;
`echo 'truncate the output'` deny; `docker compose logs ... | grep -i "drop table"` deny. В этой
сессии живой guard дважды отказал мне: `... python3 probe.py ... | grep -A1 "commit\|drop table\|DROP"`
(DROP) и `python3 -c "...open('.claude/settings.local.json')..."` (HG-09).
Чем плохо: самый частый класс трения в журналах; агент переписывает сообщение коммита и обходит
слова, что приучает к обходу.
Правка: (1) `without_data()`: убрать текст `-m`/`--message` у `git commit` и тело here-doc,
которое `cat` пишет в файл (`>` в строке `cat`) или в `-m "$(cat <<EOF`; (2) правила слов
применять только к простым командам, которые не чтение (`grep`, `rg`, `echo` и прочее из `READERS`);
секреты и запись в `.env`, хуки, отметки по-прежнему по всему тексту.
Проверка: формы выше allow; все 39 `test_guard_denies` и 100 `test_guard_asks_the_owner` прежние.
Размер: M; класс B; патч владельцу.
Старый ID: 14 §7 (make check в сообщении), журналы.

### HG-07 [средняя] `bends_make_check` избыточен и даёт ложные отказы

Где: `guard.py:166-185`, `1036-1037`.
Факт: `make check > /tmp/s/check.log 2>&1` deny, `make -j4 check` deny, `git commit -m "... make
check ..."` deny; при этом `make check >/tmp/log` allow. Защиту уже даёт `run_check`: снимает
`MAKEFLAGS`, `MFLAGS`, `GNUMAKEFLAGS`, `MAKELEVEL`, `MAKEFILES`, `PYTEST_ADDOPTS`
(`scripts/agent_state.py:51-58,278`), тест `tests/unit/test_agent_state.py:824`; цели `lint` и
`test` не читают переменных `?=` (`Makefile:138-154`).
Чем плохо: ложные отказы на обычном перенаправлении вывода; 20 строк и 12 тестов без защиты сверх
`run_check`.
Правка: удалить `MAKE_CHECK_ENV`, `REDIRECT`, `bends_make_check` и вызов; удалить
`test_guard_denies_make_check_bent_to_stamp_failing_checks` (168-189); добавить allow-случаи `make
check > log 2>&1`, `make -j4 check`.
Проверка: тест-копия зелёная; `test_run_check_drops_the_make_and_pytest_option_variables` зелёный.
Размер: S; класс B; патч владельцу.
Старый ID: 14 §7.

### HG-08 [низкая] Python, который только читает `agent_state`, получает отказ

Где: `guard.py:1029-1033`.
Факт: `uv run python -c "from scripts.agent_state import tree_hash; ...print(tree_hash(...))"` и
`python - <<'EOF'` с `read_stamp`: deny «writes a gate stamp by hand».
Правка: deny, только если рядом с `agent_state` и словом python названа функция записи
(`write_stamp|record_review|_store|run_check`); `STAMP_CLI` и запрет имени отметки остаются.
Проверка: две формы allow; `python3 -c "from scripts.agent_state import write_stamp; ..."` deny.
Размер: S; класс B; патч владельцу.
Старый ID: 14 §7 (29.10).

### HG-09 [низкая] `open()` на чтение файла харнесса считается записью

Где: `guard.py:113-115` (ветка `\bopen\([^)]*` + путь в `shell_write`).
Факт: `python3 -c "...json.load(open('.claude/settings.local.json'))"` deny «shell write to the agent
hooks» (живой отказ в этой сессии); `python3 -c "print(open('AGENTS.md').read())"` ask «edits the
agent roles or rules».
Правка: ветка только с режимом записи: `open\([^)]*<путь>[^)]*,\s*["'][wax+]`.
Проверка: обе формы allow; `python3 -c "open('AGENTS.md', 'w').write('')"` ask (`test_agent_hooks.py:306`).
Размер: S; класс B; патч владельцу.
Старый ID: нет.

### HG-10 [низкая] Чтения, которые спрашивают как действие C

Где: `guard.py:331`, `guard.py:269`.
Факт: `trino --execute "show create table lake.silver.orders"` ask «DDL outside migrations»;
`docker exec lakehouse-airflow-scheduler-1 rm /tmp/probe.txt` ask «stops or removes stack
containers» (у первой ветки нет исключения `exec`, у второй есть).
Правка: `(?<!show )\b(alter|create)\s+...`; `(?![^\n;&|]*\bexec\b)` и в первую ветку 269.
Проверка: обе allow; `docker rm -f ...`, `docker compose rm -f minio` ask (`:276-277`).
Размер: S; класс B; патч владельцу.
Старый ID: нет.

### HG-11 [низкая] Запись в любой `*.env` получает «shell write to .env»

Где: `guard.py:77-82` (`[^\s;|&]*\.env\b`).
Факт: `sed -i s/a/b/ docker/airflow/airflow.env` и `cp /tmp/x docker/airflow/airflow.env` deny, а
Write того же файла allow (`SECRET_FILE` требует `/` перед `.env`, строка 60).
Правка: путь только с именем `.env`: `([^\s;|&]*/)?\.env\b` во всех трёх ветках.
Проверка: две формы allow; `echo X=1 >> .env`, `cp /tmp/x .env.local` deny.
Размер: S; класс B; патч владельцу.
Старый ID: нет.

### HG-12 [средняя] Целевой вид: удалить разбор форм обхода (R-45)

Где: `guard.py:27-42,130,133-165,359-367,634-879,1027-1035`; тесты ниже.
Факт: прототип `HG-work/slim/.claude/hooks/guard.py` (709 строк после `ruff format`, ruff чист)
против HEAD (1063). Корпус 7324: `ask -> ask` 3667 из 3667, мягче на секретах 0; `deny -> allow`
1209, все одного вида: `import scripts.agent_state as s` в пайпе в python без функции записи
(`classify.py`); `allow -> ask` 604 (строже). `normal.json` 57: 50 без изменений, 6 строже
(`git grep -n .env | bash ... scripts/x.sh`), 1 ask. Тест-копия: 748 passed, 111 failed, все в
функциях форм обхода или точности (список ниже); ни один случай `test_guard_denies`,
`test_guard_asks_the_owner`, `test_guard_asks_before_a_command_shows_a_secret`,
`test_guard_allows`, гейта коммита не упал.
Чем плохо сейчас: 246 строк третьего токенизатора, флаги python, node, perl, ruby и оболочек, разбор
комментариев; каждая правка шла 3-4 прохода ревью; код противоречит своему правилу (обход
запрещён регламентом, а не хуком).
Правка: раздел «Целевой вид» ниже.
Проверка: `make check`; корпус `probe.py` HEAD против новой версии: на секретах мягче 0, мягче
только формы без функции записи; ruff, mypy.
Размер: L (около 4 ч с ревью); класс B; патч владельцу (guard и тесты одним патчем).
Старый ID: R-45, Б18 (остаток).

### HG-13 [средняя] `decision()` не отличает ask правила от ask упавшего guard (R-02)

Где: `tests/unit/test_agent_hooks.py:39-44`.
Факт: мутация «`check_bash` бросает исключение первой строкой» (копия `HG-work/broken`): 662 failed,
197 passed, из них 120 Bash-ask случаев (`test_guard_asks_the_owner` 100,
`test_the_forms_that_asked_before_still_ask` 11, `test_a_backslash...` 6, `test_forty_odd...` 3).
Окно упавшего guard тоже содержит «AGENTS.md hard rule» (`guard.py:449`), поэтому проверка
`"AGENTS.md hard rule" in result.stdout` его не отличает.
Правка: в `decision()` первой строкой `if "guard.py failed" in result.stdout: return "crash"`;
`test_guard_fails_closed` ждёт `"crash"`. Тест на отказ: та же мутация даёт 0 passed среди ask-тестов.
Проверка: мутация в копии: `test_guard_asks_the_owner` 0 passed; без мутации всё зелёное.
Размер: S; класс A (тесты, агент); «ок» не нужно, кроме общего на пакет.
Старый ID: R-02.

### HG-14 [средняя] Guard в процессе через `main()` (R-08, R-27)

Где: `guard.py:1055-1063` (проверка при импорте); `test_agent_hooks.py:21-36` (подпроцесс на каждый
случай), `1910-1918` (`load_guard` режет исходник по тексту).
Факт: (1) обёртка `def main()` и `if __name__ == "__main__": main()` (`HG-work/step1-main.diff`,
29 строк diff) не меняет поведение: неизменённый тестовый файл против неё 859 passed за 40.1 с.
(2) Тестовая копия с `run_guard()` в процессе (`HG-work/tests-inprocess-proto.diff`): 858 passed и
`test_guard_fails_closed` (ждёт новое значение `crash`) за 10.0 с против 66.3 с.
Правка: guard (патч владельцу): `main()` и `__main__`. Тесты (агент): `GUARD` импортом через
`importlib.util.spec_from_file_location`; `run_guard(event, root)` подменяет `GUARD.ROOT`,
`sys.stdin`, ловит `SystemExit`, собирает stdout и stderr в `CompletedProcess`; `bash()` и
`hook("guard.py", ...)` идут через него; `load_guard` заменить тем же импортом и
`monkeypatch.setattr(GUARD, "check_bash", ...)`; оставить 3 подпроцессных теста (deny с кодом 2 и
stderr, ask с JSON, мусор на stdin даёт ask): они проверяют запуск как хука.
Проверка: `uv run pytest tests/unit/test_agent_hooks.py -q` меньше 15 с; R-27 по набору около −55 с.
Размер: S (guard) + M (тесты); класс B; первый шаг патчем владельцу.
Старый ID: R-08, R-27.

### HG-15 [низкая] Дубли и устаревший текст

Где: `guard.py:325-329` (два правила 8083 повторяют `HTTP_WRITE` 295-302; `connect/register.sh`
перенести в 299); docstring 27-42 описывает механизм, который уходит; `SEPARATORS` после HG-12 не
нужен.
Правка: в рамках HG-12; docstring начать с границы: «reads the text of a command, so it catches a
mistake in the usual form, not a bypass (13-harness.md, section 2)».
Размер: S; класс B; патч владельцу.
Старый ID: нет.

## Целевой вид (проект правки)

### guard.py: что остаётся

`SECRET_FILE`, `GIT`, `FORCE_PUSH`, `DROP`, `TRUNCATE`, `DELETE`, `SLOT_SKIP`, `LOGICAL_MESSAGE`,
`SHELL_WRITE_ENV` (HG-11), `HARNESS_FILE`, `HARNESS_DOC`, `STAMP_FILE`, `shell_write` (HG-09),
`STAMP_CLI`, `LINE_CONTINUATION` и проверка двух текстов (12 строк, закрывает `ls # x \` плюс
команда), `HTTP_WRITE`, `COMMIT`, `VERIFY_THEN_COMMIT`, `ASK` (HG-01..04, HG-10, без дублей HG-15),
`VerdictError`, `deny`, `ask`, секреты (`subcommand`, `format_prints_env`, `inspect_prints_env`,
`prints_environment`, `exec_prints_environment`, `secret_in_segment`, `compose_secret`,
`secret_shown`), `commit_gap`, `listed`, `repo_path`, `check`, `check_bash`, новый `main()`.

### Что удалить

| Что | Строки HEAD | Почему |
|---|---|---|
| `SEGMENT` | 130 | только `-X 'a;b'` |
| `WRAPPER_NAMES`, `WRAPPER_ITEM`, `WRAPPER_VALUE`, `WRAPPER_ARGS`, `CODE_RUNNERS`, `AFTER_PIPE`, `READS_STDIN`, `INLINE_PYTHON` | 133-165 | пайп в интерпретатор через обёртки |
| `MAKE_CHECK_ENV`, `REDIRECT`, `bends_make_check` | 166-185 | HG-07 |
| `INTERPRETERS`, `INLINE_CODE` | 359-367 | заменяет одно правило ниже |
| `PUNCTUATION` ... `stdin_code_runners` (`Flavor`, `FLAVORS`, `runner_flavor`, `command_start`, `reads_code_from_stdin`, `strip_comments`, `scan_commands`) | 634-879 | третий токенизатор, только обход |
| `shell_words` | 489-517 | сливается с токенизатором чтения |
| ветка `"agent_state" in command and (INLINE_PYTHON ...)` | 1029-1033 | HG-08 |
| дубли 8083 | 325-329 | HG-15 |

### Что упростить или добавить

1. Один токенизатор `commands(text)`: `shlex` с `punctuation_chars`, перевод строки и обратная
   кавычка как разделители, скобки и `; | & && ||` начинают новую команду, редирект остаётся в своей
   команде; `arguments(words)` отдаёт слова без редиректов и файлы `<`. На нём `is_read(words)`,
   `reads_only`, секреты, отметки.
2. Секрет через код: `.env` назван (вне `--env-file`) и в команде есть интерпретатор или `eval`
   (`python|pypy|perl|ruby|node|bash|sh|zsh|dash|ksh|eval`) даёт ask. Покрывает все 3667 ask
   корпуса; строже на 604 формах.
3. Отметки: `STAMP_CLI`; имя отметки в простой команде, которая не чтение; `agent_state` плюс
   python плюс функция записи.
4. `without_data()` и правила слов только по командам, которые не чтение (HG-06).
5. `READERS` плюс `echo printf stat test [ file du diff pwd true realpath`.

### Размер

- guard.py: 1063 -> около 700 строк (прототип 709 после `ruff format`), код без пустых и комментариев
  921 -> 632.
- test_agent_hooks.py: 2236 -> около 1600; случаев 859 -> около 500; время 66 с -> около 8-10 с.

### Тесты: что удалить, оставить, добавить

Удалить целиком (формы обхода или точность разбора, которого больше нет):
`test_a_shell_option_with_a_value_does_not_make_the_piped_text_a_script_file` (29),
`test_the_inline_code_of_the_other_forms_that_reads_env_asks` (23),
`test_the_other_forms_of_inline_python_that_name_the_stamp_code_are_denied` (12),
`test_the_forms_that_asked_before_still_ask` (11),
`test_a_stamp_written_through_python_u_and_a_process_substitution_is_still_denied` (1),
`test_a_script_file_or_a_module_keeps_the_piped_text_as_data` (19),
`test_forty_wrapper_options_are_decided_in_under_a_second` (12),
`test_a_comment_after_the_interpreter_does_not_make_the_piped_text_data` (9),
`test_a_comment_after_the_interpreter_does_not_hide_the_stamp_code_in_the_pipe` (3),
`test_a_hash_inside_a_word_or_quotes_is_not_a_comment` (6),
`test_a_quote_after_a_separator_inside_a_comment_does_not_hide_the_next_line` (7),
`test_a_stamp_written_after_a_comment_with_a_separator_and_a_quote_is_denied` (1),
`test_the_quotes_decide_which_hash_starts_a_comment` (11),
`test_a_script_file_with_a_hash_in_quotes_is_still_a_script_file` (5),
`test_wrapper_options_with_a_decimal_a_suffix_or_an_assignment_still_feed_the_interpreter` (15),
`test_wrapper_options_with_a_decimal_or_an_assignment_still_feed_the_shell` (9),
`test_a_wrapper_after_an_option_is_not_the_value_of_that_option` (7),
`test_forty_odd_wrapper_options_are_decided_in_under_a_second` (17),
`test_guard_denies_make_check_bent_to_stamp_failing_checks` (12),
`test_guard_denies_a_gate_stamp_written_through_an_unusual_interpreter_call` (20; из них 3 формы с
`write_stamp` перенести в `test_guard_denies_a_gate_stamp_written_by_hand`).
Строки 733-766 и 1743-2236, кроме двух тестов отказа одного текста (1921-1950).

Сократить до представителей: `test_inline_code_that_names_env_is_still_asked` (79 -> около 10:
`-c`, `-c"..."`, heredoc, here-string, `$(pwd)/.env`, имя в переменной, `xargs`, `node -e`, `perl -e`,
перенос `\`), `test_guard_asks_when_the_code_reaches_the_interpreter_in_an_unusual_way` (60 -> около
6), `test_guard_lets_the_unusual_forms_without_env_pass` (30 -> около 10 без `.env`),
`test_guard_allows_the_unusual_forms_that_do_not_touch_the_stamp_code` (11 -> 4).

Оставить без изменений (на прототипе все зелёные): `test_guard_denies`,
`test_guard_denies_a_gate_stamp_written_by_hand` (23), `test_guard_denies_every_file_tool_on_a_gate_stamp`, `test_guard_asks_the_owner`,
`test_guard_asks_before_a_command_shows_a_secret`, `test_guard_lets_a_command_that_shows_no_secret_pass`,
`test_guard_allows`, `test_guard_on_file_writes`, `test_a_backslash_in_a_comment_does_not_hide_the_next_line`,
все тесты гейта коммита, stop_gate, review_stamp, session_context, settings.

Добавить (первыми, красные на HEAD): allow-формы HG-05..HG-11 (около 25 случаев из
`HG-work/fp.json`, `fp2.json`, `commit.json`); ask-формы HG-01..HG-04 (11 случаев из `miss.json`);
один тест времени в процессе: 6 команд по 8-16 KB (`HG-work/gen_long.py`) решаются быстрее 1 с каждая
(сейчас худший `curl x:8083/` x2000 около 1.4 с на guard: lookahead `HTTP_WRITE` квадратичен; на
обычной длине это микросекунды).

### Что перестанет ловиться и почему это приемлемо

| Класс | Пример | Почему приемлемо |
|---|---|---|
| импорт кода отметок без функции записи в тексте | `echo 'import scripts.agent_state as s' \| nice -n 5 python3` (1209 форм корпуса) | импорт ничего не пишет; запись требует второго шага, обход запрещён `13-harness.md:101-104` |
| `make check` с флагом или переменной | `make -i check`, `MAKEFLAGS=-i make check` | `run_check` снимает эти переменные сам (`agent_state.py:51-58`), есть тест |
| команда в теле here-doc, которое `cat` пишет в файл, и затем запуск этого файла в той же строке | `cat > x.sh <<EOF` с DROP, затем `bash x.sh` | это «скрипт с действием C», запрещён `13-harness.md:101-103`; хук и сейчас не видит скрипт, записанный Write |
| слова в шаблоне grep и echo | `docker logs x \| grep "drop table"` | это данные, а не действие |
| точность: `.env` плюс интерпретатор со скриптом | `git grep -n .env \| python3 scripts/x.py` | теперь ask вместо allow; окно в безопасную сторону, форма редкая (6 из 57 в `normal.json`, это синтетические близкие к границе формы) |

Нарочный обход (склейка слов, кодирование, `cd` и скрипт) не ловится и сейчас: SEC-04,
`13-harness.md:97-104`.

### Кандидаты в `permissions` `.claude/settings.json` (синтаксис сверяет HC)

- deny: `Edit(.claude/hooks/**)`, `Edit(.claude/settings.json)`, `Edit(.claude/settings.local.json)`,
  `Edit(.verify-stamp)`, `Edit(.check-stamp)`, `Edit(.review-stamp)` (если правило `Edit` не
  покрывает Write и NotebookEdit, то и для них).
- ask: `Edit(AGENTS.md)`, `Edit(CLAUDE.md)`, `Edit(docs/agent-rules.md)`,
  `Edit(docs/planning/13-harness.md)`, `Edit(scripts/agent_state.py)`, `Edit(.claude/agents/**)`,
  `Edit(.claude/skills/**)`.
- ask, второй слой для Bash (prefix не видит `git -C x push`, `$COMPOSE`, опции перед подкомандой,
  поэтому guard остаётся первым): `git push`, `git rebase`, `git reset --hard`, `make silver`,
  `make nuke`, `make bootstrap`, `make replay-*`, `make chaos-*`, `make down`, `docker compose down`,
  `gh pr create`, `gh workflow run`, `docker push`.
- Рекомендация: файловую ветку guard (`guard.py:963-977`, около 20 строк) переносить только если HC
  подтвердит, что `Edit(...)` закрывает все файловые инструменты и абсолютные пути. `SECRET_FILE`
  оставить в guard: правило в `permissions` не умеет «`.env.*`, кроме `.env.example`»
  (`test_agent_hooks.py:1711-1714` прямо держит это для Read).

## Порядок внедрения

Хуки и `settings.json` агент не правит: копия в scratchpad и патч, владелец применяет. Тесты
правит агент. Каждый шаг оставляет набор зелёным.

1. Патч владельцу П-HG1 (`guard.py` только): `def main()` и `__main__` (`HG-work/step1-main.diff`).
   Применение: `git apply <scratchpad>/hg1.patch && make check`. Неизменённые тесты: 859 passed
   (проверено на копии). Поведение хука прежнее (тот же код в `main()`).
2. Агент, тесты (класс A/B, ревью): R-02, R-08, R-27 (HG-13, HG-14) в `tests/unit/test_agent_hooks.py`;
   удалить тесты форм обхода из списка выше (удаление не краснит). Зелёный на guard шага 1.
   `make check`, `reviewer`, цикл verify, коммит.
3. Патч владельцу П-HG2 одним файлом: `guard.py` целевого вида (HG-01..HG-12, HG-15) и новые тесты
   (allow-формы ложных срабатываний, ask-формы ложных пропусков, тест времени, сокращение
   представителей). Новые тесты красные на guard шага 1, поэтому идут в одном патче с guard, как
   П-4 и П-5. Агент готовит в копии: тесты первыми (красные на копии HEAD), затем guard; прогон корпуса
   (`probe.py`: на секретах мягче 0, мягче только `agent_state` без функции записи), `normal.json`,
   полный `tests/unit` в копии, `reviewer` на копии. Владелец: `git apply <scratchpad>/hg2.patch &&
   make check`; хук живой сразу после `git apply`, поэтому `make check` в той же строке. Затем
   ревью на дереве, цикл verify, коммит.
4. По желанию, после ответа HC: патч П-HG3 (`settings.json` и `test_settings_*` в одном патче).
5. Документы (класс C, окно на AGENTS.md и 13-harness.md): строка «Хуки» AGENTS.md о том, что guard
   не читает данные (сообщение коммита, here-doc `cat`, шаблоны поиска); `13-harness.md` раздел 10
   запись о правке; `15-audit-p5-review/probe.py.txt` больше не нужен для guard (корпус сохранить
   как историю или удалить решением DC).

## Находки «не делать»

| ID | что | почему не делать |
|---|---|---|
| HG-n1 | `rm -rf <scratchpad>/...` даёт окно, хотя `13-harness.md:40` относит файлы scratchpad к классу A | противоречие правил, а не guard; решение владельца: оставить окно (проще) или исключить `/tmp/claude-*`; рекомендую оставить |
| HG-n2 | `git restore --staged x` ask «discards uncommitted work» | редко, окно в безопасную сторону |
| HG-n3 | `uv run pytest ... -k expire_snapshots` ask | редко, клик |
| HG-n4 | `docker exec lakehouse-prometheus-1 kill -HUP 1`, `airflow dags trigger silver_upsert`, `airflow variables set ...` allow | перезагрузка конфига и ручной запуск DAG, который и так идёт по расписанию; не в списке AGENTS.md; правило держит регламент |
| HG-n5 | `find ... \| xargs grep "git push --force"`, `awk '/DROP TABLE/'` deny | `xargs` и `awk` исполняют код; редкие формы |
| HG-n6 | квадратичный `HTTP_WRITE` на команде 16 KB (около 1.4 с) | нереальная длина; тест времени из HG-12 держит границу |
| HG-n7 | `.env` в одной команде с интерпретатором ask даже при разных частях (Б11б) | принято владельцем 30.10, сторона безопасная |
| HG-n8 | `CALL lake.system.rewrite_manifests` allow | переписывает только метаданные; снимок остаётся |

## Разрыв с продом

- Хук по тексту команды не граница безопасности: в проде агент работал бы в песочнице с
  ограниченными учётками (Postgres и Trino только на чтение для агента; `lake_ro` есть только для BI).
- Нет журнала решений хука (deny и ask не пишутся), трение и попытки считаются только по памяти.
- Гейт коммита держат локальные файлы отметок; в проде то же требует сервер: обязательные проверки CI
  и CODEOWNERS на `.claude/` и `scripts/agent_state.py`.
- Корпус регрессий хука живёт в `docs/planning`, а не в CI.
- Правка харнесса без ревью второго человека (владелец применяет патч, агент ревьюер).

## Не проверено

- Синтаксис и семантика `permissions` (кандидаты выше): область HC.
- Живой хук в сессии с прототипом: прототип проверен только в копиях (в процессе и подпроцессом);
  проверит: после `git apply` выполнить команды `HG-work/fp.json` вручную или `probe.py`.
- Полный `tests/unit` против прототипа не запускался (только копия `test_agent_hooks.py`); проверит:
  `make check` после применения.
- Мутационное тестирование прототипа не делалось; проверит: мутации `is_read`, `without_data`,
  `writes_stamp`, исключения scheduler, по одной, тест-копия должна краснеть.
- `shlex.join` в проверке слов на редких токенах (`$'...'`, NUL) не исследовался; при несбалансированных
  кавычках прототип проверяет весь текст (как HEAD).
- Защита ветки на GitHub и CODEOWNERS не проверялись (область IN).
- Время набора в CI после R-27 не измерено; проверит: `gh run view <id>` после коммита.

Пути опытов (scratchpad):
`<scratchpad>/audit/HG-work/`:
`probe.py` (решения одной или двух копий, `GATE_OPEN=1` открывает гейт), `fp.json`, `fp2.json`,
`commit.json`, `miss.json`, `long.json`, их `*-out.txt`, `corpus-out.txt`, `normal-out.txt`,
`classify.py`, `slim/.claude/hooks/guard.py` и `slim-fmt.py` (прототип), `slim-proto.diff`,
`step1-main.diff`, `make_test_copy.py`, `tests-inprocess-proto.diff`, `t_head/`, `t_slim/`,
`t_step1/`, `broken/` (мутация R-02), `slim-fail.txt` (111 упавших случаев прототипа).
