# OB. Наблюдаемость и эксплуатация

Аудит 13.11.2026, HEAD `a8c1d49` плюс незакоммиченные правки владельца (не тронуты). Только чтение:
файлы, `git`, GET к Prometheus `127.0.0.1:9090`, `docker ps`, `docker logs --tail/--since`,
`docker stats --no-stream`, `docker inspect -f` (без Env), `scripts/obs/check_dashboards.py` (только
запросы чтения в Prometheus и Trino как `grafana`). Chaos, реплей, `make alerts-test` не запускались.
Копии и выводы проб: `<scratchpad>/audit/OB-work/`
(`rules.json`, `alerts.json`, `targets.json`, `runtime.json`, `ops_headers.txt`, `ops_refs.txt`,
`check_md_links.py`).

## Оценки

- SRE: 3 из 5. Правила алертов сильные и протестированы, восстановление доказано числами, но у 7 из 13
  алертов нет ранбука, `AirflowDagFailed` ложно срабатывает после сна хоста, а 138 KB OPERATIONS без
  оглавления не годятся дежурному.
- Платформа, DevOps (наблюдаемость как код): 4 из 5. Provisioning, закреплённые образы, свой
  container-exporter с тестами, `check_dashboards.py`; минус: имя проекта в правилах и дашборде Infra.
- QA (тесты правил): 4 из 5. 25 групп promtool, сначала отказные случаи, края TTL и дыр скрейпа; нет
  кейсов на другое имя проекта, на one-shot `-init-`/`-migrate-`, на контейнер merge и на дыру скрейпа
  у `AirflowDagFailed`.
- Тимлид, нанимающий: 4 из 5. Время срабатывания и сценарии записаны числами с датами
  (`docs/evidence.md:123-150`, `:63-85`); мешает вес OPERATIONS.
- Новый инженер: 2 из 5. OPERATIONS 1794 строки без оглавления, журнал сценариев и заметки к коммитам
  вперемешку с процедурами.
- Руководитель: 3 из 5. Честно названы пределы («Nothing watches the watcher», `OPERATIONS.md:830-833`;
  Backup без RPO/RTO, `:1775`), но SLO не сформулированы.

## Сильные стороны

- Отказные случаи promtool первыми и края времени: TTL statsd и передача `stale` -> `gone` без дыры
  (`observability/prometheus/alerts_test.yml:557-589`), дыра скрейпа как после сна
  (`:440-465`), короткая история серии (`:390-408`), всего 25 групп, 39 ожиданий «не срабатывает».
- Тихий источник не равен «всё спокойно»: у каждого gauge-алерта есть близнец `absent()` или
  `last_over_time` (`observability/prometheus/alerts.yml:47-53,70-78,84-94`), причина каждого порога
  записана (`OPERATIONS.md:835-851`, колонка «Why this threshold»).
- Живые срабатывания с временем: 7 алертов показаны вживую, `SparkRestartLoop` на сохранённых данных
  (`docs/evidence.md:130-140`); живой Prometheus сейчас: 16 правил, все `health: ok`, 8 из 8 targets up
  (GET `/api/v1/rules`, `/api/v1/targets`, 13.11 18:30 UTC).
- Восстановление доказано числами: 11 сценариев с датами, скрипты выходят с 1 на неубедительном
  результате (`OPERATIONS.md:1305-1310`, `scripts/chaos/spark-kill.sh`), сводка в
  `docs/evidence.md:69-81`.
- Проверка дашбордов исполнением: `uv run --no-sync python scripts/obs/check_dashboards.py` 13.11:
  `queries ok: 32`, 7 `idle:` панелей Spark, rc 0; отличает простой от опечатки.
- Свой container-exporter вместо cAdvisor с фильтром проекта и падением скрейпа на пустом списке
  (`observability/container-exporter/container_exporter/collector.py:50-97`, ADR-023).

## Старый бэклог

| ID | статус сейчас (file:line или коммит) | делать / не делать | причина |
|---|---|---|---|
| R-04 (алерты) | открыт: `observability/prometheus/alerts.yml:58` `name="lakehouse-spark-bronze-1"`, `:156-157` `name=~"lakehouse-.+"`; плюс `observability/grafana/dashboards/infra.json:43,76,109,142,175,208,241` | делать (OB-02) | при другом `COMPOSE_PROJECT_NAME` молчит page-алерт и пуст дашборд Infra |
| R-04 (chaos) | открыт: `scripts/chaos/spark-kill.sh:6`, `late.sh:14-15`, `connect-restart.sh:9` | делать в области IN | скрипты не мои; в `lib.sh:156-159` уже есть `service_healthy` через `compose ps -q` |
| R-03 | открыт: `scripts/chaos/lib.sh:318` `state=$(dag_run_state ...)` без `\|\| state=unknown` | делать в области IN | скрипты не мои |
| R-63 | открыт: `OPERATIONS.md` 137 688 байт, 1794 строки, оглавления нет (`wc -c`, `ops_headers.txt`) | делать (OB-04) | главный документ дежурного нечитаем |
| R-67 | открыт: у 7 из 13 нет ранбука, `annotations` ни у одного правила (live `/api/v1/rules`: `ann= {}` у всех 16) | делать (OB-03) | см. таблицу алертов ниже |
| R-66 (часть OB) | открыт: `alerts.yml:1-3,18,62,97,110-111,116,124-125` (W4-T05, W6-T05, B3, W4-D3, W4-D4, W6-D9, DATA-02, B6, F-01); `pipeline-health.json:676` (W5-T04); `scripts/obs/check_dashboards.py:1` (W4-T04, W6-T01); `observability/statsd/mapping.yml:3,24` (W4-T03); `observability/postgres-exporter/queries.yaml:2` (W4-D3) | делать вместе с OB-03 | те же файлы правятся; ID карточек видит внешний читатель |
| PF-01 | закрыт: `/api/v1/rules` 16 правил, `GoldStaleAtRest` есть; `runtimeinfo` `reloadConfigSuccess: true` | закрыто | |
| PF-24 | частично: `OPERATIONS.md:849` говорит «while nothing is in flight», но не называет молчание под непрерывной нагрузкой | делать (OB-05) | одна фраза |
| PF-25 | открыт: строки о порядке старта после рестарта Docker нет (`grep -n -i "docker restart" OPERATIONS.md`) | делать (OB-03, ранбук containers) | объясняет `ContainerRestarting` после рестарта Docker |
| PF-27 | открыт: `observability/README.md:14-16` «Names it does not map ... `lakehouse.dq.gold_stale_runs` becomes» против `observability/statsd/mapping.yml:26-28` (`lakehouse.dq.*`, ttl 45m) | делать (OB-05) | ложное утверждение |
| PF-30 | открыт: в `OPERATIONS.md:1768-1794` нет «checkpoint восстанавливать только вместе с каталогом» | делать (OB-05) | строка в Backup |
| PF-54 | открыт: `OPERATIONS.md:798-801` только о томе `/kafka/config` | делать (OB-05) | строка; чистка только по «ок» |
| PF-16 | открыт: `OPERATIONS.md:1220-1225` «Not covered» без CVE-сканирования | делать в области IN | одна строка в том же списке |
| PF-65 | открыт: `tests/unit/test_container_exporter.py:261` сокет в `tmp_path` | делать (OB-09), можно отдать QA | дешёвая правка с ясной проверкой |
| PF-26 | `scripts/report.sh` | область HS | |
| спека 14, разд. 7, п. 36 (кейсы promtool `-init-`, `-migrate-`) | открыт: в `alerts_test.yml:280-293` только `lakekeeper-bootstrap` | делать (OB-02) | те же правила переписываются |
| спека 14, разд. 7, описание панели слота | открыт: `pipeline-health.json:225` называет только `SlotWalRetainedHigh` | делать (OB-06) | дёшево |
| спека 14, разд. 7, точка `13m` у `SlotWalHeldIdle` | открыт: `alerts_test.yml:86-88` тривиальна | не делать | мутации ловят точки 73m и 118m |
| Б10 (живые: потеря checkpoint на копии, MinIO при записи, миграция 003) | kill silver закрыт (`50659c5`, сценарий 10b); остальное: решения владельца 04.11, записано в `docs/evidence.md:271-285` | не делать | разрушительно или бюджет реплея, читатель видит честное «Not proven yet» |
| Б19 | закрыт `a3a56f8`; 13.11 `check_dashboards.py` rc 0, 7 idle | закрыто | |
| F-27 | = PF-25 | делать (OB-03) | |
| HANDOFF 10.11: «Grafana на 512M проверить через сутки» | `max_over_time(docker_container_memory_usage_bytes{service="grafana"}[3d])` = 439.7 MiB из 512; `docker stats` 391.7 MiB; `docker_container_oom_killed` 0 у всех | не делать | OOM нет; swap внутри cgroup не проверен (нужен `docker exec`, вне правил аудита) |

