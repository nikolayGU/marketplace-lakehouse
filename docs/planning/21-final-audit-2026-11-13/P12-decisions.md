# P12. DECISIONS: ADR-027..ADR-030, сжатие до 40 KB, устаревшие ADR

Статус: не начат. Сессия на Opus: `/task docs/planning/21-final-audit-2026-11-13/P12-decisions.md`.

## Цель

`DECISIONS.md` не больше 40 960 байт (цель 39 900, запас не меньше 1 KB), ни один раздел ADR не
больше 2 560 байт; замеры и журналы проверок дословно в новом разделе `docs/evidence.md`, в ADR
ссылка; ADR-027 (Superset с MCP), ADR-028 (`lake_ro`, ACL Trino), ADR-029 (модель безопасности),
ADR-030 (gold) записаны после «ок» владельца на текст; ADR-014, ADR-017 помечены заменёнными;
у ADR-003, 006, 012 есть короткие разделы; «last community release» и «no console» исправлены.

## Находки пакета

| ID | Серьёзность | Суть | Где подробности |
|---|---|---|---|
| AR-01 (часть) | высокая | «last community release», «no console», «`mc` as the console» ложны; CVE тега не названа | `reports/AR.md` AR-01 |
| AR-02 | средняя | нет ADR на Superset с MCP и на `lake_ro` с ACL; ADR-014 устарел | `reports/AR.md` AR-02, черновики в «Решения без ADR» |
| AR-02 (доп.) | средняя | нет ADR на модель безопасности и на gold (черновики ADR-029, ADR-030) | `reports/AR.md`, «Решения без ADR» |
| AR-04 | средняя | DECISIONS 62 890 байт, ADR-005 15 110 | `reports/AR.md` AR-04, «Целевой вид DECISIONS» |
| AR-05 | средняя | 8 ADR только строкой, ADR-012 «until week 6», ADR-001 «must be checked», ADR-016 без `stateful`, `jobs` | `reports/AR.md` AR-05 |
| AR-08 | низкая | DECISIONS:4 шлёт в русский устаревший `00-mini-architecture-review.md` | `reports/AR.md` AR-08 |

## Решения владельца и действия класса C

- В-n нет. Тексты ADR-027..ADR-030 идут владельцу на «ок» одним сообщением (README, раздел 4;
  поправки шага 1). Без «ок» не вставляются, ADR-014 не помечается, куски под ADR-029 остаются.
- Действий класса C нет: стек не трогается, тег MinIO не меняется (AR-N1, README раздел 6).

## Зависимости

- После P10 (README, раздел 4). P06 по В-03 добавляет в ADR-005 строку об удалении слоя JDBC и
  исполняет AR-10; P11 перестраивает OPERATIONS: всё во «Входе» искать по цитате.
- P13 идёт после: README, комментарии compose и `docker/minio/Dockerfile:1` (вторая половина
  AR-01), ARCHITECTURE (AR-03: раздел о гарантиях доставки ссылается на ADR-030; ссылки на
  ADR-027..030) и `README.md:20` «ADR-001 to ADR-026».

## Вход

1. `wc -c DECISIONS.md` -> 62 890 на `a8c1d49` (после P06 больше). Размеры разделов в байтах
   (команда `SIZES` в «Готово, когда»): больше 2 560 у 005 (15 110), 007 (3 420), 011 (2 695),
   019 (2 675), 021 (2 709), 023 (4 537), 024 (3 440), 025 (5 352), 026 (5 333); шапка 4 011.
2. Цитаты: `:4` «Longer reasoning lives in `docs/planning/00-mini-architecture-review.md` (ru)»;
   `:11` «last community release pulled from quay.io»; `:19` «No Schema Registry until week 6»;
   `:21` «Superset optional; marts are shown through Grafana»; `:24` ADR-017 повторяет ADR-024;
   `:41-42` «license must be checked before shipping a sample»; `:51` «removed the web console»;
   `:58` «since there is no console»; `:425-426` профили без `stateful` и `jobs`; `:768`
   «`mc` as the console»; `:825-826` «The CVEs of the 2025-09 tag stay, as ADR-004 said».
3. Куски под ADR-029: ADR-005 (c) `:129-137` («(c) Encryption key»), `:245-247` («No
   authentication. Lakekeeper still runs `allow-all`»); ADR-011 `:378-381` («The socket is root
   on the host in effect»), `:382-384` («No login (D12)»); ADR-023 `:611-612` («root on the
   host in effect, like the Airflow scheduler»).
