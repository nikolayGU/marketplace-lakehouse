# P09. Наблюдаемость: правила алертов, annotations, ранбуки, горящие алерты на дашборде
Статус: исполнен 20.11.2026, `78b3754`; HUP (В-06) 21:02Z по «ок». Оркестратор Opus по `13-harness.md`: `/task docs/planning/21-final-audit-2026-11-13/P09-observability.md`.

## Цель

Алерты не горят ложно после сна хоста и не зависят от имени проекта compose; у каждого из 16
правил есть `summary` и `runbook_url` на существующий ранбук; Pipeline health первым рядом
показывает, что горит. Один коммит кода и документов, затем перечитывание правил (C).

## Находки пакета

| ID | серьёзность | суть | где подробности |
|---|---|---|---|
| OB-01 | средняя | `AirflowDagFailed` горит 25-30 мин после дыры скрейпа длиннее 5 мин | `reports/OB.md`, OB-01 |
| OB-02 | средняя | имя проекта в `SparkRestartLoop`, `ContainerRestarting`, 7 выражениях `infra.json`; merge даёт `ContainerRestarting`; кейсы one-shot (спека 14, разд. 7, п. 36) | `reports/OB.md`, OB-02 |
| OB-03 | средняя | у 7 из 13 алертов нет ранбука, `annotations` пусты у всех 16 правил | `reports/OB.md`, OB-03 |
| OB-06 | низкая | Pipeline health: имя горящего алерта не видно, панель внизу; описание слота без `SlotWalHeldIdle` | `reports/OB.md`, OB-06 |
| OB-07 | низкая | `SparkNoBatch5m{cause="stuck"}` без `for` мигает page после сна | `reports/OB.md`, OB-07 |
| PF-24 | низкая | `GoldStaleAtRest` молчит под непрерывной нагрузкой: строка в ранбуке | `18-postfix-audit-2026-11-06.md`, PF-24 |
| 14-7.19 | низкая | порог 200 точек `SlotWalHeldIdle` закреплён тестом только снизу | `registry.md`, разделы 2.4 и 4; `14-closeout-spec.md:709-710` |
| R-66, часть | низкая | ID карточек и «audit» в комментариях `observability/` | `work/DC/r66_pattern.txt` |

## Решения владельца и действия класса C

- **В-06** (рекомендация «да»), по «ок» владельца на точный текст, после коммита:
  `docker exec lakehouse-prometheus-1 kill -HUP 1`. Не `docker kill -s HUP`
  (`OPERATIONS.md:792-796`; PF-01, `18-postfix-audit-2026-11-06.md:47`). Обратимо: revert и HUP.
- Grafana рестарта не требует: провайдер `file`
  (`observability/grafana/provisioning/dashboards/files.yml`) перечитывает каталог дашбордов,
  смонтированный из репозитория (`docker/compose.yaml`, сервис `grafana`).
- Комментарии `statsd/mapping.yml`, `postgres-exporter/queries.yaml`, datasource `trino.yml`
  меняют только текст: перезапуск не нужен.

## Зависимости

- P09 идёт после P05: комментарии гейта (`alerts.yml:110-112`, `:124-128`) и `dq-checks.md`
  описывают гейт по снапшотам. P05 не исполнен: эти строки не трогать, записать в «Итог».
- P11 после переносит в ранбуки абзацы OPERATIONS (граница в «Границы»). P10 файлы
  `observability/` не трогает: их ID чистит этот пакет.
- `tests/unit/test_check_dashboards.py` правит и P07 (тест дедлайна Trino): P07 идёт раньше,
  строки искать по цитате.

## Вход

- `observability/prometheus/alerts.yml:58` `name="lakehouse-spark-bronze-1"`; `:156-157`
  `name=~"lakehouse-.+"` и исключения `-init-`, `-bootstrap-`, `-migrate-`; `:145-150`
  `AirflowDagFailed`; `:42-46` stuck без `for`. `infra.json:43,76,109,142,175,208,241`:
  `{name=~\"lakehouse-.+\"}`.
