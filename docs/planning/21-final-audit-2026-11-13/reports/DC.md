# DC. Документы и подача (нанимающий, интервьюер, новый инженер)

Дерево: HEAD `a8c1d49` плюс незакоммиченные правки владельца (`.github/workflows/ci.yml`,
`OPERATIONS.md`, `docs/HANDOFF.md`, `docs/NEXT_SESSION.md`, `tests/unit/test_workflows.py`) и
неотслеживаемая папка `docs/planning/21-final-audit-2026-11-13/`. Номера строк по рабочему дереву
13.11.2026. Ничего в репозитории и на стенде не менялось. Скрипты и сырые выводы:
`<scratchpad>/audit/DC-work/` (путь scratchpad в финальном сообщении агента; в отчёт не вписан,
потому что содержит имя пользователя) (`check_docs.py`, `compose_facts.py`, `links.txt`, `fileline.txt`, `dashes.txt`, `names.txt`,
`ai.txt`, `r66_pattern.txt`, `r66_final.txt`, `r66_grouped.txt`).

## Оценки

- Тимлид, нанимающий (3 минуты): 3 из 5. Сильный первый абзац и честные числа, но README 19.7 KB
  с журналом статуса 7.4 KB, полупустой скриншот Grafana от 29.10 вместо Superset v2, ложное
  «4 charts», нет версий стека и блока «что доказано», строка «LEARNING.md is empty», красный CI
  у последнего коммита.
- Интервьюер (30 минут): 4 из 5. evidence и interview-notes с датой и источником у каждого числа,
  259 относительных ссылок без единой битой вне истории, все 34 ссылки `file:N` в interview-notes
  указывают на нужную строку кода; спотыкается о ссылки в русские HANDOFF и планы, ID карточек
  (`W6-D17`), OPERATIONS 137 KB без оглавления, нет раздела о разрыве с продом и цифр
  производительности.
- Новый инженер: 4 из 5. Один `make bootstrap`, путь с чистого клона еженедельно зелёный в smoke;
  не названы инструменты хоста (`envsubst`, `curl`, `make`), нет предупреждения о смене `BIND_IP`.

## Сильные стороны

- Каждое число с датой и источником; 0 битых ссылок: `python3 -I DC-work/check_docs.py <repo> links`
  -> `links checked: 259, github-relative: 15, broken: 1` (единственная в истории,
  `docs/planning/08-w3-plan/T00-clean-clone.md:361`, черновик текста README).
- Ссылки на код в interview-notes точны: `check_docs.py <repo> fileline` печатает для всех 34
  ссылок ту строку, о которой говорит ответ (например `docs/interview-notes.md:116 ->
  streaming/spark_jobs/silver_upsert.py:158: newer = "(t._last_lsn is null or s._last_lsn >
  t._last_lsn)"`).
- Все 10 запусков Actions из README и evidence существуют и имеют заявленный итог:
  `gh run view <id> --json conclusion,headSha` (42848376843 ci success 63e5650, 40907438614 и
  ещё 2 smoke success, 40897412910 ci failure f206596, 40290595866 smoke failure и т. д.).
- Честный список недоказанного: `docs/evidence.md:271-285` («Not proven yet»), отказ от 24-часового
  окна назван прямо (`README.md:160`).
- Таблица сценариев отказа с измеренным временем и итогом: `README.md:168-181`,
  `docs/evidence.md:69-81`; 10 скриптов в `scripts/chaos/`.
- Раздел «How it was built» считает артефакты, а не обещает: `docs/evidence.md:287-348` (журнал
  «ок» 28 записей с командой пересчёта, примеры находок ревью, пределы процесса).
- Гигиена: длинных тире в отслеживаемых файлах 4 строки, все в одном плане
  (`check_docs.py dashes` -> `lines with long dashes: 4`); GitHub About, 16 topics и MIT
  на месте (`gh repo view`: `licenseInfo.key: mit`).

## Старый бэклог

| ID | статус сейчас | делать / не делать | причина |
|---|---|---|---|
| R-60 | закрыт `3e00084` (README:37 о protect.sh верен, `streaming/README.md` без «W2-T09» и «W4-T02»); новые расхождения ниже как DC-01, DC-06 | закрыт | остатки «вне карточки» (комментарии в коде) у DP и IN |
| R-62 | открыт: `wc -c README.md` 19712, раздел Status 7421 байт, `README.md:225` ведёт в пустой `LEARNING.md` | делать (DC-02, DC-03) | первое впечатление рекрутера |
| R-65 | у HR (размер документов агентов) | не в DC | область HR |
| R-66 | открыт: 156 строк в 80 файлах (шаблон ниже) | делать (DC-04, DC-05) | история в коде видна внешнему читателю |
| R-68 | закрыт: `LICENSE.md`, README «Data»/«License», About и topics (`gh repo view`) | закрыт | атрибуция в seed не нужна (решение 10.11) |
| PF-03 | открыт: `grep -n -i loopback .env.example README.md` пуст; `.env.example:4` без комментария | делать (DC-07) | публичный репозиторий, порты без входа |
| PF-04 | открыт: «last community» в `README.md:51`, `docker/compose.yaml:154`, `docker/minio/Dockerfile:1`, `DECISIONS.md:11` | делать (DC-06) | ложное утверждение на первой странице |
| PF-40 | открыт: в evidence «CI and smoke» нет строки, что smoke кончается на silver | делать (DC-14) | честность доказательства |
| PF-50 | закрыт `3e00084` (`README.md:59-62`, `ARCHITECTURE.md:142-143` с условиями) | закрыт | |
| PF-51 | закрыт: `grep -n 'had five\|is .planned\|825 passed' README.md docs/evidence.md` пуст | закрыт | новые устаревшие числа в DC-13 |
| PF-52 | открыт: в Mermaid `ARCHITECTURE.md:16-53` нет `postgres-meta` | делать (DC-16) | дёшево, видно на схеме |
| PF-53 | у GB/OB (кэш Superset) | не в DC | |
| PF-55 | открыт в `17-audit-fixes.md` | не делать | история планирования, не переписывать |
| PF-60, PF-61 | закрыты (`LICENSE.md`, `README.md:227-238`) | закрыт | |
| PF-62 | открыт: фамилия в 4 отслеживаемых файлах (DC-10) плюс новый `00-audit-prompt.md:234` | делать (DC-10) | правило «нет имён владельца» |
| PF-63 | у HR | не в DC | |
| PF-64 | открыт: `gh api repos/{owner}/{repo}/branches` -> `main`, `w3-fernet-replay-data` | делать по «ок» (DC-21) | посетитель видит 2 ветки |
| Д2.5 остаток (README и скриншот) | открыт: `README.md:87` «4 charts», `docs/evidence.md:269` «Screenshot: planned»; в бандле 13 графиков (`ls docker/superset/dashboards/charts | wc -l` -> 13) | делать (DC-01) | ложное утверждение на первой странице |
| Д2.5 остаток (тест `annotation_layers`, `rename`) | у GB | не в DC | |
| Спека 14, раздел 7: `LEARNING.md:4` «task the AI» | открыт | делать (DC-03) | упоминание AI вне разрешённого места |
| Спека 14, раздел 6, п. 8 (гейты в LEARNING) | отложено владельцем 06.11 | решение владельца (DC-03) | файл пуст и виден |
| HANDOFF верх: «README:213 без JDK 17», скриншот и строка README | открыт | делать (DC-13, DC-01) | после коммита починки CI |
| Аудит 15, раздел 10 | пунктов по документам подачи нет (Б1-Б20 про код и харнесс) | не в DC | |