4. `git ls-remote --tags https://github.com/minio/minio 'RELEASE.2025-*' | tail -2` ->
   `RELEASE.2025-10-15T17-29-55Z`, новее закреплённого 2025-09-07 (`docker/minio/Dockerfile:13`);
   `gh api "/repos/minio/minio/security-advisories?per_page=50"`: CVE-2025-62506, high, patched
   в нём. `mc` 2025-08-13 последний. Консоль: `docker/compose.yaml:164,172` (порт 9001).
5. Входящие ссылки (`git grep -n "DECISIONS.md"`): `docs/interview-notes.md` (29 ссылок на
   якоря, из них 2 на `#cutover-2026-10-08`, строки 234, 508), `README.md:20,132,148,163`,
   `ARCHITECTURE.md:136`, `docs/evidence.md:91,307`, `contracts/README.md:3`, правила агентов.
   Тесты и скрипты DECISIONS не читают. От переезда зависят: якорь `#cutover-2026-10-08`
   (заголовок `### Cutover, 2026-10-08` в ADR-005) и `evidence.md:307` «ADR-001 to ADR-026».
6. Отсылки DECISIONS к разделам OPERATIONS («"Lakekeeper"», «scenario 5», «"Profiles"»,
   «"Maintenance"») после P11 проверить; проверка ссылок: `work/DC/check_docs.py.txt` в
   scratchpad как `check_docs.py`, из корня `python3 -I <scratchpad>/check_docs.py . links`;
   13.11 -> `broken: 1` (`docs/planning/08-w3-plan/T00-clean-clone.md:361`, история).

## Границы

- Менять можно: `DECISIONS.md` (оркестратор); `docs/evidence.md`, новый раздел и строка `:307`
  (`docs-writer` по брифу); `docs/planning/00-mini-architecture-review.md`, одна строка статуса.
- Нельзя: код, README, ARCHITECTURE, interview-notes, OPERATIONS, compose (P06, P11, P13); смысл
  решений (только сжатие и перенос); заголовки `## ADR-NNN` (на них якоря); тег MinIO.
- Живой стек: только `select` (проверка ADR-030).

## Шаги

1. ADR-027..ADR-030 (оркестратор). Черновики `reports/AR.md` с поправками, сверено 13.11:
   - ADR-027: (а) добавить решения спеки 20, отнесённые сюда (`20-superset-dashboard.md`,
     раздел 1, «Не входит»): якорь `SUPERSET_DATA_ANCHOR` (С-Д7; двигается руками после
     реплея) и тема в `superset_config.py`, потому что импорт темы `overwrite=False` (С-Д8);
     (б) импорт удаляет колонки и метрики датасетов бандла, которых нет в YAML, объекты вне
     бандла остаются (комментарий над `superset-mcp` в compose); (в) порт «bound to `BIND_IP`»;
     (г) «Metabase or Evidence (another stack, no MCP)»: «no MCP» не проверено, убрать или дать
     источник; (д) плитки `pop_kpi` требуют `CHART_PLUGINS_EXPERIMENTAL`
     (`superset_config.py:16`). Верно: 6.1.0 по digest и драйверы (`docker/superset/Dockerfile:7,
     12`), метаданные в `postgres-meta`, пользователь `superset`, `allow_dml: false`,
     `MCP_DEV_USERNAME = "admin"` (`:37`), проверка Host и Origin, вход в UI, 1280M и 512M.
   - ADR-028: сверено (`rules.json`; `lake_ro.properties` отличается от `lake.properties` одной
     строкой `iceberg.security=read_only`; нет `security.refresh-period`); дописать «no
     functions» и что запросы только `execute`.
   - ADR-029: верно: все порты через `${BIND_IP:?...}` (заголовок compose `:1-2`), `.env` в
     `.gitignore:1`, `make secrets` заменяет каждое `change_me` случайным секретом
     (`scripts/make_env.py:1,22`), один ключ MinIO root у Spark, Trino, Lakekeeper
     (`compose.yaml:166` `MINIO_ROOT_USER: ${S3_ACCESS_KEY}`), сокет у scheduler (`:616`) и
     container-exporter (`:793`). Поправки: (а) в список без входа добавить Prometheus и
     `kafka-ui` (профиль `tools`); консоль MinIO входит по root-ключам S3; (б) одна учётка
     суперпользователя `postgres-meta` (`META_USER`) у Lakekeeper, Airflow, Superset
     (`compose.yaml:219`, `docker/airflow/airflow.env:17`, `SUPERSET_DATABASE_URI`), а до P06
     ещё у слоя JDBC: писать по состоянию после P06; (в) `:ro` на сокете не ограничивает API
     (exporter только читает по коду); (г) ключ `LAKEKEEPER_ENCRYPTION_KEY` из ADR-005 (c) одной
     фразой. Затем куски из «Входа», п. 3 уходят из ADR-005, 011, 023 (в 005 и 011 по ссылке
     «see ADR-029»), полный текст (c) дословно в evidence с остальным ADR-005.
   - ADR-030: верно: `on_table_exists: replace` и причина (`dbt/dbt_project.yml:18-20`), views
     и tables (`:21-26`), `delete+insert` по `purchase_date` с водяным знаком
     `max(source_updated_at)` (`mart_daily_sales.sql:4-9,23-34`), Asset и пул `gold_writers`
     (`airflow/dags/dbt_build.py:15,27`), gold без защиты и 7 дней снапшотов (ADR-025).
     «delete+insert is two commits» подтверждено: `lake.gold."mart_daily_sales$snapshots"` даёт
     пары `delete` и `append` с разницей около 0,3 с (2026-11-06 16:20:50.521 и .759). Поправка:
     добавить известный предел D18 (продавец сменил штат: старые даты витрины устаревают,
     `_marts.yml` у `mart_daily_sales`) и `on_schema_change='fail'`.
   Сообщение владельцу: четыре текста целиком; после «ок» вставить; в индексе ADR-014
   «superseded by ADR-027», строки ADR-027..ADR-030.
