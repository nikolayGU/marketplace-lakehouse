# 17. Исправления по аудиту 06.11.2026 (P1)

Статус: закрыто 06.11 16:31 UTC («Итог» в конце); push не сделан, ждёт «ок». Начато 06.11 ~14:20 UTC. Основание: `docs/planning/16-audit-2026-11-06/` (находки
F-01..F-31, roadmap в разделе 10 `AUDIT_REPORT.md`). «ок» владельца 06.11 ~14:15 UTC: «да ок на
всё начни вносить правки необходимы и подключай mcp superset если необходимо» в ответ на четыре
пункта: (1) Superset оживить, (2) действия класса C из P1 (рестарт MinIO, Kafka,
`make up PROFILE=stateful`), (3) живая проверка `make replay-burst SECONDS=30`, (4) строка аудита в
индексе и коммиты. Push в `origin` в «ок» не входил.

Дашборд Superset кладётся в репозиторий как файлы и импортируется при старте: так он
воспроизводим с чистого клона. MCP Superset сначала был признан ненужным; владелец 06.11 ~14:30
UTC решил: «настрой и подключи MCP для Superset». Поэтому в К2 добавлен встроенный MCP-сервис
Superset 6.1 (`superset.mcp_service`, extra `fastmcp<4.0,>=3.1.0`): сервис compose `superset-mcp`
на `${BIND_IP}:5008`, локальный режим `MCP_DEV_USERNAME=admin` (как Airflow без логина, D12; для
не-loopback развёртывания обязателен JWT). Подключение к Claude Code по решению владельца
(«mcp ставим официальный в claude code в репозиторий не постим его настройки»): только локально,
`claude mcp add --transport http --scope local superset http://127.0.0.1:5008/mcp` (запись в
`~/.claude.json` этого проекта, выполнено 06.11 15:05 UTC); `.mcp.json` в репозиторий не кладём,
он в `.gitignore`. Права MCP не шире базы `Lakehouse (Trino lake_ro)`: пользователь Trino
`superset` с ACL как у `grafana`, `allow_dml: false`.

## Карточки

| # | Находки | Что | Кто | Класс |
|---|---|---|---|---|
| К1 | F-01, F-03 | `dq_checks`: счётчик прогонов «в покое, а gold или витрины отстают» и алерт на 2 прогона; `silver-kill.sh` запускает `dbt_build` после снятия своей паузы | `implementer` | B (DAG, алерты), пауза `dq_checks` на время правки |
| К2 | F-02, F-07, F-20 | Superset на Trino `lake_ro` (образ с драйверами, конфиг, одноразовый init, пользователь Trino `superset` с ACL как у `grafana`, дашборд из файлов); консоль MinIO на `${BIND_IP}:9001`; listener Kafka для хоста `localhost:9092` | `implementer` | B (compose, Dockerfile, ACL Trino) |
| К3 | F-07, F-20, F-10, F-02 | живое применение: пауза трёх DAG, пересоздание `kafka` и `minio`, `make up PROFILE=stateful`, `make up PROFILE=bi`, проверки | оркестратор | C, «ок» получен |
| К4 | F-01, F-28, F-29 | документация: правило паузы и событий Asset, алерт, Superset, консоль MinIO, порты, число job CI, README компонентов, раздел README «Explore the stack» | `docs-writer` | A |
| К5 | живой E2E | `make replay-burst SECONDS=30`, новый заказ от Postgres до Grafana и Superset через Airflow без ручных шагов | оркестратор | C, «ок» получен |

Порядок: К1 и К2 параллельно (разные файлы), `make check`, К3, ревью К1 и К2 (`reviewer`, по
диффу каждой), цикл verify, коммиты К1 и К2; затем К4, коммит; затем К5, запись результата,
коммит. Не больше двух кругов исправлений на карточку.

## Готово, когда

- К1: unit-тесты: прогон в покое с отставшим gold или витриной увеличивает счётчик, догнавший
  обнуляет, прогон не в покое обнуляет; promtool-кейс алерта; тест `silver-kill.sh` на запуск
  `dbt_build` после снятия паузы; `make check`, `make dags-check`, `make alerts-test` зелёные.
- К2: `make check` зелёный (правила compose, pinning, ACL Trino, hadolint matrix); живьём
  `superset` healthy, дашборд импортирован, SQL графиков возвращает строки от пользователя
  `superset`, а `superset` не читает `lake_ro.silver` и `lake`; `curl http://127.0.0.1:9001` 200;
  клиент Kafka с хоста перечисляет топики по `127.0.0.1:9092`; bronze и коннектор живы, `make
  reconcile` 7 из 7.
- К4: каждое утверждение документа сверено с кодом или выводом команды.
- К5: новый заказ burst виден в Kafka, bronze, silver, gold, в SQL Grafana и в данных графика
  Superset; run `dbt_build` создан событием Asset; `dq_checks` после burst без расхождений.

## Риски

- Пересоздание Kafka и MinIO останавливает CDC и запись bronze на десятки секунд: DAG на паузе,
  после старта проверка offsets bronze и reconcile.