- Живой Prometheus 13.11: `/api/v1/rules` 16 правил, `annotations` у 0. Серии
  `airflow_dagrun_failed_seconds_count` с метками `dag_id`, `instance="statsd-exporter:9102"`,
  `job="statsd-exporter"`; `up` с теми же `instance`, `job`. У
  `docker_container_start_time_seconds` метки `name`, `service`
  (`observability/container-exporter/container_exporter/collector.py:17`, `service` из
  `com.docker.compose.service`, `:111`).
- `docker image inspect lakehouse/spark:dev --format '{{json .Config.Labels}}'` -> `service`
  `spark-bronze`; у `lakehouse/airflow:dev` `airflow-api-server`. Запрос `count by (name,
  service) (last_over_time(docker_container_start_time_seconds{name!~"lakehouse-.+-[0-9]+"}[7d]))`
  -> 5 случайных имён со `spark-bronze` (`make test-spark`), 2 с `airflow-api-server`
  (`make dags-check`), 6 `lakehouse-spark-silver-run-<hex>`.
- One-shot сервисы compose: `minio-init`, `lakekeeper-migrate`, `lakekeeper-bootstrap`,
  `superset-init` (имя постоянное, перезапуск на каждом `make start`); `spark-silver run`
  (имя новое на каждый запуск, старт один).
- `alerts_test.yml`: 34 строки `exp_labels`; кейсы `:156-170` (`AirflowDagFailed`, серия без
  `instance`), `:189-201` (stuck, `eval_time: 6m`), `:280-293` (bootstrap и kafka без `service`).
- `docs/runbooks/`: `catalog-cutover`, `connector-failed`, `disk-full`, `freshness`,
  `slot-wal-growth`, `spark-stalled`. Таблица «Runbooks» `OPERATIONS.md:1756-1766`.
- `make alerts-test` (`Makefile:149-151`): `docker run --rm` `prom/prometheus:v3.14.0`,
  `promtool check rules` и `test rules`; образ без меток compose, стек не трогает.
- `uv run --no-sync python scripts/obs/check_dashboards.py` -> `queries ok: 32`, 7 `idle:`, rc 0.

## Границы

- Менять: `observability/prometheus/alerts.yml`, `alerts_test.yml`; дашборды `infra.json`,
  `pipeline-health.json`; комментарии `observability/statsd/mapping.yml:3,24`,
  `observability/postgres-exporter/queries.yaml:2`,
  `observability/grafana/provisioning/datasources/trino.yml:5`; новый `tests/unit/test_alerts.py`;
  `tests/unit/test_check_dashboards.py`; `docs/runbooks/`; в `OPERATIONS.md` только строки
  таблицы Alerts изменённых правил, таблицу «Runbooks» и одну фразу сценария 10b.
- Граница с P11: новые ранбуки не копируют абзацы OPERATIONS (сон хоста `:718-724`, красная
  задача `dq_checks` `:703-716`, устройство сверки `:662-701`, заметки экспортеров `:808-811`),
  а ссылаются на `../../OPERATIONS.md#airflow` и `#observability`. P11 переносит абзацы в
  ранбуки и снимает ссылки: у каждого факта одно место.
- Нельзя: новые правила и сервисы, пороги; `scripts/obs/check_dashboards.py` (его ID в docstring
  чистит P10); `observability/README.md` (PF-27, P11).
- Живой стек: до коммита только чтение; HUP после коммита по «ок».

## Шаги

Код и тесты пишет `implementer`, ранбуки и строки OPERATIONS `docs-writer` (английский).

1. **Строгость promtool.** `annotations` (`summary`, `runbook_url`) только у `ScrapeTargetDown`,
   `make alerts-test`. `FAILED` на его кейсах: сравнение строгое, каждому ожиданию с
   `exp_labels` нужен `exp_annotations` с раскрытым текстом. `SUCCESS`: `exp_annotations` всё
   равно в один кейс на правило, чтобы шаблон был проверен. Вывод в «Итог».