2. AR-01, строки DECISIONS (оркестратор): индекс ADR-004 «MinIO, a pinned community release
   (2025-09-07), first pulled from quay.io»; ADR-004 Context без «removed the web console»,
   Decision «administer it with `mc`; the web console on :9001 only browses the bucket»
   (OPERATIONS, «MinIO console»); `:63-64` «will not receive upstream fixes» заменить ссылкой на
   ADR-026; ADR-026 `:768` «`mc` as the admin tool»; в ADR-026 одна строка: «A later tag,
   RELEASE.2025-10-15T17-29-55Z, fixes CVE-2025-62506 (service account and STS session
   policies, not used here); staying on 2025-09-07 is an accepted risk.»
3. AR-05 (оркестратор): индекс ADR-017 «superseded by ADR-024»; ADR-012 без «until week 6»;
   ADR-002 «postgres-meta holds the metadata of Lakekeeper, Airflow and Superset»; ADR-015 «no
   data quality framework: dbt tests plus `dq_checks`»; ADR-001 без «must be checked»; ADR-016
   профили `core, query, orchestrate, obs, bi, tools, stateful, jobs` (8). Разделы ADR-003,
   ADR-006, ADR-012 по строкам `reports/AR.md`, «Строки в существующие ADR»; в ADR-006 статус
   поддержки Spark 3.5 только с источником (в отчёте не проверен). Туда же строки ADR-011 (Asset
   и пауза DAG, `ARCHITECTURE.md`, п. 6) и ADR-020 (альтернативы decimal на проводе).
