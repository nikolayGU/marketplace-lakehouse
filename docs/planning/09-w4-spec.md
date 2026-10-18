# 09. Спека: неделя 4, наблюдаемость и отказы

Версия 0.1, 18.10.2026, черновик. Решения раздела 2 ждут «ок» владельца; до него ни одна карточка не стартует. Формат по `06-spec-standard.md`, структура как у `07-w3-spec.md`. Архитектура и исходные задачи в `00-mini-architecture-review.md` (§6 RAM, §8 сценарии отказа) и `01-roadmap.md` (неделя 4 и список «Спека недели 4 обязана закрыть»); здесь решения, проверенные факты, карточки и проверки. Сверено 18.10: compose и образы (`docker compose config`, `docker manifest inspect`, опыт с `--dry-run` в scratch-проекте), документация Airflow, Debezium 3.5, postgres_exporter, statsd_exporter, kafka_exporter, Spark 3.5, Prometheus (context7 и страницы проектов), живые метрики bronze (`curl 127.0.0.1:4041/metrics`), `docker stats`. Что не проверено, помечено «не проверено» с командой проверки или оформлено шагом «проверить первым».

## 1. Цель и границы

Цель недели: по дашборду видно lag, freshness, ошибки и память; шесть алертов из роадмапа, каждый доказан срабатыванием в своём сценарии; все 8 обязательных сценариев отказа описаны в `OPERATIONS.md` по пяти ответам.

Состояние на входе (18.10):

- `observability/` содержит только `README.md` и четыре пустых каталога (`find observability -type f` печатает один файл). Compose монтирует read-only файлы, которых нет: `observability/prometheus` целиком (`docker/compose.yaml:551`, внутри нет `prometheus.yml`, Prometheus не стартует), `grafana/provisioning` и `grafana/dashboards` (`:574-575`), `postgres-exporter/queries.yaml` (`:609`), `statsd/mapping.yml` (`:621`).
- У `kafka-exporter`, `postgres-exporter`, `statsd-exporter`, `cadvisor` нет `healthcheck` и `depends_on` (`docker/compose.yaml:590-643`). Три тега помечены `TODO(W4): verify tag` (`:603`, `:618`, `:631`); `docker manifest inspect` 18.10 находит все шесть образов профиля `obs`.
- Для Connect JMX exporter нет: `TODO(W4-T01)` в `docker/compose.yaml:121-122`. В `docker/airflow/airflow.env` нет `AIRFLOW__METRICS__STATSD_*`, в compose `TODO(W4-T01): statsd` (`:474`).
- `streaming/spark_jobs/metrics.py` отдаёт на 4041 три метрики bronze; `spark_streaming_kafka_lag` нет. Живые ряды 18.10: `spark_streaming_last_batch_timestamp`, `spark_streaming_input_rows_total`, `spark_streaming_batch_duration_seconds` с `query="bronze_cdc_ingest"`.
- `dq_checks` каждые 15 минут (`airflow/dags/dq_checks.py:31`) печатает строки `dq <name>=<value>` (`:45`, `:59`, `:69-74`, `:87`); в Prometheus они не попадают.
- Airflow стал писателем silver 18.10; `make verify` отказывается при запущенном scheduler (`scripts/verify.sh:22`), `make silver` не отказывается (`Makefile`, цель `silver`).
- Скриптов chaos 5, 6, 8 нет; у chaos 7 есть половина про данные (`scripts/chaos/poison-event.sh`), алерта нет (OPERATIONS, таблица сценариев).
- Реплей: `virtual_now` 2026-07-13 03:37:18, W3 потратила 1 д 17 ч 39 мин из 10 дней D2 (HANDOFF, «Что живёт в стеке»). До горизонта 2026-09-21 около 70 виртуальных дней.

Входит: W4-T01a..W4-T06b. За владельцем: решения раздела 2, W4-T07 (гейт observability), Modify-гейт `quarantine_rows_total` (W4-D8).

Не входит: Grafana по gold (W6-T01), reconciliation-отчёт на дашборде (W5-T04), метрики stateful job (W5-T01), доставка алертов наружу (W4-D6), скрейп Trino, Lakekeeper и реплеера (раздел 7).

## 2. Решения до старта

Блок стартует после «ок» владельца на эту таблицу. Карточки ссылаются на решения по ID. Все решения в статусе «ждёт «ок» владельца».