## Таблица алертов (дерево HEAD, живой Prometheus 13.11)

| Алерт | Условие, `for`, severity | Ранбук сейчас | Тест promtool | Живое доказательство | Дыра |
|---|---|---|---|---|---|
| ConnectorNotRunning | `absent(task_status{running}==1)`, 1m, page (`alerts.yml:11-15`) | `connector-failed.md` (заголовок про FAILED, имя алерта только в п. 3) | 2 точки, `alerts_test.yml:295-308` | сценарий 6, 95 с | нет кейса FAILED при живом Connect |
| SlotWalRetainedHigh | >64 MiB и неактивен, или >512 MiB; 5m, page (`:19-26`) | `slot-wal-growth.md` | 4 (`:8-51`) | сценарий 6, 326 с | |
| SlotWalHeldIdle | min за 1ч >64 MiB, ≥200 точек, активен, ≤512 MiB; warn (`:32-39`) | `slot-wal-growth.md` | 9 (`:53-131`) | нет | |
| SparkNoBatch5m (stuck, gone) | `time()-ts>300` без `for`; `absent()` 5m; page (`:42-53`) | `spark-stalled.md` | 4 (`:172-201`) | gone 315 с | stuck без `for` мигает после сна (OB-07) |
| SparkRestartLoop | `changes(start_time{name="lakehouse-spark-bronze-1"}[10m])>2`, page (`:57-60`) | `spark-stalled.md` п. 2 | 5 (`:203-278`) | ретро на данных сценария 8 | имя проекта (OB-02) |
| FreshnessAbove15m (lag, unknown) | `last_over_time(lag[1h])>900`; `absent(lag)` 15m; warn (`:66-78`) | `freshness.md` | 7 | 1561 с | `cause=unknown` в ранбуке не разобран |
| DqChecksStale (stale, gone) | возраст отметки >1800; `absent()` 15m; warn (`:84-94`) | нет | 6 | нет | ранбук |
| CdcStalledSourceWrites | min за 20m ==1, ≥70 точек; warn (`:103-108`) | нет | 11 | сценарий 6, 29.10 | ранбук |
| SilverGoldNotCompared | `last_over_time(...[1h])>=24`; warn (`:119-122`) | нет | 13 | нет | ранбук |
| GoldStaleAtRest | `last_over_time(...[1h])>=2`; warn (`:130-133`) | нет (абзац `OPERATIONS.md:637-645`) | 5 | нет | ранбук; нет кейса «серия ушла» |
| ScrapeTargetDown | `up{job!="spark-orders-per-minute"}==0`, 2m, warn (`:137-141`) | нет (абзац `OPERATIONS.md:808-811`) | 2 | нет | ранбук |
| AirflowDagFailed | `increase(...[30m])>0 or (X unless X offset 30m)`, warn (`:145-150`) | нет (абзац `OPERATIONS.md:703-716` только про `dq_checks`) | 2 | сценарий 9, 17 с | ложное срабатывание после сна (OB-01); ранбук |
| ContainerRestarting | `changes(start_time{name=~"lakehouse-.+", не init/bootstrap/migrate}[15m])>0`, warn (`:154-158`) | нет | 2 | сценарии 5, 8, 10b | имя проекта; контейнер merge (OB-02); ранбук |

Живые срабатывания за 7 дней (`count_over_time(ALERTS{alertstate="firing"}[7d])`): `ContainerRestarting`
по 58-91 вычислению у 12 контейнеров и 471 у `airflow-scheduler` (циклы verify останавливают
scheduler); `AirflowDagFailed` по 240 у трёх DAG; одиночные вспышки `ConnectorNotRunning`,
`DqChecksStale`, `FreshnessAbove15m{cause="unknown"}`, `SparkNoBatch5m{cause="stuck"}` ровно на первом
вычислении после дыр скрейпа (11-10 13:32:19, 11-12 12:38:34, 11-13 08:48, 13:48, 18:12; сырые точки
`ALERTS{...}[7d]`). Сейчас горит `ContainerRestarting` по `lakehouse-spark-orders-per-minute-1`:
после сна хоста 17:38-18:12 UTC драйвер потерял heartbeat (`docker logs`: «no recent heartbeats:
2066229 ms», 18:12:47) и перезапущен политикой в 18:22:55 (`RestartCount` 1). Алерт верен, ранбука нет.

## SLI и пороги

