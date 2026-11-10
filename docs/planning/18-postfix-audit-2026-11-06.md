# 18. Независимая post-fix проверка 06.11.2026: решение и бэклог на будущее

Обновление 10.11: PF-01 закрыт (`docker exec lakehouse-prometheus-1 kill -HUP 1` 14:28:45 UTC по
«ок» владельца, `/api/v1/rules` 16 с `GoldStaleAtRest`); PF-05 закрыт (smoke 42606043447, schedule,
headSha `4169df6`, success 09.11); PF-02 в карточке Д1 файла `19-review-2026-11-10.md`, там же
бэклог ревью 10.11 (R-01..R-68).

Статус: справка и бэклог, ничего не исправлено. Решение владельца 06.11 ~18:15 UTC: «пометь всё
что можно отправить исправить пока не будем но пометим на будущее в репозитории». Пункт берётся в
работу только карточкой по циклу `AGENTS.md` и с «ок» владельца на неё; класс действий по
`13-harness.md`, раздел 2.

Основание: проверка только чтением 06.11 16:40-18:10 UTC на HEAD `4169df6` (равен `origin/main`,
`git ls-remote`). Workflow из 37 агентов на Opus: 9 ролей (Airflow и DQ, BI и Superset, CDC и
streaming, dbt, SRE и CI, AppSec, публичный репозиторий, документация и архитектура, QA), 27
независимых перепроверок (все исходные MEDIUM, все SHOULD и MUST, спорные и P1), критик полноты.
Исходники: аудит `16-audit-2026-11-06/` (F-01..F-31), исправления `17-audit-fixes.md` (К1..К5).
Рабочее дерево, сервисы, настройки и remote проверка не меняла.

## 1. Вердикт

**READY WITH ACCEPTED DEBT. MUST FIX: 0.** Проект можно оставить как есть; ниже то, что можно
исправить потом.

| Что | Команда | Результат |
|---|---|---|
| CI на HEAD | `gh run view 42253894035` | success, 12 job, все шаги; промежуточные SHA ушли одним push, их код в HEAD без изменений (`git diff bd8ad43 HEAD` без `.md` даёт только svg) |
| unit-тесты | `uv run --no-sync pytest tests/unit -q -p no:cacheprovider` | 1852 passed, 145 skipped (Spark и Postgres; в CI идут с `FAIL_ON_SKIP`) |
| линтеры, `dbt parse`, promtool, импорт DAG | без кэшей и без записи в репозиторий | все exit 0; в `alerts.yml` 16 правил |
| сверка | `. scripts/chaos/lib.sh && reconcile` (только SELECT) | 7 из 7, orders 96358 |
| секреты | `gitleaks git --redact --log-opts=--all` | 131 коммит всех refs, 0 находок; GitHub secret scanning: 0 алертов |
| MCP Superset в новой сессии Claude Code | `health_check`, `execute_sql` | 6.1.0 healthy; `gold.fct_orders` 96358; `lake.silver.orders` PERMISSION_DENIED |
| живой Prometheus | GET `/api/v1/rules` | 15 правил, `GoldStaleAtRest` нет (PF-01) |

P1 подтверждён: К1..К5; F-01, F-02, F-03, F-07, F-10, F-20, F-29 закрыты. У F-11 закрыто
последствие, хотя `17-audit-fixes.md:73` числит её открытой: сигнал К1 сравнивает снапшоты всех 7
таблиц silver, включая `reviews` (`airflow/dags/lakehouse/reconcile.py:112,195-202`). Сам признак
`SILVER_UPDATED` (`reconcile.py:171-176`, от него `gold_ready` в `airflow/dags/dq_checks.py:278-280`)
по-прежнему без `reviews`; сигнал К1 считает только в покое, и его алерт на стенде не загружен
(PF-01).

## 2. Бэклог SHOULD FIX