| ID | Вопрос | Рекомендация | Альтернатива | Цена ошибки | Статус |
|---|---|---|---|---|---|
| W4-D1 | Откуда в Connect берётся jar JMX exporter | Свой слой образа `docker/connect/Dockerfile`: `FROM quay.io/debezium/connect:3.5`, jar `jmx_prometheus_javaagent-1.6.0.jar` с GitHub-релиза через `ADD --checksum=sha256:...` в `/kafka/libs/`, `metrics.yaml` в `/kafka/config/`; образ `lakehouse/connect:dev`, в compose `ENABLE_JMX_EXPORTER=true`. Версия 1.6.0 (07.06.2026), а не 1.7.0 (05.10.2026, моложе двух недель) | Bind-маунт jar и `metrics.yaml` с хоста, jar качает цель `make` | Bind-маунт отсутствующего файла создаёт на хосте каталог от root, `ls /kafka/libs/jmx_prometheus_javaagent*.jar` в entrypoint ничего не находит, JVM Connect не стартует, а Connect в `core`: встаёт CDC. Свой образ меняет образ звена `core` | ждёт «ок» владельца |
| W4-D2 | Как значения `dq_checks` попадают в Prometheus | Задачи `dq_checks` шлют gauge в формате DogStatsD по UDP на `statsd-exporter:9125` из модуля `airflow/dags/lakehouse/metrics.py` (без импорта `airflow`, тестируется на хосте); ошибка отправки печатается и не валит задачу | Клиент статистики самого Airflow (`airflow.sdk.observability.stats`): теги в метки он переводит только в режиме Datadog или InfluxDB. Pushgateway: новый сервис, только через ADR | Без нового сервиса UDP теряет значения молча, пока `obs` выключен; это закрывает TTL (W4-T03). Pushgateway без ADR нарушает правило «новый сервис только через ADR» | ждёт «ок» владельца |
| W4-D3 | Порог `SlotWalRetainedHigh` и поведение на простое | Своя метрика удержания `pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)` и флаг `active` из `queries.yaml`; правило `(удержание > 64 MiB и слот неактивен) или удержание > 512 MiB`, `for: 5m`. `heartbeat.action.query` в W4 не включать | `heartbeat.action.query` с таблицей в публикации: слот двигается каждые 10 с, хватает одного порога 64 MiB. Это миграция `shop`, новый топик (автосоздание выключено, урок ADR-019) и правка коннектора, значит ADR и отдельное «ок» | Порог без условия на активность либо горит на простом ноутбуке (хвост WAL растёт без отказа), либо не горит в chaos 6 (порция в 60 с даёт около 35 MB WAL, вывод из LSN в HANDOFF) | ждёт «ок» владельца |
| W4-D4 | Freshness-алерт против каденции `dq_checks` 15 минут | `FreshnessAbove15m` по `lakehouse_silver_lag_seconds`: сколько секунд самый старый снапшот bronze ждёт merge в silver, 0 в покое. Порог 900, без `for`; каденция 15 минут остаётся (D10 W3), задержка обнаружения до 15 минут пишется в OPERATIONS. `lakehouse_table_freshness_seconds{layer,table}` из роадмапа идёт на дашборд, без алерта | Алерт по `now() - max(_updated_at)` больше 900 (горит всегда между порциями реплея). Или `dq_checks` раз в 5 минут: втрое больше запросов в Trino, который на 95% лимита | Алерт, который горит на простое, никто не читает; алерт на «давно не было данных» не отличает «нет трафика» от «silver встал» | ждёт «ок» владельца |
| W4-D5 | RAM со всеми рабочими профилями | `core+query+orchestrate+obs` вместе, Trino на `-Xmx2g`; стоп-правило: любой `OOMKilled=true` или сумма `docker stats` больше 10 GiB, и тогда `orchestrate` поднимается только на шаги, которым он нужен. Лимит Trino не меняется: по замеру NMT 18.10 принят D20 W3 (`MALLOC_ARENA_MAX=4`, та же нагрузка 2.91 вместо 3.18 GiB), лимит 4-4.5 GB решается по замеру этого шага | `obs` только с `core+query`, Airflow поднимать на chaos 9 и проверку `AirflowDagFailed`: тогда silver на это время пишет `make silver` при остановленном scheduler | Лимиты 15.8 GiB (core 7.25, trino 3.5, orchestrate 2.05, `merge` silver 2, obs 0.98) при VM 11.68 GiB; реально 6.84 GiB без `obs` (`docker stats`, 18.10): OOM-kill Trino или minio посреди chaos даёт красные DAG, которые выглядят как результат сценария | ждёт «ок» владельца |
| W4-D6 | Alertmanager | Не ставить (ADR-015 убрал доставку алертов): правила в Prometheus, состояние в UI, `/api/v1/alerts` и на дашборде | Alertmanager как новый сервис с ADR, около 50 MB | На ноутбуке доставлять некуда; на собесе это объясняется словами | ждёт «ок» владельца |
| W4-D7 | Как chaos-скрипт доказывает, что алерт сработал | Функция `alert_firing <name> <seconds>` в `scripts/chaos/lib.sh`: опрос `curl -s 127.0.0.1:9090/api/v1/alerts` каждые 5 с до `state == "firing"`, печать `alert <name> firing after <n> s`, код 1 по таймауту. В конце сценария запрос `max_over_time(ALERTS{alertstate="firing"}[<окно>])` печатает всё, что горело за окно | Скриншот UI вручную | Без программной проверки DoD «алерт срабатывает» проверяется на глаз, а время до срабатывания не измеряется | ждёт «ок» владельца |
| W4-D8 | Метрика карантина | Не экспортировать: `quarantine_rows_total` и алерт на неё это Modify-гейт владельца (`02-learning-gates.md`, Observability). W4-T03 шлёт все строки `dq`, кроме `quarantined_last_hour`; у chaos 7 в OPERATIONS «алерт: Modify-гейт владельца» | Экспортировать `quarantined_last_hour` из `dq_checks` как gauge, гейт сводится к алерту | Гейт теряет смысл, или chaos 7 до гейта без алерта | ждёт «ок» владельца |
| W4-D9 | Откуда lag bronze | Только listener (ADR-013): `spark_streaming_kafka_lag{query,topic,partition}` = `latestOffset` минус `endOffset` последнего прогресса; idle-событие ставит 0 | Listener отдаёт обработанные offsets, lag считается в PromQL против `kafka_topic_partition_current_offset` из kafka-exporter: lag растёт и когда Spark встал | Lag из listener замирает, когда Spark встал; это ловит `SparkNoBatch5m`, а не lag. Соединение рядов в PromQL ломается на расхождении имён меток | ждёт «ок» владельца |
| W4-D10 | Бюджет реплея W4 | До 5 виртуальных дней из 15 по D2 W3: T02 12 ч, chaos 5 6 ч, chaos 6 до 36 ч, chaos 8 24 ч, проверка `FreshnessAbove15m` 12 ч, остальное запас; потраченное пишется в HANDOFF | 15 дней по D2 | Перерасход оставляет W5-T01 и демо без трафика | ждёт «ок» владельца |
| W4-D11 | Как chaos 6 «убивает» коннектор на 30 минут | REST `PUT /connectors/shop-connector/stop`, затем `PUT .../resume`; контейнер жив, метрики Connect видны. Состояние STOPPED хранится в `connect-configs` и переживает рестарт, поэтому `resume` в `trap EXIT` | `docker stop kafka-connect` на 30 минут. Или `PUT .../pause`: задача остаётся, walsender, скорее всего, держит слот активным (не проверено) | При `pause` слот активен, условие W4-D3 не выполняется, алерт не горит. Упавший скрипт без `trap` оставляет CDC остановленным навсегда | ждёт «ок» владельца |
| W4-D12 | Chaos-скрипты при Airflow-писателе silver | Функция `merge_silver` в `lib.sh`: при запущенном scheduler `run_dag silver_upsert <run_id>` (`lib.sh:191`), иначе `run_silver`; все вызовы `run_silver` в `scripts/chaos/*.sh` переходят на неё. `make silver` отказывается при запущенном scheduler, как `scripts/verify.sh:22` | Скрипт сам останавливает scheduler на время сценария | Сейчас `connect-restart.sh:75`, `duplicates.sh:48`, `late.sh:24`, `poison-event.sh:15,24` зовут `make silver`: при включённом `silver_upsert` это второй писатель на один checkpoint | ждёт «ок» владельца |

## 3. Ограничения блока

- `$COMPOSE` означает `docker compose --env-file .env -f docker/compose.yaml` из корня репо, как в `Makefile`.
- Версии: Prometheus `v3.14.0`, Grafana `13.2.2`, kafka-exporter `v1.10.0`, postgres-exporter `v0.17.1`, statsd-exporter `v0.28.0`, cadvisor `v0.52.1` (теги есть в реестрах, `docker manifest inspect` 18.10); Connect `quay.io/debezium/connect:3.5` (Debezium 3.5.2.Final, Kafka 4.2.0 по `docker image inspect`); JMX exporter 1.6.0 (W4-D1); Airflow 3.3.2; Spark 3.5.9. Поведение сверяется с документацией этих версий, не по памяти.
- Профили: рабочая комбинация `core+query+orchestrate+obs` по W4-D5; `bi` и `tools` не поднимаются, все профили сразу никогда. При работающем Airflow каждый `make start` только с `TRINO_XMX=2g` (OPERATIONS, Airflow).
- Новых сервисов нет: только шесть сервисов `obs`, которые уже описаны в compose (ADR-016). Pushgateway и Alertmanager только через ADR (W4-D2, W4-D6).
- Один писатель silver, это Airflow. Ручной `make silver` и полный `make verify` только при остановленном scheduler по процедуре HANDOFF («Что живёт в стеке»). Chaos-скрипты получают silver через `merge_silver` (W4-D12). Проверки в сценариях: `reconcile` и `bronze_offsets_ok` из `lib.sh` после merge в покое.
- Коммит: хук `guard.py` требует полный `make verify` этого дерева, а он требует остановленного scheduler. Перед каждым коммитом: дождаться, пока нет запусков в полёте, остановить scheduler, `make verify`, запустить scheduler.
- Реплей только порциями `make replay-burst`, в пределах W4-D10; каждая порция требует «ок» владельца (AGENTS.md, запреты). Потраченное пишется в HANDOFF.
- Перезапуск звена `core` (Connect в W4-T01b, spark-bronze в W4-T02) только с «ок» владельца, без идущего реплея, после `bronze_caught_up`.
- Настройки Postgres и коннектора Debezium не меняются. `PUT /stop` и `/resume` в chaos 6 меняют состояние коннектора, не его конфиг; запуск сценария с «ок».
- Порты только на 127.0.0.1; у экспортеров host-портов нет, Prometheus ходит к ним по сети `lake`. Секреты только из `.env`; пароль Grafana в командах только через окружение (`. scripts/chaos/lib.sh` экспортирует `.env`), не текстом.
- `docker/airflow/airflow.env` правится через Edit: `guard.py` блокирует `sed -i` по этому пути (HANDOFF, отклонения W3).
- Конфиги `observability/` проходят `yamllint` (`make lint` уже включает `observability`).
- Каждый файл, который монтирует compose, существует до первого `make up PROFILE=obs`. Проверка перед стартом: `find observability -type d -name '*.y*ml'` пусто.
- Один коммит на карточку, после проверок раздела 6 и «ок» владельца на дифф.

## 4. Карточки

### W4-T01a Профиль `obs`: конфиги, healthcheck, `depends_on`, теги

**Зачем.** Сейчас `make up PROFILE=obs` не поднимает Prometheus и создаёт на хосте каталоги от root вместо файлов. Без живого профиля ни одна метрика и ни один алерт недели не проверяются.
**Оценка** 4 ч. **Зависит от:** W4-D5. **Область коммита:** `obs`.