## Находки «делать»

### DC-01 [высокая] Ложное «4 charts» и устаревший образ дашборда на первой странице
Где: `README.md:8-9`, `README.md:11`, `README.md:87`, `README.md:163`; `ARCHITECTURE.md:116-117`;
`docs/evidence.md:269`.
Факт: `README.md:87` «dashboard "Marketplace" (4 charts over `lake_ro.gold`)»;
`ARCHITECTURE.md:116-117` «it shows the same four questions as a dashboard `Marketplace`»; в бандле 13
графиков (`ls docker/superset/dashboards/charts | wc -l` -> 13, `grep -c chartId
docker/superset/dashboards/dashboards/*.yaml` -> 13), evidence сам пишет «13 charts»
(`docs/evidence.md:256`). Hero-картинка `README.md:11` это Grafana от 2026-10-29: 4 панели и пустая
нижняя треть кадра 1600x1000 (`docs/img/marketplace-dashboard.png`). `README.md:8` называет 4 вопроса,
а Superset v2 добавляет KPI (GMV, заказы, AOV, доля фрахта, on-time, доля отмен) и статусы заказов.
Чем плохо: рекрутер видит в первом экране устаревший слабый скриншот, интервьюер находит
расхождение README с evidence.
Правка: README:87 «13 charts: KPI tiles with the previous period, GMV by month against a year ago,
top categories, on-time delivery by month and the worst states, cancellations, order statuses»;
README:8-9 перечислить вопросы v2 (по `docs/planning/20-superset-dashboard.md`, вариант A);
ARCHITECTURE:116-117 «a dashboard `Marketplace` of 13 charts over the same marts»; README:163 строка
статуса с check.py 13 из 13 (2026-11-13, `docs/evidence.md:268`). Картинка: владелец кладёт
`docs/img/superset-marketplace.png` (PNG, ширина 1600, без панели браузера и имён), README:11
показывает её с подписью «Superset, <дата> UTC»; Grafana-скриншот остаётся только в
`docs/evidence.md:190`. evidence:269 «Screenshot: planned» заменить ссылкой на картинку. Если
картинки нет к моменту правки: hero не трогать, но подпись «Grafana view of the same marts» и
строку 269 оставить.
Проверка: `grep -n '4 charts\|four questions\|same four' README.md ARCHITECTURE.md` пуст;
`test -f docs/img/superset-marketplace.png && grep -c superset-marketplace.png README.md` -> 1;
`python3 -I DC-work/check_docs.py . links` -> `broken: 1` (только история).
Размер: S; класс A (документы); картинку даёт владелец.
Старый ID: Д2.5 остаток; HANDOFF верх.

### DC-02 [высокая] README: журнал вместо витрины, 19.7 KB, нет версий стека и итогов
Где: `README.md:1-238`; раздел `## Status` `README.md:134-183` (7421 байт).
Факт: `wc -c README.md` -> 19712; размеры разделов: Quick start 3527, Explore the stack 2276,
Status 7421. Версий стека в README нет ни одной (`grep -nE '[0-9]+\.[0-9]+\.[0-9]+' README.md` даёт
только запуски Actions). Строки `planned` о том, что после заморозки не будет сделано:
`README.md:158-159`, `:162`, `:181`. Таблица профилей не называет профиль `jobs` (`spark-silver`,
`docker/compose.yaml`, профили по `compose_facts.py`), строка Airflow `README.md:86` перечисляет 4
DAG из 5 (нет `iceberg_orphans`, `airflow/dags/iceberg_orphans.py:30`).
Чем плохо: за 3 минуты рекрутер не находит «что доказано» и «на чём сделано»; `planned` после
заморозки читается как брошенная работа.
Правка: переписать по целевой структуре (раздел «Целевая структура README» ниже), до 10 KB.
Таблицу статуса компонентов перенести в `docs/evidence.md` (новый раздел «Status» вверху),
сценарии отказа оставить в evidence (они там уже есть, `docs/evidence.md:69-81`), полную
таблицу адресов и профилей в OPERATIONS (разделы «Ports», «Profiles» уже есть). Все `planned`
после заморозки заменить на `not done` с причиной в одну строку.
Проверка: `test $(wc -c < README.md) -le 10240`; `grep -c '^## ' README.md` 9-11;
`grep -n 'planned' README.md` пуст; `check_docs.py . links` без новых битых; каждая цифра README
есть в evidence или в коде (ревьюер сверяет по таблице «Числа README против кода» ниже).
Размер: M; класс A; `docs-writer`.
Старый ID: R-62.

### DC-03 [средняя] Пустой `LEARNING.md` в корне и две ссылки на него
Где: `LEARNING.md:1-30`; `README.md:162`, `README.md:223-225`; `docs/evidence.md:283`;
`LEARNING.md:4` («task the AI with a change»).
Факт: в файле только шапка и пустая таблица гейтов; README пишет «LEARNING.md is empty».
Чем плохо: пустой файл в корне и строка «is empty» на первой странице; упоминание AI вне
разрешённого места (правило W6-D15, `AGENTS.md:128-131`).
Правка (рекомендация владельцу, решение О-1): `git rm LEARNING.md`; убрать README:162 и раздел
`## What I learned` (`README.md:223-225`), строку `docs/evidence.md:283`; вместо них раздел
«Lessons from the failure runs» в `docs/interview-notes.md` (6-8 пунктов, каждый со ссылкой на
evidence или OPERATIONS: пауза DAG теряет событие Asset `docs/evidence.md:142-147`; кэш метаданных
Trino скрывает лежащий MinIO (`docs/evidence.md:54-61`); kill Connect повторяет до 60 с событий
(`docs/interview-notes.md:72-84`); удержание Kafka 24 ч и простой 26 ч (`docs/interview-notes.md:49-55`);
`SparkNoBatch5m` молчит при crash-loop (`docs/evidence.md:149-151`); тест с фиксированными часами
(`docs/evidence.md:173-175`); двойной счёт заказов по штатам (`docs/evidence.md:196-199`)).
Ссылки правил на LEARNING (`AGENTS.md:128`, `docs/agent-rules.md:65`) правит оркестратор с окном
подтверждения; `docs/planning/02-learning-gates.md` не трогать (история).
Проверка: `test ! -e LEARNING.md`; `git grep -n 'LEARNING' -- . ':!docs/planning' ':!docs/HANDOFF.md'` пуст;
`check_docs.py . links` без новых битых.
Размер: S; класс A; удаление файла по «ок» владельца.
Старый ID: R-62, спека 14 раздел 7 (`LEARNING.md:4`).

### DC-04 [средняя] История в коде: ID карточек, аудитов, решений недели и даты (R-66)
Где: 156 строк в 80 файлах, полный список в «Приложение А».
Команда, которая воспроизводит список (из корня репозитория):

```bash
P='\b(W[0-9](-[TD][0-9]+[ab]?)?|D[0-9]{1,2}|(QA|SEC|REL|DATA|DOC|MODEL|ARCH|AI|PF|F|R)-[0-9]{2}|RT-S[0-9]|[BbБК][0-9]{1,2})\b|[Aa]udit|[Ww]eek[ -][0-9]|verified 202|[(, ]202[0-9]-[01][0-9]-[0-3][0-9]\b'
git ls-files | grep -vE '^(docs/|\.claude/)|(^|/)[^/]*\.md$|^uv\.lock$|^data/sample/|\.(csv|svg|png)$' \
  | xargs grep -nE "$P" | grep -vE '^tests/unit/test_agent_hooks.py:(1171|1176):'
```