| ID | Находки | Что | Где | Минимальная правка | Проверка | Класс |
|---|---|---|---|---|---|---|
| PF-01 | NEW-airflow-1, NEW-sre-2, NEW-docs-1, NEW-qa-1 | Живой Prometheus не перечитал `alerts.yml` после `85f84bb`: 15 правил, `GoldStaleAtRest` не вычисляется (последняя загрузка 11:52:18 UTC, коммит 16:08 UTC). На стенде исправление F-01 и F-03 алертом не действует, остаётся `SilverGoldNotCompared` через 6 ч. Репозиторий верен, свежий старт грузит 16 | стенд; `OPERATIONS.md:747,782` | `docker exec lakehouse-prometheus-1 kill -HUP 1` (не `docker kill -s HUP`); в «Готово, когда» карточек с правкой `alerts.yml` шаг «правило загружено»; по желанию `scripts/report.sh` сравнивает число правил в файле и в API | `/api/v1/rules`: 16, есть `GoldStaleAtRest` | C |
| PF-02 | NEW-bi-1, NEW-sre-3, NEW-docs-2 | `make down PROFILE=orchestrate` и `make down PROFILE=bi` останавливают `postgres-meta`, базу каталога Lakekeeper в core: у него `profiles: [core, orchestrate, bi]`. Рецепт советуют `OPERATIONS.md:10` (демо Superset) и `:558` (остановка Airflow). Факт: `config --services` профилей orchestrate и bi называет `postgres-meta`; эффект `down` выведен из семантики Compose, живьём не воспроизводился. В рецепте `:10` вторая половина (`make up PROFILE=bi`) сама поднимает `postgres-meta` снова, каталог без базы только между `down` и `up`; после `:558` база стоит до `make start`. Гипотеза: данные не теряются; как Lakekeeper и bronze переживают возврат базы, не проверено | `Makefile:45-46`; `docker/compose.yaml:534`; `OPERATIONS.md:10,558` | сначала подтвердить: `docker compose --dry-run --env-file .env -f docker/compose.yaml --profile orchestrate down`; затем либо текст (останавливать сервисы поимённо или `make start` после `down`), либо `down` без сервисов core в Makefile с тестом в `tests/unit/test_makefile.py` | dry-run не называет `postgres-meta` | A (текст) или B (Makefile); dry-run по «ок» |
| PF-03 | NEW-sec-2, NEW-docs-4, NEW-docs-5, остаток F-29 | Нет предупреждения у `BIND_IP` и единой модели безопасности, репозиторий публичный. При не-loopback `BIND_IP` наружу уходят Airflow без входа (у scheduler `docker.sock`), MCP с правами Superset Admin, Trino, Connect, Kafka, Lakekeeper. Таблица Access control (`OPERATIONS.md:296-299`) противоречит правилам: строка «everyone else (... any new name)» даёт всем прочим все права на `lake`, а `superset` в `docker/trino/etc/rules.json:3-4,12-13` ограничен как `grafana` | `.env.example:4`; `README.md:72-94`; `OPERATIONS.md:278-339` | комментарий у `BIND_IP`; абзац «Security model» в README: без аутентификации Airflow, Trino, Connect, Lakekeeper, Kafka (с хоста можно писать в `oltp.shop.*`), MCP; `docker.sock`; root-консоль MinIO; пароль Debezium в Connect REST (F-09); общие учётки (F-08); root-процессы (F-22); advisories MinIO (PF-04). `superset` в таблицу Access control. Фраза под таблицей «Explore the stack»: консоль MinIO, Lakekeeper UI, Kafka UI, Airflow и MCP могут менять и удалять | `grep -n -i loopback .env.example README.md` | A, `docs-writer` |
| PF-04 | F-21 | «last community release/tags» неверно: есть `RELEASE.2025-10-15T17-29-55Z`, репозиторий `minio/minio` archived. Advisories 2026 исправлены только в AIStor; здесь недостижимы (нет service accounts, STS, OIDC, LDAP; loopback; ключ `token_urlsafe(24)`). Там же про консоль: `DECISIONS.md:51` («removed the web console»), `:58` («there is no console»), `:761` («`mc` as the console»), а консоль на 9001 есть (`docker/compose.yaml:163,171`) | `README.md:51`; `docker/compose.yaml:153`; `docker/minio/Dockerfile:1,13,38`; `DECISIONS.md:11,51-58,761,818-819` | «pinned community releases» (MinIO 2025-09-07, `mc` 2025-08-13); запись в ADR-026 с датой: более поздний тег, список advisories, почему риск принят; поправить «no console». Смена тега отдельным решением владельца | `grep -rn 'last community' README.md DECISIONS.md docker` пуст | A; смена тега B, пересоздание `minio` C |
| PF-05 | P11, NEW-qa-3 | Старт с чистого клона после P1 не доказан: последний smoke `42216951898` на `bccd194`, до P1 (P1 менял listener Kafka и консоль MinIO в core) | `.github/workflows/smoke.yml:10` (cron, понедельник 03:00 UTC) | ничего не запускать: плановый smoke 2026-11-09 03:00 UTC идёт на HEAD сам; прочитать итог, записать run в `docs/evidence.md`; красный: стоп и разбор | `gh run list --workflow smoke.yml --limit 1`: headSha `4169df6` или новее, success | A (чтение); `gh workflow run` раньше срока C |