**Вход.**
- Факты раздела 1 про `observability/` и compose.
- Опыт 18.10 на scratch-compose (Docker Compose v5.5.1): сервис профиля `obs` с `depends_on` на сервис профиля `core` делает проект невалидным при `--profile obs` без `core` (`service "b" depends on undefined service "a": invalid compose project`); с `required: false` у зависимости проект валиден, `up --dry-run` проходит. `make up PROFILE=obs` передаёт только `--profile obs`.
- statsd_exporter: web `:9102`, statsd `:9125` UDP и TCP, `/-/healthy`, TTL `0` значит «не истекает», DogStatsD-теги разбираются по умолчанию (README и `main.go` проекта, 18.10).
- kafka_exporter: `--kafka.version` по умолчанию `2.0.0`, web `:9308` (README проекта). Kafka 4.x не принимает протоколы старше 2.1 (KIP-896).
- postgres_exporter: `extend.query-path` (`PG_EXPORTER_EXTEND_QUERY_PATH`) помечен deprecated, но есть; встроенный коллектор слотов отдаёт `confirmed_flush_lsn` только у активного слота (`collector/pg_replication_slots.go`, context7 18.10). Поэтому удержание считает свой запрос.
- Docker Desktop 29.8.0, cgroup v2, драйвер cgroupfs, VM 12 542 664 704 байта (`docker info`, 18.10).

**Сделать.**
1. Проверить первым, вывод в описание коммита:
   - shell и `wget` в образах: `for i in prom/prometheus:v3.14.0 grafana/grafana:13.2.2 danielqsj/kafka-exporter:v1.10.0 prometheuscommunity/postgres-exporter:v0.17.1 prom/statsd-exporter:v0.28.0 gcr.io/cadvisor/cadvisor:v0.52.1; do echo "$i $(docker run --rm --entrypoint sh $i -c 'command -v wget' 2>&1)"; done`. Где `wget` нет, healthcheck через собственный бинарь образа; если и его нет, стоп и вопрос владельцу.
   - флаги cadvisor: `docker run --rm gcr.io/cadvisor/cadvisor:v0.52.1 --help 2>&1 | grep -E 'docker_only|disable_metrics|store_container_labels|housekeeping_interval'`.
2. `observability/prometheus/prometheus.yml`: `scrape_interval: 15s`, `evaluation_interval: 15s`, `rule_files: [alerts.yml]`; jobs `prometheus` (`localhost:9090`), `spark-bronze` (`spark-bronze:4041`), `kafka-exporter` (`kafka-exporter:9308`), `postgres-exporter` (`postgres-exporter:9187`), `statsd-exporter` (`statsd-exporter:9102`), `cadvisor` (`cadvisor:8080`). Job `kafka-connect` добавляет W4-T01b. `observability/prometheus/alerts.yml`: одна группа `lakehouse` с пустым `rules: []`, правила пишет W4-T05.
3. `observability/postgres-exporter/queries.yaml`, ключ `lakehouse_slot`: `select slot_name, pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) as retained_bytes, active::int as active from pg_replication_slots`; `slot_name` LABEL, `retained_bytes` и `active` GAUGE. В Prometheus это `lakehouse_slot_retained_bytes{slot_name}` и `lakehouse_slot_active{slot_name}` (W4-D3).
4. `observability/statsd/mapping.yml`: `mappings: []`; маппинги Airflow добавляет W4-T01b, `lakehouse.*` добавляет W4-T03.
5. `observability/grafana/provisioning/datasources/prometheus.yml` (`uid: prometheus`, `url: http://prometheus:9090`, `isDefault: true`) и `provisioning/dashboards/files.yml` (провайдер `file`, `path: /var/lib/grafana/dashboards`). Сами дашборды пишет W4-T04.
6. `docker/compose.yaml`, раздел `obs`: healthcheck у четырёх экспортеров по их HTTP (`/metrics` у kafka- и postgres-exporter, `/-/healthy` у statsd-exporter, `/healthz` у cadvisor) по образцу Prometheus (`:555-559`); `depends_on` с `condition: service_healthy` и `required: false`: kafka-exporter от `kafka`, postgres-exporter от `postgres-oltp`; grafana от `prometheus` (тот же профиль, без `required: false`); у kafka-exporter `--kafka.version=` версии брокера, совместимой с sarama образа (по шагу 1 логов: `kafka_brokers 1`); флаги cadvisor `--docker_only=true` и отключение лишних групп метрик по шагу 1; комментарии `TODO(W4): verify tag` заменить на `verified 2026-10-18`.
7. Поднять: `make up PROFILE=obs` при живом `core+query+orchestrate`. Записать `docker stats --no-stream` в `00-mini-architecture-review.md` §6 и OPERATIONS.
8. Документация: `observability/README.md` по факту (что лежит, какие jobs), OPERATIONS: раздел «Observability» (как поднять, где UI, как проверить targets, что `obs` без `core` стартует, но экспортеры core-звеньев красные), строка `obs` в «Profiles» с замером.

**Готово, когда.**
- `find observability -type d -name '*.y*ml'` пусто до и после старта.
- `$COMPOSE --profile obs config -q` без `--profile core`: код 0. `make lint` зелёный.
- `docker run --rm -v "$PWD/observability/prometheus:/etc/prometheus:ro" --entrypoint promtool prom/prometheus:v3.14.0 check config /etc/prometheus/prometheus.yml`: `SUCCESS`.
- `$COMPOSE --profile obs ps`: 6 сервисов `healthy` не позже 2 минут после `make up PROFILE=obs`.
- `curl -s 127.0.0.1:9090/api/v1/targets | python3 -c 'import json,sys; t=json.load(sys.stdin)["data"]["activeTargets"]; print(sorted((x["labels"]["job"], x["health"]) for x in t))'`: 6 jobs, все `up`.
- `curl -s 127.0.0.1:9090/api/v1/query --data-urlencode 'query=lakehouse_slot_retained_bytes{slot_name="shop_slot"}'`: один ряд; значение того же порядка, что `select pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) from pg_replication_slots` в `make psql`.
- Cadvisor на Docker Desktop (проверка из роадмапа): `curl -s 127.0.0.1:9090/api/v1/query --data-urlencode 'query=count(container_memory_usage_bytes{name=~"lakehouse-.+"})'` равно `docker ps --filter name=lakehouse- -q | wc -l`. Не равно: стоп, это факт для владельца (Infra-дашборд и `ContainerRestarting` без cadvisor не строятся).
- `curl -s 127.0.0.1:9090/api/v1/query --data-urlencode 'query=prometheus_tsdb_head_series'`: число записано в OPERATIONS; Prometheus ниже 80% лимита в `docker stats`.
- `curl -s 127.0.0.1:3000/api/health`: `"database": "ok"`; `$COMPOSE logs grafana | grep -i 'provisioning' | grep -ci error` равно 0.

**Ловушки.**
- Bind-маунт отсутствующего файла создаёт каталог от root, контейнер падает на чтении конфига, а `docker compose config` этого не видит. Удаление такого каталога это `rm` в blast radius. Поэтому файлы до первого старта и проверка `find`.
- `depends_on` на сервис `core` без `required: false` ломает `make up PROFILE=obs` целиком (опыт выше).
- kafka-exporter по умолчанию говорит протоколом Kafka 2.0.0, брокер 4.3.1 его не принимает: target up, а рядов `kafka_topic_*` нет.
- Cadvisor на Docker Desktop отдаёт ряды по всем cgroup VM; без `--docker_only` и отсечения групп метрик Prometheus с лимитом 300 MB растёт по числу рядов.
- Каталог `observability/prometheus` смонтирован read-only целиком: правила перечитываются по `docker kill -s HUP <id prometheus>`, правка файла без этого ничего не меняет.
- Дашборды из provisioning в UI редактируются, но в файл не пишутся: правки только в JSON (W4-T04).

**Blast radius и пайплайн.** Нет. Новые тома `prometheus` и `grafana` уже описаны в compose. Bronze, silver, checkpoint, offsets и DAG не затронуты.