Факт (примеры): `observability/prometheus/alerts.yml:1-3` «The six alerts of week 4 (W4-T05) ...
the audit of 30.10 adds SilverGoldNotCompared (B3)»; `docker/compose.yaml:712,736,762` «verified
2026-10-19»; `dbt/tests/_tests.yml:8-9` «287 orders ... (2026-10-09)» (факт 297 по PF-45);
`tests/unit/test_compose.py:1` «SEC-02: ...»; `airflow/dags/dq_checks.py:6` «(audit MODEL-02 ...)».
Исключены как данные, а не история: литералы дат в тестах (`"2026-...`, `'2026-...`),
`SUPERSET_DATA_ANCHOR=2026-07-01` (`.env.example:74`, `docker/compose.yaml:829,907`), фикстуры
`W3-T01/W3-T02` в `tests/unit/test_agent_hooks.py:1171,1176`, теги MinIO `RELEASE.2025-...`.
Чем плохо: читатель кода видит `B3`, `W6-D17`, `audit 30.10` и не может их расшифровать (планы на
русском); даты у чисел в описаниях dbt стареют (287 против 297).
Правка, правило замены:
1. ID карточек и аудитов (`W<n>-T<nn>`, `B<n>`, `QA-01`, `SEC-02`, `REL-01`, `DATA-02`, `F-01`,
   `PF-42`, `MODEL-02`, `RT-S3`, `AI-05`, «audit of 30.10», «week 4», «review of W4 and W5»)
   удалить, предложение оставить.
2. Решения недели заменить номером ADR, если он есть, иначе удалить метку и оставить правило:
   `D4` -> ADR-009 (мягкие удаления, фильтр в потребителе); `D10`, `D12`, `W4-D12` -> ADR-011;
   `W4-D1`, `W4-D2`, `W4-D3`, `W4-D6` -> ADR-023; `W5-D11`, `W5-D12`, `W5-D13`, `W6-D6` -> ADR-025;
   `W5-T01*` -> ADR-024; `W2-T07` -> ADR-020; `W6-D17` -> ADR-028, если R-61 принят, иначе метку
   убрать; `D3`, `D5`, `D6`, `D7`, `D8`, `D13`, `D14`, `D18`, `D19`, `D20`, `W6-D9`, `W6-D11`,
   `W6-D2` без ADR: метку убрать (суть уже в предложении). Ссылку `docs/planning/07-w3-spec.md` в
   `scripts/replay-burst.sh:4` заменить на `OPERATIONS.md` (раздел о бюджете реплея).
3. Даты: «verified 2026-10-19» удалить; у чисел источника в описаниях dbt (`_core.yml:4`,
   `_tests.yml:8-21`, `_staging.yml:5,76,108`, `_marts.yml:16`, `dim_products.sql:1`,
   `assert_*.sql`) писать «on the full Olist dataset» без даты, а число держать равным факту
   (PF-45: 297) или убрать число, оставив порог из var; даты в комментариях compose и
   скриптов (`compose.yaml:507,715,779`, `scripts/chaos/lib.sh:48`,
   `tests/unit/test_container_exporter.py:89`, `tests/unit/test_minio_image.py:37`) удалить,
   оставив причину.
4. Тест на отказ первым: `tests/unit/test_no_history_in_code.py` гоняет шаблон выше по
   `git ls-files` с тем же фильтром и падает на любой строке, кроме списка исключений в самом тесте
   (фикстуры). До правки красный (156 строк), после зелёный.
Проверка: команда выше печатает 0 строк; `docker compose --env-file .env.example -f
docker/compose.yaml --profile '*' config --hash '*'` до и после совпадает построчно; `make
dbt-parse`, `make alerts-test`, `make check` зелёные; `git diff -U0 | grep -E '^[-+][^-+]' | grep
-vE '^[-+]\s*(#|--|//|"""|\{#|description:|[A-Za-z].*)'` просматривает ревьюер: меняются только
комментарии, docstring и `description`.
Размер: M (около 2 ч); класс B (код без смены поведения; `pipeline-health.json:676` и бандл
Superset меняют только `description`, живого шага не требуют); `implementer`.
Старый ID: R-66, PF-45.

### DC-05 [средняя] ID карточек и ссылки в русские документы в публичных Markdown
Где: `ARCHITECTURE.md:13` (W6-D14), `:101` (W6-D9), `:113` (W6-D17); `docs/interview-notes.md:414`
(«A week-6 rule»), `:471` («Since the audit commit `e2ae619`»); `oltp/README.md:31` (W2-T07);
`connect/README.md:6` («week 1, W1-T05»); `dbt/README.md:8,13,14,17,19,26,29,37,38` (D3..D14 и путь
`docs/planning/07-w3-spec.md`); `docs/runbooks/spark-stalled.md:30` («week 5»);
`README.md:146` (ссылки в HANDOFF и архив на русском), `README.md:176` (HANDOFF и спека 14);
`docs/evidence.md` 16 строк с ID (`31, 49, 77, 116, 138, 142, 187, 192, 207, 284, 303, 321, 323,
326, 331, 334`). В OPERATIONS 36 строк и DECISIONS 36 строк того же рода (области OB и AR).
Факт: команда `grep -nE "<шаблон DC-04 без дат>" README.md ARCHITECTURE.md docs/interview-notes.md
*/README.md docs/runbooks/*.md` даёт перечисленные строки.
Чем плохо: интервьюер не может открыть «W6-D17», а ссылка ведёт в русский HANDOFF.
Правка: README, ARCHITECTURE, interview-notes, README компонентов, runbooks: правило DC-04
(ADR или без метки; «A rule added after scenario 8», «Since commit `e2ae619`»). dbt/README: решения
D3, D4, D5, D6, D7, D13, D14 сказать словами (они уже сказаны), ADR-009 у D4. README:146 ссылаться
на `docs/evidence.md` и прогон `make dbt-build` 2026-11-12 (`dbt/target/run_results.json`: 61 pass
+ 18 success = PASS 79, warn 4), не на HANDOFF и архив. README:176 источник в evidence
(`docs/evidence.md:77`). В evidence ID оставить только как подпись источника с пометкой
«(record in Russian)» у ссылки, в повествовании убрать.
Проверка: шаблон DC-04 без части дат по `README.md ARCHITECTURE.md docs/interview-notes.md
*/README.md docs/runbooks/*.md` пуст (кроме `docs/runbooks/catalog-cutover.md`, если его увозит
R-40); `grep -n 'HANDOFF\|planning/archive' README.md ARCHITECTURE.md` пуст.
Размер: S-M; класс A; `docs-writer`.
Старый ID: R-66 (часть документов).

### DC-06 [средняя] «last community release/tags» неверно
Где: `README.md:51`; `docker/compose.yaml:154`; `docker/minio/Dockerfile:1`; `DECISIONS.md:11`.
Факт: `grep -rn 'last community' README.md DECISIONS.md docker` -> 4 строки; после закреплённого
`RELEASE.2025-09-07T16-13-09Z` (`docker/minio/Dockerfile:13`) есть более поздний тег (PF-04, 18).
Чем плохо: проверяемо ложное утверждение на первой странице.
Правка: «built from the source of pinned community releases (MinIO `RELEASE.2025-09-07T16-13-09Z`,
`mc` `RELEASE.2025-08-13T08-35-41Z`)»; в DECISIONS:11 то же. Фразы «no console» в ADR-004/026
(`DECISIONS.md:51-58,761`) правит AR.
Проверка: `grep -rn 'last community' README.md DECISIONS.md docker` пуст; `docker compose ...
config --hash '*'` без изменений.
Размер: S; класс A (комментарии и документы).
Старый ID: PF-04.