## 3. Бэклог OPTIONAL

### 3.1 Безопасность и цепочка поставок

| ID | Находки | Что | Где | Минимальная правка | Проверка | Класс |
|---|---|---|---|---|---|---|
| PF-10 | NEW-sre-7 | Без локального `lakehouse/spark:dev` DockerOperator `silver_upsert` тянет образ с Docker Hub, где namespace `lakehouse` чужой; такой образ получил бы ключи S3. Вероятность низкая (удалены образ и контейнеры, orchestrate поднят до `make start`), тяжесть высокая. Известно: ADR-026, `OPERATIONS.md:1179` | `airflow/dags/silver_upsert.py:57-65` | задача-проверка локального образа перед merge или тег с недоступным реестром | тест в `tests/unit/test_dags.py`, мутация краснеет | B |
| PF-11 | F-09 | Пароль роли Debezium литералом в GET config и tasks Connect и в топике `connect-configs` | `connect/register.sh:58-65`; `connect/shop-connector.json:9` | `EnvVarConfigProvider` с `allowlist.pattern` и ротация пароля (старые записи остаются в компактируемом топике); или только строка в OPERATIONS, Residual risk | GET config отдаёт placeholder; `make reconcile` 7 из 7 | B; перерегистрация и ротация C |
| PF-12 | NEW-bi-5 | `SUPERSET_SECRET_KEY` и `SUPERSET_DB` без `:?`; новый `SUPERSET_ADMIN_PASSWORD` не меняет существующего admin | `docker/compose.yaml:807-808,843-844,878-879`; `docker/superset/init.sh:12-19` | `:?` и тест по образцу `test_superset_admin_password_is_required_not_defaulted_to_empty`; строка о `superset fab reset-password` | `tests/unit/test_compose.py` | B |
| PF-13 | F-25 | `.gitignore` закрывает только `.env`: `.env.bak`, `.env.local` не игнорируются; `.dockerignore` нет (в контекстах сборки `.env` нет, только `__pycache__`) | `.gitignore:1` | `.env.*` и `!.env.example`; по желанию `.dockerignore` | `git check-ignore -q .env.bak && ! git check-ignore -q .env.example` | A |
| PF-14 | F-31 | `actions/checkout` без `persist-credentials: false`; pre-commit по тегам | `.github/workflows/`; `.pre-commit-config.yaml` | `persist-credentials: false`; `pre-commit autoupdate --freeze` | `tests/unit/test_workflows.py` | B |
| PF-15 | F-22, NEW-sec-1 | root у minio и lakekeeper (у Postgres root только в entrypoint, сервер от uid 999, `docker top`); нет `cap_drop` и `no-new-privileges`; `docker.sock` у container-exporter смонтирован ro, а ro Docker API не ограничивает (код шлёт только GET) | `docker/compose.yaml`; `DECISIONS.md:373` | `no-new-privileges` и `cap_drop: [ALL]` для экспортеров и `superset-*`; поправить фразу ADR-011; по желанию docker-socket-proxy | `docker inspect` CapDrop, SecurityOpt | B; пересоздание C |
| PF-16 | F-23 | Сканирования CVE образов и зависимостей нет; jar линии Spark 3.5, dbt 1.10 | `streaming/Dockerfile`; `pyproject.toml` | строка «Not covered» в OPERATIONS; по желанию разовый trivy и pip-audit с записью в evidence | | A |
| PF-17 | F-08 | Общие учётки: root-ключи MinIO у многих сервисов, суперпользователь META у Superset | `docker/compose.yaml` | роль-владелец базы superset; read-only политика MinIO для `lake_ro`; минимум абзац в PF-03 | `grep -n META_USER docker/compose.yaml` | B; применение C |

