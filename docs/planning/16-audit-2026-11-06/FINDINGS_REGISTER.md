# Реестр находок аудита 06.11.2026

Часть аудита (`AUDIT_REPORT.md`). HEAD `f7eede8`. Порядок: по severity, внутри по значимости.
Итого 31 находка: 6 MEDIUM, 25 LOW; CRITICAL и HIGH для локальной лаборатории не найдено; для публичного развёртывания у F-08 и F-09
severity HIGH (столбец «Публично» в сводке).

Статусы: CONFIRMED (подтверждено кодом и живой пробой или однозначно кодом), PROBABLE (механизм
по коду, живьём не воспроизведён), NOT VERIFIED. «Известно» означает, что находка есть в аудите
30.10 (`docs/planning/15-audit-2026-10-30.md`, разделы 3 и 10) и осталась открытой. Каждую
находку подагентов оркестратор перепроверил по коду или пробой; где перепроверки не было, это
сказано в «Evidence». Итог прошёл независимую проверку Opus в свежем контексте; её поправки
внесены (F-07 переведена в LOW, уточнены F-01, F-21, F-25).

Шкала severity задания: CRITICAL компрометация, утечка критических секретов, необратимая потеря
данных; HIGH отказ важного компонента, систематическое искажение данных, невозможность пройти
основной путь; MEDIUM частичная деградация, пробел наблюдаемости, тестов или документации; LOW
мелочи. Complexity: LOW одна правка, MEDIUM несколько модулей, HIGH переработка механизма.

Принятые известные ограничения в статистику не входят (раздел в конце). Исключение F-06 (QA-03,
принято 30.10): включено повторно, потому что из-за этого пробела F-01 и F-03 автоматикой не
ловятся, а задание прямо требует сквозных тестов.

## Сводка

| ID | Находка | Severity | Публично | Complexity | Компонент | Статус |
|---|---|---|---|---|---|---|
| F-01 | Событие Asset `lake.silver` теряется, пока `dbt_build` на паузе; gold тихо отстаёт, сигнал через 6 ч | MEDIUM | MEDIUM | LOW | Airflow, dbt | CONFIRMED |
| F-02 | Superset (профиль `bi`) не запускается; BI целевой схемы нет | MEDIUM | MEDIUM | MEDIUM | Superset | CONFIRMED, известно ARCH-02 |
| F-03 | Отставание витрин от `fct_orders` после красного `dbt_build` не даёт постоянного сигнала | MEDIUM | MEDIUM | LOW | Airflow `dq_checks` | PROBABLE |
| F-04 | Bronze пропускает эпоху только по номеру; checkpoint и таблица на старте не сверяются | MEDIUM | MEDIUM | MEDIUM | Spark bronze | PROBABLE |
| F-05 | Ядро реплеера без поведенческого теста | MEDIUM | MEDIUM | MEDIUM | Реплеер, тесты | CONFIRMED |
| F-06 | Нет автоматического сквозного теста дальше silver (dbt, Airflow, дашборд) | MEDIUM | MEDIUM | MEDIUM | CI, тесты | CONFIRMED, известно QA-03 (принято, включено повторно) |
| F-07 | Браузер на `:9000` уводит на неопубликованный порт консоли MinIO; способ просмотра бакета описан только в ADR-004 | LOW | LOW | LOW | MinIO | CONFIRMED |
| F-08 | Общие учётки с максимальными правами у многих сервисов | LOW | HIGH | MEDIUM | Docker, безопасность | CONFIRMED, частично SEC-13 |
| F-09 | Пароль роли Debezium открытым текстом в REST и топике Connect | LOW | HIGH | LOW | Debezium | CONFIRMED |
| F-10 | `spark-orders-per-minute` работает на образе, которого нет под тегом | LOW | MEDIUM | LOW | Spark, Docker | CONFIRMED |
| F-11 | Признак «gold догнал silver» не учитывает `reviews` | LOW | LOW | LOW | Airflow `dq_checks` | CONFIRMED |
| F-12 | `dbt_build` и merge silver не исключают друг друга | LOW | LOW | MEDIUM | Airflow, dbt | PROBABLE |
| F-13 | Пары source-silver `dq_checks` не защищены от записи в источник во время сверки | LOW | LOW | LOW | Airflow `dq_checks` | PROBABLE |
| F-14 | `gold_expire_commands` строит список таблиц вне пула | LOW | LOW | LOW | Airflow maintenance | PROBABLE |
| F-15 | «Доставлен без даты доставки» в двух витринах считается по-разному | LOW | LOW | LOW | dbt | CONFIRMED |
| F-16 | Временные представления `opm_batch_<id>` не удаляются | LOW | LOW | LOW | Spark `orders_per_minute` | CONFIRMED (код) |
| F-17 | Отсутствующее nullable-поле молча обнуляет значение в silver | LOW | LOW | LOW | Spark silver | CONFIRMED (код) |
| F-18 | Контракт обещает `enum` и диапазоны, silver их не проверяет | LOW | LOW | LOW | Контракты, Spark | CONFIRMED (код) |
| F-19 | `REPLAY_LATE_RATIO > 0` переставляет итоговый статус заказа | LOW | LOW | LOW | Реплеер | CONFIRMED (код) |
| F-20 | Хостовый listener Kafka не работает, документация обещает 9092 | LOW | LOW | LOW | Kafka | CONFIRMED |
| F-21 | MinIO закреплён не на последнем теге, а документация называет его последним | LOW | MEDIUM | MEDIUM | MinIO | CONFIRMED (тег), CVE PROBABLE |
| F-22 | `minio` и `lakekeeper` работают от root; нет `cap_drop` и `no-new-privileges` | LOW | MEDIUM | MEDIUM | Docker | CONFIRMED, частично SEC-13 |
| F-23 | Устаревшие jar и dbt 1.10, нет процесса обновлений и сканирования | LOW | MEDIUM | MEDIUM | Зависимости | PROBABLE, частично SEC-09 |
| F-24 | Мёртвый mount `${DATA_DIR}:/data` у `oltp-replayer` | LOW | LOW | LOW | Docker, реплеер | CONFIRMED |
| F-25 | `.gitignore` из `.env*` закрывает только `.env`; нет `.dockerignore` | LOW | MEDIUM | LOW | Репозиторий | CONFIRMED |
| F-26 | 11 анонимных томов без контейнера | LOW | LOW | LOW | Docker | CONFIRMED |
| F-27 | После рестарта Docker порядок старта не соблюдается: kafka-exporter 8 рестартов | LOW | LOW | LOW | Docker | CONFIRMED |
| F-28 | Неточности документации: число job CI, README компонентов, порты, `make kafka-groups` | LOW | LOW | LOW | Документация | CONFIRMED |
| F-29 | Нет единой страницы для новичка: UI, входы, безопасность, troubleshooting | LOW | LOW | LOW | Документация | CONFIRMED |
| F-30 | Правило `/security-review` перед коммитом не встроено в цикл `/task` и гейты | LOW | LOW | LOW | Правила агентов | CONFIRMED |
| F-31 | CI: `checkout` без `persist-credentials: false`, pre-commit по тегам | LOW | LOW | LOW | CI | CONFIRMED |