| Что | Метрика | Порог и алерт | Обоснование |
|---|---|---|---|
| Свежесть bronze к Kafka | `spark_streaming_kafka_lag`, `time()-spark_streaming_last_batch_timestamp` | 300 с без батча, `SparkNoBatch5m`; на лаг алерта нет | `alerts.yml:41`; лаг 0 в покое (`OPERATIONS.md:189-192`) |
| Свежесть silver к bronze | `lakehouse_silver_lag_seconds` | 900 с, `FreshnessAbove15m` | `OPERATIONS.md:840`; каденция `dq_checks` 15 мин даёт до 1561 с |
| Свежесть gold к silver | `lakehouse_dq_gold_stale_runs`, `..._gold_not_compared_runs` | 2 прогона в покое; 24 прогона | `alerts.yml:110-129`; метрики «возраст gold» нет |
| Свежесть таблиц | `lakehouse_table_freshness_seconds` | без алерта по замыслу | «no traffic, not a fault», `OPERATIONS.md:750` |
| CDC | `kafka_connect_connector_task_status`, `lakehouse_dq_cdc_stalled` | 1m; 20 мин | `OPERATIONS.md:837,845` |
| Слот | `lakehouse_slot_retained_bytes`, `lakehouse_slot_active` | 64 MiB неактивен, 512 MiB всегда; 64 MiB час на активном | `alerts.yml:17-31`: здоровый слот держит около 25 MB |

Вывод: SLI измеряются, пороги обоснованы в комментариях правил и в таблице OPERATIONS, но SLO (цель и
окно) нигде не записаны, а лаг Kafka и «возраст gold» без алерта. Это строка в OPERATIONS (OB-04,
раздел SLI), не новые правила.

## Находки «делать»

### OB-01 [средняя] `AirflowDagFailed` ложно горит 25-30 минут после каждой дыры скрейпа длиннее 5 минут

Где: `observability/prometheus/alerts.yml:143-150`
Факт: `ALERTS{alertname="AirflowDagFailed"}` горел 11-10 13:35-14:00 и 11-12 12:40-13:05 UTC сразу по
трём DAG (`dq_checks`, `iceberg_maintenance`, `silver_upsert`); счётчики
`airflow_dagrun_failed_seconds_count` в это время стояли на 4, 1, 3 без роста (`query_range` 11-12
11:30-13:30), а перед окнами дыры данных (`count(up)`: 11-07 04:43 -> 11-10 13:32, 11-10 21:36 -> 11-12
12:38). Вторая половина `X unless X offset 30m` после дыры истинна для каждого старого счётчика.
Чем плохо: после сна ноутбука дежурный видит «DAG failed» по трём DAG, которые не падали; ложный
красный подрывает доверие к алерту.
Правка: тест на отказ первым в `alerts_test.yml`: серия `airflow_dagrun_failed_seconds_count{dag_id="dq_checks",instance="statsd-exporter:9102",job="statsd-exporter"}` `3x10 _x40 3x20` и
`up{instance="statsd-exporter:9102",job="statsd-exporter"}` `1x10 _x40 1x20`, `eval_time: 55m`,
`exp_alerts: []` (красный на HEAD). Затем вторая половина правила:
`(airflow_dagrun_failed_seconds_count unless airflow_dagrun_failed_seconds_count offset 30m) and on (instance) up{job="statsd-exporter"} offset 30m`
(скобки обязательны: `and` связывает сильнее `or`). Существующий кейс `:156-170` переписать так,
чтобы у `up` была история 30 минут: `up` `1x40`, счётчик `_x30 1x10`, `eval_time: 33m` firing,
`3m` без алерта. Комментарий правила: первая ошибка в первые 30 минут после старта Prometheus не
ловится, это принятая цена. Строку `OPERATIONS.md:841` поправить.
Проверка: `make alerts-test` -> `SUCCESS`; на HEAD новый кейс падает (`FAILED: ... AirflowDagFailed`).
После коммита `docker exec lakehouse-prometheus-1 kill -HUP 1` и `curl -s 127.0.0.1:9090/api/v1/rules | grep -c 'offset 30m'`.
Размер: S; класс B (код правил), перечитать правила на стенде C; «ок» на HUP.
Старый ID: нет

### OB-02 [средняя] Правила контейнеров зависят от имени проекта, а `ContainerRestarting` ловит контейнер merge

Где: `observability/prometheus/alerts.yml:57-60,152-158`; `observability/grafana/dashboards/infra.json:43,76,109,142,175,208,241`; `observability/prometheus/alerts_test.yml:203-293`
Факт: (1) `SparkRestartLoop` на `name="lakehouse-spark-bronze-1"`, `ContainerRestarting` на
`name=~"lakehouse-.+"`; exporter и так отдаёт только контейнеры проекта
(`collector.py:50-56`). (2) Образ `lakehouse/spark:dev` несёт метки
`com.docker.compose.project=lakehouse`, `com.docker.compose.service=spark-bronze`
(`docker image inspect lakehouse/spark:dev --format '{{json .Config.Labels}}'`), поэтому контейнер
merge (`container_name="lakehouse-silver-merge"`, `airflow/dags/silver_upsert.py:56`), запуски
`make test-spark` и `spark-silver run` попадают в метрики: за 7 дней серии `cool_morse`,
`fervent_ramanujan` и др. с `service="spark-bronze"`, шесть `lakehouse-spark-silver-run-<hex>`
(`count by (name, service) (last_over_time(docker_container_start_time_seconds{name!~"lakehouse-.+-[0-9]+"}[7d]))`).
Значит, замена на один `service="spark-bronze"` (рецепт R-04) дала бы ложный page на каждые три
merge за 10 минут. (3) `lakehouse-silver-merge` уже совпадает с `ContainerRestarting`: два merge с
одним именем в 15 минут дают `changes() = 1`; так алерт и сработал в 10b (`OPERATIONS.md:1731-1733`:
вторая попытка завела контейнер с тем же именем). Вывод: при непрерывном реплее (merge раз в 5 минут)
он горит постоянно. Гипотеза в части «непрерывный реплей»: живьём за 7 дней merge не было; проверит
кейс promtool ниже.
Чем плохо: при `COMPOSE_PROJECT_NAME=lakehouse-fresh` (так идёт smoke, `scripts/chaos/lib.sh:154`) или
любом другом молчит page `SparkRestartLoop`, пусты 7 панелей Infra; под нагрузкой `ContainerRestarting`
шумит и теряет смысл.
Правка: тесты на отказ первыми в `alerts_test.yml`: (а) `SparkRestartLoop` по
`{name="shop-spark-bronze-1",service="spark-bronze"}` `1+1x15` с шагом 20s firing на 5m; (б)
`ContainerRestarting` по `{name="shop-kafka-1",service="kafka"}` `100 100 200 200` firing; (в) три
merge `{name="lakehouse-silver-merge",service="spark-bronze"}` `100 100 stale 200 200 stale 300 300`
на шагах 1m: ни `SparkRestartLoop`, ни `ContainerRestarting`; (г) one-shot
`shop-minio-init-1`/`minio-init`, `shop-lakekeeper-migrate-1`/`lakekeeper-migrate`,
`shop-superset-init-1`/`superset-init` перезапущены: без алерта. Затем выражения:
`changes(docker_container_start_time_seconds{service="spark-bronze", name=~".+-spark-bronze-[0-9]+"}[10m]) > 2`
и
`changes(docker_container_start_time_seconds{name=~".+-[0-9]+", service!~"minio-init|lakekeeper-migrate|lakekeeper-bootstrap|superset-init"}[15m]) > 0`
(имя compose `<проект>-<сервис>-<n>`, у merge и `run`-контейнеров последний сегмент не число). В
`infra.json` убрать `{name=~"lakehouse-.+"}` из 7 выражений. В новом `tests/unit/test_alerts.py`
тест: ни правило, ни выражение дашбордов не содержит `lakehouse-`. Обновить `spark-stalled.md:15`
(«more than two starts of `lakehouse-spark-bronze-1`») и строку 10b в сценариях (merge больше не
даёт `ContainerRestarting`; повтор виден в Airflow, `try_number`).
Проверка: `make alerts-test` -> `SUCCESS: 16 rules found` и все кейсы; на HEAD кейсы (а), (б), (в)
красные; `uv run pytest tests/unit/test_alerts.py -q`; `uv run --no-sync python scripts/obs/check_dashboards.py` -> `queries ok: 32`, rc 0.
Размер: M; класс B, HUP C.
Старый ID: R-04 (алерты), спека 14 разд. 7 п. 36