**Не входит.** JMX Connect и StatsD Airflow (W4-T01b), дашборды (W4-T04), правила (W4-T05).

### W4-T01b Метрики Connect (JMX) и StatsD Airflow

**Зачем.** `ConnectorNotRunning` не на чем строить: REST Connect Prometheus не читает. Длительность и исход `merge` silver есть только в Airflow (silver живёт минуту и метрик не отдаёт), как и падения DAG для `AirflowDagFailed`.
**Оценка** 3 ч. **Зависит от:** W4-T01a, W4-D1, W4-D5; «ок» на перезапуск Connect. **Область коммита:** `obs`.

**Вход.**
- Entrypoint образов Debezium (`debezium/container-images`, `connect-base/3.5/docker-entrypoint.sh`, ветка main, 18.10): при `ENABLE_JMX_EXPORTER=true` добавляет `-javaagent:$(ls "$KAFKA_HOME"/libs/jmx_prometheus_javaagent*.jar)=9404:$KAFKA_HOME/config/metrics.yaml`; порт 9404 зашит. В образе `KAFKA_HOME=/kafka`, порты 8083, 8778, 9092, есть `JOLOKIA_VERSION=1.7.2` (`docker image inspect`, 18.10).
- JMX exporter: на Maven Central `io.prometheus.jmx:jmx_prometheus_javaagent` заканчивается на 1.0.1 (31.05.2024); новые версии только ассетами GitHub-релизов, последний 1.7.0 от 05.10.2026, 1.6.0 от 07.06.2026 (страницы 18.10).
- Airflow: `[metrics] statsd_on`, `statsd_host`, `statsd_port`, `statsd_prefix`, переменные `AIRFLOW__METRICS__*`; нужен extra `apache-airflow[statsd]` (документация Airflow stable, context7 18.10).

**Сделать.**
1. Проверить первым:
   - тот же блок в теге 3.5: `docker run --rm --entrypoint grep quay.io/debezium/connect:3.5 -n -A2 ENABLE_JMX_EXPORTER /docker-entrypoint.sh` (ожидается строка с `-javaagent` и `9404`);
   - jar в образе нет: `docker run --rm --entrypoint sh quay.io/debezium/connect:3.5 -c 'ls /kafka/libs | grep -i jmx_prometheus || echo none'` печатает `none`;
   - клиент statsd в образе Airflow: `$COMPOSE exec airflow-scheduler python -c "import statsd; print(statsd.__file__)"`. Нет модуля: строка `apache-airflow[statsd]==3.3.2` в `airflow/Dockerfile` с тем же constraints-файлом.
2. `docker/connect/Dockerfile` по W4-D1; sha256 jar сверить с контрольной суммой на странице релиза 1.6.0. `docker/connect/metrics.yaml`: правила для `kafka.connect<type=connector-metrics, connector=(.+)><>status` и `kafka.connect<type=connector-task-metrics, connector=(.+), task=(.+)><>status` в `kafka_connect_connector_status{connector,status}` и `kafka_connect_connector_task_status{connector,task,status}` со значением 1 (строковый атрибут уходит в метку), плюс `debezium.postgres<type=connector-metrics, context=streaming, server=oltp>` (`Connected`, `MilliSecondsSinceLastEvent`, `MilliSecondsBehindSource`, `TotalNumberOfEventsSeen`).
3. `docker/compose.yaml`, `kafka-connect`: `build: ./connect`, `image: lakehouse/connect:dev`, `ENABLE_JMX_EXPORTER: "true"`; строки `TODO(W4-T01)` (`:121-122`) убрать. Порт 9404 наружу не публикуется.
4. Перезапуск Connect с «ок»: без реплея, после `bash -c '. scripts/chaos/lib.sh && bronze_caught_up'`; `TRINO_XMX=2g make start` пересоздаёт Connect из нового образа. Затем `connector_running` и `slot_reattached`.
5. `prometheus.yml`: job `kafka-connect` (`kafka-connect:9404`).
6. `docker/airflow/airflow.env` (через Edit): `AIRFLOW__METRICS__STATSD_ON=True`, `AIRFLOW__METRICS__STATSD_HOST=statsd-exporter`, `AIRFLOW__METRICS__STATSD_PORT=9125`, `AIRFLOW__METRICS__STATSD_PREFIX=airflow`; в compose убрать `TODO(W4-T01): statsd` (`:474`). Перезапуск трёх сервисов Airflow, когда нет запусков в полёте.
7. Проверить отказ: `make down PROFILE=obs`, `$COMPOSE restart airflow-scheduler`, через 2 минуты scheduler `healthy`, в `$COMPOSE logs --since 3m airflow-scheduler` нет `gaierror`. Падает без statsd-exporter: стоп и вопрос владельцу (порядок профилей это решение). Затем `make up PROFILE=obs`.
8. `mapping.yml`, маппинги Airflow: `airflow.dagrun.duration.failed.*` в `airflow_dagrun_failed_seconds{dag_id}`, `airflow.dagrun.duration.success.*` в `airflow_dagrun_success_seconds{dag_id}`, `airflow.ti.finish.*.*.*` в `airflow_ti_finish_total{dag_id,task_id,state}`, `airflow.dag.*.*.duration` в `airflow_task_duration_seconds{dag_id,task_id}`. Имена источника сверить с фактом: после одного запуска `dq_checks` `$COMPOSE exec prometheus wget -qO- http://statsd-exporter:9102/metrics | grep -iE 'dagrun|ti_finish|duration'` (немаппленные имена statsd-exporter отдаёт с подчёркиваниями). Имя другое: маппинг пишется по факту, смысл метрики тот же.
9. Документация: OPERATIONS, «Observability»: откуда метрики Connect и Airflow; DECISIONS, ADR-023 «Observability» (источники метрик, W4-D1, W4-D2, W4-D6).

**Готово, когда.**
- Targets: 7 jobs `up` (команда W4-T01a).
- `curl -s 127.0.0.1:9090/api/v1/query --data-urlencode 'query=kafka_connect_connector_task_status{connector="shop-connector",status="running"}'`: один ряд со значением 1.
- `make connector-status`: `RUNNING`; после перезапуска `bash -c '. scripts/chaos/lib.sh && bronze_caught_up && bronze_offsets_ok'` код 0 (повторов нет, как в chaos 2a).
- `$COMPOSE exec airflow-scheduler airflow config get-value metrics statsd_on`: `True`.
- После ближайшего `dq_checks`: `curl -s 127.0.0.1:9090/api/v1/query --data-urlencode 'query=airflow_ti_finish_total{dag_id="dq_checks"}'` не пуст.
- Шаг 7 пройден: scheduler `healthy` без `obs`.
- `docker stats --no-stream lakehouse-kafka-connect-1` записан; Connect в пределах 1.5 GB.
- `docker build -t lakehouse/connect:dev docker/connect`: код 0; `make lint` зелёный.

**Ловушки.**
- Нет jar в `/kafka/libs`: `-javaagent:` получает пустой путь, JVM не стартует, CDC стоит.
- Строковый атрибут `status` JMX exporter отдаёт только через правило с меткой; без правила ряда нет, и `absent()` в W4-T05 горит всегда.
- Python-клиент statsd резолвит хост при создании клиента: без контейнера `statsd-exporter` в сети имя не резолвится (шаг 7 это проверяет).
- `airflow.env` правится Edit, не `sed -i` (хук).
- Пересоздание Connect при идущем реплее даёт окно, где события Debezium ещё в буфере; поэтому без реплея.

**Blast radius и пайплайн.** Перезапуск Connect: graceful stop, offsets в `connect-offsets`, слот `shop_slot` сохраняется; повторов не ждём (2a: 0). Нужен «ок». Перезапуск Airflow при запуске в полёте убивает задачу, поэтому ждать конца запусков. Данные lake не трогаются.

**Не входит.** Правила алертов (W4-T05), `heartbeat.action.query` (W4-D3).

### W4-T02 `spark_streaming_kafka_lag` в listener