## MEDIUM

### [F-01] Событие Asset `lake.silver` теряется, пока `dbt_build` на паузе

**Severity:** MEDIUM. **Complexity:** LOW. **Component:** Airflow (`silver_upsert` -> `dbt_build`), gold. **Status:** CONFIRMED.

**Evidence:**
- REST Airflow: `GET /api/v2/assets/events?order_by=-timestamp`: событие 22 от
  `2026-11-06T12:11:49Z` (источник `silver_upsert`, run `scheduled__2026-11-06T12:10:00+00:00`)
  имеет `created_dagruns: []`; все 21 событие до него создали run `dbt_build`. Последний run
  `dbt_build`: `asset_triggered__2026-10-29T18:22:29`.
- Код Airflow 3.3.2 в образе: `airflow/assets/manager.py:354`
  `dags_to_queue_from_asset = {ref.dag for ref in asset_model.scheduled_dags if not ref.dag.is_paused}`
  (вывод `grep -n is_paused` в контейнере scheduler).
- `scripts/chaos/silver-kill.sh:16,79`: DAG `dbt_build` ставится на паузу на время сценария 10b;
  `cleanup` (`:47-53`) снимает паузу, но `dbt_build` не запускает.
- Лог `dq_checks` run `scheduled__2026-11-06T12:15`, задача `reconcile_values`:
  `gold has not caught up with silver: the silver-gold pairs wait for dbt_build`,
  `dq gold_not_compared_runs=1`; задача success.
- `observability/prometheus/alerts.yml:119-122`: `SilverGoldNotCompared` при `>= 24` прогонах
  (около 6 ч работы `dq_checks`).
- `ARCHITECTURE.md:88-89`: dbt собирает gold «after every silver merge». `OPERATIONS.md:489-491`
  говорит только о ручном trigger DAG на паузе («stays queued»); что событие Asset при паузе
  потребителя теряется, не описано нигде, кроме частного случая сценария 10b
  (`OPERATIONS.md:1613-1614`, по отчёту подагента).

**Problem:** событие Asset, выпущенное, пока потребитель на паузе, не ставится в очередь и после
снятия паузы не воспроизводится. `ARCHITECTURE.md` обещает сборку после каждого merge, общего
правила в OPERATIONS нет. Регламент агентов часто ставит DAG на паузу (`13-harness.md`, раздел 2,
особые случаи B), поэтому ситуация штатная.

**Impact:** gold отстаёт от silver до следующего merge с событиями или ручного `make dbt-build`;
при остановленном реплее бессрочно. Все прогоны `dq_checks` зелёные, `warn` приходит через 6 ч.
06.11 gold пересобран ручным `make dbt-build` в 12:18 как штатный шаг цикла verify сессии
закрытия (`fct_orders$snapshots` 12:18:48), поэтому сейчас данные равны; Airflow сам бы его не
собрал. В UI Airflow `dbt_build` выглядит не запускавшимся с 29.10.

**Root Cause:** поведение Airflow с 2.10 (событие удовлетворяет расписание только активного DAG),
не учтённое в процедурах паузы. Уверенность высокая.

**Reproduction:** без записи в данные не воспроизводится; чтение уже случившегося:
`curl -s 'http://127.0.0.1:8090/api/v2/assets/events?order_by=-timestamp&limit=3'`.

**Recommended Fix Direction:** в OPERATIONS общее правило «пауза `dbt_build` теряет события
Asset; после снятия паузы запустить `dbt_build`, если silver менялся»; в `silver-kill.sh` и
процедурах паузы запуск `dbt_build` после снятия паузы; алерт на `gold_not_compared_runs` с
меньшим порогом в покое или на разницу `SILVER_UPDATED` и `GOLD_UPDATED`.

**Verification Criteria:** после паузы `dbt_build`, merge с событиями и снятия паузы в журнале
есть run `dbt_build`; либо алерт срабатывает в пределах выбранного окна; тест на текст процедуры.

