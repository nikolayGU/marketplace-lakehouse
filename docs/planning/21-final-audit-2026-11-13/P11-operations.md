# P11. OPERATIONS: оглавление, вынос сценариев и замеров, правдивые строки

Статус: не начат. Opus, `/task docs/planning/21-final-audit-2026-11-13/P11-operations.md`.

## Цель

`OPERATIONS.md` из журнала в 134 KiB становится справочником дежурного: оглавление, процедуры и
пороги; сценарии в `docs/failure-scenarios.md`, замеры в `docs/evidence.md`, серии и проверка
дашбордов в `observability/README.md`, красные задачи в ранбуках, цепочка поставки в
`docs/supply-chain.md`. До 66 KiB с запасом для P13, без битых ссылок и ложных строк «Вход», п. 3.

## Находки пакета

| ID | Серьёзность | Суть | Где подробности |
|---|---|---|---|
| OB-04 | средняя | 137 688 байт, 1794 строки, оглавления нет | `reports/OB.md`, OB-04, «OPERATIONS: целевое оглавление и карта переноса» |
| OB-05 | средняя | ложное и устаревшее (10b «not proven», сценарий 10 «planned», память, «4 charts», «These seven») | `reports/OB.md`, OB-05 |
| OB-08 | низкая | SLI и пороги не сведены, SLO не названы | `reports/OB.md`, OB-08, «SLI и пороги» |
| PF-25, PF-27, PF-30, PF-54 | низкая | рестарт Docker; «unmapped» серии; checkpoint и каталог; анонимные тома | `reports/OB.md`, «Старый бэклог» |
| PF-53, GB-02 (часть) | высокая | кэш Superset 300 с не описан; замер `check.py` по v1; номера строк `superset_config.py` | `reports/GB.md`, GB-02 |
| OR-05 (часть) | низкая | строка `dq_checks` неполна; «1 slot» при двух пулах; PF-20 | `reports/OR.md`, OR-05 |
| IN-13, IN-15 (части) | низкая | ручной префикс `TRINO_XMX=2g`; «weekly, Monday» у smoke | `reports/IN.md` |

## Решения владельца и действия класса C

Решений В-n и действий C нет, класс A; `make verify` по разделу 5 `13-harness.md` на момент работы.

## Зависимости

- После P10 (и через него P05..P09): P09 создаёт ранбуки `dq-checks.md`, `airflow-dag-failed.md`,
  `containers.md` и таблицу «Runbooks»; P07 ставит `TRINO_XMX=2g` в `.env.example`; P06 снимает
  слой JDBC; P05 меняет `dq_checks`. Не параллельно с P12: оба пишут `docs/evidence.md`. P13
  добавит в OPERATIONS около 1.5 KiB. Строка владельца в таблице CI уходит коммитом P01 раньше.

## Вход

Сверить первым шагом по цитате (номера 13.11 сдвинутся). Не подтвердилось: шаг не делать, в «Итог».

1. `git status --short OPERATIONS.md` пусто; «до»: `wc -c OPERATIONS.md` (13.11: 137688),
   `grep -n '^#' OPERATIONS.md` (13.11: 17 разделов `##`, сценарии 1261-1755 от `## Failure
   scenarios` до `## Runbooks`; `### First live run, 2026-10-29` 1017; `### Orphans next to
   orders_per_minute, 2026-10-30` 1118). `git show HEAD:OPERATIONS.md > <scratchpad>/ops-before.md`.
2. Метки, которые нельзя менять (их печатают скрипты, проверяют тесты, на них ссылаются):