**Зачем.** kafka-exporter не видит lag Spark: Spark хранит offsets в checkpoint, а не в consumer group (ADR-013). Без lag на дашборде не отличить «bronze догоняет» от «bronze в курсе».
**Оценка** 3 ч. **Зависит от:** W4-T01a, W4-D9, W4-D10; «ок» на перезапуск spark-bronze и порцию реплея. **Область коммита:** `stream`.

**Вход.**
- `streaming/spark_jobs/metrics.py:14-48`: три метрики, `onQueryIdle` двигает только `LAST_BATCH`; listener подключается в `bronze_cdc_ingest.py:121`.
- PySpark 3.5 `SourceProgress`: `startOffset`, `endOffset`, `latestOffset` строками JSON, `numInputRows`, `metrics` (документация 3.5.6, context7 18.10). Для Kafka это `{"oltp.shop.orders": {"0": 123, ...}}`; у первого батча `startOffset` и `latestOffset` бывают `null`.
- Bronze читает 7 топиков по 3 партиции, 21 пара topic, partition (OPERATIONS, chaos 1).

**Сделать.**
1. Первым тесты на отказ, `tests/unit/test_offsets.py`: `latestOffset` равен `"null"` или `None` (пустой результат, без исключения); невалидный JSON (пустой результат); партиция есть в `latestOffset`, нет в `endOffset` (lag от 0); `endOffset` больше `latestOffset` (0, не отрицательное); обычный случай на двух топиках.
2. `streaming/spark_jobs/offsets.py` без импорта pyspark: `kafka_lag(end_offset: str | None, latest_offset: str | None) -> dict[tuple[str, int], int]`.
3. `metrics.py`: gauge `spark_streaming_kafka_lag{query,topic,partition}`; `onQueryProgress` выставляет его по `progress.sources`; `onQueryIdle` ставит 0 всем рядам этого запроса (idle значит новых данных нет). Docstring строки 1 обновить.
4. Проверить первым на живом стеке после пересборки: во время порции lag больше 0 хотя бы на одном скрейпе. Остаётся 0 всю порцию при `BRONZE_MAX_OFFSETS_PER_TRIGGER=20000`: `latestOffset` в 3.5.9 урезан лимитом, стоп и вопрос владельцу (тогда альтернатива W4-D9).
5. Пересборка и перезапуск с «ок»: без реплея, после `bronze_caught_up`, `TRINO_XMX=2g make start` (пересобирает `lakehouse/spark:dev` и пересоздаёт `spark-bronze`).
6. Порция с «ок» `make replay-burst SECONDS=60`. В той же порции замер WAL для W4-D3 и chaos 6: `select pg_current_wal_lsn()` в `make psql` до и после, разница `pg_wal_lsn_diff` в OPERATIONS и в DECISIONS (ADR-023).
7. Документация: ADR-013 (формула lag, idle ставит 0, почему не kafka-exporter), OPERATIONS «Bronze ingest», «Check it».

**Готово, когда.**
- `make test`: новые тесты зелёные; `make test-spark` зелёный.
- `curl -s 127.0.0.1:4041/metrics | grep -c '^spark_streaming_kafka_lag'`: 21.
- Во время порции `curl -s 127.0.0.1:9090/api/v1/query --data-urlencode 'query=max_over_time(max(spark_streaming_kafka_lag)[10m:15s])'` больше 0; через 3 минуты после конца порции и `bronze_caught_up` `sum(spark_streaming_kafka_lag)` равно 0.
- Bronze после перезапуска: `bronze_offsets_ok` код 0.
- WAL одной 60-секундной порции записан числом с датой.

**Ловушки.**
- Offsets приходят строками JSON, а не словарём; `json.loads` на `"null"` даёт `None`.
- Без нуля на idle последнее значение висит вечно, и дашборд показывает lag там, где его нет.
- Пересборка `lakehouse/spark:dev` меняет образ и для `spark-silver` из DockerOperator: следующий merge идёт на новом коде; тесты silver (`make test-spark`) обязательны.
- Перезапуск bronze во время порции оставляет батч в полёте; без порции перезапуск чистый.

**Blast radius и пайплайн.** Перезапуск spark-bronze: query возобновляется с checkpoint (`Resuming at batch N`), offsets и таблицы не меняются; нужен «ок». Порция тратит около 12 виртуальных часов из W4-D10.

**Не входит.** Метрики silver job (silver живёт минуту, их место Airflow), state rows и watermark (W5-T01).

### W4-T03 Экспорт `dq_checks` в Prometheus

**Зачем.** DQ, который виден только в логе задачи, никто не смотрит. Нужны freshness по таблицам на дашборде и lag silver для `FreshnessAbove15m`.
**Оценка** 2 ч. **Зависит от:** W4-T01a, W4-D2, W4-D4, W4-D8. Параллельно W4-T02. **Область коммита:** `orchestrate`.

**Вход.**
- `airflow/dags/dq_checks.py`: строки `dq` в `silver_keys_unique` (`:45`), `silver_matches_postgres` (`:59`), `report` (`:69-74`), `dbt_source_freshness` (`:87`).
- Variable `silver_upsert_last_bronze_snapshot` хранит id последнего снапшота bronze, который смержил silver; `sql.LATEST_BRONZE_SNAPSHOT` уже читает последний снапшот.
- statsd_exporter: DogStatsD `name:value|g|#k:v,k2:v2`, TTL в маппинге (`ttl: 45m`), `0` значит «не истекает» (README 18.10).

**Сделать.**
1. Первым тесты на отказ, `tests/unit/test_dq_metrics.py`: строка gauge с тегами; отрицательное значение не отправляется (в statsd `-5|g` это уменьшение на 5, а не значение); отправка на нерезолвящийся хост печатает предупреждение и не бросает; lag равен 0, когда Variable равна последнему снапшоту; Variable нет: lag не отправляется.
2. `airflow/dags/lakehouse/metrics.py`: `gauge_line(name, value, tags) -> str`, `send(lines, host, port) -> None` по UDP, `OSError` (включая `socket.gaierror`) печатается. `Settings`: `statsd_host` (по умолчанию `statsd-exporter`), `statsd_port` (9125).
3. `sql.py`: `silver_lag_seconds` = секунд с `committed_at` самого старого снапшота `lake.bronze."cdc_events$snapshots"` новее снапшота из Variable, 0, если таких нет; `bronze_freshness` по `source_table`: `now() - max(ingest_ts)`.
4. `dq_checks`: каждая задача шлёт свои значения: `lakehouse.table_freshness_seconds` с тегами `layer:silver,table:<t>` (7) и `layer:bronze,table:<source_table>` (7); `lakehouse.silver_lag_seconds`; `lakehouse.dq.silver_duplicate_keys` с `table`; `lakehouse.dq.reconcile_tables_differing` с `at_rest`; `lakehouse.dq.lsn_repeats_last_hour`; `lakehouse.dq.noop_updates_last_hour`; `lakehouse.dq.dbt_source_freshness_exit_code`; `lakehouse.dq.last_run_timestamp_seconds`. `quarantined_last_hour` только в лог (W4-D8). Строки `dq` в логе остаются.
5. `mapping.yml`: `lakehouse.*` в `lakehouse_$1`, `lakehouse.dq.*` в `lakehouse_dq_$1`, `ttl: 45m` (три каденции).
6. Документация: OPERATIONS, «Airflow» и «Observability»: какие ряды шлёт `dq_checks`, TTL, что lag это не freshness; docstring `dq_checks.py` (строки 3-6 обещают экспорт в W4).

**Готово, когда.**
- `make test`, `make lint` зелёные.
- После ближайшего `dq_checks`: `count(lakehouse_table_freshness_seconds{layer="silver"})` 7, `{layer="bronze"}` 7; `lakehouse_silver_lag_seconds` 0 в покое (запросы через `curl -s 127.0.0.1:9090/api/v1/query --data-urlencode 'query=...'`).
- `count({__name__=~".*quarantin.*"})` пуст.
- При `make down PROFILE=obs` следующий `dq_checks` success, в логе предупреждение об отправке.
- Через 50 минут после `airflow dags pause dq_checks` ряды `lakehouse_*` пропали из `$COMPOSE exec prometheus wget -qO- http://statsd-exporter:9102/metrics`; затем `airflow dags unpause dq_checks`.