### 3.2 Airflow, DQ, наблюдаемость

| ID | Находки | Что | Где | Минимальная правка | Проверка | Класс |
|---|---|---|---|---|---|---|
| PF-20 | F-12 | `dbt_build` и merge silver не исключают друг друга: ложный красный, если `dbt_build` дольше ~4.5 мин | `airflow/dags/dbt_build.py:27`; `airflow/dags/silver_upsert.py:66`; `dbt/models/marts/_core.yml:38-44` | relationships `fct_order_items.order_id` в warn с обоснованием или общий пул | тест YAML или AST пула | B |
| PF-21 | F-13 | Пары source-silver не перечитывают позицию CDC: ложный красный при записи во время сверки | `airflow/dags/dq_checks.py:252-275` | перечитать `_cdc_position()` после пар, при сдвиге «in flight» | unit-тест со сдвигом CDC между чтениями | B |
| PF-22 | F-14 | `gold_expire_commands` видит таблицы `__dbt_tmp`: ложный красный при совпадении с `dbt_build` | `airflow/dags/lakehouse/sql.py:98-103` (`GOLD_BASE_TABLES` без фильтра); `airflow/dags/iceberg_maintenance.py:59-63` (задача без пула; пул только у `expire_gold`, `:76-81`) | фильтр `__dbt_tmp` или листинг в пуле | `tests/unit/test_dags.py` | B |
| PF-23 | остаток F-01 | В процедуре паузы DAG нет шага «если на паузе был `dbt_build`, запустить его после снятия» | `docs/planning/13-harness.md:50-53` (пауза при правке DAG) и `:203,209` (цикл verify ставит и снимает паузу `dbt_build` без запуска) | строка в двух местах | | правка регламента, окно подтверждения |
| PF-24 | NEW-airflow-3 | `GoldStaleAtRest` молчит под непрерывной нагрузкой: забытая пауза `dbt_build` видна только как `SilverGoldNotCompared` через 6 ч | OPERATIONS, строка алерта | честная строка | | A |
| PF-25 | F-27 | После рестарта Docker `kafka-exporter` и `lakekeeper` стартуют раньше зависимостей, `ContainerRestarting` 15 мин | OPERATIONS | строка | | A |
| PF-26 | остаток F-10 | `make report` не сверяет образ контейнера с образом тега | `scripts/report.sh` | сравнить `.Image` контейнера с id тега | unit-тест на фикстуре | A |
| PF-27 | NEW-airflow-2, NEW-docs-6 | `observability/README.md:14-16` объясняет имя метрики как «unmapped», а `observability/statsd/mapping.yml:26-28` задаёт `lakehouse.dq.*` с ttl 45m | `observability/README.md` | заменить фразу | | A |

### 3.3 Streaming и реплеер