4. AR-04, сжатие. Замеры, проверки и подробные разборы переезжают в `docs/evidence.md`, раздел
   `## Decision measurements`, подраздел на ADR (`### ADR-005 Catalog, side by side and
   cutover` и т. д.), дословно, кроме ID карточек и решений (`W2-T09`, `D9`, `W6-D16`) и слов
   агентного процесса («owner's Modify gate», «ladder», «its own "ok"», «verdict», «then in
   `CLAUDE.md`, now in `AGENTS.md`»); даты остаются. В ADR строка-ссылка на подраздел. Без
   переноса удаляются только утверждения, переставшие быть верными («удалить» ниже), с записью
   в «Итог». `docs-writer` вставляет текст по брифу с диапазонами; DECISIONS правит оркестратор.
   Диапазоны на `a8c1d49` (сверены, искать по цитате):

   | ADR | Байт сейчас -> цель | Вынести в evidence | В ADR |
   |---|---|---|---|
   | шапка | 4 011 -> 3 000 | нет | индекс (30 строк) одной фразой на ADR; `:4` по шагу 5 |
   | 001 | 865 -> 800 | нет | без «must be checked» |
   | 004 | 1 263 -> 600 | `:51-55` проверка quay 21.09 | 2 строки и ссылка на ADR-026 |
   | 005 | 15 110 -> 2 300 | `:81-93`; `:95-160` ((a)-(f) полностью); `:162-185`; `:204-223`; `:225-256` | Context, Decision, по фразе на (a), (b), (d), (e), (f); (c) и `:245-247` в ADR-029; `### Cutover, 2026-10-08` с 2 строками; откат 1-2 строки и строка P06; удалить `:187-192` (до cutover) |
   | 007 | 3 420 -> 1 800 | `:285-308` | 2 строки и ссылка |
   | 008 | 1 025 | нет | как есть |
   | 010 | 2 356 -> 1 500 | `:339-354` таблица и optimize | `:355-359` |
   | 011 | 2 695 -> 1 900 | `:371-372` пик 579 MiB | `:378-384` в ADR-029; удалить `:391-394` (неделя 3, заменено ADR-025) и «owner's Modify gate» `:389-390` |
   | 013 | 1 808 -> 1 200 | `:410-421` | 3 строки |
   | 016 | 1 341 -> 1 100 | нет | без «weeks 3-6», `D1`, `D2` |
   | 018, 020, 022 | 4 950 -> 3 900 | `:527-530` (020) | сжать формулировки |
   | 019 | 2 675 -> 2 000 | `:480-488` | 2 строки |
   | 021 | 2 709 -> 2 450 | нет | убрать `:547-548` (повтор ADR-009) и «(W5-T05)» |
   | 023 | 4 537 -> 2 100 | `:615-627`, `:629-631`, `:633-643` | `:611-612` в ADR-029; по строке на Connect, StatsD, WAL |
   | 024 | 3 440 -> 2 200 | `:676-692` | 2 строки и ссылка |
   | 025 | 5 352 -> 2 500 | `:733-736` (проба метаданных), `:737-741`, `:749-761` | одна фраза: DAG созданы на паузе, orphans через `dry_run: false`, шаги Spark через `expire_and_compact: true`; убрать «a rung of the ladder with its own "ok"» `:733` |
   | 026 | 5 333 -> 2 500 | `:770-781`, `:785-814` | 3 строки решения; откат `:820-826` ссылкой на OPERATIONS «MinIO and mc images (ADR-026)»; `:765-767` до «Status: accepted (2026-10-27)» |
   | новые | 0 -> 6 400 | | 027 1 500, 028 1 100, 029 1 300, 030 1 200, 003 400, 006 500, 012 400 |

   Сумма целей 39 275 байт, запас 1 685 до 40 960. Если ADR-029 или ADR-030 без «ок», их
   строки и разделы не пишутся, куски под ADR-029 остаются: сумма около 36 900.