2. **`tests/unit/test_alerts.py` первым** (`yaml.safe_load`), красный на HEAD. Утверждает: у
   каждого правила непустые `annotations.summary` и `annotations.runbook_url`, других ключей
   нет, шаблоны только `{{ $labels.<имя> }}` (нет `$value`); `runbook_url` это путь от корня
   `docs/runbooks/<имя>.md`, файл существует, имя алерта есть в его тексте, путь есть в таблице
   между `## Runbooks` и следующим `## ` в `OPERATIONS.md`; ни одно `expr` правил и панелей
   `observability/grafana/dashboards/*.json` (вложенные тоже) не содержит `lakehouse-`.
3. **OB-01.** Кейс на отказ первым, `interval: 1m`, `eval_time: 55m`, `exp_alerts: []` (на HEAD
   `FAILED`): `airflow_dagrun_failed_seconds_count{dag_id="dq_checks",instance=...,job=...}`
   `3x10 _x40 3x20` и `up{instance="statsd-exporter:9102",job="statsd-exporter"}` `1x10 _x40 1x20`.
   Выражение (вторая половина дословно из отчёта):
   ```text
   increase(airflow_dagrun_failed_seconds_count[30m]) > 0
   or ((airflow_dagrun_failed_seconds_count
        unless airflow_dagrun_failed_seconds_count offset 30m)
       and on (instance) up{job="statsd-exporter"} offset 30m)
   ```
   Кейс `:156-170` переписать: `up` `1x40`, счётчик с `instance` и `job` `_x30 1x10`; `3m` без
   алерта, `33m` горит с `exp_labels` `severity`, `dag_id`, `instance`, `job`. Комментарий
   правила: первая ошибка в первые 30 минут после старта Prometheus не ловится, принятая цена.
4. **OB-02.** Кейсы на отказ первыми ((a), (b), (c) на HEAD `FAILED`), `interval: 1m`, кроме (a):
   (a) `SparkRestartLoop` по `{name="shop-spark-bronze-1",service="spark-bronze"}` `1+1x15`,
   `interval: 20s`, горит на `5m`; (b) `ContainerRestarting` по
   `{name="shop-kafka-1",service="kafka"}` `100 100 200 200` горит на `3m`; (c)
   `{name="lakehouse-silver-merge",service="spark-bronze"}` `100 100 stale 200 200 stale 300 300`:
   на `7m` нет ни `SparkRestartLoop`, ни `ContainerRestarting`; (d)
   `shop-minio-init-1`/`minio-init`, `shop-lakekeeper-migrate-1`/`lakekeeper-migrate`,
   `shop-superset-init-1`/`superset-init` со сменой старта: без алерта. Выражения дословно:
   ```text
   changes(docker_container_start_time_seconds{service="spark-bronze",
     name=~".+-spark-bronze-[0-9]+"}[10m]) > 2
   changes(docker_container_start_time_seconds{name=~".+-[0-9]+",
     service!~"minio-init|lakekeeper-migrate|lakekeeper-bootstrap|superset-init"}[15m]) > 0
   ```
   В кейс `:280-293` добавить `service="lakekeeper-bootstrap"` и `service="kafka"` (иначе
   bootstrap с пустой `service` загорится), в `exp_labels` `service: kafka`. В `infra.json` из 7
   выражений убрать `{name=~"lakehouse-.+"}`. Комментарий правила: имя compose
   `<проект>-<сервис>-<n>`, у merge и `run`-контейнеров последний сегмент не число, образ Spark
   несёт метку `spark-bronze`.
5. **OB-07.** Кейс на отказ: `spark_streaming_last_batch_timestamp{query="bronze_cdc_ingest"}`
   `0+60x10 _x30 600 2520+60x10`, `interval: 1m` (после дыры одна точка со старой отметкой,
   затем текущая), `eval_time` `41m` и `43m`, `exp_alerts: []` (на HEAD 41m `FAILED`). Правилу
   stuck `for: 1m`; кейс `:189-201` перенести на `eval_time: 7m`.
   **14-7.19.** Порог `count_over_time(...[1h]) >= 200` у `SlotWalHeldIdle` (`alerts.yml:35`)
   закреплён только снизу (кейс `:96-107`: 41 точка, `10m`). Новый кейс рядом, `interval: 15s`:
   `lakehouse_slot_retained_bytes{slot_name="shop_slot"}` `73400320+0x400` (70 MiB),
   `lakehouse_slot_active{slot_name="shop_slot"}` `1+0x400`; `eval_time: 49m15s` (198 точек)
   `exp_alerts: []`, `eval_time: 50m` (201 точка) горит, `exp_labels` `severity: warn`,
   `slot_name: shop_slot`. Мутации порога 200 -> 240 и 200 -> 190 дают `FAILED`.