### [F-02] Superset (профиль `bi`) не запускается

**Severity:** MEDIUM (против целевой схемы задания; для собственной архитектуры проекта это
заявленное ограничение). **Complexity:** MEDIUM. **Component:** Superset. **Status:** CONFIRMED,
известно ARCH-02 (аудит 30.10), открыто.

**Evidence:** `docker/compose.yaml`, сервис `superset`: том
`./superset/superset_config.py:/app/superset_config.py:ro`; `ls -la docker/superset` пуст;
`curl http://127.0.0.1:8088/health` нет соединения; `OPERATIONS.md:10` «not runnable today»;
`README.md`, строка статуса Superset `planned`; ADR-014 «optional». База `superset` в
`postgres-meta` создаётся init-скриптом, но не используется.

**Problem:** компонент описан в compose, README (таблица профилей с RAM) и порт-таблице
OPERATIONS, но не стартует: отсутствует обязательный конфиг. При `make up PROFILE=bi` Docker
создаст на месте файла каталог в дереве репозитория.

**Impact:** звено «Superset -> dashboard» целевой схемы отсутствует; BI фактически Grafana.
Пользователь по таблице профилей README ожидает рабочий профиль.

**Root Cause:** Superset отложен решением (ADR-014), а заготовка в compose осталась.

**Reproduction:** `ls docker/superset`; запуск профиля не нужен.

**Recommended Fix Direction:** решение владельца: либо минимальный `superset_config.py`,
подключение к Trino `lake_ro` пользователем с ACL как у `grafana`, один дашборд; либо убрать
сервис из compose и строку из таблицы профилей, оставив ADR.

**Verification Criteria:** `make up PROFILE=bi` даёт healthy, SQL Lab читает
`lake_ro.gold.fct_orders`; либо сервиса и упоминаний нет, тест compose это проверяет.

### [F-03] Отставание витрин от `fct_orders` после красного `dbt_build` без постоянного сигнала

**Severity:** MEDIUM. **Complexity:** LOW. **Component:** Airflow `dq_checks`, алерты.
**Status:** PROBABLE (по коду; живьём не воспроизводилось, нужен запуск сценария 9).

**Evidence:** `airflow/dags/dq_checks.py:253-255` (`gold_ready` из `GOLD_UPDATED` и
`SILVER_UPDATED`, то есть по `fct_orders`), `:329` `count_gold_run(compared=gold_ready)`;
отставание витрины даёт только `reconcile_gmv_compared=0` (`dq_checks.py:165-168,306`), у этого
gauge алерта нет (`OPERATIONS.md:634`); `AirflowDagFailed` (`alerts.yml:134-139`) гаснет через
30 мин; у `dbt_build` нет retries (`airflow/dags/dbt_build.py:3`); после упавшего теста витрины
остаются старыми (`OPERATIONS.md:1566-1567`, сценарий 9). Перепроверено оркестратором: строки
`dq_checks.py:250-256,327-330`.

**Problem:** если `dbt_build` упал после пересборки `fct_orders`, но до витрин, счётчик Б3 считает
gold сверенным, а витрины (`mart_daily_sales`, `mart_seller_performance`, `mart_delivery_sla`)
устаревают до следующего merge.

**Impact:** бизнес-дашборд показывает старые цифры без алерта дольше 30 минут.

**Root Cause:** признак готовности gold берётся от одной таблицы. Уверенность средняя.

**Reproduction:** `make chaos-break-dbt-test` без исправляющего прогона при остановленном
реплее (класс C, нужен «ок»); ожидание: `mart_daily_sales has not caught up`, `gold_not_compared_runs=0`.

**Recommended Fix Direction:** учитывать отставание витрин в счётчике Б3 или алерт на
`reconcile_gmv_compared == 0` в покое N прогонов подряд.

**Verification Criteria:** promtool-кейс и unit-тест: красный `dbt_build` после `fct_orders` даёт
рост счётчика или алерт.

### [F-04] Bronze пропускает эпоху только по номеру, без сверки checkpoint и таблицы

**Severity:** MEDIUM. **Complexity:** MEDIUM. **Component:** Spark `bronze_cdc_ingest`, восстановление.
**Status:** PROBABLE (механизм по коду и ADR; не воспроизведён).

**Evidence:** `DECISIONS.md:282-283` (sink пропускает эпоху, если последний снапшот того же
query id несёт равный или больший `epochId`); `streaming/spark_jobs/bronze_cdc_ingest.py:127-148`
без проверки соответствия checkpoint и таблицы на старте (перепроверено оркестратором); живьём один
query id, 181 append-снапшот, max epoch 180; учения Б6 копируют `checkpoints/` отдельно от
`pg_dump lakekeeper` (аудит 30.10, раздел 10).

**Problem:** если checkpoint старше таблицы (восстановлен из копии) или новее (таблица из старой
копии каталога), Spark пересчитает диапазоны offsets (`maxOffsetsPerTrigger=20000`), а sink
пропустит эпохи по номеру: offsets вне старых диапазонов тихо пропадут или эпохи, отмеченные
выполненными, в таблице не окажутся.

**Impact:** тихая потеря событий bronze при восстановлении; bronze единственная копия истории
дольше 24 ч retention. `verify` увидит дыру только в окне retention, `reconcile` позже через silver.

**Root Cause:** идемпотентность sink по номеру эпохи предполагает, что checkpoint и таблица
согласованы. Уверенность средняя.

**Reproduction:** Spark-тест по образцу `tests/unit/test_iceberg_sink.py`: эпохи 0-2, удалить
`offsets/1,2` и `commits/1,2`, добавить файл и запустить с другим `maxFilesPerTrigger`; ожидание:
часть строк не попадает в таблицу.