### DC-07 [средняя] Нет модели безопасности и предупреждения у `BIND_IP`
Где: `README.md:76-77` («Every port is bound to `127.0.0.1`»), `.env.example:4`.
Факт: `grep -n -i 'loopback\|security model' .env.example README.md` пуст; при этом Airflow «every
visitor is admin» (`README.md:86`), MCP «run as admin» (`README.md:88`), Trino «the user name is a
label» (`README.md:91`).
Чем плохо: посетитель, сменивший `BIND_IP`, откроет наружу Airflow с `docker.sock`, MCP с правами
admin, Trino, Connect, Kafka, Lakekeeper.
Правка: в README раздел «Security model» (5-6 строк): только loopback; без аутентификации Airflow,
Trino, Connect, Lakekeeper, Kafka, MCP; `docker.sock` у scheduler; общие учётки MinIO; что
сделал бы прод (ссылка на «Production gap», DC-15). Комментарий у `.env.example:4`: «127.0.0.1
only: several services have no login (README, Security model)». Строку `superset` в таблицу
Access control OPERATIONS добавляет OB.
Проверка: `grep -n -i loopback .env.example README.md` даёт 2+ строки; тест
`tests/unit/test_compose.py` не меняется.
Размер: S; класс A.
Старый ID: PF-03.

### DC-08 [средняя] Нет карты документов; индекс планов только на русском
Где: `README.md:17-21` (5 ссылок без порядка чтения); `docs/planning/README.md:1-5`; нет
`docs/runbooks/` в навигации README; OPERATIONS 137688 байт без оглавления (`grep -c '^## '
OPERATIONS.md` -> 17 разделов, первая строка сразу `## Profiles`).
Факт: посетитель из `docs/planning/` видит индекс целиком на русском.
Чем плохо: интервьюер тратит минуты на поиск, где что; «почему всё на русском» без ответа.
Правка: (а) в README раздел «Documentation» с таблицей из «Целевая карта навигации» ниже;
(б) в начало `docs/planning/README.md` английский абзац (текст в разделе «Целевой вид docs/»);
(в) оглавление OPERATIONS делает OB (R-63), здесь только ссылка на него из карты.
Проверка: `grep -n '^## Documentation' README.md` -> 1; `head -8 docs/planning/README.md | grep -c
'working history'` -> 1; `check_docs.py . links` без новых битых.
Размер: S; класс A.
Старый ID: R-62 (часть), нет.

### DC-09 [средняя] Патчи и корпус ревьюера в `docs/planning/`: 1.35 MB шума
Где: `docs/planning/13-harness-guard.patch`, `15-audit-p1-harness.patch`, `15-audit-p3-harness.patch`,
`15-audit-p4-harness.patch`, `15-audit-p5-harness.patch` (вместе 167 KB);
`docs/planning/15-audit-p5-review/` (`corpus-result-v1..v4.txt` 808 KB, `corpus.json` 544 KB,
`normal.json`, `probe.py.txt`); строки индекса `docs/planning/README.md:20,23-27`.
Факт: все патчи применены (`5ca361a`, `8577de1`, `90c64b2`, `7e5af85`; индекс); код на них не
ссылается (`git grep -n 'corpus\|p5-review' -- tests scripts .claude Makefile` пуст);
`corpus-result-v3.txt` и `probe.py.txt` содержат фамилию в пути (DC-10).
Чем плохо: посетитель открывает `docs/planning` и видит пять `.patch` и мегабайт txt.
Правка: `git rm` пяти `*.patch`, `corpus-result-v1..v4.txt`, `probe.py.txt`; `corpus.json` и
`normal.json` оставить, только если HG сохраняет токенный разбор guard (R-45), иначе удалить
каталог целиком. Строки индекса: «applied in `<commit>`; file removed at the final audit, see `git
show <commit>^:docs/planning/<name>`».
Проверка: `git ls-files 'docs/planning/*.patch' | wc -l` -> 0; `git ls-files
docs/planning/15-audit-p5-review | grep -c txt` -> 0; `check_docs.py . names` без строк из этих файлов.
Размер: S; класс A; удаление файлов по «ок» владельца (решение О-4).
Старый ID: PF-62 (часть).

### DC-10 [низкая] Фамилия из пути домашнего каталога в отслеживаемых файлах
Где (значения не раскрываются): `docs/HANDOFF.md:276,284,528`; `docs/planning/12-review-w4-w5.md:55`;
`docs/planning/15-audit-p5-review/corpus-result-v3.txt:1,803,805,1019,1077,1093,1135`;
`docs/planning/15-audit-p5-review/probe.py.txt:11`; неотслеживаемый, но пойдёт в коммит:
`docs/planning/21-final-audit-2026-11-13/00-audit-prompt.md:234`. Логин git: `LICENSE.md:3`
(разрешено), `docs/HANDOFF.md:86,505`, `docs/NEXT_SESSION.md:39`,
`docs/planning/19-review-2026-11-10.md:183`.
Факт: `python3 -I DC-work/check_docs.py . names` (печатает только вид и file:line).
Чем плохо: правило «в репо нет имён владельца» (`docs/agent-rules.md:68`); логин и так публичен в
URL и LICENSE, фамилия нет.
Правка: путь заменить на `~/` или `/home/<user>/` в HANDOFF и `00-audit-prompt.md:234` (перед
коммитом папки 21); `12-review-w4-w5.md:55` одна правка пути; файлы корпуса уходят в DC-09.
Упоминания логина в документах агентов оставить (публичен).
Проверка: `check_docs.py . names | grep SURNAME` пуст.
Размер: S; класс A.
Старый ID: PF-62.

### DC-11 [низкая] Длинные тире
Где: `docs/planning/20-superset-dashboard.md:41` (U+2014), `:44,51,52` (U+2013).
Факт: `check_docs.py . dashes` -> 4 строки, других нет.
Правка: заменить на двоеточие или дефис (правило стиля, `AGENTS.md:127`, `docs/agent-rules.md:66`).
Проверка: `check_docs.py . dashes` -> `lines with long dashes: 0`.
Размер: S; класс A.
Старый ID: нет.

### DC-12 [низкая] Упоминание агентов вне разрешённых мест
Где: `scripts/README.md:16` («which the agent hooks in `.claude/hooks/` check before a commit»);
`LEARNING.md:4` (уходит с DC-03).
Факт: `check_docs.py . ai <публичные файлы>`; остальные попадания это MCP как функция продукта
(`OPERATIONS.md:471,545`, `README.md:88`) и JMX agent (`OPERATIONS.md:736,800`), они не об авторстве.
Правка: «which the commit-gate hooks in `.claude/hooks/` check before a commit (how the project was
built: `docs/evidence.md#how-it-was-built`)».
Проверка: `grep -n -w 'agent' scripts/README.md` пуст.
Размер: S; класс A.
Старый ID: спека 14, раздел 7 (гигиена W6-T02).