6. **OB-03, annotations.** Всем 16 правилам `summary` и `runbook_url` по таблице
   `reports/OB.md`, OB-03, п. 3 (тексты дословно; строки с `{{ }}` в одинарных кавычках YAML).
   `runbook_url`: `ConnectorNotRunning`, `CdcStalledSourceWrites` -> `connector-failed.md`;
   `SlotWal*` -> `slot-wal-growth.md`; `SparkNoBatch5m`, `SparkRestartLoop` -> `spark-stalled.md`;
   `FreshnessAbove15m` -> `freshness.md`; `DqChecksStale`, `SilverGoldNotCompared`,
   `GoldStaleAtRest` -> `dq-checks.md`; `ScrapeTargetDown`, `ContainerRestarting` ->
   `containers.md`; `AirflowDagFailed` -> `airflow-dag-failed.md` (все в `docs/runbooks/`).
   `exp_annotations` по итогу шага 1.
7. **Ранбуки** (`docs-writer`; формат `freshness.md`: Symptom, шаги, Reproduce; состав
   `reports/OB.md`, OB-03, п. 2, с границей P11):
   - новый `airflow-dag-failed.md`: по `dag_id`; первым сон хоста (`Heartbeat recovered` в логе
     scheduler, ссылка на OPERATIONS «Airflow»); `silver_upsert` и 409 на merge (абзац
     «Timeouts»); `dbt_build` и красный тест; `dq_checks` -> `dq-checks.md`; `iceberg_*`;
   - новый `dq-checks.md`: `DqChecksStale` (пауза, scheduler, красный `report`),
     `SilverGoldNotCompared` (непрерывный реплей; gold не перестроен), `GoldStaleAtRest` (пауза
     `dbt_build` теряет событие Asset: `airflow dags trigger dbt_build`; PF-24: под непрерывной
     нагрузкой молчит, через 6 часов говорит `SilverGoldNotCompared`); красная задача: ссылка;
   - новый `containers.md`: `ContainerRestarting` (`docker inspect -f '{{.RestartCount}}
     {{.State.OOMKilled}}' <name>`; плановые: цикл verify останавливает scheduler, рестарт
     `superset`; после рестарта Docker `kafka-exporter` и `lakekeeper` стартуют раньше
     зависимостей, PF-25; stateful job после сна; merge больше не считается); `ScrapeTargetDown`;
   - `connector-failed.md`: заголовок `Connector not running or CDC stalled
     (ConnectorNotRunning, CdcStalledSourceWrites)`, имя файла прежнее, шаг для
     `CdcStalledSourceWrites`; `freshness.md`: шаг для `cause="unknown"`;
     `spark-stalled.md:15`: без `lakehouse-spark-bronze-1` в описании правила;
   - `OPERATIONS.md`: строки Alerts `SparkNoBatch5m` (`for` `1m / 5m`), `AirflowDagFailed`,
     `SparkRestartLoop`, `ContainerRestarting` (`:838-849`); «Runbooks» строкой на алерт плюс
     `disk-full`, `catalog-cutover`, `make nuke`; в 10b (`:1731`) фраза: merge больше не даёт
     `ContainerRestarting`, повтор виден в Airflow как `try_number` 2.
8. **OB-06.** Тест первым в `test_check_dashboards.py`: первая по `(gridPos.y, gridPos.x)` панель
   `pipeline-health.json` читает `ALERTS`; есть панель с `up == 0`; описание панели «WAL
   retained by the slot» называет `SlotWalHeldIdle`. Правка, ряд y=0: таблица «Firing alerts»
   (instant, format table)
   `count by (alertname, severity, cause) (ALERTS{alertstate="firing"}) or on() vector(0)` и stat
   «Targets down» `count(up == 0) or vector(0)`; старый stat «Firing alerts» (id 25) удалить
   (имя панели живёт в `docs/evidence.md:127`); прочие панели y+7; `(W5-T04)` убрать.