**Recommended Fix Direction:** в раннбук восстановления: bronze-checkpoint из копии не
восстанавливать, стартовать с нового (дубли поглощает silver); копировать checkpoint и каталог
только при остановленных bronze и silver; проверка на старте: последний `commits/N` равен max
`epochId` своего query id, иначе отказ.

**Verification Criteria:** Spark-тест рассогласования краснеет до правки и зеленеет после;
раннбук Б6 содержит правило.

### [F-05] Ядро реплеера без поведенческого теста

**Severity:** MEDIUM. **Complexity:** MEDIUM. **Component:** `oltp/replayer`, тесты. **Status:** CONFIRMED.

**Evidence:** `tests/unit/test_replay_evolution.py:62-93`: `FakeConn` только записывает текст SQL,
`commit()` пустой (перепроверено оркестратором); по отчёту агента `SCHEDULE`, `promote_initial` и
`step()` вне evolution-тестов не вызываются; гарантия `oltp/replayer/replay.py:5-6` (claim,
запись и `emitted_at` в одной транзакции) тестом не держится.

**Problem:** транзакционность и идемпотентность шага реплея проверяются только smoke и живым
прогоном.

**Impact:** регресс (например, `emitted_at` после `commit()`) пройдёт `make check`; повтор шага
после сбоя может дать двойное событие в источнике или потерянное.

**Root Cause:** тесты реплеера построены на подделке соединения.

**Reproduction:** мутация «перенести `update replay.schedule set emitted_at` после `commit()`»,
затем `uv run pytest tests/unit -q`: ожидается зелёный (агентом не запускалось, оценка по коду).

**Recommended Fix Direction:** интеграционный тест на Postgres CI (`RECONCILE_TEST_DSN`, как
`test_reconcile_postgres.py`): `load` на sample, исключение посреди батча, проверка отката и
равного состояния после повтора.

**Verification Criteria:** мутация выше краснеет; тест идёт в CI с `FAIL_ON_SKIP=1`.

### [F-06] Нет автоматического сквозного теста дальше silver

**Severity:** MEDIUM. **Complexity:** MEDIUM. **Component:** CI, тесты. **Status:** CONFIRMED,
известно QA-03 (принято 30.10).

**Evidence:** `.github/workflows/smoke.yml:40-58`: `make secrets`, `make bootstrap`,
`make replay-burst SECONDS=60`, `make verify`, повторный `make bootstrap`; ни dbt, ни профиля
`orchestrate`, ни проверки дашборда. Последний smoke 42216951898 на `bccd194` success (reconcile
7 из 7 на sample).

**Problem:** путь gold, Asset-триггер, `dq_checks` и SQL дашборда проверяются только руками на
живом стенде владельца.

**Impact:** регресс в dbt-моделях, DAG или ACL Trino для `grafana` не ловится до ручного прогона;
F-01 и F-03 автоматикой не обнаружились бы.

**Root Cause:** ресурсный бюджет runner и решение 30.10.

**Reproduction:** чтение `smoke.yml`.

**Recommended Fix Direction:** в smoke после `make verify`: `make dbt-build`, сверка GMV
Postgres против `mart_daily_sales`, `check_dashboards.py` по `marketplace.json`; профиль
`orchestrate` по желанию.

**Verification Criteria:** smoke краснеет на мутации модели dbt или правила `rules.json`.

## LOW

### [F-07] Браузер на `:9000` уводит на неопубликованный порт консоли MinIO

**Severity:** LOW (при первичной оценке MEDIUM; понижено при независимой проверке: отсутствие
консоли решено и описано в ADR-004). **Complexity:** LOW. **Component:** MinIO. **Status:** CONFIRMED.

**Evidence:** `DECISIONS.md:51,58` (ADR-004): MinIO «removed the web console», «administer it
with `mc` since there is no console»; `docker/compose.yaml`, сервис `minio`: `command: server /data`,
опубликован только `9000`; лог `docker logs lakehouse-minio-1`:
`WebUI: http://172.18.0.8:46311 http://127.0.0.1:46311` (порт меняется при каждом старте: 46671,
41185, 35639, 35807, 46311); `curl -A Mozilla http://127.0.0.1:9000/` даёт `307` на
`http://127.0.0.1:46311/`, который с хоста недоступен; в README и OPERATIONS способ осмотреть
бакет не описан.

**Problem:** собранный из исходников MinIO всё же поднимает урезанный браузер объектов на
случайном порту, и браузер на `:9000` редиректит туда; объектное хранилище можно осмотреть только
через Trino `$files`, `mc` с ключами или файловую систему контейнера.

**Impact:** пользователь не может открыть бакет в браузере; переход по ссылке ведёт в никуда.

**Root Cause:** нет `--console-address` и публикации порта, нет и `MINIO_BROWSER=off`.

**Reproduction:** `curl -s -o /dev/null -A Mozilla -w '%{http_code} %{redirect_url}' http://127.0.0.1:9000/`.

**Recommended Fix Direction:** `--console-address :9001` и порт `${BIND_IP}:9001:9001`, либо
`MINIO_BROWSER=off` и строка в OPERATIONS «консоли нет, смотреть через Trino `$files` или `mc`».
Учесть, что консоль последних community-версий урезана до браузера объектов.

**Verification Criteria:** `curl http://127.0.0.1:9001` даёт 200, либо 9000 не редиректит и
OPERATIONS описывает способ просмотра.

### [F-08] Общие учётки с максимальными правами