**Ловушки.**
- Знак в значении statsd-gauge это относительное изменение.
- Без TTL gauge после остановки Airflow вечно показывает последнее значение, и на дашборде «всё свежее».
- `silver_freshness_seconds` между порциями растёт часами: это «нет трафика», не поломка (W4-D4).
- UDP не подтверждает доставку: проверка только по рядам в Prometheus.

**Blast radius и пайплайн.** Нет: только чтение lake и Postgres, отправка UDP. DAG перечитывается dag-processor за минуту.

**Не входит.** Метрика карантина (Modify-гейт владельца), перевод `dq_checks` на Asset (Modify-гейт W3), reconciliation по значениям (W5-T04).

### W4-T04 Дашборды «Pipeline health» и «Infra»

**Зачем.** Одна страница, по которой ревьюер и владелец видят lag, freshness, исход batch и память, и с которой идёт гейт Read («откуда каждая панель»).
**Оценка** 3 ч. **Зависит от:** W4-T01b, W4-T02, W4-T03. **Область коммита:** `obs`.

**Сделать.**
1. `observability/grafana/dashboards/pipeline-health.json` (classic JSON, datasource `uid: prometheus`), панели и PromQL:
   - bronze lag: `sum by (topic) (spark_streaming_kafka_lag)`;
   - rows per batch и batch duration: `rate(spark_streaming_input_rows_total[5m])`, `spark_streaming_batch_duration_seconds`;
   - время с последнего батча: `time() - spark_streaming_last_batch_timestamp`;
   - коннектор и задача: `kafka_connect_connector_task_status{connector="shop-connector"}`, `debezium_*` `MilliSecondsBehindSource`;
   - удержание WAL слотом: `lakehouse_slot_retained_bytes`, `lakehouse_slot_active`;
   - lag silver и freshness: `lakehouse_silver_lag_seconds`, `lakehouse_table_freshness_seconds` по `layer`, `table`;
   - DQ: `lakehouse_dq_silver_duplicate_keys`, `lakehouse_dq_reconcile_tables_differing`, `lakehouse_dq_lsn_repeats_last_hour`, `lakehouse_dq_noop_updates_last_hour`;
   - batch Airflow: `airflow_task_duration_seconds{dag_id="silver_upsert",task_id="merge"}`, `increase(airflow_ti_finish_total{state="failed"}[1h])`, `airflow_dagrun_failed_seconds_count`;
   - активные алерты: `ALERTS{alertstate="firing"}`.
2. `infra.json`: память и лимит по контейнерам (`container_memory_usage_bytes`, `container_spec_memory_limit_bytes`), CPU (`rate(container_cpu_usage_seconds_total[5m])`), время старта (`container_start_time_seconds`), `prometheus_tsdb_head_series`.
3. `scripts/obs/check_dashboards.py`: читает оба JSON, выполняет каждое `expr` через `127.0.0.1:9090/api/v1/query`, печатает `panels ok: <n>` или пустые панели, код 1 при пустой. Тест `tests/unit/test_check_dashboards.py` на фикстуре: пустой результат даёт код 1, JSON без `targets` не роняет скрипт.
4. Скриншоты `docs/img/pipeline-health.png` и `docs/img/infra.png` снимаются во время порции W4-T05 (шаг 5), когда на панелях есть трафик, и идут в коммит W4-T05. У агента без браузера это шаг владельца: агент отдаёт URL и время.
5. Документация: OPERATIONS, «Observability»: таблица панель → метрика → источник (она же ответ на гейт Read).

**Готово, когда.**
- `uv run python scripts/obs/check_dashboards.py`: `panels ok: <n>`, код 0 (после W4-T02 и W4-T03 все ряды существуют).
- `bash -c '. scripts/chaos/lib.sh && curl -s -u "admin:$GRAFANA_ADMIN_PASSWORD" "127.0.0.1:3000/api/search?type=dash-db" | python3 -c "import json,sys; print(sorted(d[\"title\"] for d in json.load(sys.stdin)))"'`: оба дашборда.
- `make test`, `make lint` зелёные. Скриншоты в DoD W4-T05.

**Ловушки.**
- Панель с опечаткой в имени метрики показывает «No data» так же, как метрика без данных; поэтому скрипт.
- Grafana 13 умеет новый формат дашбордов; файлы в classic JSON с `schemaVersion`, иначе provisioning может их пропустить (не проверено: `$COMPOSE logs grafana | grep -i dashboard` после старта).
- Freshness обновляется раз в 15 минут: панель ступенчатая, это не баг.

**Blast radius и пайплайн.** Нет.

**Не входит.** Дашборд по gold (W6-T01).

### W4-T05 Шесть алертов и их проверка

**Зачем.** Алерт, который не срабатывал ни разу, не доказан. Каждый из шести проверяется юнит-тестом правил и живым срабатыванием.
**Оценка** 4 ч. **Зависит от:** W4-T01b, W4-T02, W4-T03, W4-D3, W4-D4, W4-D6, W4-D7; «ок» на остановку bronze и порцию реплея. **Область коммита:** `obs`.

**Вход.** Prometheus разрешает несколько правил с одним `alertname`; `promtool test rules` проверяет правила на заданных рядах; `/api/v1/alerts` отдаёт активные алерты с `state` (документация Prometheus, context7 18.10). OPERATIONS, chaos 1: без `absent()` `SparkNoBatch5m` не горит, когда driver умер и ряд пропал.

**Сделать.**
1. `observability/prometheus/alerts.yml`, группа `lakehouse`:

   | Алерт | Выражение | `for` | Доказательство |
   |---|---|---|---|
   | `ConnectorNotRunning` | `absent(kafka_connect_connector_task_status{connector="shop-connector",status="running"} == 1)` | 1m | chaos 6 (W4-T06b) |
   | `SlotWalRetainedHigh` | `(lakehouse_slot_retained_bytes{slot_name="shop_slot"} > 64 * 1024 * 1024 and on (slot_name) lakehouse_slot_active == 0) or lakehouse_slot_retained_bytes{slot_name="shop_slot"} > 512 * 1024 * 1024` | 5m | chaos 6 |
   | `SparkNoBatch5m` | правило 1: `time() - spark_streaming_last_batch_timestamp{query="bronze_cdc_ingest"} > 300`; правило 2: `absent(spark_streaming_last_batch_timestamp{query="bronze_cdc_ingest"})` | 0s и 5m | шаг 4 |
   | `FreshnessAbove15m` | `lakehouse_silver_lag_seconds > 900` | 0s | шаг 5 |
   | `AirflowDagFailed` | `increase(airflow_dagrun_failed_seconds_count[30m]) > 0 or (airflow_dagrun_failed_seconds_count unless airflow_dagrun_failed_seconds_count offset 30m)` | 0s | chaos 9 |
   | `ContainerRestarting` | `changes(container_start_time_seconds{name=~"lakehouse-.+",name!~".*-init-.*",name!~".*-bootstrap-.*",name!~".*-migrate-.*"}[15m]) > 0` | 0s | chaos 5 (W4-T06a) |