| ID | Находки | Что | Где | Минимальная правка | Проверка | Класс |
|---|---|---|---|---|---|---|
| PF-30 | F-04, NEW-cdc-2 | Bronze пропускает эпоху по номеру без сверки checkpoint и таблицы; JDBC-каталог включается одним env-флагом. Срабатывает только при ручном восстановлении checkpoint, которого проект не поддерживает | `streaming/spark_jobs/bronze_cdc_ingest.py:118-150`; `streaming/spark_jobs/settings.py:16-18` | строка в OPERATIONS, Backup: checkpoint восстанавливать только вместе с каталогом; по желанию проверка на старте bronze | Spark-тест подмены checkpoint | A (текст), B (код) |
| PF-31 | F-05 | Ядро реплеера без поведенческого теста (мутации commit проходят набор) | `oltp/replayer/replay.py:193-218` | интеграционный тест на Postgres CI с `FAIL_ON_SKIP` | мутация краснеет | B |
| PF-32 | NEW-qa-2 | SQL проверки дыр offsets bronze без теста семантики: ослабление условия проходит набор | `scripts/chaos/lib.sh:219-227` | прогон SQL на сервисном Postgres CI с одним дублем и одной дырой | мутация краснеет | B |
| PF-33 | F-16 | Временные представления `opm_batch_<id>` не удаляются | `streaming/spark_jobs/orders_per_minute.py:96-97` | фиксированное имя или `dropTempView` | Spark-тест | B |
| PF-34 | F-17 | Отсутствующее nullable-поле обнуляет значение в silver | `streaming/spark_jobs/silver_upsert.py:108-122` | причина `missing_field` | Spark-тест | B |
| PF-35 | F-18, F-19 | `enum` и диапазоны контракта справочные (держит CHECK источника); `REPLAY_LATE_RATIO > 0` может переставить итоговый статус (на поставляемых настройках недостижимо; chaos 4 эту ручку не задаёт, реестр 16 тут неточен) | `contracts/README.md`; `oltp/replayer/replay.py:197-206` | две честные строки | | A |
| PF-36 | F-24 | Мёртвый mount `${DATA_DIR}:/data` у `oltp-replayer` | `docker/compose.yaml:466-468` | убрать | `tests/unit/test_compose.py` | B |

### 3.4 dbt, BI, CI

| ID | Находки | Что | Где | Минимальная правка | Проверка | Класс |
|---|---|---|---|---|---|---|
| PF-40 | F-06 | Нет автоматического E2E дальше silver (принято как QA-03 30.10) | `.github/workflows/smoke.yml` | строка в `docs/evidence.md`, «CI and smoke»: gold, Asset, `dq_checks` и дашборды доказаны ручными прогонами; по желанию шаг `make dbt-build` и сверка GMV в smoke | мутация модели краснеет в smoke | A; smoke B |
| PF-41 | NEW-bi-4, NEW-sre-1 | CI не собирает образ Superset; smoke не проверяет bi, 9001, 9092; бандл не сверяется с колонками dbt | `.github/workflows/ci.yml`; `tests/unit/test_superset_bundle.py` | job `superset-image` по образцу `airflow-image`; тест колонок бандла против yml моделей | переименование колонки краснеет | B |
| PF-42 | NEW-dbt-3 | Фильтр мягких удалений в графике Superset `gmv_by_category` не защищён тестом (у Grafana защищён) | `docker/superset/dashboards/charts/gmv_by_category.yaml:20-21` | тест по образцу `tests/unit/test_marketplace_dashboard.py:102-107` | удаление фильтра краснеет | A |
| PF-43 | NEW-dbt-1 | decimal в gold держится на типах silver, контракта dbt нет | `dbt/models/marts/` | `contract: {enforced: true}` для денежных колонок или singular-тест | мутация `cast(... as double)` краснеет | A |
| PF-44 | F-15 | «Доставлен без даты доставки» в `mart_delivery_sla` и `mart_seller_performance` считается по-разному (8 заказов источника против 7 строк продавец-месяц) | `dbt/models/marts/mart_seller_performance.sql:74-75` | описать `late_rate` в `_marts.yml` или выровнять | `dbt parse` или singular-тест | A |
| PF-45 | NEW-dbt-2 | Базовая цифра WARN-теста 287 устарела (сейчас 297) | `dbt/tests/_tests.yml:6-10` | обновить цифру и дату | `dbt parse` | A |
| PF-46 | NEW-bi-3, NEW-sre-5 | `superset-init` наследует HEALTHCHECK образа и после выхода помечен unhealthy | `docker/compose.yaml:830-856` | `healthcheck: {disable: true}` и тест | `tests/unit/test_compose.py` | B |