9. **Комментарии `observability/`** по шаблону `work/DC/r66_pattern.txt` (ID карточек,
   D-номера, «audit», «week N», даты): шапка `alerts.yml:1-6`, строки `:18,62,97,111,116,124-125`,
   `pipeline-health.json:676`, `mapping.yml:3,24`, `queries.yaml:2`, `trino.yml:5`. Смысл
   остаётся, номера ADR можно. Гейт (`:110-112`, `:124-128`) после P05: silver и gold
   сравниваются в покое, когда каждая gold-таблица перестроена после последнего коммита данных
   silver (снапшоты Iceberg); удалённый заказ сравнение больше не держит.
10. **Проверки и коммит.** `make check`, `make alerts-test`, `check_dashboards.py`, `reviewer`
    (код), цикл verify (`13-harness.md`, раздел 5), коммит
    `observability: alert rules without the project name, annotations and runbooks`. Затем
    запрос «ок» на HUP по шаблону `13-harness.md`, раздел 2; HUP; проверки после.

## Готово, когда

- [ ] новые кейсы шагов 3-5 и `test_alerts.py` записаны `FAILED` на HEAD (вывод в «Итог»);
      кейс 14-7.19 зелёный и `FAILED` на мутациях порога 240 и 190
- [ ] `uv run pytest tests/unit/test_alerts.py tests/unit/test_check_dashboards.py -q`
      -> без `failed`
- [ ] `make alerts-test` -> `SUCCESS: 16 rules found` и `SUCCESS` юнит-тестов
- [ ] `uv run --no-sync python scripts/obs/check_dashboards.py` -> `queries ok: 33`, те же 7
      `idle:`, rc 0
- [ ] `grep -rn 'lakehouse-' observability/prometheus/alerts.yml observability/grafana/dashboards/`
      -> пусто
- [ ] `grep -rnE "$(cat docs/planning/21-final-audit-2026-11-13/work/DC/r66_pattern.txt)"
      observability/` -> пусто (`work/` удаляет P14 по В-23: до того)
- [ ] `make check` -> exit 0; `reviewer` «принять» (с замечаниями); `make verify` -> `verify ok`
- [ ] после HUP: `curl -s 127.0.0.1:9090/api/v1/rules | python3 -c 'import json,sys; r=[x for g in
      json.load(sys.stdin)["data"]["groups"] for x in g["rules"]]; print(sum(1 for x in r if
      x["annotations"].get("runbook_url")), len(r))'` -> `16 16`; GET
      `/api/v1/status/runtimeinfo` -> `reloadConfigSuccess` true, `lastConfigTime` позже HUP;
      все правила `health: ok`
- [ ] Grafana: «Firing alerts» первым рядом Pipeline health (владелец глазами или «не проверено»)

## Не входит

- OB-04, OB-05, OB-08 (структура OPERATIONS, PF-27 `observability/README.md:14-16`, PF-30,
  PF-54, SLI), перенос абзацев OPERATIONS в ранбуки: P11. Оставить в «Итог» список ссылок
  ранбуков на OPERATIONS, которые P11 заменит текстом.
- Строки OPERATIONS о гейте `dq_checks` (`:850` «deleted order»): P11.
- ID карточек в docstring `scripts/obs/check_dashboards.py:1` (W4-T04, W6-T01): P10 (идёт до
  P11, список собирает сам); P11 правит там только ссылку на якорь OPERATIONS, если он переедет.
- OB-09 (сокет экспортера, PF-65): P07. Docker-команды с `lakehouse-` в ранбуках не трогать.

## Риски и откат

- `exp_annotations` даёт 70-100 строк `alerts_test.yml`: текст в двух местах, их сверяет promtool.
- После OB-01 первая ошибка DAG в первые 30 минут после старта Prometheus молчит; после сна
  молчит и настоящая 30 минут (видна в Airflow и на панели «Failed Airflow DAG runs»).