**Severity:** LOW (лаборатория) / HIGH (публично). **Complexity:** MEDIUM. **Component:** Docker,
безопасность. **Status:** CONFIRMED; частично известно SEC-13.

**Evidence:** root-ключи MinIO (`MINIO_ROOT_USER/PASSWORD` из `S3_ACCESS_KEY/S3_SECRET_KEY`,
`docker/compose.yaml`, сервис `minio`) используют spark-bronze, spark-silver, spark-orders-per-minute,
trino (и каталог `lake_ro`), warehouse Lakekeeper и `docker/airflow/airflow.env:40-41`, который
получают и api-server, и dag-processor, хотя им ключи не нужны; суперпользователь `META_USER` у
Airflow, Lakekeeper, JDBC-каталога и в env Trino ради отката; владелец OLTP у `dq_checks`
(`airflow.env:49-50`) и postgres-exporter.

**Problem:** нет разделения прав: любой сервис имеет полный доступ к lake и метаданным.

**Impact:** компрометация любого контейнера даёт полный доступ к данным и каталогу; при публикации
недопустимо.

**Root Cause:** упрощение лаборатории. **Reproduction:** чтение compose и `airflow.env`.

**Recommended Fix Direction:** политики MinIO на сервис (read-only для Trino `lake_ro`), отдельные
роли Postgres (read-only для `dq_checks` и exporter), не передавать S3-ключи api-server и dag-processor.

**Verification Criteria:** `trino --user grafana` не может писать даже при ошибке ACL; exporter
работает под ролью без записи.

### [F-09] Пароль роли Debezium открытым текстом в REST и топике Connect

**Severity:** LOW / HIGH (публично). **Complexity:** LOW. **Component:** Debezium, Kafka Connect.
**Status:** CONFIRMED.

**Evidence:** `connect/register.sh:58-65` подставляет пароль через `envsubst`; живая проба
`GET http://127.0.0.1:8083/connectors/shop-connector/config` без аутентификации: ключ
`database.password` есть, значение не placeholder `${...}` (длина 32, значение не выводилось);
тот же конфиг лежит в топике `connect-configs` (Kafka без аутентификации).

**Problem:** пароль роли с правом REPLICATION читается любым клиентом REST или Kafka.

**Impact:** доступ к полному потоку изменений источника.

**Root Cause:** конфиг коннектора с литералом. **Reproduction:** проба выше с маскированием значения.

**Recommended Fix Direction:** `EnvVarConfigProvider` или `FileConfigProvider` Kafka Connect
(`${env:DEBEZIUM_PASSWORD}`), имена ключей сверить по документации Connect 4.2.

**Verification Criteria:** `GET .../config` показывает ссылку, а не значение; коннектор RUNNING.

### [F-10] `spark-orders-per-minute` работает на образе, которого нет под тегом

**Severity:** LOW / MEDIUM. **Complexity:** LOW. **Component:** Spark, Docker. **Status:** CONFIRMED.

**Evidence:** `docker ps`: образ контейнера `7037a848362b` (id, не тег), контейнер создан
2026-10-23; `lakehouse/spark:dev` = `sha256:72e423bd...`, собран 2026-10-29T16:05:14Z; по отчёту
агента файлы задачи (`orders_per_minute.py`, `metrics.py`, `progress.py`, `settings.py`,
контракты) совпадают с HEAD по md5, отличаются `run-job.sh`, `catalog.py`, `bronze_cdc_ingest.py`,
`offsets.py`, `silver_upsert.py`, нет `maintenance.py`. Так же `lakehouse-lakekeeper-bootstrap-1`
на `025cd8f2f679`.

**Problem:** запущенный код не равен ни тегу, ни (частично) HEAD; образ не восстановить.

**Impact:** сейчас поведение задачи равно HEAD; риск в следующем рестарте и в доказательствах
(«что запущено»).

**Root Cause:** `make start` пересобирает тег и пересоздаёт только `core` и `query`; профиль
`stateful` не пересоздаётся.

**Reproduction:** `docker ps --format '{{.Names}} {{.Image}}'`.

**Recommended Fix Direction:** после `make start` выполнять `make up PROFILE=stateful` (класс C);
`make report` сравнивает `.Image` с id тега для всех `lakehouse/*`.

**Verification Criteria:** у всех контейнеров `lakehouse/*` образ равен id текущего тега.

### [F-11] Признак «gold догнал silver» не учитывает `reviews`

**Severity:** LOW. **Complexity:** LOW. **Component:** Airflow `dq_checks`. **Status:** CONFIRMED.

**Evidence:** `airflow/dags/lakehouse/reconcile.py:171-177`: `SILVER_UPDATED` берёт
`orders`, `order_items`, `payments` (перепроверено); `mart_seller_performance.sql:24-30`
использует отзывы (`avg_review_score`).

**Problem / Impact:** merge, менявший только отзывы, при потерянном событии или упавшем dbt
оставляет `avg_review_score` устаревшим без сигнала.

**Recommended Fix Direction:** добавить `reviews` в признак свежести. **Verification Criteria:**
unit-тест: свежий `silver.reviews` при старом gold даёт «не догнал».

### [F-12] `dbt_build` и merge silver не исключают друг друга

**Severity:** LOW. **Complexity:** MEDIUM. **Component:** Airflow, dbt. **Status:** PROBABLE.

**Evidence:** `dbt_build.py:27` пул `gold_writers`, `silver_upsert.py:66` пул `lake_writers`
(перепроверено); по отчёту агента перекрытие живьём 2026-10-23: dbt_build 18:00:32-18:05:46 и
merge 18:05:00-18:05:48 (прогон успешен); `relationships` в gold severity error
(`dbt/models/marts/_core.yml:41-44`) против обоснования `warn` в staging (`_staging.yml:1-6`).