5. AR-08 (оркестратор): `:4` «Measurements behind the decisions:
   [docs/evidence.md](docs/evidence.md#decision-measurements)»; после заголовка
   `docs/planning/00-mini-architecture-review.md` строка «Статус: история (19.09.2026);
   действующее: `ARCHITECTURE.md`, `DECISIONS.md`». `docs/evidence.md:307` «ADR-001 to
   ADR-030»; ссылка на новый раздел в строке навигации `evidence.md:10`.
6. Проверки, ревью `reviewer` (предмет документ: сжатие не меняет решений, ADR-029 и ADR-030
   против кода; список удалённых строк), коммит Markdown по гейту `13-harness.md`, раздел 5:
   `docs: decisions compressed under 40 kb, bi access, security model and gold recorded`.

## Готово, когда

Команда `SIZES` (байты каждого раздела `## `):

```bash
LC_ALL=C awk '/^## /{if(n)print n,b;n=$2;b=0} n{b+=length($0)+1} END{print n,b}' DECISIONS.md
```

- [ ] `wc -c DECISIONS.md` -> не больше 39 900 (предел 40 960); `SIZES` через `awk '$2>2560'`
      -> пусто.
- [ ] `grep -c '^## ADR-' DECISIONS.md` -> 25 (18 + 003, 006, 012 + 027..030); 23, если владелец
      не дал «ок» на ADR-029 и ADR-030 (отказ записан в «Итог»).
- [ ] `grep -n 'ADR-014\|ADR-017' DECISIONS.md` -> строки индекса с «superseded by ADR-027» и
      «superseded by ADR-024».
- [ ] `grep -n -i 'last community\|no console\|removed the web console\|as the console'
      DECISIONS.md` -> пусто; `grep -c 'CVE-2025-62506' DECISIONS.md` -> 1.
- [ ] `grep -n -i 'ladder\|modify gate\|verdict\|CLAUDE.md\|until week 6\|must be checked'
      DECISIONS.md` и `grep -n '00-mini' DECISIONS.md` -> пусто;
      `grep -nE '\bW[0-9]-[TD][0-9]+|\bD[0-9]{1,2}\b' DECISIONS.md` -> пусто.
- [ ] `grep -n 'root on the host' DECISIONS.md` -> не больше одной строки, в ADR-029.
- [ ] `grep -n '^## Decision measurements' docs/evidence.md` -> строка;
      `grep -n '^### Cutover, 2026-10-08' DECISIONS.md` -> строка.
- [ ] Ничего не потеряно: числа старого файла есть в новых (пусто или каждое объяснено в «Итог»):

      ```bash
      python3 - <<'EOF'
      import re, subprocess
      num = lambda t: set(re.findall(r"\d+(?:[ .,:]\d+)*", t))
      git = ["git", "show", "HEAD:DECISIONS.md"]
      old = subprocess.run(git, capture_output=True, text=True).stdout
      files = ["DECISIONS.md", "docs/evidence.md", "OPERATIONS.md"]
      new = "".join(open(p).read() for p in files)
      print(sorted(num(old) - num(new)))
      EOF
      ```

- [ ] `python3 -I <scratchpad>/check_docs.py . links` -> `broken: 1` (та же строка истории).
- [ ] `sed -n 1,5p docs/planning/00-mini-architecture-review.md | grep -c 'история'` -> 1.
- [ ] Вердикт `reviewer` по документу; коммит по гейту `13-harness.md`, раздел 5.

## Не входит

- AR-10 исполняет P06 (текст отказа orphans bronze в `maintenance.py` и два теста);
  код и комментарии слоя JDBC (AR-07, R-40) тоже P06.
- README, компоненты README, комментарии compose и `docker/minio/Dockerfile:1` (AR-01, DC-06,
  IN-12), ARCHITECTURE (AR-03, AR-06, AR-09), interview-notes: P13. Для P13: после этого пакета
  замеры и проверки ADR-007 (в том числе «So bronze is exactly once across Spark restarts») и
  других ADR живут в `docs/evidence.md`, раздел «Decision measurements»; AR-03 правит
  формулировку там, а раздел ARCHITECTURE о гарантиях доставки ссылается на ADR-030.
- Смена тега MinIO, апгрейды стека (AR-N1..AR-N5); разделы ADR-002, 009, 015 (AR-N6).

## Риски и откат

- Сжатие меняет смысл решения: ревью сверяет каждое `Decision` до и после. Якоря
  interview-notes: заголовки `## ADR-NNN` и `### Cutover, 2026-10-08` не менять.
- ADR-029 описывает состояние после P06: если В-03 «нет», учётка `META_USER` остаётся и у
  Spark, Trino, Airflow через слой JDBC, текст это называет.
- Откат: `git revert` коммита; стек не затронут.

## Расхождения с отчётом аудита

- AR-10 против DP (R-60 «ложная находка»): оба правы про разные строки. `maintenance.py:9-10`
  (снапшоты, ADR-021) верна; `:84` (файлы данных) неточна, правило в ADR-025
  (`DECISIONS.md:722-724`), ADR-005 даёт только мотив. Отчёт AR не заметил тестов
  `test_maintenance.py:121`, `:384` на «ADR-021». Исполняет P06.
- AR-04: план отчёта не сходился (ADR-005 оставался около 9 KB, ADR-021 2 709 байт больше
  порога, хотя в таблице ADR отчёта «2.2 KB»); таблица шага 4 пересчитана под 40 960 байт.
- Черновики: в ADR-027 нет С-Д7, С-Д8; в ADR-029 нет Prometheus, `kafka-ui`, учётки
  `postgres-meta`; «two commits» ADR-030 отчёт не проверял (здесь подтверждено). AR-01:
  «stripped the console to an object browser» не проверено, в пакет не взято.

## Итог

По разделу 6 `13-harness.md`; для P13: якоря «Decision measurements» и где легли замеры ADR-007.