- `infra.json` без фильтра показывает и одноразовые контейнеры `make test-spark`, `dags-check`.
- Откат: `git revert`, `make alerts-test`, HUP по «ок».

## Расхождения с отчётом аудита

- Сверено: все `file:line` OB-01..OB-03, OB-06, OB-07; имена метрик и меток по живому
  Prometheus и `collector.py`; метка `spark-bronze` у образа и пяти контейнеров `make test-spark`.
  `lakehouse-silver-merge` за 7 дней в метриках нет: его метку несёт образ (вывод, не проба).
  `check_dashboards.py` повторён: `queries ok: 32`, rc 0.
- Новое: кейс `:280-293` без `service` после OB-02 упадёт (отчёт не назвал); у кейса
  `:156-170` в `exp_labels` добавляются `instance` и `job`.
- OB-07: серия отчёта `0+60x10 _x30 1800+60x10` отстаёт от `time()` на 660 с всё время, с
  `for: 1m` алерт загорелся бы на 42m; здесь серия, которая догоняет время.
- OB-06: удаление старого stat и `queries ok: 33` решены здесь (отчёт: 33 или 34).
- `make alerts-test`, `make check` не запускались (бриф); строгость annotations проверяет шаг 1.

## Итог

Исполнено 20.11.2026 (UTC) одной сессией на Opus (оркестратор), коммит `78b3754` (16 файлов).
Решения из аргумента `/task`: рутина сессии «да», В-06 «да» (команда HUP на «ок»). Код и тесты:
`implementer`, 2 брифа параллельно (А `alerts.yml`, `alerts_test.yml`, `test_alerts.py`; Б
дашборды, `test_check_dashboards.py`, комментарии `mapping.yml`, `queries.yaml`, `trino.yml`);
ранбуки и строки OPERATIONS: `docs-writer`; шаг 1, правки по ревью (до 20 строк в файле),
формулировки ранбуков и живые шаги: оркестратор; ревью `reviewer`, два круга.

| Критерий | Проверка | Результат |
|---|---|---|
| Вход | чтение, grep цитат, GET Prometheus | подтверждено, кроме трёх пунктов (ниже «Расхождения со входом»); номера OPERATIONS сдвинуты: Alerts `:822-836`, 10b `:1729`, Runbooks `:1754` |
| Шаг 1, строгость promtool | `annotations` только у `ScrapeTargetDown` в копии, `promtool test rules` | `FAILED ... exp: Annotations:{} got: Annotations:{runbook_url="docs/runbooks/containers.md", summary="Prometheus cannot scrape postgres-exporter"}`: сравнение строгое, `exp_annotations` у всех 37 `exp_labels` |
| Тесты на отказ | правила HEAD | `test_alerts.py` `34 failed, 34 passed`; promtool FAILED `AirflowDagFailed` 55m, `SparkNoBatch5m` 41m, `SparkRestartLoop` 5m (a), `ContainerRestarting` 3m (b) и 7m (c); (d), 14-7.19 и OB-07 43m зелёные; дашборды `3 failed, 34 passed` |
| Мутации | копии в scratchpad | `>= 240` FAILED 50m; `>= 190` FAILED 49m15s; `for: 0m` у stuck FAILED 41m; без `offset 30m` у `up` FAILED 55m; без `name=~".+-[0-9]+"` FAILED 7m; без фильтра имени `SparkRestartLoop` FAILED 10m (кейс (c) усилен по ревью до четырёх стартов) |
| Тесты пакета | `uv run pytest tests/unit/test_alerts.py tests/unit/test_check_dashboards.py -q` | `105 passed` |
| `make alerts-test` | | `SUCCESS: 16 rules found`, `SUCCESS` |
| Дашборды | `uv run --no-sync python scripts/obs/check_dashboards.py` | `queries ok: 33`, те же 7 строк `empty:`, rc 1 (на HEAD `queries ok: 32`, те же 7 `empty:`, rc 1: нет батча с данными больше 7 дней; пункт «7 `idle:`, rc 0» на стенде не достижим без реплея) |
| grep | `lakehouse-` в правилах и дашбордах; шаблон `r66_pattern.txt` по `observability/` | пусто; пусто |
| `make check` | после круга 2 | `2215 passed, 149 skipped`, exit 0 |
| Ревью | `reviewer` | круг 1 «принять с замечаниями» (1 среднее: фильтр имени `SparkRestartLoop` не закреплён кейсом; 4 низких: два неверных комментария про merge и `run`, цитата лога в `dq-checks.md`, пулы `iceberg_*`); все исправлены; круг 2 «принять» |
| Verify | цикл §5 перед коммитом | `verify ok`, full-отметка дерева `bc8574e0` |
| CI | `gh run watch 44815798932 --exit-status` | exit 0, `success` на `78b3754`, 12 job `success` |
| Паузы | `silver_upsert`, `dbt_build`, `dq_checks` на время цикла verify | сняты после коммита в порядке §5; silver без новых данных, `dbt_build` не запускался вручную |
| HUP (В-06) | `docker exec lakehouse-prometheus-1 kill -HUP 1` 2026-11-20T21:02:44Z по «ок» владельца | rc 0; до: 16 правил, `annotations` у 0, `lastConfigTime` 2026-11-18T06:21:48Z; после: скрипт «Готово, когда» `16 16`, `reloadConfigSuccess` true, `lastConfigTime` 2026-11-20T21:02:44Z, все правила `health: ok` без `lastError`, `offset 30m` в 1 правиле; горит `ContainerRestarting` на `lakehouse-airflow-scheduler-1` с новым `summary` (плановый стоп scheduler в цикле verify) |