**Problem / Impact:** dbt читает silver разными снапшотами во время merge: ложный красный тест,
пропуск витрин (далее F-03).

**Recommended Fix Direction:** сериализовать `dbt_build` с merge (общий пул) или понизить
gold-relationships до `warn` с тем же обоснованием. **Verification Criteria:** тест DAG на пул.

### [F-13] Пары source-silver `dq_checks` не защищены от записи в источник во время сверки

**Severity:** LOW. **Complexity:** LOW. **Component:** Airflow `dq_checks`. **Status:** PROBABLE.

**Evidence:** по отчёту агента позиция CDC перечитывается только перед GMV (`dq_checks.py:169`),
пары `source_silver` (`:227-238`) и `silver_matches_postgres` (`:117-138`) опираются на `at_rest`,
прочитанный раньше; окно около 8 с (`dq reconcile_seconds=7.7`). Не перепроверено живьём.

**Impact:** ложный красный `dq_checks` и `AirflowDagFailed`, если burst начнётся внутри окна.

**Recommended Fix Direction:** перечитывать `CDC_PROGRESS` после пар и давать `in flight`, как
для GMV. **Verification Criteria:** unit-тест с событийной подделкой CDC.

### [F-14] `gold_expire_commands` строит список таблиц вне пула

**Severity:** LOW. **Complexity:** LOW. **Component:** Airflow `iceberg_maintenance`. **Status:** PROBABLE.

**Evidence:** по отчёту агента `iceberg_maintenance.py:59-63` без пула, пул только у mapped-задач
(`:76-81`); dbt-trino создаёт и удаляет `mart_daily_sales__dbt_tmp`.

**Impact:** при `expire_and_compact` во время dbt `expire` получает удалённую таблицу: 3 попытки и
ложный `AirflowDagFailed`. **Recommended Fix Direction:** листинг в пуле `gold_writers` или
фильтр `__dbt_tmp`. **Verification Criteria:** тест DAG.

### [F-15] «Доставлен без даты доставки» в двух витринах считается по-разному

**Severity:** LOW. **Complexity:** LOW. **Component:** dbt. **Status:** CONFIRMED.

**Evidence:** `dbt/models/marts/mart_delivery_sla.sql:7` `count_if(is_delivered and not is_late)`
и `mart_seller_performance.sql:75` `count_if(is_delivered and is_late)`: при `is_late` null заказ
не попадает ни в on-time, ни в late (перепроверено); по пробе агента таких заказов 8.

**Impact:** `late_rate + on_time_rate` не равно 1 для этих групп; определение не описано в
`_marts.yml`. **Recommended Fix Direction:** описать правило или выровнять (null как «нет даты»).
**Verification Criteria:** singular-тест или описание в `_marts.yml`.

### [F-16] Временные представления `opm_batch_<id>` не удаляются

**Severity:** LOW. **Complexity:** LOW. **Component:** Spark `orders_per_minute`. **Status:** CONFIRMED (код), рост памяти PROBABLE.

**Evidence:** `streaming/spark_jobs/orders_per_minute.py:96-97` `createOrReplaceTempView(f"opm_batch_{batch_id}")`,
`dropTempView` в `streaming/` нет (grep пуст).

**Impact:** каталог сессии постоянно работающего драйвера растёт на план каждого непустого батча.
**Recommended Fix Direction:** фиксированное имя или `dropTempView` в `finally`.
**Verification Criteria:** unit-тест: N батчей не увеличивают `spark.catalog.listTables()`.

### [F-17] Отсутствующее nullable-поле молча обнуляет значение в silver

**Severity:** LOW. **Complexity:** LOW. **Component:** Spark silver. **Status:** CONFIRMED (код), поведение описано.

**Evidence:** `streaming/spark_jobs/silver_upsert.py:109-112`: `type_mismatch` требует
`_fields[c].isNotNull()`, для отсутствующего поля это ложь; `update set *` пишет null
(перепроверено); `contracts/README.md:34-35` описывает это, а `contracts.py:84` утверждает
«Debezium sends every column».

**Impact:** удаление или переименование nullable-колонки в источнике обнуляет значение при каждом
следующем изменении, без quarantine. **Recommended Fix Direction:** причина `missing_field` для
`op != d`. **Verification Criteria:** Spark-тест с payload без колонки уходит в quarantine.

### [F-18] Контракт обещает `enum` и диапазоны, silver их не проверяет

**Severity:** LOW. **Complexity:** LOW. **Component:** контракты, Spark. **Status:** CONFIRMED (код).

**Evidence:** `contracts/silver/orders.json`, `payments.json` содержат `enum`; в
`streaming/spark_jobs/contracts.py` нет обработки `enum`, `minimum`, `maximum` (grep пуст);
`SILVER_TYPES` допускает `decimal(p,s)` при любом p при wire `double`.

**Impact:** сейчас защищает CHECK источника; при расширении контракта нарушение не попадёт в
quarantine. **Recommended Fix Direction:** проверять или пометить поля справочными; отказ
`number` при p > 15. **Verification Criteria:** тест контракта.

### [F-19] `REPLAY_LATE_RATIO > 0` переставляет итоговый статус заказа

**Severity:** LOW. **Complexity:** LOW. **Component:** реплеер. **Status:** CONFIRMED (код, по отчёту агента; не перепроверено).

