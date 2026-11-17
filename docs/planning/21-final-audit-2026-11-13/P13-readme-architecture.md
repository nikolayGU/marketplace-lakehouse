# P13. Витрина: README, ARCHITECTURE, evidence, interview-notes, README компонентов

Статус: не начат. Opus, `/task docs/planning/21-final-audit-2026-11-13/P13-readme-architecture.md`.

## Цель

Первая страница за 3 минуты отвечает «что доказано, на чём сделано, как запустить, где пределы»:
README до 10 KiB без журнала и ложных чисел; ARCHITECTURE с честными гарантиями, `postgres-meta` и
Production gap; Security model; evidence со статусом и производительностью; interview-notes шире.

## Находки пакета

| ID | Серьёзность | Суть | Где подробности |
|---|---|---|---|
| DC-01, GB-02 | высокая | «4 charts» при 13, «same four questions», скриншот Grafana, «previous quarter» | `reports/DC.md` DC-01; `reports/GB.md` GB-02 |
| DC-02 | высокая | README 19.7 KB, журнал статуса 7.4 KB, нет версий стека | `reports/DC.md` DC-02, «Целевая структура README» |
| DC-06, AR-01, IN-12 | высокая | «last community release» неверно (есть тег 2025-10-15) | `reports/AR.md` AR-01; `reports/IN.md` IN-12 |
| DC-03 | средняя | пустой `LEARNING.md` и «is empty» на первой странице | `reports/DC.md` DC-03 |
| DC-07, IN-04, DP-09 | средняя | нет Security model; `BIND_IP` без предупреждения; пароль Debezium в REST Connect | `reports/IN.md` IN-04; `reports/DP.md` DP-09 |
| AR-03, DP-07 | средняя | «exactly-once» шире кода: «merge on a unique key», «deduplicates by (table, key, lsn)» | `reports/AR.md` AR-03; `reports/DP.md` DP-07, «Exactly-once: стыки» |
| DC-15, AR-09, DC-16, AR-06 | средняя | нет Production gap, «deliberately absent» устарел; на схеме нет `postgres-meta` | `reports/AR.md` AR-06, «Разрыв с продом» |
| DC-17, DC-18 | средняя | interview-notes без BI, тестов, прода, уроков; нет цифр производительности | `reports/DC.md` |
| Б6 | низкая | учений восстановления из копии не было: назвать в строке Production gap о резервных копиях | `registry.md`, раздел 4 |
| DC-13, DC-14, IN-15, QA-09 | средняя | старые числа CI; smoke до silver не назван; «every Monday»; `tests/README.md` | `reports/DC.md`; `reports/QA.md` QA-09, «Карта набора» |
| DC-05, DC-08, DC-12, DC-19, DP-10, OR-05 | средняя | ID карточек и ссылки в русские документы; нет карты документов; «agent»; инструменты хоста; «POSTing»; строка `dq_checks` в `airflow/README.md` | `reports/DC.md`; `reports/DP.md`; `reports/OR.md` |

## Решения владельца и действия класса C

Одним вопросом в начале сессии, рекомендация первой:
- В-07, `docs/img/superset-marketplace.png` (PNG 1600 px, без панели браузера и имён). Есть: hero
  «Superset, <дата> UTC», evidence:269 ссылкой. Нет: hero Grafana «Grafana view of the same marts,
  2026-10-29», evidence:269 как есть.
- В-08, `LEARNING.md`. (а) рекомендуется: `git rm LEARNING.md` («да» и есть «ок»); `## Lessons from
  the failure runs` в interview-notes (7 пунктов DC-03 со ссылками); убрать README:162, :223-225,
  evidence:283; `AGENTS.md:128`, `docs/agent-rules.md:65` через окно подтверждения (если строки
  о `LEARNING.md` остались после P04). (б) файл написал
  владелец: ссылка без «is empty», без AI (`LEARNING.md:4`). (в) файл остаётся: ссылки убрать.
- В-09: `## How it was built` после «What is proven», одна фраза (W6-D15), вклад автора первым
  (`reports/DC.md`, О-2), ссылка `docs/evidence.md#how-it-was-built`. Нет: строка вверху, как сейчас.