Расхождения со входом:
- `docs/runbooks/catalog-cutover.md` в дереве нет (удалён с откатом на JDBC в P06): строки в
  таблице «Runbooks» для него нет.
- `check_dashboards.py` на HEAD: 7 `empty:` и rc 1, а не 7 `idle:` и rc 0 (условие данных, не
  кода). Критерий проверен как «33 запроса, те же 7 строк, ни одной новой».
- Номера строк OPERATIONS сдвинуты (см. таблицу). Живой `ContainerRestarting` в момент входа
  горел на `lakehouse-airflow-scheduler-1`: плановый стоп scheduler в цикле verify P08.

Отклонения от пакета:
- Новые кейсы promtool стоят в конце `alerts_test.yml` блоком, а не рядом со старыми кейсами.
- Таблица «Firing alerts» с трансформацией `organize` (скрыт `Time`, `Value` -> `count`);
  при пустом наборе одна строка с 0 без имени (так и написано в описании панели).
- В шапке `alerts.yml` «No Alertmanager» ссылается на ADR-015 и ADR-023 вместо `W4-D6`.
- `freshness.md`, шаг 6: что делать с пропавшей Variable, источники не говорят; фраза не
  написана.

Ссылки ранбуков на OPERATIONS, которые P11 заменит текстом:
- `docs/runbooks/airflow-dag-failed.md`: `../../OPERATIONS.md#airflow` на абзацы «Host sleep
  pauses the Docker VM», «Timeouts», «A red `dq_checks` task».
- `docs/runbooks/dq-checks.md`: `../../OPERATIONS.md#airflow`, абзац о красной задаче
  `dq_checks`.
- `docs/runbooks/containers.md`: `../../OPERATIONS.md#observability`, заметки экспортеров
  (`DOCKER_GID`, `COMPOSE_PROJECT_NAME`, healthcheck).

Не проверено: вид таблицы «Firing alerts» в Grafana (владелец глазами); кейсы containers.md шаги 3-4
(старт `kafka-exporter` и `lakekeeper` раньше зависимостей, stateful job после сна) взяты из
отчётов аудита, живьём не воспроизводились.

Замечено вне пакета: строки `SilverGoldNotCompared` и `GoldStaleAtRest` таблицы Alerts
OPERATIONS говорят про удалённый заказ и `B6` (P11, «Не входит»); в `infra.json` наложение
панелей (h 9 при шаге y 7), было до пакета.

Риски: первая ошибка DAG в первые 30 минут после старта Prometheus или после сна молчит (видна в
Airflow и на панели «Failed Airflow DAG runs»); `infra.json` без фильтра показывает и
одноразовые контейнеры `make test-spark`, `dags-check`.