- Память: Superset добавляет до 1.25 ГБ к 8.5 ГБ занятых из 11.7; при нехватке остановить профиль
  `stateful` на время проверки.
- Сборка образа Superset тянет пакеты из PyPI: версии закреплены `==`.

## Итог 06.11.2026

| # | Коммит | Что | Доказательство |
|---|---|---|---|
| К1 | `85f84bb` | `dq_checks`: счётчик `dq_gold_stale_runs` (в покое, а последний снапшот данных silver новее самой старой пересборки табличных витрин, или `mart_daily_sales` отстаёт от `fct_orders`), gauge `lakehouse_dq_gold_stale_runs`, алерт `GoldStaleAtRest` (>= 2); `silver-kill.sh` запускает `dbt_build` после снятия своей паузы | `make check` 1852 passed; `make alerts-test` 16 правил; ревью Opus 3 прохода: «принять с замечаниями» (2 средних, 4 низких), круг 1 «принять с замечаниями» (2 низких, тесты дописал оркестратор, мутация P1d красная), круг 2 «принять с замечаниями»; живьём `dq_checks` 16:15 и 16:30 `gold_stale_runs=0` |
| К2 | `bd8ad43` | Superset 6.1 на Trino `lake_ro` (образ с драйверами и `constraints.txt`, `superset-init`, бандл Marketplace, `check.py`), `superset-mcp` с проверкой Host и Origin, пользователь Trino `superset` с правами `grafana`, консоль MinIO на 9001, listener Kafka `localhost:9092`, `make secrets` дописывает ключи | ревью Opus 3 прохода: «принять с замечаниями» (4 средних, 4 низких), круг 1 «принять с замечаниями» (1 средняя: комментарий compose, исправил оркестратор), круг 2 «принять с замечаниями» (2 низких, документация); живьём см. К3 |
| К3 | без кода | пересоздание `kafka` 15:01, `minio` 15:02, рестарт `trino` 15:02, `make up PROFILE=stateful` (F-10), `make secrets` (по повторному «ок», 2 ключа), `make up PROFILE=bi` 15:07, пересоздание `superset-*` 15:51 | Kafka с хоста: брокер `localhost:9092`, 7 топиков; `:9001` 200 `MinIO Console`; ACL `superset`: `fct_orders` 96346, silver, `lake`, `stg_*`, `create table` Access Denied; `check.py` 601, 601, 27, 10 строк; MCP: чужой Host 421, чужой Origin 403, loopback 200, `get_instance_info` 1 дашборд, 4 графика; `claude mcp list` Connected; повтор init `admin exists`, код 0 |
| К4 | `a9dfa55` | README «Explore the stack», OPERATIONS (порты с профилями, Superset, MCP, консоль MinIO, правило паузы `dbt_build`, алерт, `make secrets`, 10b), ARCHITECTURE (Mermaid и SVG с Superset), evidence (раздел Superset and local access), README компонентов | выборочная сверка оркестратора; длинных тире нет; 254 ссылки проверены `docs-writer` |
| К5 | этот docs-коммит | `make replay-burst SECONDS=30` 16:17:06-16:17:37: 28 событий (12 `order_insert`, 16 `order_status`), `virtual_now` 2026-07-18 00:06:35 -> 06:02:03 (5:55:28 виртуальных) | заказ `1aa7e7505275a3ce08be4b00f1d7a16d`: Kafka `oltp.shop.orders` p0 offsets 77480 `op=c` и 77481 `op=u` (LSN 1873267528, 1873344160); bronze `ingest_ts` 16:17:20; `silver_upsert` run 16:20 `merge` 16:20:01-16:20:28, silver `approved`, `_last_lsn 1873344160`; событие Asset 16:20:28 создало run `dbt_build` (success 16:20:52); `gold.fct_orders` `approved`, `items_value 89.90`; тот же ряд от `grafana` и `superset` через `lake_ro`; GMV дня 2026-07-18: Postgres 1186.13 = `mart_daily_sales` от `superset`; Superset запросил витрину 16:21:41; `check_dashboards.py` Marketplace `queries ok: 4`; `make reconcile` 7 из 7 (orders 96358); `dq_checks` 16:30: 13 пар по 0, `gold_stale_runs=0`, алертов нет |

Цикл verify 16:05-16:08: `stop airflow-scheduler`, `make verify` verify ok 7 из 7 (full 16:07:12Z),
`make dbt-build` `PASS=79 WARN=4 ERROR=0`, `start airflow-scheduler`; паузы трёх DAG сняты 16:09,
`dq_checks` последним. Алерт `ContainerRestarting` по `airflow-scheduler` 16:08 ожидаем (окно 15 мин).

Не сделано и открыто: push в `origin` (нужно «ок»); CI на новых коммитах не запускался; P2 и P3
аудита 16 (F-04, F-05, F-06, F-08, F-09, F-11..F-19, F-21..F-27, F-30, F-31) кандидаты в
поддержку; MCP-сессия клиента в новой сессии Claude Code не проверялась (проверено `claude mcp
list` и прямым JSON-RPC); память при `bi` вместе с остальными профилями не измерена.