- В-25: `not done (<причина>)` вместо `planned` в evidence (роль `docs-writer` и раздел 6
  `13-harness.md` знают только `done`, `measured`, `planned`: исключение называет бриф). Нет:
  остаётся `planned`, и grep по `planned` в «Готово» относится только к README.
- В-26: цифры производительности из истории Airflow и Trino (класс A). Нет: раздел
  `Performance on the laptop` без длительностей; либо по отдельному «ок» владельца на точный
  текст `make replay-burst SECONDS=60` (класс C, расход бюджета реплея) и затем запросы к
  Prometheus из шага о производительности.

## Зависимости

После P11 (`docs/failure-scenarios.md`, `docs/supply-chain.md`), P12 (ADR-027..ADR-030), P01
(зелёный CI) и всех пакетов кода. P14 после: `docs/harness.md`, тест гигиены.

## Вход

Сверить первым шагом по цитате (номера 13.11 сдвинутся). Не подтвердилось: шаг в «Итог».

1. Ложные строки: `grep -n "4 charts\|four questions\|last community\|is empty" README.md
   ARCHITECTURE.md docker/compose.yaml docker/minio/Dockerfile` (README:8,51,87,162;
   ARCHITECTURE:116-117; compose:154; Dockerfile:1); «merge on a unique key», «deduplicates by»
   (ARCHITECTURE:80,127; interview-notes:253-254); evidence:259-261, :269; `connect/README.md:6`
   «POSTing» при PUT в `connect/register.sh:62-65`; `scripts/README.md:16`; README:117 «dbt unique_key».
2. Код против текста гарантий (13.11): `dbt/models/marts/mart_daily_sales.sql:5-7` `delete+insert`,
   `unique_key='purchase_date'`; `dbt/dbt_project.yml:20-26` marts `table`, `on_table_exists:
   replace`; `streaming/spark_jobs/silver_upsert.py:140-144` одна строка на ключ по `_last_lsn desc
   nulls last, ts_ms, kafka_offset`; `:158` `(t._last_lsn is null or s._last_lsn > t._last_lsn)`;
   `:280-289` MERGE по таблице в цикле; `docker/compose.yaml:84-85` retention 24 ч и 2147483648
   байт; `scripts/chaos/lib.sh` `bronze_offsets_ok` (дыры между `min` и `max`), `bronze_caught_up`;
   ADR-019 (начало топиков вернулось снапшотом), ADR-021 (LSN растёт по ключу при одном писателе).
   ADR ссылать только существующие: `grep -n '^## ADR-0[23]' DECISIONS.md`.
3. Версии (13.11; перепроверить `grep -n 'image:' docker/compose.yaml`, `grep -n '^FROM'
   streaming/Dockerfile airflow/Dockerfile docker/*/Dockerfile`): PostgreSQL 17
   (`docker/compose.yaml:40,543`); Kafka 4.3.1 KRaft (`:69`); Debezium 3.5
   (`docker/connect/Dockerfile:1`); Spark 3.5.9, Java 17 (`streaming/Dockerfile:1`,
   `pyproject.toml:18`); Iceberg 1.11.0 (`streaming/Dockerfile:15`); Lakekeeper 0.13.6
   (`docker/compose.yaml:212`); MinIO `RELEASE.2025-09-07T16-13-09Z`, mc `RELEASE.2025-08-13T08-35-41Z`
   (`docker/minio/Dockerfile:13,38`); Trino 483 (`docker/compose.yaml:491`); dbt-core 1.10.23,
   dbt-trino 1.10.4 (`airflow/Dockerfile:15`); Airflow 3.3.2 (`airflow/Dockerfile:3`); Prometheus
   3.14.0, Grafana 13.2.2 (`docker/compose.yaml:656,679`); Superset 6.1.0
   (`docker/superset/Dockerfile:7`); Python 3.12 (`.python-version:1`, `pyproject.toml:5`).