### OB-03 [средняя] 7 из 13 алертов без ранбука, ни одного `annotations`

Где: `observability/prometheus/alerts.yml` (все 16 правил без `annotations`); `docs/runbooks/`;
`OPERATIONS.md:1756-1766`
Факт: ранбуки есть у `ConnectorNotRunning`, `SlotWalRetainedHigh`, `SlotWalHeldIdle`,
`SparkNoBatch5m`, `SparkRestartLoop`, `FreshnessAbove15m`; нет у `DqChecksStale`,
`CdcStalledSourceWrites`, `SilverGoldNotCompared`, `GoldStaleAtRest`, `ScrapeTargetDown`,
`AirflowDagFailed`, `ContainerRestarting`. Живой `/api/v1/rules`: `annotations: {}` у всех 16.
Чем плохо: алерт в UI Prometheus не говорит, что делать; знание разбросано по абзацам OPERATIONS
(`:637-645`, `:703-724`, `:808-811`).
Правка:
1. Тест на отказ первым: `tests/unit/test_alerts.py` (`yaml.safe_load`): у каждого правила есть
   `annotations.summary` и `annotations.runbook_url`; файл ранбука существует; имя алерта есть в
   тексте ранбука; каждый ранбук из правил есть в таблице «Runbooks» OPERATIONS; ни одно выражение не
   содержит `lakehouse-` (OB-02). Красный на HEAD.
2. Ранбуки (английский, формат как `freshness.md`: Symptom, шаги, Reproduce):
   - новый `docs/runbooks/airflow-dag-failed.md`: `AirflowDagFailed` по DAG: сон хоста
     (`Heartbeat recovered` в логе scheduler, перенос `OPERATIONS.md:718-724`); `silver_upsert` и
     409 на `lakehouse-silver-merge` (ссылка на абзац «Timeouts», метку не менять);
     `dbt_build` и тест (сценарий 9); `dq_checks` -> `dq-checks.md`; `iceberg_maintenance`,
     `iceberg_orphans`; ложное срабатывание после дыры скрейпа до OB-01.
   - новый `docs/runbooks/dq-checks.md`: `DqChecksStale` (пауза, scheduler, красная `report`),
     `SilverGoldNotCompared` (непрерывный реплей или удалённый заказ; B6 даёт его по замыслу),
     `GoldStaleAtRest` (пауза `dbt_build` теряет Asset, `airflow dags trigger dbt_build`; под
     непрерывной нагрузкой молчит, PF-24), разбор красной задачи `dq_checks` (перенос
     `OPERATIONS.md:703-716`) и смысл сверки (`:662-701`, сжать).
   - новый `docs/runbooks/containers.md`: `ContainerRestarting` (какой контейнер:
     `docker inspect -f '{{.RestartCount}} {{.State.OOMKilled}}'`; плановые рестарты: цикл verify
     останавливает scheduler, рестарт `superset`; после рестарта Docker `kafka-exporter` и
     `lakekeeper` стартуют раньше зависимостей, PF-25; stateful job падает после сна хоста), и
     `ScrapeTargetDown` (перенос `OPERATIONS.md:808-811`: `DOCKER_GID`, `COMPOSE_PROJECT_NAME`,
     healthcheck экспортеров).
   - `docs/runbooks/connector-failed.md`: заголовок «Connector not running or CDC stalled
     (ConnectorNotRunning, CdcStalledSourceWrites)», имя файла не менять; шаг для
     `CdcStalledSourceWrites` (Kafka стоит, task RUNNING с заблокированным producer, п. 3).
   - `docs/runbooks/freshness.md`: шаг для `cause="unknown"` (нет Variable
     `silver_upsert_last_bronze_snapshot`, снапшот исчез, `dq_checks` не идёт -> `DqChecksStale`).
3. `annotations` у всех 16 правил: только статичный текст и `{{ $labels.<имя> }}` (без `$value`, чтобы
   ожидания promtool не зависели от формата числа). Формат по документации Prometheus
   (`docs/configuration/alerting_rules.md`, «Templating»): `summary`, `description`; ключ
   `runbook_url` по общепринятому соглашению, значение путь от корня репозитория. Тексты:

| Правило | summary | runbook_url |
|---|---|---|
| ConnectorNotRunning | `Debezium task of shop-connector is not running: no CDC` | `docs/runbooks/connector-failed.md` |
| SlotWalRetainedHigh | `shop_slot retains over 64 MiB of WAL with no reader, or over 512 MiB` | `docs/runbooks/slot-wal-growth.md` |
| SlotWalHeldIdle | `shop_slot held over 64 MiB for an hour on an idle source` | `docs/runbooks/slot-wal-growth.md` |
| SparkNoBatch5m, stuck | `Bronze query made no progress for 5 minutes` | `docs/runbooks/spark-stalled.md` |
| SparkNoBatch5m, gone | `Bronze driver metrics gone for 5 minutes: the driver is down` | `docs/runbooks/spark-stalled.md` |
| SparkRestartLoop | `spark-bronze started more than twice in 10 minutes` | `docs/runbooks/spark-stalled.md` |
| FreshnessAbove15m | `A bronze snapshot has waited over 15 minutes for the silver merge` | `docs/runbooks/freshness.md` |
| FreshnessAbove15m, unknown | `Silver lag not reported for 15 minutes` | `docs/runbooks/freshness.md` |
| DqChecksStale, stale | `dq_checks has not finished a run for 30 minutes` | `docs/runbooks/dq-checks.md` |
| DqChecksStale, gone | `dq_checks metrics are gone` | `docs/runbooks/dq-checks.md` |
| CdcStalledSourceWrites | `The source writes, the replication slot has not moved for two dq_checks runs` | `docs/runbooks/connector-failed.md` |
| SilverGoldNotCompared | `Silver and gold not compared for 24 dq_checks runs (6 hours)` | `docs/runbooks/dq-checks.md` |
| GoldStaleAtRest | `Gold not rebuilt after the last silver change: dbt_build paused or red` | `docs/runbooks/dq-checks.md` |
| ScrapeTargetDown | `Prometheus cannot scrape {{ $labels.job }}` | `docs/runbooks/containers.md` |
| AirflowDagFailed | `DAG {{ $labels.dag_id }} has a failed run in the last 30 minutes` | `docs/runbooks/airflow-dag-failed.md` |
| ContainerRestarting | `Container {{ $labels.name }} started again in the last 15 minutes` | `docs/runbooks/containers.md` |

4. `alerts_test.yml`: promtool сравнивает и аннотации сработавшего алерта (гипотеза по исходнику
   `cmd/promtool/unittest.go`, `reflect.DeepEqual` меток и аннотаций; документация задаёт
   `exp_annotations` рядом с `exp_labels`), поэтому каждому ожиданию с `exp_labels` (около 30) нужен
   `exp_annotations` с раскрытым текстом. Если `make alerts-test` проходит без них, гипотеза неверна, и
   `exp_annotations` всё равно добавить в один кейс на правило, чтобы шаблон был проверен.
5. Шапку `alerts.yml:1-6` и комментарии с ID карточек (R-66) переписать по правилу и ADR; таблицу
   «Runbooks» OPERATIONS сделать по строке на алерт.
Проверка: `uv run pytest tests/unit/test_alerts.py -q` (красный до, зелёный после); `make alerts-test`
-> `SUCCESS: 16 rules found`, все кейсы; `python3 -I <scratchpad>/audit/OB-work/check_md_links.py` без
новых битых; после коммита HUP по «ок» и
`curl -s 127.0.0.1:9090/api/v1/rules | python3 -c 'import json,sys; r=[x for g in json.load(sys.stdin)["data"]["groups"] for x in g["rules"]]; print(sum(1 for x in r if x["annotations"].get("runbook_url")), len(r))'` -> `16 16`.
Размер: M; класс B (правила, тест), A (ранбуки, `docs-writer`), HUP C.
Старый ID: R-67, PF-24, PF-25, часть R-66

### OB-04 [средняя] OPERATIONS 134 KiB без оглавления: целевая структура и карта переноса

Где: `OPERATIONS.md:1-1794`
Факт: 137 688 байт, 18 разделов `##`, оглавления нет; крупнейшие куски: сценарии `:1261-1755`
35.2 KiB, Observability `:726-945` 23.7 KiB (с Alerts и Dashboards), Airflow `:560-724` 13.1 KiB, CI
`:1136-1260` 10 KiB, первый прогон обслуживания `:1017-1135` 7.1 KiB (размеры: `awk` по диапазонам).
Чем плохо: дежурный и новый инженер не находят процедуру; журнал сценариев, заметки к коммиту и
замеры с датами в 3-5 копиях (R-63).
Правка: см. раздел «OPERATIONS: целевое оглавление и карта переноса» ниже. Порядок: сначала
перенос со ссылками, потом сжатие; заголовки из списка «не трогать» оставить буква в букву.
Проверка: `wc -c OPERATIONS.md` -> не больше 66 000 (цель около 60 000);
`python3 -I <scratchpad>/audit/OB-work/check_md_links.py` -> по `OPERATIONS` и `failure-scenarios` 0
битых (на HEAD 77 проверено, 0 битых); `grep -rn "OPERATIONS.md, scenario\|OPERATIONS.md#[0-9]\|OPERATIONS.md#first-live\|OPERATIONS.md#orphans" $(git ls-files | grep -v ^docs/planning)` пусто;
`grep -n "^Timeouts\|^## Airflow$\|^### Pinned images and actions$\|What deletes files" OPERATIONS.md`
находит все метки; `uv run pytest tests/unit/test_chaos_silver_kill.py -q` зелёный.
Размер: L; класс A (`docs-writer`); комментарии в `scripts/chaos/*.sh` и `dbt/tests/assert_chaos_break_test.sql` класс B (код, нужен `make check`).
Старый ID: R-63

### OB-05 [средняя] Ложные и устаревшие утверждения в документах наблюдаемости

Где и факт:
- `OPERATIONS.md:1793` «Not proven live: ... killing `spark-silver` mid-merge» против сценария 10b,
  доказанного 2026-11-06 (`OPERATIONS.md:1717-1754`, `docs/evidence.md:81`).
- `OPERATIONS.md:1279` и `docs/evidence.md:83`: сценарий 10 `chaos-trino-memory` «planned (week 3)»;
  скрипта нет (`ls scripts/chaos`).
- `OPERATIONS.md:943-944`: «Grafana 123 of 256, container-exporter 29 of 64»; лимиты 512 и 128
  (`docker stats`: 391.7 MiB / 512 MiB, 54.3 MiB / 128 MiB).
- `OPERATIONS.md:533-536`: замер «v1 bundle (4 charts)», в бандле 13 графиков (`:490`).
- `OPERATIONS.md:816-824`: «The first six ... the next three ... These seven are proven by promtool»
  не сходится с таблицей (`SlotWalHeldIdle`, `DqChecksStale`, `ScrapeTargetDown`,
  `SilverGoldNotCompared`, `GoldStaleAtRest` только promtool, `docs/evidence.md:140`).
- `observability/README.md:14-16` (PF-27), нет строк PF-24 (`OPERATIONS.md:849`), PF-30 (Backup), PF-54.
Чем плохо: внешний читатель видит противоречие evidence и OPERATIONS; дежурный ищет несуществующий
сценарий.
Правка: в рамках OB-04: убрать «killing spark-silver mid-merge» из `:1791-1794`; строку 10 удалить
из обеих таблиц (или «not implemented»); `:943-944` удалить (числа памяти только в Profiles);
`:533-536` заменить на «13 of 13» с датой из HANDOFF 13.11 или удалить; вступление Alerts в три
строки: «13 alerts in 16 rules; live proof and time to fire: evidence»; PF-27: «`lakehouse.*` and
`lakehouse.dq.*` are mapped with a 45-minute TTL (`statsd/mapping.yml`)»; PF-24 в строку
`GoldStaleAtRest`: «quiet under a continuous replay: `SilverGoldNotCompared` speaks after 6 hours»;
PF-30 в Backup: «a checkpoint restores only together with the catalog it was written against»;
PF-54: одна строка про анонимные тома и чистку только по «ок».
Проверка: `grep -n "killing .spark-silver. mid-merge\|planned (week 3)\|123 of 256\|v1 bundle\|These seven" OPERATIONS.md docs/evidence.md` пусто; `grep -n "Names it does" observability/README.md` пусто.
Размер: S; класс A.
Старый ID: PF-24, PF-27, PF-30, PF-54