### DC-13 [средняя] Устаревшие числа CI и проверок после починки CI
Где: `README.md:156` (зелёный run `42848376843` на `63e5650`), `README.md:213-221` (нет шага
Temurin 17), `README.md:39-42` (времена smoke 29.10), `docs/evidence.md:177-181` («`make check` 1879
passed», «239 passed»).
Факт: на `main` CI красный (`gh run list --workflow ci.yml --limit 3`: 43423260590 и 43420783131
failure на `a8c1d49` и `4adbab9`); починка в дереве не закоммичена; `make check` на дереве 1927
passed (HANDOFF:24); последний smoke 42872707771 success 10m47s 2026-11-10.
Чем плохо: страница репозитория показывает красный крест у последнего коммита; README называет
зелёный run трёхдневной давности.
Правка: после коммита починки CI (область IN) и зелёного run: README:213 добавить «Temurin 17
for the local SparkSession tests» в `lint-and-test`; README:156 и evidence:177-181 итоговые
числа и id зелёного run финального коммита; README:39-42 последние smoke (42872707771, 10 мин 47 с,
2026-11-10). Последней правкой пакета документов, после финального CI.
Проверка: `gh run list --workflow ci.yml --limit 1 --json conclusion,headSha` -> success на HEAD;
`grep -n '1879 passed\|42848376843' README.md docs/evidence.md` пуст.
Размер: S; класс A; зависит от пакета IN (CI).
Старый ID: HANDOFF верх (README:213), PF-51 (продолжение).

### DC-14 [средняя] Smoke доказывает путь только до silver, документы этого не говорят
Где: `README.md:157`, `README.md:36-42`; `docs/evidence.md:165-171`.
Факт: шаги `.github/workflows/smoke.yml` (`grep -nE 'run:|name:'`): bootstrap, минута реплея и
verify, повторный bootstrap; `make dbt-build`, Asset, `dq_checks`, дашборды не входят.
Правка: одна фраза в evidence «CI and smoke» и в строке README: «smoke stops at silver; gold, the
Asset chain, `dq_checks` and the dashboards are proven by the dated manual runs above».
Проверка: `grep -n 'stops at silver' docs/evidence.md README.md` -> 2 строки.
Размер: S; класс A.
Старый ID: PF-40.

### DC-15 [средняя] Нет раздела «что нужно до прода»
Где: `ARCHITECTURE.md:133-136` («What is deliberately absent» в 2 строки); нет ссылки из README.
Факт: ограничения разбросаны: `docs/interview-notes.md:493-515` (Q30), `docs/evidence.md:271-285`,
OPERATIONS «Access control».
Чем плохо: главный вопрос интервьюера Senior DE «что бы вы сделали в проде» без ответа в одном
месте.
Правка: `ARCHITECTURE.md` раздел «## Production gap» после «What is deliberately absent»: таблица
до 1.5 KB (HA, масштаб, безопасность, управление данными, среды и деплой, стоимость, DR: есть,
нет, чем заменено здесь) по матрице области AR; ссылка из README (раздел Status/limits) и из Q30.
Проверка: `grep -n '^## Production gap' ARCHITECTURE.md` -> 1; ссылка `ARCHITECTURE.md#production-gap`
открывается (`check_docs.py . links`).
Размер: S; класс A; содержание из отчёта AR.
Старый ID: нет.

### DC-16 [низкая] Схема без `postgres-meta`
Где: `ARCHITECTURE.md:16-53`, `docs/img/architecture.svg`.
Факт: в Mermaid нет узла `postgres-meta` (база Lakekeeper, Airflow, Superset; `docker/compose.yaml`,
сервис `postgres-meta`); `grep -c postgres-meta docs/img/architecture.svg` -> 0.
Правка: узел `PGM[("postgres-meta<br/>Lakekeeper, Airflow, Superset metadata")]` и пунктир к LK,
Airflow, SS; переэкспорт командой `ARCHITECTURE.md:59-62`.
Проверка: `grep -c postgres-meta docs/img/architecture.svg` -> 1+.
Размер: S; класс A (docker run Mermaid CLI тянет образ: B).
Старый ID: PF-52.

### DC-17 [средняя] interview-notes: нет BI, тестов, безопасности, прода и «что сделал бы иначе»
Где: `docs/interview-notes.md:7-10` (7 тем: Kafka, Spark, Iceberg, идемпотентность, DQ,
наблюдаемость, system design).
Факт: нет вопросов о метриках и зерне gold (история `orders_count` 96 650 против 96 163,
`docs/evidence.md:196-199`), о Superset и `lake_ro`, о стратегии тестов (`FAIL_ON_SKIP`, мутации,
`test_reconcile_postgres.py`), о безопасности, о масштабе x100 и цене, о процессе.
Чем плохо: интервьюер аналитики или тимлид задаст эти вопросы первыми.
Правка: раздел «Analytics and BI» (2 вопроса: определение метрики и зерно; как BI читает только
витрины), «Testing and CI» (2: как доказать, что тест ловит отказ; что не покрыто), «Production»
(2: что поменять для прода, со ссылкой на DC-15; что при x100 данных), раздел «Lessons» (DC-03).
Q25 `:414` «A week-6 rule» -> «A later rule»; Q28 `:471` «Since the audit commit» -> «Since commit».
Вопросы о работе с агентами в interview-notes не писать (правило W6-D15), а добавить 3 коротких
Q&A в `docs/evidence.md#how-it-was-built` (решение О-3). Счёт вопросов в README обновить.
Проверка: `grep -c '^\*\*[0-9]*\.' docs/interview-notes.md` -> 36; `check_docs.py . fileline` без
`PASTEND`/`MISSING`; `check_docs.py . links` без новых битых.
Размер: M; класс A; `docs-writer`, ревьюер сверяет числа.
Старый ID: нет.

### DC-18 [средняя] Нет цифр производительности
Где: `docs/evidence.md` (разделов о скорости нет; `grep -n -iE 'latency|per second|throughput'
docs/evidence.md` пуст).
Факт: цифры есть в Prometheus, проба только чтением 13.11:
`max_over_time(airflow_task_duration_seconds{quantile="0.9",task_id=~"merge|dbt_build"}[30d])` ->
merge 27.1 с, dbt_build 23.9 с; `quantile_over_time(0.5, spark_streaming_batch_duration_seconds[30d])`
-> bronze 4.18 с, orders_per_minute 0.55 с (это проба, а не замер для документа).
Правка: раздел «Performance on the laptop» в evidence: длительность батча bronze (p50, p90),
merge silver (p90), `dbt_build` (p90), `dq_checks` `reconcile_values`, задержка от записи в
Postgres до gold (лаг silver плюс dbt), объёмы (строки 7 таблиц, `bronze.cdc_events`, байты
`warehouse/`), дата и запрос у каждой цифры; одна строка в README Highlights.
Проверка: `grep -n '^## Performance' docs/evidence.md` -> 1; каждый запрос раздела повторяется
`curl -s 127.0.0.1:9090/api/v1/query --data-urlencode 'query=...'`.
Размер: S-M; класс A (GET к Prometheus, select в Trino).
Старый ID: нет.

### DC-19 [низкая] Требования не называют инструменты хоста
Где: `README.md:48-49`.
Факт: `make bootstrap` зовёт `envsubst` (`connect/register.sh:58`), `curl` (16 вызовов в
`register.sh`, `verify.sh`, `lib.sh`, `protect.sh`), `timeout`, `make`.
Правка: «Host tools: `make`, `curl`, `envsubst` (gettext-base), GNU coreutils `timeout`, `git`».
Проверка: `grep -n envsubst README.md` -> 1.
Размер: S; класс A.
Старый ID: нет.

### DC-20 [низкая] Тест ссылок, тире и имён не входит в `make check`
Где: `tests/unit/` (теста нет); проверки делались разовыми скриптами в scratchpad (спека 14, «Итог»
W6-T02, W6-T03).
Правка: `tests/unit/test_docs_hygiene.py`: относительные ссылки и якоря всех отслеживаемых `*.md`
(вне `docs/planning/`), U+2013/U+2014 во всех отслеживаемых, фамилия из `$HOME` вне
`LICENSE.md` (логика `DC-work/check_docs.py`, режимы `links`, `dashes`, `names`); тест на отказ:
временный файл с битой ссылкой краснеет.
Проверка: `uv run pytest tests/unit/test_docs_hygiene.py -q` зелёный после DC-01..DC-11.
Размер: S; класс A.
Старый ID: нет.