**Evidence:** `oltp/replayer/replay.py:197-205` откладывает `delivered` на
`REPLAY_LATE_DELAY_SECONDS` (300), `load.py:86-92` ставит итоговый статус на t3+1 мин; в
`data/raw` 6 заказов `canceled` с датой доставки.

**Impact:** при chaos 4 такой заказ остаётся `delivered` в `shop` и в витрине отмен; CDC честно
повторяет источник. **Recommended Fix Direction:** не откладывать `delivered`, если есть более
позднее событие статуса. **Verification Criteria:** unit-тест расписания.

### [F-20] Хостовый listener Kafka не работает

**Severity:** LOW. **Complexity:** LOW. **Component:** Kafka. **Status:** CONFIRMED (конфиг и порт; реальный клиент не запускался).

**Evidence:** `docker/compose.yaml`, сервис `kafka`: `KAFKA_ADVERTISED_LISTENERS ... HOST://localhost:29092`,
публикация `127.0.0.1:9092 -> 29092`; проба `/dev/tcp/127.0.0.1/29092`: `Connection refused`;
`OPERATIONS.md:33` «kafka 9092».

**Impact:** клиент с хоста получает в метаданных `localhost:29092` и не подключается; в репозитории
такого клиента нет. **Recommended Fix Direction:** `HOST://localhost:9092`.
**Verification Criteria:** `kcat -b 127.0.0.1:9092 -L` с хоста перечисляет топики.

### [F-21] MinIO закреплён не на последнем теге

**Severity:** LOW / MEDIUM. **Complexity:** MEDIUM. **Component:** MinIO. **Status:** CONFIRMED (тег), CVE PROBABLE.

**Evidence:** `git ls-remote --tags https://github.com/minio/minio 'RELEASE.2025-1*'` даёт
`RELEASE.2025-10-15T17-29-55Z`; закреплён `RELEASE.2025-09-07T16-13-09Z` (`docker/compose.yaml`);
ADR-004 (`DECISIONS.md:53-54`, проверка 2026-09-21) и `README.md:51` называют его последним
community-релизом; по отчёту агента runtime `go1.24.6`.
CVE-2025-62506 (политики service accounts и STS) по памяти агента, офлайн не проверено; в стенде
используются только root-ключи.

**Recommended Fix Direction:** решение владельца о переходе; `govulncheck -mode=binary`;
поправить формулировку «последний». **Verification Criteria:** запись в ADR-026 с датой проверки.

### [F-22] `minio` и `lakekeeper` работают от root; нет `cap_drop`, `no-new-privileges`

**Severity:** LOW / MEDIUM. **Complexity:** MEDIUM. **Component:** Docker. **Status:** CONFIRMED; частично известно SEC-13.

**Evidence:** `docker top lakehouse-minio-1` и `lakehouse-lakekeeper-1`: USER root
(перепроверено); в `docker/minio/Dockerfile` и `oltp/Dockerfile` нет `USER`; по отчёту агента
`CapDrop` и `SecurityOpt` пусты у всех 21 контейнера.

**Recommended Fix Direction:** `USER` в Dockerfile (MinIO с `chown` тома), `cap_drop: [ALL]` и
`security_opt: [no-new-privileges:true]` где возможно. **Verification Criteria:** `docker top`
без root, кроме обоснованных.

### [F-23] Устаревшие jar и dbt 1.10, нет процесса обновлений и сканирования

**Severity:** LOW / MEDIUM. **Complexity:** MEDIUM. **Component:** зависимости. **Status:** PROBABLE; частично известно SEC-09.

**Evidence:** `streaming/Dockerfile:18,21`: `kafka-clients-3.4.1.jar`, `aws-java-sdk-bundle-1.12.262.jar`
(SDK v1); `dbt ls` печатает «This version of dbt is deprecated and no longer receives regular
patches» (dbt 1.10.23); в `.github/` нет dependabot или renovate; по отчёту агента pydantic в
образах 2.14.1 против 2.13.5 в `uv.lock` (транзитивные pip без хэшей).

**Impact:** закрепление по digest замораживает уязвимости; эксплуатируемость в стенде не оценена.
**Recommended Fix Direction:** Renovate по digest и SHA; `trivy image` и `uvx pip-audit` в CI;
план перехода dbt. **Verification Criteria:** отчёт сканера в CI.

### [F-24] Мёртвый mount `${DATA_DIR}:/data` у `oltp-replayer`

**Severity:** LOW. **Complexity:** LOW. **Component:** Docker, реплеер. **Status:** CONFIRMED.

**Evidence:** `.env.example:5` `DATA_DIR=./data`; путь разрешается от `docker/`, получается
`docker/data` (каталог root, пуст: `ls -la docker/`); контейнер запускает `start`
(`oltp/Dockerfile:19` по отчёту агента), CSV читает только `load`.

**Recommended Fix Direction:** убрать mount и `DATA_DIR` или `../data`. **Verification Criteria:**
`docker/data` не создаётся.

### [F-25] `.gitignore` закрывает только `.env`; нет `.dockerignore`

**Severity:** LOW / MEDIUM. **Complexity:** LOW. **Component:** репозиторий. **Status:** CONFIRMED.

**Evidence:** `.gitignore:1` `.env`: из семейства `.env*` закрыт только сам `.env` (всего в
`.gitignore` 20 записей); копия вида `.env.bak` (рекомендована REL-04) не закрыта;
`.dockerignore` нет ни в одном контексте сборки (`.env` в контексты не попадает).

**Recommended Fix Direction:** `.env*` и `!.env.example`; `.dockerignore` с `__pycache__`.
**Verification Criteria:** `git check-ignore .env.bak` отвечает путём.