2. Первым тест правил, `observability/prometheus/alerts_test.yml`, отказные случаи: активный слот, удержание растёт на 24 MB в сутки 3 дня (`SlotWalRetainedHigh` не горит); неактивный слот с 70 MiB 6 минут (горит); `lakehouse_table_freshness_seconds` 7200 при `lakehouse_silver_lag_seconds` 0 (`FreshnessAbove15m` не горит); ряд `airflow_dagrun_failed_seconds_count` появился сразу со значением 1 (горит: первое падение после старта экспортера); ряд `spark_streaming_last_batch_timestamp` пропал (горит через 5 минут); перезапуск `lakehouse-lakekeeper-bootstrap-1` (не горит). Цель `make alerts-test`: `docker run --rm -v "$PWD/observability/prometheus:/etc/prometheus:ro" --entrypoint promtool prom/prometheus:v3.14.0 test rules /etc/prometheus/alerts_test.yml`.
3. `lib.sh`: `alert_firing <name> <seconds>` и `alerts_in_window <seconds>` по W4-D7. Перечитать правила: `docker kill -s HUP $($COMPOSE ps -q prometheus)`.
4. `SparkNoBatch5m` с «ок»: без реплея, `$COMPOSE stop spark-bronze`, `alert_firing SparkNoBatch5m 600`, `$COMPOSE start spark-bronze`, `bronze_caught_up`. Время до срабатывания в OPERATIONS.
5. `FreshnessAbove15m` с «ок»: `airflow dags pause silver_upsert`, `make replay-burst SECONDS=60`, `alert_firing FreshnessAbove15m 2400` (15 минут порога плюс до 15 минут каденции), `airflow dags unpause silver_upsert`, алерт гаснет после следующего `dq_checks`.
6. `AirflowDagFailed`: `make chaos-break-dbt-test`, затем `alert_firing AirflowDagFailed 120`.
7. Документация: OPERATIONS, «Observability»: таблица алертов (выражение, порог, почему порог такой, сценарий, время до срабатывания); строки «What monitoring shows» у chaos 1, 2b, 9 обновить фактом; раннбуки `docs/runbooks/slot-wal-growth.md` и `freshness.md` (обещаны в OPERATIONS, «Runbooks»); ADR-023 дополняется порогами W4-D3 и W4-D4.

**Готово, когда.**
- `make alerts-test`: `SUCCESS`; `promtool check rules` там же без ошибок.
- `curl -s 127.0.0.1:9090/api/v1/rules | python3 -c 'import json,sys; print(sorted({r["name"] for g in json.load(sys.stdin)["data"]["groups"] for r in g["rules"]}))'`: шесть имён.
- В покое (`core+query+orchestrate+obs`, без порции) `curl -s 127.0.0.1:9090/api/v1/alerts` без `firing` 30 минут.
- Шаги 4, 5, 6 печатают `alert <name> firing after <n> s`; числа в OPERATIONS.
- `ls docs/img/pipeline-health.png docs/img/infra.png`: оба файла (шаг 4 W4-T04).

**Ловушки.**
- `increase()` не видит первое значение нового ряда счётчика: первое падение DAG после старта statsd-exporter без второй половины выражения не горит (это тест шага 2).
- `absent()` горит и тогда, когда выключен источник: `ConnectorNotRunning` и `SparkNoBatch5m` горят при `obs` без `core`. Это записывается, не лечится.
- `lakekeeper-bootstrap`, `lakekeeper-migrate` и `minio-init` это одноразовые контейнеры, они перезапускаются на каждом `make start`; без исключения в выражении `ContainerRestarting` горит на каждом старте.
- Пауза `silver_upsert` в шаге 5 оставляет silver позади, пока DAG не снят с паузы; `trap EXIT` в команде шага снимает паузу.

**Blast radius и пайплайн.** Шаг 4 останавливает bronze на 10 минут: Kafka держит данные 24 ч, после старта query догоняет с checkpoint. Шаг 5 тратит 12 виртуальных часов. Оба с «ок».

**Не входит.** Доставка алертов (W4-D6), алерт карантина (Modify-гейт).

### W4-T06a Chaos 5 (Postgres restart) и chaos 8 (Kafka down)

**Зачем.** Два отказа звеньев, на которых стоит CDC. Ответ системы должен быть измерен, а не описан.
**Оценка** 4 ч. **Зависит от:** W4-T05, W4-D7, W4-D10, W4-D12; «ок» на каждый прогон. **Область коммита:** `cdc`.

**Вход.**
- `lib.sh`: `no_other_replayer`, `replay_burst`, `bronze_caught_up`, `bronze_offsets_ok`, `connector_running`, `slot_reattached`, `reconcile`, `run_dag`; вызывать, не переписывать.
- Как задача Debezium переживает рестарт Postgres (повтор подключения или FAILED) и как Spark и Connect переживают остановку Kafka на 6 минут, не проверено: это и есть результат сценариев. Ожидания ниже это гипотезы.

**Сделать.**
1. Первым `merge_silver` по W4-D12 и отказ `make silver` при запущенном scheduler; тест: `bash -c '. scripts/chaos/lib.sh && type merge_silver'` и `make silver` при запущенном scheduler печатает отказ, код 2. Все вызовы `run_silver` в `scripts/chaos/*.sh` на `merge_silver`.
2. `scripts/chaos/postgres-restart.sh` (`make chaos-postgres-restart`): `no_other_replayer`, `connector_running`, `bronze_caught_up`; запомнить `confirmed_flush_lsn` слота; `$COMPOSE restart postgres-oltp`; ждать `healthy`; ждать `connector_running` до 300 с, иначе код 1 с именем раннбука `docs/runbooks/connector-failed.md` (это ответ сценария, а не повод чинить конфиг); `replay_burst 30`; `bronze_caught_up`, `bronze_offsets_ok`, `merge_silver`, `reconcile`; `alert_firing ContainerRestarting 180`; `alerts_in_window`. Печатает времена: рестарт, коннектор снова RUNNING, первый батч bronze после него.
3. `scripts/chaos/kafka-down.sh` (`make chaos-kafka-down`): предусловия как в шаге 2; `replay_burst 120` в фоне; через 30 с `$COMPOSE stop kafka`; 6 минут простоя; `$COMPOSE start kafka`; ждать `healthy`, `connector_running` до 300 с; `bronze_caught_up` до 900 с; `bronze_offsets_ok`, `merge_silver`, `reconcile`; `alerts_in_window` печатает, что горело (гипотеза: `SparkNoBatch5m`, `ContainerRestarting` у spark-bronze, `ConnectorNotRunning`). Падает только на проверках данных, набор алертов записывается как факт.
4. Документация: OPERATIONS, сценарии 5 и 8 по шаблону из пяти ответов с числами прогона; статус в таблице сценариев.

**Готово, когда.**
- `make chaos-postgres-restart`: код 0, `ok`, `ContainerRestarting` firing, `reconcile` 7 из 7 ok.
- `make chaos-kafka-down`: код 0, каждый offset Kafka в bronze ровно один раз, `reconcile` ok, список сработавших алертов и времена в OPERATIONS.
- Существующие сценарии с `merge_silver` не сломаны: `make chaos-poison-event` при запущенном scheduler код 0.
- `make lint`, `make test` зелёные.

**Ловушки.**
- Реплеер на хосте пишет в Postgres: рестарт Postgres во время порции роняет реплеер, `replay_burst` вернёт не 124. Поэтому в chaos 5 порция после рестарта.
- Задача Debezium в FAILED не поднимается сама; скрипт не делает `POST .../restart` молча, иначе сценарий спрячет ответ системы.
- Spark при недоступной Kafka может упасть и уйти в цикл рестартов Docker; checkpoint это переживает (chaos 1), но `RestartCount` растёт: это видно в Infra.
- Kafka стоит 6 минут, retention 24 ч: потерь нет. Простой дольше 24 ч с `failOnDataLoss=true` (`bronze_cdc_ingest.py:134`) это другой сценарий (раздел 7).
- `merge_silver` при паузе `silver_upsert` ставит запуск в очередь навсегда: `run_dag` не снимает паузу (`lib.sh:188-190`), таймаут `RUN_DAG_WAIT`.

**Blast radius и пайплайн.** Рестарт Postgres и остановка Kafka без удаления томов; слот и offsets сохраняются. Порции: 6 ч и 24 ч виртуального времени. Silver пишет только Airflow. Каждый прогон с «ок».

**Не входит.** Правка конфигов Postgres и коннектора по итогам (решение владельца, раздел 7).

### W4-T06b Chaos 6 (коннектор мёртв 30 минут), chaos 7 и OPERATIONS по всем сценариям

**Зачем.** Chaos 6 это главный сценарий наблюдаемости CDC: слот держит WAL, пока потребителя нет, и диск источника заканчивается молча. После него в OPERATIONS 8 обязательных сценариев по пяти ответам.
**Оценка** 4 ч. **Зависит от:** W4-T06a, W4-D3, W4-D8, W4-D11; WAL порции из W4-T02; «ок» на прогон. **Область коммита:** `cdc`.