4. Числа в момент исполнения (13.11 в скобках) в `<scratchpad>/p13-facts.md`: графики
   `ls docker/superset/dashboards/charts | wc -l` (13); правила `grep -c '^ *- alert:'
   observability/prometheus/alerts.yml` (16), имена `... | sort -u | wc -l` по `grep -h` (13); DAG
   `ls airflow/dags/*.py | wc -l` (5); сервисы `docker compose --env-file .env.example -f
   docker/compose.yaml --profile '*' config --services | wc -l` (27), `config --profiles` (8); job
   CI `sed -n '/^jobs:/,$p' .github/workflows/ci.yml | grep -cE '^  [a-z-]+:$'` (6); ADR
   `grep -c '^| ADR-' DECISIONS.md` (26); вопросы `grep -c '^\*\*[0-9]*\.' docs/interview-notes.md`
   (30); chaos `ls scripts/chaos/*.sh | grep -vc lib.sh` (10); тесты: строка `passed` из `make
   check`; dbt: статусы и `metadata.generated_at` в `dbt/target/run_results.json` (2026-11-12: pass
   61, success 18, warn 4); `gh run list --workflow ci.yml --limit 1 --json
   databaseId,conclusion,headSha,createdAt`, то же `smoke.yml` (13.11: ci 43423260590 failure на
   `a8c1d49`; smoke 42872707771 success 2026-11-10).
5. Производительность. Prometheus хранит 7 дней (`docker/compose.yaml:658`); 13.11 в окне нет ни
   merge, ни `dbt_build`, батч bronze один старый (GET, проверено): `increase(spark_streaming_input_rows_total{query="bronze_cdc_ingest"}[7d])`
   и `increase(airflow_task_duration_seconds_count{task_id=~"merge|dbt_build"}[7d])` -> 0. Длительности
   из истории Airflow (A, аудитом не запускалось): `$COMPOSE exec -T postgres-meta sh -c 'psql -U
   "$POSTGRES_USER" -d airflow -At' < <scratchpad>/perf.sql`, запрос: `select dag_id, task_id,
   count(*), percentile_cont(0.5) within group (order by duration), percentile_cont(0.9) within
   group (order by duration), max(duration), min(start_date)::date, max(start_date)::date from
   task_instance where state = 'success' and (dag_id, task_id) in (('silver_upsert','merge'),
   ('dbt_build','dbt_build'), ('dq_checks','reconcile_values')) group by 1, 2;`. Батч bronze, если
   первый запрос больше 0: `quantile_over_time(0.9, spark_streaming_batch_duration_seconds[7d])`.
   Объёмы `make trino`: `count(*)` и `sum(file_size_in_bytes)` из `"<table>$files"`. В документ:
   число, дата UTC, окно, запрос.
6. Безопасность (P06 меняет учётки, снять заново): `grep -n docker.sock docker/compose.yaml` (:616
   scheduler, :793 container-exporter); `grep -c 'S3_ACCESS_KEY}' docker/compose.yaml` (7);
   `grep -n 'META_USER}\|OLTP_USER}' docker/compose.yaml docker/airflow/airflow.env`;
   `docker/airflow/airflow.env:11-12` все админы; `connect/register.sh:58-65` пароль в конфиге
   `GET /connectors/shop-connector/config`; `git ls-remote --tags https://github.com/minio/minio
   'RELEASE.2025-1*'` (тег 2025-10-15); `grep -n CVE-2025-62506 DECISIONS.md`.
7. Экспорт `ARCHITECTURE.md:55-62` (`minlag/mermaid-cli:11.4.2` есть локально: `docker image ls`);
   `grep -c postgres-meta docs/img/architecture.svg` (0). Скрипты проверки как в P11, «Вход», п. 6.

## Границы

Можно: только файлы шагов 2-7. Нельзя: `DECISIONS.md`, код, значения конфигов, `.claude/`, стек.

## Шаги

Общее для брифов: английский, без длинного тире и имён, AI только в «How it was built»; число из
`p13-facts.md` или ссылкой на evidence; ID карточек по правилу DC-04 (`reports/DC.md`). Якоря
заранее: `ARCHITECTURE.md#delivery-guarantees-effectively-once`, `#production-gap`;
`docs/evidence.md#status`, `#performance-on-the-laptop`; `docs/interview-notes.md#lessons-from-the-failure-runs`;
отказ до правки («Готово, когда», п. 2-4 красные) в «Итог».