### DC-21 [низкая] Что видит посетитель на GitHub кроме README
Где: GitHub. Факт: `gh repo view --json ...`: About с полным стеком, 16 topics, MIT, `homepageUrl`
пуст, `hasWikiEnabled: true`, `hasProjectsEnabled: true`, релизов 0 (`gh api .../releases --jq
length` -> 0), ветка `w3-fernet-replay-data`, OpenGraph по умолчанию; у последнего коммита красный
CI; сообщения коммитов в списке файлов с ID карточек («(card d2.5), ci red from the ubuntu-26.04
runner jdk»).
Правка (класс C, владелец): удалить ветку `w3-fernet-replay-data`; выключить Wiki и Projects (`gh
repo edit --enable-wiki=false --enable-projects=false`); после зелёного финального CI тег и релиз
`v1.0` с 5 строками заметок; social preview из скриншота Superset (вручную в Settings). Сообщения
финальных коммитов пакетов: `<область>: <что>` без ID карточек и дат, потому что список файлов
корня показывает последнее сообщение у каждого каталога.
Проверка: `gh api repos/{owner}/{repo}/branches --jq '.[].name'` -> `main`; `gh repo view --json
hasWikiEnabled,hasProjectsEnabled` -> false, false; `gh release list` -> `v1.0`.
Размер: S; класс C; «ок» владельца на каждую запись в GitHub.
Старый ID: PF-64, R-68 (продолжение).

## Числа README и ARCHITECTURE против кода

| Утверждение | Где | Код | Итог |
|---|---|---|---|
| 16 rules, 13 alerts | `README.md:85,153`, `ARCHITECTURE.md:50,108` | `grep -c '^ *- alert:' observability/prometheus/alerts.yml` -> 16, имён 13 | верно |
| DAG 5 | `README.md:147` | `ls airflow/dags/*.py` -> 5 | верно; `README.md:86` называет 4 (DC-02) |
| CI шесть job, семь Dockerfile в hadolint | `README.md:156,213-221` | `.github/workflows/ci.yml:18,74,97,107,123,148`; матрица 7 = `git ls-files | grep -ic dockerfile` 7 | верно; нет шага Java 17 (DC-13) |
| RAM профилей | `README.md:64-72` | `compose_facts.py`: core без реплеера 7680 MiB, query 3584, orchestrate 2100, obs 1132, stateful 1792, bi 1792 + 1024, tools 400 | верно; профиль `jobs` (spark-silver 2048M) не назван |
| Порты | `README.md:82-96` | compose `ports` у 17 сервисов | верно |
| `make replay-burst SECONDS=60` = 12 виртуальных часов | `README.md:32` | `scripts/replay-burst.sh:7` SPEED 720, 60 x 720 = 43200 с | верно |
| `make up` отказывает `core` | `README.md:58-59` | `Makefile:39-42` | верно |
| ADR-001..ADR-026 | `README.md:20` | `DECISIONS.md:8-33` | верно |
| 30 вопросов | `README.md:21,161` | `grep -c '^\*\*[0-9]*\.' docs/interview-notes.md` -> 30 | верно |
| dbt `PASS=79 WARN=4` | `README.md:146` | `dbt/target/run_results.json` 2026-11-12: pass 61 + success 18, warn 4; manifest: 17 models, 65 tests, 1 seed | верно, источник устарел (DC-05) |
| Superset 4 charts, «same four questions» | `README.md:87`, `ARCHITECTURE.md:116-117` | 13 файлов в `docker/superset/dashboards/charts` | неверно (DC-01) |
| «last community tags» | `README.md:51` | PF-04 | неверно (DC-06) |
| Airflow 3.3 | `ARCHITECTURE.md:92` | `airflow/Dockerfile:3` `apache/airflow:3.3.2` | верно |
| `iceberg_maintenance` daily 03:30, `dq_checks` 15 min, `silver_upsert` 5 min | `ARCHITECTURE.md:33,42-43` | `schedule=` в DAG: `30 3 * * *`, `*/15`, `*/5` | верно |
| one-shot без лимита только `minio-init` | `ARCHITECTURE.md:146-147` | `compose_facts.py`: `minio-init mem=None` | верно |
| Версии стека | нигде в README | Postgres 17, Kafka 4.3.1, Debezium connect 3.5, Spark 3.5.9, Iceberg 1.11.0, Lakekeeper 0.13.6, MinIO RELEASE.2025-09-07, Trino 483, dbt-core 1.10.23 / dbt-trino 1.10.4, Airflow 3.3.2, Prometheus 3.14.0, Grafana 13.2.2, Superset 6.1.0, Python 3.12, JDK 17 | добавить (DC-02) |
| Запуски Actions | README, evidence | 10 из 10 существуют с заявленным итогом (`gh run view`) | верно |

## Целевая структура README (до 10 KB, по порядку)

| # | Раздел | Бюджет | Что внутри |
|---|---|---|---|
| 0 | Заголовок, бейдж `ci` (после зелёного финального run; бейдж smoke не ставить: расписание после заморозки само отключится через 60 дней без активности) | 0.2 KB | |
| 1 | Pitch | 0.6 KB | что это (Olist, 2 года, ~96 тыс. заказов, 7 таблиц), путь Postgres -> Debezium -> Kafka -> Spark -> Iceberg -> Trino/dbt -> Superset/Grafana, гарантия: silver совпадает с Postgres по строкам, ключам, суммам и отпечатку значений после 10 сценариев отказа; ноутбук 16 GB |
| 2 | Hero-картинка | 0.2 KB | Superset v2 с датой (DC-01) |
| 3 | What is proven (Highlights) | 1.2 KB | 6-7 строк с числом и ссылкой: сверка 7 из 7 (`docs/evidence.md#reconciliation-source-against-silver`); 10 сценариев отказа без потерь; 16 правил, 7 алертов показаны живьём со временем срабатывания; обслуживание Iceberg до и после (595 -> 30 файлов); путь с чистого клона в smoke ~10 мин еженедельно; BI читает только витрины (`lake_ro`); производительность одной строкой (DC-18) |
| 4 | Architecture | 0.8 KB | SVG `docs/img/architecture.svg`, 3 строки потока, ссылка на ARCHITECTURE (вместо ASCII `README.md:100-107`) |
| 5 | Stack | 1.3 KB | одна таблица: компонент, версия, задача, отвергнутая альтернатива (слить «Why each piece» `README.md:119-132` с версиями из таблицы выше) |
| 6 | Quick start | 1.5 KB | требования с инструментами хоста (DC-19), 5 команд, время bootstrap, 4 адреса (Superset, Grafana, Airflow, Trino); полная таблица портов и профилей только в OPERATIONS |
| 7 | Business layer | 0.7 KB | на какие вопросы отвечает gold и дашборд, модели, где словарь метрик (`dbt/models/docs.md`, `make dbt-docs`) |
| 8 | Quality, tests and CI | 0.9 KB | слить «Data quality» и «Testing and CI»: verify, dq_checks, dbt-тесты, 6 job CI, smoke до silver (DC-14) |
| 9 | Limits and security | 0.9 KB | Security model (DC-07), 4-5 строк «not done» с причиной, ссылка на «Production gap» (DC-15) и «Not proven yet» |
| 10 | Documentation | 0.6 KB | таблица карты навигации (ниже) |
| 11 | How it was built | 0.3 KB | одна строка по W6-D15 (формулировка: решение О-2) и ссылка |
| 12 | Data, License | 0.5 KB | как сейчас (`README.md:227-238`) |