### OB-06 [низкая] Pipeline health не отвечает «что сломалось» за минуту

Где: `observability/grafana/dashboards/pipeline-health.json:835-860` (панель «Firing alerts»,
`gridPos y=77`, последняя из 25), `:225`, `:676`
Факт: имя горящего алерта на дашборде не видно: только `count(ALERTS{alertstate="firing"}) or vector(0)` в
правом нижнем углу; нет панели «targets down» и возраста последнего прогона `dq_checks`; описание
панели слота не называет `SlotWalHeldIdle`; `(W5-T04)` в описании.
Чем плохо: дежурный листает 11 рядов, затем идёт в UI Prometheus.
Правка: первым рядом (y=0) таблица `count by (alertname, severity, cause) (ALERTS{alertstate="firing"}) or on() vector(0)`
(instant, format table) и stat `count(up == 0) or vector(0)`; остальные панели сдвинуть на 7;
описание `:225` дополнить `SlotWalHeldIdle`; `(W5-T04)` убрать. Тест в
`tests/unit/test_check_dashboards.py`: первая по `gridPos.y` панель Pipeline health читает `ALERTS`.
Проверка: `uv run pytest tests/unit/test_check_dashboards.py -q`; `uv run --no-sync python scripts/obs/check_dashboards.py` -> `queries ok: 33` или 34, rc 0.
Размер: S; класс B; пересоздавать Grafana не нужно (provisioning файлом подхватывается, проверить в UI).
Старый ID: спека 14 разд. 7 (описание панели слота)

### OB-07 [низкая] `SparkNoBatch5m{cause="stuck"}` без `for` мигает page после каждого сна хоста

Где: `observability/prometheus/alerts.yml:42-46`
Факт: `ALERTS{alertname="SparkNoBatch5m",cause="stuck"}[7d]` одна точка 11-12 12:38:34, первое
вычисление после дыры 11-10 21:36 -> 11-12 12:38: `time()` прыгнул, idle-событие ещё не пришло.
Чем плохо: ложный page в истории ALERTS и всплеск панели «Firing alerts».
Правка: тест на отказ: серия `0+60x10 _x30 1800+60x10` (отметка движется, дыра 30 минут) и
`eval_time` на первой точке после дыры, `exp_alerts: []`; затем `for: 1m` у правила; кейс
`:189-201` сдвинуть на `eval_time: 7m`. Строку таблицы OPERATIONS («0 / 5m») поправить.
Проверка: `make alerts-test` -> `SUCCESS`, новый кейс красный на HEAD.
Размер: S; класс B; HUP C.
Старый ID: нет

### OB-08 [низкая] SLO не записаны

Где: `OPERATIONS.md:726-878`
Факт: пороги есть (таблица выше), формулировки цели нет; лаг Kafka и возраст gold без алерта названы
только косвенно.
Правка: в новом подразделе «SLIs and thresholds» (OB-04) таблица из 6 строк (SLI, метрика, порог,
алерт или «no alert, why»), одна строка: «targets for a laptop, not an SLO with an error budget».
Проверка: `grep -n "SLIs and thresholds" OPERATIONS.md`.
Размер: S; класс A.
Старый ID: нет

### OB-09 [низкая] Тест сокета container-exporter падает при длинном basetemp

Где: `tests/unit/test_container_exporter.py:260-262`
Факт: `path = str(tmp_path / "docker.sock")`; AF_UNIX ограничен 108 байтами.
Правка: тест на отказ: `uv run pytest tests/unit/test_container_exporter.py -q --basetemp=/tmp/$(python3 -c 'print("x"*100)')` падает `AF_UNIX path too long`; затем сокет в `tempfile.mkdtemp(dir="/tmp")` с удалением в teardown.
Проверка: та же команда зелёная; `uv run pytest tests/unit/test_container_exporter.py -q`.
Размер: S; класс A (только тест).
Старый ID: PF-65

## OPERATIONS: целевое оглавление и карта переноса

Целевой файл около 60-66 KB, оглавление сразу под `# Operations`. Заголовки, на которые есть входящие
ссылки, сохранить буква в букву (якоря GitHub).

### Не трогать (входящие ссылки, скрипты, тесты)

| Метка в OPERATIONS | Кто ссылается |
|---|---|
| `## Airflow` | `scripts/verify.sh:41`, `Makefile:101` (печатают «OPERATIONS.md, Airflow»); ARCHITECTURE:96, interview-notes:364,477, `airflow/README.md:4,16` |
| абзац «Timeouts» в Airflow (`:647`) | `scripts/chaos/silver-kill.sh:68,198` печатают «OPERATIONS.md, Timeouts»; `tests/unit/test_chaos_silver_kill.py:274` проверяет; interview-notes:477. Можно убрать «(audit 30.10, B1)», слово `Timeouts` в начале абзаца оставить |
| `### Pinned images and actions` | `docker/compose.yaml:8` |
| «What deletes files» (`:412`) | `docker/trino/etc/catalog/lake.properties:2`, `docs/runbooks/catalog-cutover.md:206` |
| «After the cutover» (`:395`) | `docs/runbooks/catalog-cutover.md:5` (если R-40 уводит ранбук в архив, метку можно убрать) |
| `### Access control` | 5 ссылок `#access-control` (ARCHITECTURE:115, evidence:225,285, interview-notes:510, сам OPERATIONS:542); `tests/unit/test_trino_access.py:10` |
| `## Superset (profile \`bi\`)` | 5 ссылок `#superset-profile-bi` (README:88, ARCHITECTURE:120, evidence:234,258, сам OPERATIONS:10) |
| `## Ports (all on 127.0.0.1)` | README:77, interview-notes:509 |
| `## Profiles and what runs together` | interview-notes:454; «OPERATIONS "Profiles"» в ARCHITECTURE:143, DECISIONS:426 |
| `## Daily commands`, `## Bronze ingest`, `## Silver upsert`, `## Stateful job`, `## Maintenance`, `## CI`, `## Observability`, `### Alerts`, `### Dashboards` | README:42,152; evidence:61,128,181,192; interview-notes (34 ссылки); `observability/README.md:3,12`; `docs/runbooks/disk-full.md:23,30`, `spark-stalled.md:20`, `freshness.md:24`; DECISIONS:749; ARCHITECTURE:104 |
| `## Lakekeeper (REST catalog)` | `scripts/README.md:37`, DECISIONS:261 |
| `## Failure scenarios` | README:166, interview-notes:257 (оставить коротким разделом-указателем) |
| «Limits worth knowing» в Alerts | interview-notes:416,437 |