1. Оркестратор: «Вход», п. 4-6 в `<scratchpad>/p13-facts.md`, вход всех брифов.
2. Оркестратор, код до 20 строк: MinIO (`compose.yaml:154`, `Dockerfile:1`) «built from the source
   of a pinned community release (MinIO `RELEASE.2025-09-07T16-13-09Z`; the later 2025-10-15 tag is
   not taken, ADR-026) and of the last `mc` tag»; над `BIND_IP`: «127.0.0.1 only: Airflow, Trino,
   Kafka, Connect, Lakekeeper and the Superset MCP have no login, and the Airflow scheduler holds
   the Docker socket (README, Security model)»; `lake_ro.properties:1-2` назвать `superset`, если P08
   не назвал. `... --profile '*' config --hash '*'` (команда п. 4) до и после равны.
3. Бриф R, `docs-writer`, `README.md` по таблице ниже. Строка о CI называет Java 17
   (`setup-java` в `lint-and-test`; пункт H-3 реестра, его сюда передали P01 и P06). Уезжает: статус (140-163) в evidence
   `## Status`; сценарии (165-183) строкой со ссылкой; «Explore the stack» (74-96) колонкой «Login»
   в OPERATIONS «Ports»; профили (58-72) удалить (есть «Profiles» и «Ports»); сборка MinIO (51-56)
   ссылкой на `docs/supply-chain.md`; ASCII и слои (98-117) в ARCHITECTURE; «Repository» тремя
   строками в «Documentation»; «What I learned» по В-08. Проверка bronze: «no Kafka offset twice
   and no gap between the first and the last offset bronze took per partition».
4. Бриф A, `docs-writer`, `ARCHITECTURE.md`. Mermaid: `PM[("postgres-meta<br/>catalog, Airflow and
   Superset metadata")]`, `LK -.- PM`, `SS -.- PM`, `SU -. "Airflow metadata" .- PM`; узел
   обслуживания «iceberg_maintenance daily 03:30, iceberg_orphans weekly, paused (ADR-025)». Data
   flow п. 4 по DP-07; п. 9 «a dashboard `Marketplace` of 13 charts: KPI tiles with the previous
   period, trends of sales, delivery and cancellations, top categories, worst states» (ADR-027,
   если есть); W6-D14, W6-D9, W6-D17 убрать; слои из README, у gold «rebuilt tables;
   `mart_daily_sales` replaces whole days»; «Resource model» называет `stateful` и `jobs`.
   `## Where exactly-once comes from` -> `## Delivery guarantees: effectively-once` (текст ниже);
   «What is deliberately absent» 2 строки без «(stretch)», «known to the author»; затем `## Production
   gap`: матрица `reports/AR.md`, «Разрыв с продом», статус версий только проверенный `scout`. SVG:
   оркестратор, `ARCHITECTURE.md:59-62`; образа нет: Mermaid, строку SVG убрать, файл по «ок».
5. Бриф E, `docs-writer`, `docs/evidence.md`, `docs/interview-notes.md`, `LEARNING.md` (В-08).
   evidence: `## Status` вверху (таблица README; Superset по проверке 13.11 и ADR-027, CI по `gh`,
   вместо HANDOFF и архива evidence и `run_results.json`); `## Performance on the laptop` по «Вход»,
   п. 5; «CI and smoke»: числа DC-13, «smoke stops at silver; gold, the Asset chain, `dq_checks` and
   the dashboards are proven by the dated manual runs above», QA-09 «CI runs `dbt parse` and static
   checks of the SQL; `dbt build`, DAG runs, chaos and the dashboards are proven on the live stack
   only», расписание по IN-15; 259-261 «against the previous 91 days (2025-12-31 to 2026-03-31)»;
   269 по В-07; 47 как в шаге 3; ID в тексте убрать (DC-05). interview-notes: Q15 (253-254) текстом
   гарантий и новым якорем; Q25 «A later rule», Q28 «Since commit `e2ae619`»; 6 вопросов DC-17
   (Analytics and BI, Testing and CI, Production); «Lessons» по В-08; оглавление с числами.
6. Бриф K, `docs-writer`: `tests/README.md` по `reports/QA.md`, «Карта набора» и «Пропуски на
   хосте» (без чисел); `connect/README.md:6` по DP-10; `airflow/README.md:10` строка `dq_checks` по
   задачам DAG; `scripts/README.md:16` по DC-12; `dbt/README.md`, `oltp/README.md:31`,
   `spark-stalled.md:30` по DC-05; OPERATIONS: колонка «Login» в «Ports», строка `connect-configs`
   в «Access control» (что видно, почему принято, `EnvVarConfigProvider` в проде);
   `docs/supply-chain.md`, «Not covered»: «no CVE scanning of the images».