Уезжает: таблица статуса компонентов (`README.md:140-163`) -> `docs/evidence.md`, раздел «Status»
вверху; таблица сценариев (`README.md:165-183`) -> уже есть в `docs/evidence.md:69-81`, в README
одна строка; «Explore the stack» (`README.md:74-96`) -> OPERATIONS «Ports»; таблица профилей
(`README.md:58-72`) -> OPERATIONS «Profiles»; абзац о сборке MinIO (`README.md:51-56`) -> OPERATIONS
«Daily commands» или «CI»; «Repository» (`README.md:185-199`) -> 8 строк в «Documentation» или
убрать; «What I learned» -> удалить (DC-03).

## Целевая карта навигации

| Читатель | Время | Порядок |
|---|---|---|
| Рекрутер | 3 мин | README разделы 1-5 |
| Интервьюер DE | 30 мин | README -> ARCHITECTURE (схема, поток, «Where exactly-once comes from», «Production gap») -> `docs/evidence.md` (Status, сверка, сценарии, Performance) -> DECISIONS (индекс ADR) -> `docs/interview-notes.md` -> код: `streaming/spark_jobs/silver_upsert.py` (`merge_sql`), `airflow/dags/dq_checks.py`, `dbt/models/marts/` |
| Аналитик, заказчик | 10 мин | README раздел 7 -> `dbt/README.md` -> `dbt/models/docs.md` (словарь метрик) -> дашборд |
| Новый инженер | 1 ч | README Quick start -> OPERATIONS (оглавление, Profiles, Ports, Daily commands) -> README компонентов (`oltp/`, `connect/`, `streaming/`, `airflow/`, `dbt/`, `observability/`, `scripts/`, `tests/`) -> `docs/runbooks/` |
| Дежурный | 5 мин | OPERATIONS «Alerts» -> `docs/runbooks/<алерт>.md` |
| Интересуется процессом | 15 мин | `docs/evidence.md#how-it-was-built` (англ.) -> `AGENTS.md` -> `docs/planning/README.md` (английская шапка) -> `docs/planning/13-harness.md` -> `docs/planning/21-final-audit-2026-11-13/` |

## Целевой вид корня и `docs/`

Корень после правок (из 31 записи уходит одна):

```
.claude/ .github/ airflow/ connect/ contracts/ data/ dbt/ docker/ docs/ observability/ oltp/ scripts/ streaming/ tests/
.env.example .gitignore .pre-commit-config.yaml .python-version .sqlfluff .yamllint
AGENTS.md ARCHITECTURE.md CLAUDE.md DECISIONS.md LICENSE.md Makefile OPERATIONS.md README.md pyproject.toml uv.lock
```

`LEARNING.md` удалён (DC-03). `AGENTS.md`, `CLAUDE.md`, `.claude/` остаются в корне: этого требуют
инструменты, и это витрина процесса.

```
docs/
  evidence.md            en: Status, сверка, сценарии, обслуживание, алерты, CI, Performance, Not proven, How it was built
  interview-notes.md     en: 36 вопросов и Lessons
  failure-scenarios.md   en: только если OB выносит разборы из OPERATIONS (R-63)
  runbooks/              en: 5 ранбуков; catalog-cutover.md в docs/planning/archive/, если R-40 принят
  img/                   architecture.svg, superset-marketplace.png, marketplace-dashboard.png
  agent-rules.md HANDOFF.md NEXT_SESSION.md   ru: рабочие файлы агентов, пути читают хуки
  planning/              ru: история; README.md с английской шапкой; без *.patch; 15-audit-p5-review/ урезан или удалён
    archive/             история HANDOFF (и разделы, которые увозит R-65)
```

Английская шапка для `docs/planning/README.md` (вставить строками 2-6):