**Сделать.**
1. `scripts/chaos/connect-pause.sh` (`make chaos-connect-pause`): предусловия как в W4-T06a; `trap` на `EXIT` с `curl -sf -X PUT 127.0.0.1:8083/connectors/shop-connector/resume`; `curl -sf -X PUT .../stop`; проверить первым: через 30 с `select active from pg_replication_slots where slot_name = 'shop_slot'` равно `f` (не `f`: стоп, W4-D11 пересматривается); `alert_firing ConnectorNotRunning 180`; порции `replay_burst` числом секунд, которое по замеру W4-T02 даёт больше 64 MiB WAL (около 120 с при 35 MB на 60 с, вывод); `alert_firing SlotWalRetainedHigh 900`; держать остановленным до 30 минут от `stop`; `resume`; `slot_reattached`, `bronze_caught_up`, `bronze_offsets_ok`, `merge_silver`, `reconcile`; удержание слота после догона меньше 64 MiB; `alerts_in_window`.
2. Chaos 7: OPERATIONS по пяти ответам; «What monitoring shows»: `lakehouse_dq_*` без карантина, строка `dq quarantined_last_hour` в логе `dq_checks`, алерт это Modify-гейт владельца (W4-D8).
3. OPERATIONS: таблица сценариев (статусы 5-8, сценарий 10 optional остаётся planned); у всех сценариев «What monitoring shows» с именами алертов и временем до срабатывания; раннбук `slot-wal-growth.md` ссылается на chaos 6.
4. Исправить расхождения из роадмапа: в `02-learning-gates.md` Operate-гейт observability называет dbt test сценарием 8, по таблице это 9; в `00-mini-architecture-review.md` §8 у сценария 7 «алерт по `quarantine_rows`» по W4-D8, у сценария 6 команда и порог по W4-D3 и W4-D11.

**Готово, когда.**
- `make chaos-connect-pause`: код 0; `ConnectorNotRunning` и `SlotWalRetainedHigh` firing, оба времени в OPERATIONS; после `resume` коннектор RUNNING, `reconcile` ok, каждый offset в bronze ровно один раз.
- Скрипт, убитый `kill -INT` посреди простоя, оставляет коннектор RUNNING (`make connector-status`).
- `grep -cE '^### (1|2a|2b|3|4|5|6|7|8|9)\. ' OPERATIONS.md`: 10; `grep -c '^Why no loss or duplication:' OPERATIONS.md`: 11 (шаблон и 10 сценариев; 18.10 это 7).
- `make lint`, `make test` зелёные.

**Ловушки.**
- `pause` вместо `stop` держит слот активным, и W4-D3 не горит.
- STOPPED хранится в `connect-configs`: без `trap` упавший скрипт оставляет CDC остановленным и после рестарта Connect.
- `max_slot_wal_keep_size = -1` (HANDOFF, проверки 17.10): Postgres держит WAL без предела, место на диске VM заканчивается раньше, чем что-то упадёт.
- Догон после 30 минут простоя большой: `bronze_caught_up` с таймаутом 900 с, как `VERIFY_WAIT`.

**Blast radius и пайплайн.** Коннектор остановлен до 30 минут, слот держит WAL (десятки MB по замеру); данные не теряются, пока слот жив. Порции до 36 ч виртуального времени. С «ок».

**Не входит.** `heartbeat.action.query` (альтернатива W4-D3, отдельный ADR), алерт карантина.

### W4-T07 Гейт observability (владелец)

По `02-learning-gates.md`, ответы в `LEARNING.md`. Operate: chaos 6 и chaos 9 с алертами и временем до срабатывания. Modify: `quarantine_rows_total` и алерт на неё, проверка chaos 7; исполнитель даёт файлы (`airflow/dags/dq_checks.py`, задача `report`, где уже считается `quarantined_last_hour`; `airflow/dags/lakehouse/metrics.py` из W4-T03; `observability/prometheus/alerts.yml`) и подсказку (счётчик против gauge за час, как алерт переживёт TTL), не код.

## 5. Порядок и коммиты

| # | Задача | Область | Зависит от |
|---|---|---|---|
| 1 | W4-T01a профиль `obs` | `obs` | W4-D5 |
| 2 | W4-T01b JMX Connect, StatsD Airflow | `obs` | 1, W4-D1 |
| 3 | W4-T02 lag в listener, замер WAL порции | `stream` | 1, W4-D9, W4-D10 |
| 4 | W4-T03 экспорт `dq_checks` | `orchestrate` | 1, W4-D2, W4-D4, W4-D8; параллельно 3 |
| 5 | W4-T04 дашборды | `obs` | 2, 3, 4 |
| 6 | W4-T05 алерты | `obs` | 2, 3, 4, W4-D3, W4-D6, W4-D7 |
| 7 | W4-T06a chaos 5, 8, `merge_silver` | `cdc` | 6, W4-D12 |
| 8 | W4-T06b chaos 6, 7, OPERATIONS | `cdc` | 7, W4-D11 |
| 9 | HANDOFF, итоги W4, потраченный бюджет реплея, `docker stats` | `docs` | все |

Сумма оценок 27 ч против 20 ч роадмапа. Если неделя не влезает, первым режется W4-T04 до одного дашборда, а не алерты и сценарии.

## 6. Проверки для каждой задачи

- `make lint`, `make test`; для `stream` ещё `make test-spark`; для compose `$COMPOSE --profile '*' config -q` и `$COMPOSE --profile obs config -q`; для правил `make alerts-test`.
- Первый тест на отказ: отсутствующий offset, отрицательный gauge, нерезолвящийся statsd-хост, первое падение DAG, простой с растущим WAL при живом слоте.
- Живой старт, а не только `config`: targets `up`, ряды существуют, `find observability -type d -name '*.y*ml'` пусто.
- Влияние на checkpoint, слот, offsets, реплей и DAG пишется явно; перезапуск звена `core` и порция реплея только с «ок».
- Полный `make verify` перед коммитом при остановленном scheduler (раздел 3).
- Ревью диффа по разделу «Плагины агента» в `docs/agent-rules.md`, коммит после «ок» владельца.

## 7. Замечено и не входит в W4

Кандидаты на решение владельца:

- `heartbeat.action.query` (альтернатива W4-D3). Факты 18.10: при простое `shop` `confirmed_flush_lsn` слота отстаёт от `pg_current_wal_lsn()`, хвост WAL пишут PRUNE_ON_ACCESS на `shop.orders`, autoanalyze (`pg_statistic`), checkpoint и записи `replay.*`, удержание 24 MB (аудит 18.10, перепроверка: `select pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)), active from pg_replication_slots` в `make psql`). Debezium 3.5 советует для малонагруженной БД таблицу и `heartbeat.action.query` с INSERT в неё (документация коннектора PostgreSQL, раздел WAL disk space consumption).
- Retention Kafka 24 ч против `failOnDataLoss=true`: простой bronze дольше суток даёт цикл рестартов (HANDOFF, открытые вопросы 17.10). `ContainerRestarting` его покажет, но решения о выходе нет; ADR-003 есть только строкой индекса.
- Скрейп Trino, Lakekeeper и реплеера (обещан в `observability/README.md`). Реплеер играет с хоста на `127.0.0.1:8000`, из сети `lake` не виден; Trino и Lakekeeper не в DoD роадмапа. Решить до W6 или убрать из README.
- Trino на 95% лимита контейнера (3.341 GiB из 3.5 GiB при `-Xmx2g`, 18.10) и minio на 81%: по замеру NMT 0.55 GiB RSS были аренами glibc malloc вне учёта JVM; D20 W3 (`MALLOC_ARENA_MAX=4`) снял около 0.27 GiB, лимиты решает замер W4-D5.
- JMX exporter 1.7.0 вышел 05.10.2026; переход с 1.6.0 после двух недель без проблем.
- Метрики Debezium (`MilliSecondsBehindSource`) как второй lag CDC, кроме удержания слота: панель есть в W4-T04, алерт не ставится.
- Pushgateway и Alertmanager остаются за ADR (W4-D2, W4-D6).