7. Оркестратор: английская шапка `docs/planning/README.md` (`reports/DC.md`, «Целевой вид корня и
   docs/»); по В-08 «а» `AGENTS.md:128`, `docs/agent-rules.md:65`, `git rm LEARNING.md`.
8. Проверки; `reviewer` (предмет `код` для шага 2, `документ` для остального; сверка каждого числа
   README с `p13-facts.md`); гейт; коммит `docs: readme rewritten as a showcase, delivery
   guarantees, production gap and security model`.

Текст раздела о гарантиях (сверен с «Вход», п. 2):

```text
End to end the pipeline is effectively-once: at-least-once delivery plus idempotent sinks, not a
transactional exactly-once. Silver equals the source as long as Kafka retention (24 h or 2 GiB per
partition) and the replication slot outlive any consumer outage, the source has one writer per key
(ADR-021), and a restored Spark checkpoint matches its table. Silver keeps the newest event per
key (highest LSN; a snapshot read without one loses to any streamed change): a repeated streamed
event is a no-op, a repeated snapshot read rewrites its row with the same values. Silver commits
table by table, so a reader can see `orders` merged before `order_items`. Gold marts are rebuilt
tables; `mart_daily_sales` replaces whole purchase dates (`delete+insert`). Bronze is checked for
no offset twice and no gap between the first and the last offset it took; the start of the topics
that Kafka retention removed before bronze existed came back as a snapshot (ADR-019).
```

Структура README (9.7 KiB):

| Раздел | KiB | Что внутри | Откуда факт |
|---|---|---|---|
| Заголовок, бейдж `ci` | 0.2 | бейдж только после зелёного финального run | `gh run list` |
| Pitch | 0.6 | Olist, 2 года, около 96 тыс. заказов, 7 таблиц; Postgres, Debezium, Kafka, Spark, Iceberg, Trino и dbt, Superset и Grafana; сверка с источником; 16 GB | README:3-6, evidence «Reconciliation» |
| Hero | 0.2 | по В-07 | владелец |
| What is proven | 1.2 | 6-7 строк с числом и ссылкой: сверка 7 из 7, сценарии отказа, живые алерты, обслуживание 595 -> 30 файлов, smoke около 10 мин, BI только витрины, производительность | evidence, `p13-facts.md` |
| How it was built | 0.3 | по В-09 | evidence |
| Architecture | 0.8 | SVG или Mermaid, 3 строки потока, ссылки на ARCHITECTURE | ARCHITECTURE |
| Stack | 1.3 | компонент, версия, задача, отвергнутая альтернатива | «Вход», п. 3; README:119-132 |
| Quick start | 1.5 | хост: `make`, `git`, `curl`, `envsubst` (gettext-base), `timeout`, Python 3.12 и `uv`, Docker; 5 команд; время bootstrap; 4 адреса | README:25-49; DC-19; smoke |
| Business layer | 0.7 | вопросы витрин и дашборда, модели, словарь `dbt/models/docs.md`, `make dbt-docs` | `reports/GB.md`, «Что слой даёт бизнесу» |
| Quality, tests and CI | 0.9 | verify, `dq_checks`, тесты dbt, 6 job, smoke stops at silver, что только на стенде | DC-14, QA-09 |
| Limits and security | 0.9 | `### Security model` (loopback; сервисы без входа; общие учётки; `docker.sock`; пароль Debezium в REST Connect; MinIO без тега 2025-10-15; нет сканирования CVE); 3-4 «not done» с причиной; ссылки Production gap, Not proven yet | «Вход», п. 6; README:158-160 |
| Documentation | 0.6 | `reports/DC.md`, «Целевая карта навигации», плюс failure-scenarios, supply-chain, runbooks | DC-08 |
| Data, License | 0.5 | как сейчас | README:227-238 |

## Готово, когда

- [ ] `test $(wc -c < README.md) -le 10240 && echo ok` -> `ok`; `grep -c '^## ' README.md` -> 10..12.
- [ ] `grep -n "4 charts\|planned\|is empty\|last community\|four questions\|HANDOFF\|planning/" README.md`
      и `grep -rn "last community" docker` -> пусто.