```
> **About this folder.** The working history of the project, kept in Russian as it was written:
> weekly specs and plans (`04`-`10`), the rules of the AI-agent process (`13-harness.md`), the
> closing spec (`14`) and the audits and reviews (`15`-`21`). It is not needed to run or understand
> the platform: see `ARCHITECTURE.md`, `DECISIONS.md` and `docs/evidence.md` (English); the process
> in English: `docs/evidence.md#how-it-was-built`.
```

Судьба спорных путей:

| Путь | Решение | Причина |
|---|---|---|
| `LEARNING.md` | удалить, Lessons в interview-notes (О-1) | пуст 7 недель, гейты отложены владельцем |
| `docs/planning/*.patch` (5) | удалить (`git rm`, О-4) | применены, в истории git, код не ссылается |
| `docs/planning/15-audit-p5-review/` | удалить txt; json по решению HG | 1.35 MB, фамилия в двух файлах |
| `.superpowers/` | в репозитории ничего не делать | не отслеживается (`.superpowers/sdd/.gitignore` = `*`, `git status --ignored` -> `!! .superpowers/`), на GitHub не виден; 4.8 MB локально, удалить может владелец |
| `docs/planning/archive/` | оставить | цель переноса для R-65; на него ссылается README:146 (ссылку убрать, DC-05) |
| Закрытые спеки 04-12 | оставить на месте | перенос ломает 6 ссылок (`git grep -nE 'planning/(0[4-9]|1[0-2])' -- . ':!docs/planning'`: AGENTS.md, DECISIONS x2, OPERATIONS, dbt/README, replay-burst.sh), нумерация уже даёт хронологию |
| Шапка `docs/planning/README.md` на английском | да | посетитель GitHub попадает сюда из дерева |

## Находки «не делать»

| ID | что | почему не делать |
|---|---|---|
| DC-N1 | перенести закрытые спеки и планы 04-12 в `archive/` | ломает 6 ссылок вне планов, выгоды для читателя нет |
| DC-N2 | перевести `docs/planning` на английский | правило проекта: рабочая история на русском; шапки достаточно |
| DC-N3 | исправить ссылку `docs/planning/08-w3-plan/T00-clean-clone.md:361` | черновик текста README внутри закрытого плана, история |
| DC-N4 | переписать сообщения прошлых коммитов | история git, решение владельца (переписывать нельзя) |
| DC-N5 | перенести HANDOFF, NEXT_SESSION, agent-rules в `docs/agents/` | пути читают хуки и `session_context.py`, правка харнесса ради вкуса |
| DC-N6 | убрать `.claude/`, AGENTS.md, CLAUDE.md из публичного репозитория | витрина процесса, владелец хочет показать и процесс |
| DC-N7 | убрать «MCP endpoint for agents» и «Example for Claude Code» (`OPERATIONS.md:471,545`) | описание функции продукта, не авторства |
| DC-N8 | бейдж smoke, публикация dbt docs на GitHub Pages | smoke после заморозки отключится и может покраснеть; Pages это новый хостинг |
| DC-N9 | ADR для каждого решения недели `Dn` | дорого; суть уже в тексте, метки убираются (DC-04) |

## Решения владельца (с рекомендуемым ответом)

- О-1. `LEARNING.md`: удалить и заменить разделом «Lessons» в interview-notes из проверенных
  фактов (рекомендуется) или заполнить самому. Рекомендация: удалить.
- О-2. Строка «How it was built» в README сейчас третьим абзацем (`README.md:13-15`). Рекомендация:
  перенести в конец (раздел 11 целевой структуры) с формулировкой, где первым идёт вклад автора:
  «The author set the architecture and the ADRs, approved every risky action and accepted each
  result against recorded evidence; AI coding agents wrote the code and the documentation under that
  process: How it was built». Правило W6-D15 (одна строка) соблюдается.
- О-3. Вопросы о работе с агентами: 3 коротких Q&A в `docs/evidence.md#how-it-was-built`
  (разрешённое место), не в interview-notes. Рекомендация: да.
- О-4. `git rm` пяти патчей и txt корпуса (DC-09). Рекомендация: да.
- О-5. GitHub: удалить ветку, выключить Wiki и Projects, релиз `v1.0` после зелёного CI,
  social preview. Рекомендация: да всем, social preview по желанию.
- О-6. Скриншот Superset v2 для README (`docs/img/superset-marketplace.png`). Рекомендация: дать
  до пакета документов.
- О-7 (с HR). Строка-указатель на английском в начале `AGENTS.md` («Agent rules, in Russian; the
  process in English: docs/evidence.md#how-it-was-built»). Рекомендация: по желанию.

## Разрыв с продом (документы)

- Нет одного документа «что нужно до прода» (DC-15).
- Нет опубликованного каталога данных и lineage для потребителя (dbt docs только локально).
- Нет SLO-документа с обоснованием порогов (область OB).
- Нет версий и журнала изменений (CHANGELOG, релизы).
- Нет цифр производительности и объёмов в одном месте (DC-18).
- Проверки документов (ссылки, стиль, имена) не в CI (DC-20).
- Модель угроз сведена к фразе «loopback only» (DC-07).

## Не проверено

- Разрешение ссылок `../../actions/runs/<id>` на странице репозитория в браузере: API отдаёт
  относительный `href` (`gh api repos/{owner}/{repo}/readme -H "Accept: application/vnd.github.html"`),
  на github.com их переписывает фронтенд; проверить кликом по README:40.
- Показывает ли GitHub пустую вкладку Wiki посетителю: открыть репозиторий без входа.
- Имена работодателей: список имён не задан, поиск не проводился.
- Вывод `make dbt-build` после 2026-11-12 (dbt не запускался, только `dbt/target/run_results.json`).
- Цифры производительности (DC-18) сняты пробой, не замером: повторить запросами из DC-18.
- Публичные документы OPERATIONS и DECISIONS по существу (области OB и AR); здесь только их место
  в навигации и счёт ID карточек (по 36 строк).

## Приложение А. R-66: полный список file:line (рабочее дерево 13.11)

Команда в DC-04. В `.github/workflows/ci.yml` и `tests/unit/test_workflows.py` есть
незакоммиченные правки владельца: номера строк по рабочему дереву.

```
.github/workflows/ci.yml: 96,173
.github/workflows/smoke.yml: 6
Makefile: 131,133
airflow/dags/dbt_build.py: 1
airflow/dags/dq_checks.py: 5,6,10,17,214
airflow/dags/iceberg_maintenance.py: 1,12
airflow/dags/iceberg_orphans.py: 1
airflow/dags/lakehouse/maintenance_commands.py: 25
airflow/dags/lakehouse/metrics.py: 1
airflow/dags/lakehouse/reconcile.py: 1,2
airflow/dags/lakehouse/settings.py: 25,43,86
airflow/dags/silver_upsert.py: 1
dbt/dbt_project.yml: 19
dbt/macros/trino__reset_csv_table.sql: 4
dbt/models/intermediate/int_daily_sales.sql: 51
dbt/models/marts/_core.yml: 4,11,95,112
dbt/models/marts/_marts.yml: 5,7,16
dbt/models/marts/dim_customers.sql: 1
dbt/models/marts/dim_products.sql: 1
dbt/models/marts/fct_order_items.sql: 2
dbt/models/marts/fct_orders.sql: 28
dbt/models/marts/mart_daily_sales.sql: 26
dbt/models/marts/mart_delivery_sla.sql: 2
dbt/models/staging/_staging.yml: 5,9,40,76,108,149
dbt/seeds/_seeds.yml: 5
dbt/tests/_tests.yml: 4,9,13,17,21,25,27
dbt/tests/assert_categories_have_translation.sql: 2
dbt/tests/assert_delivered_not_before_carrier.sql: 1
dbt/tests/assert_gold_has_no_deleted_entities.sql: 1,2
dbt/tests/assert_mart_daily_sales_matches_full_recompute.sql: 3
dbt/tests/assert_payments_match_order_value.sql: 2
dbt/tests/assert_products_have_category.sql: 1
dbt/tests/generic/relationships_live.sql: 3
docker/airflow/airflow.env: 4,11,20
docker/compose.yaml: 108,348,407,507,684,712,715,736,762,779
docker/connect/Dockerfile: 4
docker/connect/metrics.yaml: 1
docker/superset/dashboards/datasets/Lakehouse_Trino_lake_ro/fct_order_items.yaml: 30
docker/superset/dashboards/datasets/Lakehouse_Trino_lake_ro/fct_orders.yaml: 30
docker/superset/superset_config.py: 34
docker/trino/etc/access-control.properties: 1
docker/trino/etc/catalog/lake_ro.properties: 1
observability/grafana/dashboards/pipeline-health.json: 676
observability/grafana/provisioning/datasources/trino.yml: 5
observability/postgres-exporter/queries.yaml: 2
observability/prometheus/alerts.yml: 1,2,3,4,18,62,97,111,116,124,125
observability/statsd/mapping.yml: 3,24
oltp/migrations/evolution/003_orders_sales_channel.sql: 1
oltp/replayer/settings.py: 32
scripts/chaos/connect-pause.sh: 5,33,38
scripts/chaos/late.sh: 80
scripts/chaos/lib.sh: 48,136,334,346
scripts/chaos/silver-kill.sh: 24
scripts/demo/watermark.sh: 2,17
scripts/obs/check_dashboards.py: 1
scripts/replay-burst.sh: 4
scripts/report.sh: 19
streaming/spark_jobs/catalog.py: 10
streaming/spark_jobs/maintenance.py: 1
streaming/spark_jobs/metrics.py: 2
streaming/spark_jobs/offsets.py: 1
streaming/spark_jobs/orders_per_minute.py: 1
streaming/spark_jobs/progress.py: 1
streaming/spark_jobs/settings.py: 45
streaming/spark_jobs/silver_upsert.py: 126
tests/unit/test_agent_hooks.py: 227,484,606,983,1045,1094,1288,1321,1743
tests/unit/test_agent_state.py: 151,173,485
tests/unit/test_compose.py: 1
tests/unit/test_container_exporter.py: 89
tests/unit/test_dags.py: 764,843,999,1199
tests/unit/test_dbt_soft_delete.py: 1,9,127
tests/unit/test_maintenance.py: 1,454
tests/unit/test_marketplace_dashboard.py: 1,3
tests/unit/test_minio_image.py: 37
tests/unit/test_pinning.py: 1
tests/unit/test_reconcile_postgres.py: 1
tests/unit/test_report.py: 1,144
tests/unit/test_silver_upsert.py: 559
tests/unit/test_spark_settings.py: 97
tests/unit/test_superset_bundle.py: 174
tests/unit/test_workflows.py: 26,46,70
```

Разделение: всё выше это код и конфиги (чистить, DC-04). Документы планирования (`docs/planning/`,
`docs/HANDOFF.md`, `docs/NEXT_SESSION.md`, `docs/agent-rules.md`, `AGENTS.md`, `CLAUDE.md`,
`.claude/`) не трогать: там ID карточек это язык работы. Публичные Markdown (README, ARCHITECTURE,
evidence, interview-notes, README компонентов, runbooks) по DC-05; OPERATIONS и DECISIONS по OB и AR.