### [F-26] 11 анонимных томов без контейнера

**Severity:** LOW. **Complexity:** LOW. **Component:** Docker. **Status:** CONFIRMED.

**Evidence:** `docker volume ls`: 16 анонимных томов; по `docker system df -v` (агент) 11 без
ссылок, около 44 МБ: VOLUME образов kafka и connect после удаления контейнеров без `-v`.

**Recommended Fix Direction:** именованные тома для VOLUME образа connect или запись в
OPERATIONS; чистка требует «ок» (blast radius). **Verification Criteria:** `docker volume ls -f dangling=true` пуст.

### [F-27] После рестарта Docker порядок старта не соблюдается

**Severity:** LOW. **Complexity:** LOW. **Component:** Docker. **Status:** CONFIRMED.

**Evidence:** `docker inspect`: `kafka-exporter` RestartCount 8, `lakekeeper` 1, оба healthy;
HANDOFF 06.11: `ContainerRestarting` по `kafka-exporter`.

**Impact:** шум алерта после каждого рестарта хоста. **Recommended Fix Direction:** описать в
OPERATIONS или подавить алерт первые минуты. **Verification Criteria:** нет алерта после рестарта.

### [F-28] Неточности документации

**Severity:** LOW. **Complexity:** LOW. **Component:** документация. **Status:** CONFIRMED.

**Evidence:**
- `README.md:130,187` «five jobs», в `.github/workflows/ci.yml` шесть (`alerts-test:` на `:91`);
  таблица `OPERATIONS.md:1002-1010` без `alerts-test`.
- `observability/README.md:5-9`: «Kafka Connect (JMX) lands with W4-T01b», «rules land with W4-T05»;
  в `prometheus.yml` уже есть `kafka-connect` и `spark-orders-per-minute`, правил 15.
- `airflow/README.md:8-11` описывает 4 DAG из 5 (нет `iceberg_orphans`).
- `README.md:120` `PASS=51 WARN=0` от 17.10 в статусе `measured`; 06.11 `PASS=79 WARN=4`.
- `OPERATIONS.md:27-46` перечисляет `superset 8088` и `kafka-ui 8085` без пометки «не запущен».
- Lakekeeper UI `http://127.0.0.1:8181/ui/` (200) нигде не описан.
- `OPERATIONS.md:122` `make kafka-groups # consumer groups and lag (connect only ...)`: живьём
  команда описывает только пустую группу `console-consumer-*`, группу Connect (тип `connect`) не
  показывает (`kafka-groups.sh --list` её видит).
- `docs/evidence.md:168` `make check` 825 passed (29.10, датировано); 06.11 `make test` 1801 passed.

**Recommended Fix Direction:** одна правка `docs-writer` по списку. **Verification Criteria:** grep
по каждому пункту.

### [F-29] Нет единой страницы для новичка

**Severity:** LOW. **Complexity:** LOW. **Component:** документация. **Status:** CONFIRMED.

**Evidence:** README без таблицы UI и способов входа (grep `login|password` пуст); безопасность
только в `OPERATIONS.md:267-327`; слова troubleshooting нет, есть 6 раннбуков; адреса UI и входы
разбросаны по OPERATIONS.

**Recommended Fix Direction:** раздел README «Explore the stack» по образцу
`LOCAL_ACCESS_GUIDE.md` (на английском, без паролей). **Verification Criteria:** новичок по README
открывает все UI.

### [F-30] Правило `/security-review` перед коммитом не встроено в цикл

**Severity:** LOW. **Complexity:** LOW. **Component:** правила агентов. **Status:** CONFIRMED.

**Evidence:** `docs/agent-rules.md:78`, `docs/planning/03-agent-tooling.md:32,41,62` требуют
`/security-review` перед коммитом; в `.claude/skills/task/SKILL.md` и `docs/planning/13-harness.md`
его нет (grep пуст); гейт `guard.py` проверяет только verify, check и вердикт `reviewer`.

**Recommended Fix Direction:** включить шаг в `/task` и раздел 5 регламента или убрать требование
(правка правил: класс C). **Verification Criteria:** один источник правила.

### [F-31] CI: `checkout` без `persist-credentials: false`, pre-commit по тегам

**Severity:** LOW. **Complexity:** LOW. **Component:** CI. **Status:** CONFIRMED.

**Evidence:** `.github/workflows/ci.yml:38-41`: в блоке `with` только `fetch-depth: 0`, grep
`persist-credentials` по `.github/workflows` пуст; `.pre-commit-config.yaml` `rev:` по тегам (по
отчёту агента). Токен
`contents: read`, поэтому риск мал. **Recommended Fix Direction:** `persist-credentials: false`,
`rev` по SHA. **Verification Criteria:** `test_workflows.py` проверяет флаг.

## Известное и принятое, не считается в статистике

Подтверждено живьём в этом аудите и осталось как было: SEC-06 (`docker.sock` на запись у
scheduler, ADR-011), SEC-07 (Trino, Connect, Lakekeeper, Kafka, Airflow без аутентификации;
Lakekeeper `authz-backend: allow-all`), SEC-10 (`change_me` принимается), REL-09
(`max_slot_wal_keep_size=-1`), ARCH-03 (простой дольше 24 ч: bronze падает громко,
`failOnDataLoss=true`), DATA-04, DATA-07, MODEL-01 (D18), QA-02 (Spark-тесты вне гейта коммита).
Деньги на проводе как `double` (`decimal.handling.mode=double`) приняты в ADR-020; отпечатки
Postgres и silver равны, GMV равен до копейки, дефекта нет.