| Метка | Кто ссылается (13.11) |
|---|---|
| `## Airflow` | `scripts/verify.sh:41`, `Makefile:101`, `airflow/README.md:4,16`, `ARCHITECTURE.md:96` |
| абзац `Timeouts` | `scripts/chaos/silver-kill.sh:68,198`, `tests/unit/test_chaos_silver_kill.py:274`, interview-notes:477 |
| `### Access control` | `tests/unit/test_trino_access.py:10`, ARCHITECTURE:115, evidence:225,285, interview-notes:510 |
| `## Superset (profile \`bi\`)` | README:88, ARCHITECTURE:120, evidence:234,258 |
| `What deletes files`; `After the cutover` | `docker/trino/etc/catalog/lake.properties:2`, `catalog-cutover.md:206`; `catalog-cutover.md:5` (снять, только если P06 увёз ранбук) |
| `### Pinned images and actions` | `docker/compose.yaml:8` |
| `## Lakekeeper (REST catalog)` | `scripts/README.md:37`, `DECISIONS.md:261` |
| `## Observability`, `### Alerts`, `Limits worth knowing`, `### Dashboards` | `observability/README.md:3,12`, `alerts.yml:5-6`, `freshness.md:24`, evidence:128, interview-notes |
| `## Profiles and what runs together`, `## Ports (all on 127.0.0.1)`, `## Daily commands` | interview-notes:454,509, README:42,77, evidence:61 |
| `## Bronze ingest`, `## Silver upsert`, `## Stateful job`, `## Maintenance`, `## CI` | `spark-stalled.md:20`, `disk-full.md:23,30`, interview-notes, DECISIONS:749, evidence:181 |
| `## Failure scenarios` и номера сценариев | README:166, interview-notes:257; текст «OPERATIONS.md, scenario N» в 8 `scripts/chaos/*.sh`, `dbt/tests/assert_chaos_break_test.sql:1`, `DECISIONS.md:308`, `slot-wal-growth.md:8,35` |

   Сверка: `git grep -n OPERATIONS -- . ':!docs/planning' ':!docs/HANDOFF.md' ':!docs/NEXT*'`
   (13.11: 126 строк, как `work/OB/ops_refs.txt`). Текст OPERATIONS тесты не читают
   (`grep -rln OPERATIONS tests/` даёт два файла из таблицы). Если P09 добавил тест таблицы
   «Runbooks» (`grep -n Runbooks tests/unit/test_alerts.py`), её не урезать.