### Целевое оглавление

1. Profiles and what runs together
2. Ports (all on 127.0.0.1)
3. Daily commands
4. Bronze ingest
5. Silver upsert
6. Query (Access control)
7. Lakekeeper (REST catalog)
8. MinIO console
9. Superset (profile `bi`)
10. Airflow
11. Observability (SLIs and thresholds, Alerts, Dashboards)
12. Stateful job
13. Maintenance
14. CI (Pinned images and actions)
15. Failure scenarios (таблица-указатель)
16. Runbooks (строка на каждый алерт)
17. Backup

### Карта переноса

| Строки | KiB | Что | Действие |
|---|---|---|---|
| 1-2 | | заголовок | добавить оглавление (около 0.8 KiB) |
| 3-37 | 3.4 | Profiles | остаётся; `:9` скобку с историей лимитов 10.11 сократить до лимитов; `:14-22` до 3 строк (комбинация всех профилей, пик 8.33 GiB, условия) |
| 38-69 | 1.5 | Ports | остаётся |
| 70-95, 126-155 | 3.3 | Daily commands | остаётся |
| 96-124 | 2.3 | три пробы verify с историей замеров | сжать до 6-8 строк (пробы и тексты отказов `:108-114`); история замеров `:116-124` удалить, ссылка на evidence «Probe: MinIO stopped» (`docs/evidence.md:54`) |
| 156-200 | 2.8 | Bronze ingest | остаётся; «Verified on 2026-09-22» `:165-166` и SQL от 2026-09-26 `:182-185` удалить |
| 201-255, 259-265 | 4.6 | Silver upsert | остаётся; `:208` «Airflow takes over scheduling in week 3» удалить |
| 256-257 | 0.2 | первый прогон 2026-09-23 | удалить (журнал) |
| 266-341 | 4.4 | Query, Access control, проверочный блок | остаётся |
| 342-350 | 0.8 | Residual risk | остаётся единственным местом; дубли `:538-542` и `:933-939` заменить ссылкой `[Access control](#access-control)` |
| 352-394, 411-460 | 6.1 | Lakekeeper | остаётся; замер `:368-370` удалить |
| 395-410 | 1.2 | After the cutover, Registration | сжать до 3 строк (точка отката отпущена 29.10, JDBC не включать); при R-40 удалить вместе с ранбуком |
| 461-468 | 0.4 | MinIO console | остаётся |
| 469-532, 537-559 | 5.7 | Superset | остаётся; `:538-542` ссылкой (см. выше) |
| 533-536 | 0.3 | замер v1 (4 графика) | удалить или заменить на 13 из 13 (OB-05) |
| 560-617, 619-660 | 5.4 | Airflow: сервисы, ключи, старт, DAG, один писатель, пауза `dbt_build`, Timeouts | остаётся; fernet-абзац `:579-587` про `.env` до 2026-10-09 удалить |
| 618 | 0.3 | замер памяти 2026-10-18 | удалить |
| 662-701 | 3.6 | устройство `reconcile_values` и GMV | перенести в `docs/runbooks/dq-checks.md` (раздел «What the check compares», сжать вдвое); в OPERATIONS 2 строки и ссылка |
| 703-716 | 1.3 | красная задача `dq_checks` | перенести в `docs/runbooks/dq-checks.md` |
| 718-724 | 0.6 | сон хоста | перенести в `docs/runbooks/airflow-dag-failed.md`, в Airflow одна строка-ссылка |
| 726-747, 779-813 | 4.8 | Observability: targets, StatsD, проверка, заметки | остаётся; `:808-811` перенести в `docs/runbooks/containers.md` |
| 748-778 | 4.0 | таблицы серий `lakehouse_*` | перенести в `observability/README.md` (раздел «Series»), в OPERATIONS ссылка |
| новое | 1.0 | SLIs and thresholds | добавить (OB-08) |
| 814-834 | 1.6 | вступление Alerts, «Nothing watches the watcher» | вступление в 3 строки (OB-05), «Nothing watches the watcher» оставить |
| 835-851 | 5.1 | таблица алертов | оставить колонки Alert, Expression, `for`, severity, Why this threshold, Runbook; колонки «Shown in» и «Time to fire» удалить (они в `docs/evidence.md:130-140`); interview-notes:380,409 перевести на `docs/evidence.md#alerts-and-time-to-fire` |
| 852-878 | 2.6 | Limits worth knowing | сжать до списка из 5 пунктов; разбор chaos 8 и chaos 6 убрать (он в сценариях) |
| 880-885, 897-911 | 1.6 | Dashboards | остаётся |
| 886-896 | 1.0 | логика `idle:` в `check_dashboards.py` | перенести в docstring `scripts/obs/check_dashboards.py` (там же убрать W4-T04, W6-T01), в OPERATIONS 2 строки |
| 912-932 | 1.9 | Marketplace в Grafana, плагин, подсчёт заказов | остаётся, сжать до 1 KiB |
| 933-939 | 0.6 | риск плагина | ссылка на Access control |
| 940-945 | 0.3 | шаг панелей, замер памяти 2026-10-19 | `:941` оставить, `:943-944` удалить (OB-05) |
| 946-969, 977-981 | 2.2 | Stateful job | остаётся |
| 970-976 | 0.6 | живая проверка 2026-10-23 | перенести в `docs/evidence.md` (там уже есть цифры в README:148) или удалить |
| 982-1016 | 2.3 | Maintenance | остаётся |
| 1017-1116 | 6.5 | First live run, 2026-10-29 | перенести в `docs/evidence.md`, раздел «Maintenance, before and after» (`:87-121`), убрав дубль таблицы evidence; заголовок `### First live run, 2026-10-29` сохранить там (ссылки evidence:52,90, interview-notes:212 перевести на `docs/evidence.md#first-live-run-2026-10-29`) |
| 1118-1127 | 0.6 | Orphans next to orders_per_minute | туда же, ссылку evidence:121 перевести внутрь файла |
| 1128-1135 | 0.5 | Not proven yet (обслуживание) | остаётся |
| 1136-1160 | 2.7 | CI, smoke | остаётся; история красных smoke `:1155-1159` до одной строки |
| 1161-1188, 1219-1226 | 2.5 | Pinned images and actions, Not covered | остаётся (+ PF-16 в области IN) |
| 1189-1218 | 2.1 | «On a running stack this commit changes the config hash of 11 services» | удалить (заметка к коммиту 30.10) |
| 1227-1260 | 2.7 | MinIO and mc images | сжать до 6 строк (сборка, проверка, смена тега); откат и замер сборки удалить (они в ADR-026); «213 tests in CI run 40011971965» `:1257` удалить |
| 1261-1281 | 1.8 | Failure scenarios: вводная и таблица | остаётся указателем: таблица 10 строк со ссылками в `docs/failure-scenarios.md`, строку 10 удалить, длинную ячейку 10b сократить до названия |
| 1282-1755 | 33.4 | Template, правила helpers, сценарии 1-10b | перенести в новый `docs/failure-scenarios.md` с теми же заголовками `### 1. ...` и т. д. (якоря сохраняются, меняется только файл) |
| 1756-1767 | 0.5 | Runbooks | переписать: строка на каждый алерт (13) плюс disk-full, catalog-cutover (если остаётся), `make nuke` |
| 1768-1794 | 1.7 | Backup | остаётся; `:1791-1794` поправить (OB-05), PF-30 добавить |