### 3.5 Документация

| ID | Находки | Что | Где | Минимальная правка | Класс |
|---|---|---|---|---|---|
| PF-50 | NEW-bi-2, NEW-sre-4, NEW-docs-3 | «Never start orchestrate and bi together» против стенда и К5; пик всех контейнеров за 3 ч 8.33 GiB, OOM нет | `OPERATIONS.md:10,14,465`; `README.md:69`; `ARCHITECTURE.md:142-143` | строка комбинации с измеренными числами и условием (`TRINO_XMX=2g`, без tools) | A |
| PF-51 | F-28, NEW-sre-6, NEW-qa-4 | Устаревшие строки CI и smoke: `README.md:154` («had five»), `docs/evidence.md:169` («planned»), `:175` («825 passed») | `README.md`; `docs/evidence.md` | ci 42253894035, smoke 41430931906 и 42216951898, `make check` 1852; проверка: `grep -n 'had five\|is .planned\|825 passed'` пуст | A, `docs-writer` |
| PF-52 | NEW-docs-7 | Схема ARCHITECTURE без `postgres-meta` (каталог, Airflow, метаданные Superset) и без пути MCP к Trino | `ARCHITECTURE.md:16-53`; `docs/img/architecture.svg` | узел и рёбра, переэкспорт | A |
| PF-53 | NEW-bi-6 | Кэш данных Superset 300 с не описан для демо «новый заказ виден в Superset» | `docker/superset/superset_config.py:13-15` | строка в OPERATIONS, раздел Superset | A |
| PF-54 | F-26 | 11 анонимных томов без контейнера (~44 МБ, `docker volume ls -q -f dangling=true`) не описаны; `OPERATIONS.md:753-756` говорит только о томе `/kafka/config` у Connect | OPERATIONS | строка: откуда они, чистка только по «ок» | A |
| PF-55 | К3, `17-audit-fixes.md` | В «Итог» 17 не записано пересоздание `postgres-meta` при `make up PROFILE=bi` (15:07:52); «7 топиков» это `oltp.shop.*`, всего 16; у F-11 последствие закрыто сигналом К1 (раздел 1) | `docs/planning/17-audit-fixes.md` | строки в «Итог» | A |

### 3.6 Публичность и процесс