3. Ложные строки: «killing \`spark-silver\` mid-merge» (1793) при 10b от 2026-11-06; «planned
   (week 3)» (1279) и evidence:83; «Grafana 123 of 256, container-exporter 29 of 64» (943-944);
   «Measured with the v1 bundle (4 charts)» (533); «These seven are proven by promtool» (821);
   `superset_config.py:32` (548) и `:28-31` (557) при `MCP_DEV_USERNAME` на
   `docker/superset/superset_config.py:37`; «pool lake_writers, 1 slot» (598) при
   `Makefile:127-131`; «weekly, Monday 03:00 UTC, W6-D2» (1150); «every Kafka offset is in bronze
   exactly once» (91), а `bronze_offsets_ok` в `scripts/chaos/lib.sh` ищет дыры только между
   первым и последним offset партиции.
4. PF-27: `observability/README.md:14-16` «Names it does not map» против
   `observability/statsd/mapping.yml:26-28` (`lakehouse.dq.*`, `ttl: 45m`). PF-53:
   `superset_config.py:19-20` `CACHE_DEFAULT_TIMEOUT: 300`.
5. После P09: `ls docs/runbooks/` содержит три новых ранбука; перенесён ли текст:
   `grep -l 'Heartbeat recovered\|silver_keys_unique\|DOCKER_GID' docs/runbooks/*.md`,
   `grep -il 'docker restart' docs/runbooks/containers.md` (PF-25). После P07:
   `grep -n '^TRINO_XMX=' .env.example` -> `TRINO_XMX=2g`, иначе префиксы не трогать. После P06:
   `git grep -n CATALOG_TYPE -- docker streaming scripts`, `ls docs/runbooks/catalog-cutover.md`.
6. Скрипты ссылок скопировать в `<scratchpad>` без `.txt`: `work/OB/check_md_links.py.txt`,
   `work/DC/check_docs.py.txt`. В копии `check_docs.py` режим `dashes` сломан (при записи
   аудита символы заменены дефисами): в `mode_dashes` два литерала `"-"` заменить на
   `chr(0x2013)` и `chr(0x2014)`. Проверено 13.11: `python3 -I <scratchpad>/check_docs.py . links`
   -> `links checked: 259, github-relative: 15, broken: 1` (история: `T00-clean-clone.md:361` в
   `docs/planning/08-w3-plan/`); `python3 -I <scratchpad>/check_md_links.py OPERATIONS` ->
   `links checked: 77, broken: 0`.
   Без фильтра `check_md_links.py` считает битыми 16 ссылок `../../../actions/runs/`: это его
   предел, их проверяет `check_docs.py`.

## Границы

- Менять можно: `OPERATIONS.md`; новые `docs/failure-scenarios.md`, `docs/supply-chain.md`;
  `docs/evidence.md`; ссылки в `docs/interview-notes.md` и `README.md`; `observability/README.md`;
  `docs/runbooks/*.md` (перенесённый текст и ссылки).
- Нельзя: код и конфиги (`scripts/`, `dbt/`, `docker/`, `*.yml`, `*.json`, `*.py`), `DECISIONS.md`
  (P12), `.claude/`, правила агентов. Одно исключение, его передал P09: ссылка на якорь
  OPERATIONS в docstring `scripts/obs/check_dashboards.py`, если якорь переехал (одна строка;
  тогда коммит несёт код: `make check` и ревью с предметом `код`). «OPERATIONS.md, scenario N» в коде верно через
  таблицу-указатель (шаг 4), не править. Живой стек: не трогать.

## Шаги

Правила для всех брифов. Перенос дословный; каждое удалённое предложение идёт в список
«Удалено» отчёта брифа (первые слова и причина: журнал, дубль, устарело, есть в evidence или
ADR). Метки «Вход», п. 2 буква в букву. ID карточек, решений недели и аудитов (`W6-D17`, `B1`,
`audit 30.10`, `week 3`, `D12`) убрать по правилу DC-04 (`reports/DC.md`): номер ADR, если есть,
иначе метку удалить, суть оставить; ссылки на `docs/planning/` убрать. Отказ до правки, вывод в
«Итог»: «Готово, когда», п. 1, 2, 4 красные.

1. Бриф A, `docs-writer`, `docs/failure-scenarios.md` (новый): `# Failure scenarios`, строка о
   назначении, затем дословно от «Each scenario is a \`make chaos-<name>\` target» до конца 10b
   без таблицы статусов. Уровни `###` не менять: якоря те же, меняется файл. Внутри две ссылки
   вместо текста: «see Alerts above» -> `../OPERATIONS.md#alerts`, «(see "Airflow")» ->
   `../OPERATIONS.md#airflow`. Проверка: `diff` блока `ops-before.md` с файлом до чистки ID
   показывает только шапку и две ссылки; затем чистка ID.
2. Бриф B1, `docs-writer`, `docs/evidence.md`, `docs/interview-notes.md`, `README.md`. В evidence
   раздел «Maintenance, before and after» получает дословно `### First live run, 2026-10-29` и
   `### Orphans next to orders_per_minute, 2026-10-30` с заголовками; сводка evidence:95-111 и
   абзац 118-121 повторяют их числа: убрать; ссылки 52, 90 сделать внутренними; строку о
   сценарии 10 (evidence:83) убрать.
   Ссылки на перенесённые якоря перевести на новые файлы, список:
   `git grep -nE 'OPERATIONS\.md#([0-9]|first-live|orphans-next)' -- '*.md' ':!docs/planning'`
   (13.11: README 2, evidence 14, interview-notes 13). Ссылки ради колонок «Shown in» и «Time to
   fire» (interview-notes:380,409) перевести на `evidence.md#alerts-and-time-to-fire`.
3. Бриф B2, `docs-writer`, `observability/README.md`, `docs/runbooks/*.md`, `docs/supply-chain.md`.
   В `observability/README.md` разделы «Series» (748-778 дословно), «Dashboard check» (логика
   `idle:`, 886-896), «Notes» (787-807: mount, HUP без `docker kill`, том `/kafka/config`,
   provisioning, файлы до первого старта); PF-27: «`lakehouse.*` and `lakehouse.dq.*` are mapped
   with a 45-minute TTL (`statsd/mapping.yml`)». Ранбуки, если по «Вход», п. 5 текста там нет:
   662-701 (смысл `reconcile_values` и GMV, можно сжать вдвое, числа и запросы сохранить) и 703-717
   в `dq-checks.md`; 718-725 в `airflow-dag-failed.md`; 808-813 в `containers.md` с PF-25: «after a
   Docker restart `kafka-exporter` and `lakekeeper` can start before their dependencies and
   restart once: `ContainerRestarting` for up to 15 minutes». Ранбуков нет: стоп, вопрос владельцу.
   `docs/supply-chain.md`: дословно «Pinned images and actions» (1161-1188), «Not covered»
   (1220-1225), «MinIO and mc images» (1227-1256) без отката и замера сборки (они в ADR-026).
4. Бриф C, `docs-writer`, после A, B1, B2, `OPERATIONS.md`: оглавление списком ссылок под
   `# Operations` по `reports/OB.md`, «Целевое оглавление»; дальше карта и бюджет ниже. Новое:
   - «SLIs and thresholds» перед «Alerts»: 6 строк из `reports/OB.md`, «SLI и пороги» (SLI,
     метрика, порог и алерт или «no alert, why») и «targets for a laptop, not SLOs with an error
     budget»; вступление «Alerts» в 3 строки: «13 alerts in 16 rules, tested by `make alerts-test`;
     live proof and time to fire: docs/evidence.md#alerts-and-time-to-fire»;
   - Superset: абзац «Freshness»: silver merge every 5 minutes, `dbt_build` on its Asset, chart
     cache 300 s (`CACHE_DEFAULT_TIMEOUT`, `superset_config.py`), «Data through» is the date of the
     last purchase, not the build time; про `check.py` «exits 1 for a failing or empty chart; last
     run: docs/evidence.md#superset-dashboard-v2»; вместо номеров строк имя `MCP_DEV_USERNAME`;
   - Airflow: строка `dq_checks` по задачам `airflow/dags/dq_checks.py` на момент исполнения (дубли
     ключей, silver против Postgres, значения source-silver и silver-gold, GMV против источника,
     красный при сбое запросов снапшотов gold и `dbt source freshness`); `make airflow-init` «pools
     lake_writers and gold_writers, 1 slot each»; PF-20: «`dbt_build` and the silver merge do not
     exclude each other: a build longer than about 4 minutes can meet a merge and fail on a
     relationships test; the next build fixes it»; при `TRINO_XMX=2g` в `.env.example` префиксы
     (9, 596) и абзац 601-603 убрать, строка «an existing `.env` keeps its value; set 2g there»;
   - Alerts и Airflow, из «Итога» P05: строка таблицы Alerts со словами «deleted order»
     (около `:850`) и абзацы о гейте `dq_checks` описывают гейт по снапшотам и «in flight» при
     сдвиге CDC, плюс узкое окно PF-20 после нового гейта; P05 исполнен с В-04 «нет»: описать
     окна ложного красного как есть;
   - Daily commands, 91: «no Kafka offset twice and no gap between the lowest and the highest
     offset of each partition, and bronze reached Kafka's end offsets»;
   - Access control: строка `grafana` -> «`grafana` (Grafana), `superset` (Superset)»
     (`docker/trino/etc/rules.json`, `grafana|superset`);
   - CI: smoke «weekly (Monday 03:00 UTC) while the repository is active: GitHub pauses scheduled
     workflows after 60 days without activity»; красные smoke 1155-1159 одной строкой;
     `### Pinned images and actions` остаётся заголовком: две строки и ссылка на supply-chain;
   - Backup: из 1791-1794 убрать «killing \`spark-silver\` mid-merge»; PF-30 «a checkpoint restores
     only together with the catalog it was written against»; PF-54 «anonymous volumes left by
     recreated containers (`docker volume ls -q -f dangling=true`) take a few MB; removing them is
     the owner's call»;
   - «Failure scenarios»: таблица-указатель (номер, сценарий, цель make, дата, ссылка
     `docs/failure-scenarios.md#<якорь>`); строку 10 убрать, ячейку 10b до названия.
4а. В тот же бриф C: две ловушки эксплуатации из `docs/NEXT_SESSION.md` (после P04 они лежат
   в HANDOFF, «Открыто»; искать по словам `ImageManifestDescriptor` и `memory.swap`). Образы
   под containerd store сверяются по манифесту, а не по digest индекса; память контейнера
   смотрится в cgroup (`memory.stat`, `memory.swap.current`, `memory.events`), потому что
   `docker stats` не видит swap. По одному абзацу на английском в разделах о закреплённых
   образах и о памяти; если такой абзац в OPERATIONS уже есть (`grep`), не дублировать.
5. Оркестратор: «Готово, когда», затем `reviewer` (предмет `документ`): дословность (`diff` с
   `ops-before.md`), список «Удалено», метки, ссылки. Гейт и коммит `docs: operations reorganised
   around a table of contents; scenarios, evidence and runbooks moved out`.

Карта и бюджет (KiB, 13.11; итог около 63). Заголовок по цитате, номера только ориентир.

| Диапазон, заголовок | Куда и что | KiB | Причина |
|---|---|---|---|
| 1-37 Profiles | остаётся; скобка лимитов (9) без истории, 14-22 в 3 строки, 32-33 (D2) убрать | 3.5 -> 2.5 | журнал |
| 38-69 Ports | остаётся | 1.5 | |
| 70-155 Daily commands | остаётся; пробы 96-124 в 8 строк с текстами отказов, замеры 116-124 удалить | 5.6 -> 4.0 | есть в evidence «Probe: MinIO stopped» |
| 156-200 Bronze ingest | «Verified on 2026-09-22», SQL от 2026-09-26 удалить | 2.8 -> 2.4 | журнал |
| 201-265 Silver upsert | «in week 3» (208), «First run on 2026-09-23» (256-257) удалить | 4.8 -> 4.3 | журнал |
| 266-351 Query, Access control | остаётся; «Residual risk» единственное место | 6.2 -> 5.9 | |
| 352-460 Lakekeeper | замер 368-370 удалить; 395-410 в 3 строки, без слоя JDBC (P06) удалить с колонкой JDBC в «What deletes files» | 7.3 -> 5.5 | устарело |
| 461-559 MinIO console, Superset | по шагу 4 | 6.4 -> 5.8 | GB-02 |
| 560-661 Airflow | fernet 579-587 и замер 618 удалить; шаг 4 | 7.4 -> 6.6 | журнал |
| 662-725 | ранбуки; в OPERATIONS 3 строки со ссылками | 5.6 -> 0.4 | процедура дежурного |
| 726-747, 779-786 Observability | остаётся; плюс «SLIs and thresholds» | 2.8 -> 3.8 | OB-08 |
| 748-778, 787-813 | `observability/README.md`, `containers.md` | 6.0 -> 0.3 | справка |
| 814-879 Alerts | вступление 3 строки, «Nothing watches the watcher» оставить; колонки «Shown in», «Time to fire» удалить, ячейки «Why» в 1-2 фразы; «Limits worth knowing» в 5 пунктов | 9.2 -> 4.9 | дубль evidence и сценариев |
| 880-945 Dashboards | 886-896 вынесен; 912-932 до 1 KiB; 933-940 ссылкой; 943-945 удалить | 5.7 -> 2.6 | |
| 946-981 Stateful job | живая проверка 970-976 удалить: те же числа в README, строка Stateful job (P13 переносит в evidence) | 2.8 -> 2.2 | дубль |
| 982-1016, 1128-1135 Maintenance | остаётся; ссылка на evidence «First live run» | 2.7 -> 2.8 | |
| 1017-1127 | `docs/evidence.md` (шаг 2) | 6.7 -> 0 | замер с датой |
| 1136-1160 CI | по шагу 4 | 2.7 -> 2.2 | |
| 1161-1188, 1220-1256 | `docs/supply-chain.md`; заголовок и ссылка | 5.2 -> 0.3 | справка |
| 1189-1219 «changes the config hash of 11 services» | удалить | 2.1 -> 0 | заметка к коммиту 30.10 |
| 1257-1259 «213 tests in CI run 40011971965» | строка без числа | 0.2 | устарело |
| 1261-1281 Failure scenarios | таблица-указатель | 2.1 -> 1.5 | |
| 1282-1755 | `docs/failure-scenarios.md` | 33.1 -> 0 | шаг 1 |
| 1756-1794 Runbooks, Backup | как сделал P09; Backup по шагу 4 | 2.2 -> 2.8 | |

Не хватает до предела: сжимать ячейки таблицы алертов и абзацы MCP и импорта в Superset, затем
проверочный блок Access control (320-340) до 6 команд. Процедуры, команды и метки не удалять.

## Готово, когда

- [ ] `test $(wc -c < OPERATIONS.md) -le 67584 && echo ok` -> `ok` (66 KiB); цель около 64 000.
- [ ] `sed -n 1,40p OPERATIONS.md | grep -c '](#'` -> не меньше 17.
- [ ] Метки «Вход», п. 2 построчно в `<scratchpad>/labels.txt`; `while read -r l; do grep -q -- "^$l"
      OPERATIONS.md || echo "MISSING $l"; done < <scratchpad>/labels.txt` -> пусто.
- [ ] `grep -n "killing .spark-silver. mid-merge\|planned (week 3)\|123 of 256\|v1 bundle\|These seven\|superset_config.py:[0-9]\|pool lake_writers, 1 slot\|config hash of 11\|Monday 03:00 UTC, W6" OPERATIONS.md docs/evidence.md docs/failure-scenarios.md`
      -> пусто; `grep -n "Names it does" observability/README.md` -> пусто.
- [ ] `grep -nE '\b(W[0-9]-[TD][0-9]+[ab]?|D[0-9]{1,2}|B[0-9]{1,2})\b|[Aa]udit|[Ww]eek[ -][0-9]|docs/planning' OPERATIONS.md docs/failure-scenarios.md docs/supply-chain.md`
      -> пусто.
- [ ] `grep -c 'SLIs and thresholds\|CACHE_DEFAULT_TIMEOUT\|gold_writers\|dangling' OPERATIONS.md` -> 4.
- [ ] `grep -c 'deleted order' OPERATIONS.md` -> 0, если P05 исполнен с В-04 «да»;
      `grep -c 'ImageManifestDescriptor\|memory.swap.current' OPERATIONS.md` -> не меньше 2.
- [ ] `python3 -I <scratchpad>/check_docs.py . links` -> `broken: 1` (только `T00-clean-clone.md:361`);
      `check_md_links.py OPERATIONS` и `check_md_links.py failure-scenarios` -> `broken: 0`.
- [ ] `python3 -I <scratchpad>/check_docs.py . dashes | grep -v docs/planning` -> одна итоговая строка.
- [ ] `git grep -nE 'OPERATIONS\.md#([0-9]|first-live|orphans-next)' -- '*.md' ':!docs/planning'` -> пусто.
- [ ] `make check` зелёный; `git status --short` только файлы из «Границы».
- [ ] `reviewer` «принять» или «принять с замечаниями»; гейт коммита пройден.

## Не входит

Ранбуки на алерты и `annotations` (P09); README, ARCHITECTURE, Security model, строки CVE и
`connect-configs` и колонка входа в «Ports» (P13); DECISIONS, в том числе `DECISIONS.md:749`
«numbers in OPERATIONS.md, "Maintenance"» (верно через ссылку; P12); «OPERATIONS.md, scenario N»
в коде (верно через указатель); формулировка `scripts/verify.sh:2` (P07).

## Риски и откат

- Потеря текста: `diff` с `ops-before.md` до чистки ID, список «Удалено» у ревьюера. Битый якорь
  в чужом файле: проверка ссылок до ревью. Откат до коммита: `git restore` только по «ок».
- Бюджет не сходится в 66 KiB без удаления процедур: стоп, владельцу размер и кандидаты.

## Расхождения с отчётом аудита

- OB-04 оценивает итог в 62-66 KiB; сумма диапазонов 13.11 по его карте около 70 KiB. Нужен вынос
  `docs/supply-chain.md` (у OB «по желанию») и заметок «Observability»: бюджет выше их учёл.
- OB-04 переносит логику `idle:` в docstring `check_dashboards.py` и правит «scenario N» в
  `scripts/chaos/*.sh` и `dbt/tests`: здесь всё в Markdown, без кода и паузы `dbt_build`.
- `check_md_links.py` без фильтра на HEAD даёт `broken: 16`, не 0; `dashes` копии `check_docs.py`
  сломан («Вход», п. 6). Сверх OB: строка 91 «exactly once» (как OR-05 у `verify.sh:2`) и
  `superset` в Access control (DC-07 отдал её OB). PF-25 OB отдал P09: здесь, если P09 не сделал.

## Итог