- [ ] `grep -n "same four\|merge on a unique key\|deduplicates by\|(stretch)\|W6-D" ARCHITECTURE.md docs/interview-notes.md`
      и `git grep -n where-exactly-once-comes-from -- '*.md' ':!docs/planning'` -> пусто.
- [ ] `grep -c '^## Delivery guarantees: effectively-once$\|^## Production gap$' ARCHITECTURE.md` -> 2;
      `grep -c postgres-meta docs/img/architecture.svg` -> 1+ (или запасной путь шага 4).
- [ ] `grep -c 'Java 17' README.md` -> 1+ (H-3); `grep -ci 'restore' ARCHITECTURE.md` -> 1+ (Б6);
      `grep -c 'exactly once across Spark restarts' docs/evidence.md` -> 0 (если P12 исполнен).
- [ ] `grep -ci 'security model' README.md` -> 1+; `grep -B3 '^BIND_IP=' .env.example | grep -ci loopback` -> 1.
- [ ] `grep -c '^## Status$\|^## Performance on the laptop$' docs/evidence.md` -> 2; `grep -c 'stops at
      silver' README.md docs/evidence.md` -> по 1; `grep -c 'previous quarter' docs/evidence.md` -> 0.
- [ ] `grep -c '^\*\*[0-9]*\.' docs/interview-notes.md` -> 36; при В-08 «а» `test ! -e LEARNING.md` и
      `git grep -n LEARNING -- . ':!docs/planning' ':!docs/HANDOFF.md'` -> пусто.
- [ ] `grep -n "POSTing\|W1-T05" connect/README.md; grep -n -w agent scripts/README.md` -> пусто;
      `grep -o 'test_agent_state\|RECONCILE_TEST_DSN\|spark-tests\|dbt build' tests/README.md | sort -u | wc -l` -> 4.
- [ ] `grep -c connect-configs OPERATIONS.md` -> 1; `test $(wc -c < OPERATIONS.md) -le 67584 && echo ok`.
- [ ] `check_docs.py . links` -> `broken: 1` (`T00-clean-clone.md:361`); `fileline | grep -c
      'PASTEND\|MISSING'` -> 0; `dashes | grep -v docs/planning` -> итог; `names | grep SURNAME` -> пусто;
      `ai README.md ARCHITECTURE.md docs/evidence.md docs/interview-notes.md */README.md` -> только
      «How it was built» (README, evidence), MCP как функция Superset, JMX agent.
- [ ] `make check` зелёный; `gh run list --workflow ci.yml --limit 1` success, этот id в README;
      `reviewer` «принять» или «принять с замечаниями» по коду и документу; гейт пройден.

## Не входит

`DECISIONS.md` (P12); `scripts/verify.sh:2` (P07); P14. Фраза ADR-007 «So bronze is exactly once
across Spark restarts» входит: после P12 она лежит в `docs/evidence.md`, раздел «Decision
measurements», её правит бриф evidence по AR-03 («no offset twice and no gap across Spark
restarts»). P12 не исполнен и фраза ещё в `DECISIONS.md`: не трогать, строка в «Итог» для P12.

## Риски и откат

README больше 10 KiB: резать Stack и What is proven, не Security model; откат `git restore` по «ок».

## Расхождения с отчётом аудита

- AR-09 заменяет «What is deliberately absent» матрицей, DC-15 ставит Production gap после: раздел
  остаётся в 2 строки, его якорь нужен interview-notes:505.
- AR-03 ссылается на ADR-030: при сведении 18.11 он добавлен в P12 (ADR-027..ADR-030); ссылку
  не ставить, только если владелец не дал «ок» на его текст. Добавлено начало топиков (README
  папки, раздел 2; ADR-019). Б6 (учений восстановления не было): строка Production gap о
  резервных копиях и восстановлении называет это прямо (`registry.md`, раздел 4).
- DC-18 брал Prometheus `[30d]` при retention 7 дней; 13.11 в окне нет merge и `dbt_build`.
  В-09 ведёт на `docs/harness.md` из P14: до P14 ссылка на evidence. Q&A об агентах (О-3 DC) без
  В-n: P14 (В-21). README:117 «dbt unique_key» неверно, как AR-03. DC-06 убирает «last community»
  везде, IN-12 оставляет для `mc`: здесь «last `mc` tag», grep пуст.

## Итог