| ID | Находки | Что | Где | Минимальная правка | Класс |
|---|---|---|---|---|---|
| PF-60 | NEW-pub-1 | Нет LICENSE, GitHub показывает «No license» | корень | решение владельца: MIT или Apache-2.0 для кода с оговоркой, что `data/sample` и seed под CC BY-NC-SA 4.0, или явное «All rights reserved» | A, решение владельца |
| PF-61 | NEW-pub-2 | Атрибуция Olist только в `data/README.md:10-14`, без URL; корневой README лицензию не называет | `README.md:226-228`; `dbt/seeds/_seeds.yml` | строки со ссылками на датасет и лицензию | A |
| PF-62 | NEW-pub-3 | Пути с именем пользователя WSL (фамилия владельца) в 4 файлах: `docs/HANDOFF.md`, `docs/planning/12-review-w4-w5.md:55`, `docs/planning/15-audit-p5-review/corpus-result-v3.txt` и `probe.py.txt` (`git grep -l` по имени); правило «В репо нет имён владельца» (`docs/agent-rules.md:68`). Имя уже публично в метаданных коммитов, утечки нет | эти файлы | заменить пути на `~/` и `<repo>` или уточнить правило до публичных документов | A; правка правил с окном подтверждения |
| PF-63 | F-30 | `/security-review` перед коммитом требуют `docs/agent-rules.md:78` и `docs/planning/03-agent-tooling.md:32,41,62`, но шаг не встроен в `/task` и гейты | `.claude/skills/task/SKILL.md`; `.claude/agents/reviewer.md` | один источник: убрать требование или встроить шаг | правка правил с окном подтверждения |
| PF-64 | NEW-pub-4 | Слитая ветка `w3-fernet-replay-data` на remote (содержимое целиком в main, секретов нет) | remote | по желанию удалить и включить `delete_branch_on_merge` | C (запись в remote) |
| PF-65 | NEW-qa-5 | Тесты сокета container-exporter падают при длинном basetemp (AF_UNIX path too long) | `tests/unit/test_container_exporter.py:263` | сокет в коротком каталоге | A |

## 4. Принято, исправлять не нужно

Условие принятия: ограничение честно описано (PF-03, PF-16, PF-24, PF-35, PF-40, PF-54); для
NEW-pub-4 описание не нужно (содержимое ветки целиком в main).

- Безопасность карточки К2 (`17-audit-fixes.md`, коммит `bd8ad43`): MCP действует как Superset
  Admin без входа на loopback (`docker/superset/superset_config.py:32`). Проверки Host и Origin
  работают (чужой Host 421, чужой Origin и `null` 403); запись данных закрыта тремя слоями:
  `allow_dml: false` (`docker/superset/dashboards/databases/Lakehouse_Trino_lake_ro.yaml:8`), ACL
  Trino `superset` (`docker/trino/etc/rules.json:3-13`), `iceberg.security=read_only` у `lake_ro`.
  Локальный процесс вне браузера проверки обходит: тот же класс, что принятый SEC-07.
- F-06, F-08, F-18, F-19, F-22, F-23, F-26; NEW-airflow-3; NEW-sec-1; NEW-pub-4.

## 5. Не делать

- Переписывать историю git (email и имя в метаданных приняты владельцем).
- Добавлять E2E в CI ради F-06 сейчас.
- Менять тег MinIO ради CVE: здесь они недостижимы (PF-04 только про текст).
- Добавлять JWT для MCP на loopback.
- Чистить анонимные тома и удалять ветку без «ок».
- Повторять replay ради К5: путь до gold подтверждают текущие сигналы.

## 6. Ограничения и следы проверки

- Не проверено: CVE по бинарям и образам (govulncheck, trivy, pip-audit); содержимое артефактов
  Actions (54 SARIF по 6816 байт, по выводу пустые); wiki GitHub; MCP при `BIND_IP=0.0.0.0`; обход
  `allow_dml` многооператорным SQL (только код); эффект `make down` живьём (PF-02); старт с чистого
  клона после P1 (PF-05).
- Память, снимок 06.11 ~16:45 UTC при bi: used 8.7 из 11 GiB, available 2.9 GiB, swap 1.6 GiB; пик
  всех контейнеров за 3 ч по Prometheus 8.33 GiB, OOMKilled нет; bi около 540 МБ (superset 307,
  superset-mcp 233). Это снимки в покое и в малом burst, не стресс-тест.
- Следы: 2 строки в истории запросов Superset от `execute_sql` через MCP (запрос с
  PERMISSION_DENIED остался в статусе `running`) и логи MCP; история запросов Trino, статистика
  Postgres, access-логи сервисов; каталоги pytest в `/tmp`. `.git/FETCH_HEAD` обновлялся в 17:44 и
  18:05 UTC сторонним процессом (по выводу автообновление git в редакторе); refs не изменились.
- Полные ответы агентов лежат в scratchpad сессии, вне репозитория.