Оценка итога: около 62-66 KiB. Чтобы выйти на 60, по желанию: «Pinned images and actions» и «MinIO and mc
images» (около 3.5 KiB после сжатия) в `docs/supply-chain.md`, проверочный блок Access control
(`:320-340`, 1.1 KiB) в `docker/trino/README` или в ADR.

Входящие ссылки, которые меняются вместе с переносом (без них проверка ссылок красная):
- якоря сценариев `OPERATIONS.md#1-...` ... `#10b-...`: README.md:144,149; docs/evidence.md:71-81,151;
  docs/interview-notes.md:24,35,69,81,83,128,178,284,345,366,413 (замена файла на
  `docs/failure-scenarios.md`, из `docs/` это `failure-scenarios.md#...`);
- `#first-live-run-2026-10-29`: docs/evidence.md:52,90, docs/interview-notes.md:212;
  `#orphans-next-to-orders_per_minute-2026-10-30`: docs/evidence.md:121;
- текст «OPERATIONS.md, scenario N»: `scripts/chaos/spark-kill.sh:3`, `connect-restart.sh:5`,
  `duplicates.sh:8`, `kafka-down.sh:4`, `postgres-restart.sh:4`, `connect-pause.sh:4`,
  `break-dbt-test.sh:4`, `silver-kill.sh:2`; `dbt/tests/assert_chaos_break_test.sql:1`;
  `DECISIONS.md:308`; `docs/runbooks/slot-wal-growth.md:8,35`; README.md:19 «(profiles, runbooks,
  failure scenarios)»;
- `docs/failure-scenarios.md` внутри: «see Alerts above» (`:1673`), «see "Airflow"» (`:1752`),
  «the silver section» (`:1792`) превратить в ссылки на `../OPERATIONS.md#...`.

## Находки «не делать»

| ID | что | почему не делать |
|---|---|---|
| OB-N1 | Алерты на лаг Kafka bronze, падение брокера, `pg_up == 0`, `docker_container_running == 0` | косвенно покрыты (`SparkNoBatch5m`, `SparkRestartLoop`, `ConnectorNotRunning`, `AirflowDagFailed`); порогов на этом объёме не обосновать; назвать в SLI-таблице (OB-08) |
| OB-N2 | Alertmanager, watchdog (deadman) | новый сервис (ADR-023); предел уже честно записан (`OPERATIONS.md:830-833`) |
| OB-N3 | Алерты stateful job `orders_per_minute` | профиль необязательный, `ScrapeTargetDown` исключает его по замыслу (`alerts.yml:135-138`) |
| OB-N4 | Шум `ContainerRestarting` на плановых рестартах (471 вычисление у scheduler за 7 дней от циклов verify) | warn по замыслу; объяснить в `containers.md` (OB-03) |
| OB-N5 | Повторные живые chaos (MinIO при записи, потеря checkpoint, миграция 003, live `SparkRestartLoop`) | бюджет реплея и разрушительные действия; уже в `docs/evidence.md:271-285` |
| OB-N6 | Точка `eval_time: 13m` у `SlotWalHeldIdle` | тривиальна, мутации ловят соседние точки |
| OB-N7 | Метрика и алерт карантина | Modify-гейт владельца W4-D8 (`OPERATIONS.md:1643-1646`) |
| OB-N8 | Лимит Grafana 512M | пик 439.7 MiB за 3 дня, OOM нет; swap не проверен |
| OB-N9 | Stateful job падает после сна хоста (18:22:55 сегодня, `RestartCount` 1) | политика рестарта восстанавливает, чекпоинт цел; одна строка в `containers.md` |

## Разрыв с продом

- Нет доставки алертов и дежурства: без Alertmanager, без маршрутизации, без watchdog; упавший
  Prometheus значит тишину.
- Один Prometheus без HA, retention 7 дней, без долговременного хранилища.
- Нет метрик хоста и диска (node_exporter), диск не под алертом (`docs/runbooks/disk-full.md:4`).
- Нет агрегации логов и трассировки: диагностика через `docker logs`.
- Нет SLO с бюджетом ошибок; пороги подобраны под ноутбук.
- Trino, Lakekeeper, MinIO и реплеер не скрейпятся (`observability/README.md:9`).
- Chaos запускается руками раз в несколько недель, не по расписанию; восстановление из бэкапа не
  проверялось.

## Не проверено

- Строгость сравнения аннотаций в promtool (OB-03, п. 4): гипотеза по исходнику; проверит
  `make alerts-test` после добавления `annotations`.
- `ContainerRestarting` по `lakehouse-silver-merge` при непрерывном реплее: вывод из 10b и семантики
  `changes()`; проверит кейс (в) OB-02 в `make alerts-test`.
- `make alerts-test` на HEAD не запускался (запрет брифа); тесты правил оценены чтением.
- Grafana UI: анонимный GET `/api/search` даёт 401, `/api/health` 200 (13.2.2); рендер панелей и
  `noValue` не смотрел.
- Swap Grafana внутри cgroup: нужен `docker exec lakehouse-grafana-1 cat /sys/fs/cgroup/memory.swap.current`.
- Причина 240 вычислений `AirflowDagFailed`: доказаны неизменные счётчики и дыры до окон; что старые
  падения были от сна хоста, не проверено (`airflow dags list-runs -d dq_checks --state failed`).
- Содержимое `test_container_exporter.py`, `test_chaos_silver_kill.py` и `test_check_dashboards.py`
  по качеству (это область QA); оценено только то, что касается OB.
- Размер после переноса (62-66 KiB) оценён суммой диапазонов, не сборкой файла.
