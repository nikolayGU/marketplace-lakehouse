# 14. Спека W6: закрытие проекта

Версия 0.2, 27.10.2026, по `06-spec-standard.md`. Единственный бэклог блока: остаток W5 (T05b), путь
с чистого клона, открытые находки W4-W5 и W6 по `01-roadmap.md`. Как исполнять: `13-harness.md`.
Карточка открывается, когда приняты решения, от которых она зависит (раздел 5, «Зависит от»).
Решения групп A и B агент принимает сам (`13-harness.md`, раздел 2.1), группы C ждут владельца.

## 1. Цель и границы

**Результат.** Критерии «Проект сделан, когда» из `06-spec-standard.md:14-19` выполнены и доказаны
(раздел 6): ревьюер за 3 минуты видит работающий конвейер, числа и бизнес-ответ; путь с чистого
клона воспроизводится одной командой; исполнитель без контекста продолжает по спеке и HANDOFF.

**Состояние на входе, 27.10.2026** (проверено командами, HANDOFF «Состояние на 27.10.2026»):
- HEAD `8964292` равен `origin/main`; CI зелёный на HEAD (run 40021181828);
  `uv run pytest tests/unit -q`: 458 passed, 83 skipped (Spark на хосте); ruff и mypy чистые.
- Отметка verify: полный, 23.10 20:41 UTC, дерево `4153eaf` равно дереву HEAD. О текущем стеке она
  ничего не говорит.
- Ноутбук выключен 24.10 01:25, включён 27.10 17:23 по времени Windows (UTC+4, `tzutil /g`:
  Georgian Standard Time), то есть 23.10 21:25 и 27.10 13:23 UTC (журнал System, события 1074, 6006;
  последние запуски DAG 23.10 21:25 UTC совпадают). `wevtutil` печатает местное время.
  Docker Desktop не запущен: `AutoStart = False`, интеграция с дистрибутивом `Ubuntu` уже включена
  (`IntegratedWslDistros`), данные Docker на `D:\DockerDesktop\DockerDesktopWSL`. Стек и реплей не
  проверены.
- `smoke.yml` красный: 23.10 `no such manifest`, 26.10 (schedule) `minio Error unauthorized` на
  загрузке `quay.io/minio/minio`. `minio/minio` archived 24.04.2026, архив `dl.min.io` отвечает 410,
  quay 401. Копия образов: `~/lakehouse-image-backup/minio-images.tar` (84 862 976 байт, 23.10,
  `docker load` не проверен).
- W5-T05b: код и защиты готовы, ни одна деструктивная процедура не выполнялась.
- Гейты владельца все открыты, `LEARNING.md` пуст. W6 не начата: статус в `README.md:8-10`
  устарел, `docs/img/` пуст, `docs/interview-notes.md` из пустых заголовков.
- Реплей по последней записи (23.10): потрачено 3 д 17 ч 56 мин из 8 дней (W4-D10 5 и W5-D14 3),
  `virtual_now` 2026-07-16 21:33, осталось 22 293 события. На 27.10 не проверено.
- Сон 19.10 и 21.10: система входила в современный ждущий режим (Kernel-Power 506), затем в
  гибернацию «Hibernate from Sleep - Fixed Timeout» (событие 42). От сети сон и гибернация по
  таймеру уже «никогда» (`STANDBYIDLE` и `HIBERNATEIDLE` AC 0), значит вход был по крышке, кнопке
  или от батареи (от батареи сон 2 ч, гибернация 3 ч).

**Входит:** W6-T00, W5-T05b, W6-T01..T03, W6-T05..T10 (раздел 4).
**За владельцем:** решения группы C (раздел 2), «ок» на действия класса C, гейты (раздел 4,
«Гейты владельца»), запуск Docker Desktop, применение патча хука, питание ноутбука для W6-T09.
Список действий с командами: HANDOFF, «Действия владельца».
**Не входит:** W6-T04 (Superset, Schema Registry: буфер уходит на W6-T00 и W6-T05..T08),
S3FileIO, `expire_snapshots` bronze (ADR-021), замена S3-слоя.

## 2. Решения

Группы по `13-harness.md`, раздел 2.1: A решает агент, B агент после вердикта `reviewer`, C владелец.
Работа, которую решение не блокирует, идёт без него.

| ID | Решение | Группа | Рекомендация | Цена отказа | Обратимо | Блокирует | Статус |
|---|---|---|---|---|---|---|---|
| W6-D1 | Источник образов MinIO и mc | B | сборка из исходников тех же тегов, ADR-026 | smoke красный, чистый клон не стартует | да | W6-T00 | принято, B, 27.10: вердикт `reviewer` «принять» (второй проход по изменённым строкам; первый «принять с замечаниями», 11 замечаний закрыты); ADR-026 `Accepted`. Отклонения от текста: Go 1.24.6, healthcheck `wget`, `pull_policy: never`, ADR-004 заменён только по источнику образа |
| W6-D2 | Расписание smoke до починки | A; правка `smoke.yml` идёт через ревью W6-T00 | только `workflow_dispatch` до первого зелёного | красный запуск каждый понедельник | да | ничего | принято исполнителем 27.10, A |
| W6-D3 | Push и запуск smoke агентом | C | постоянное разрешение без force, строка в журнал | каждая карточка ждёт владельца на последнем шаге | нет, история публичная | W6-T00 часть 5, карточки на GitHub | принято владельцем 29.10 15:35 UTC: «да», push 23-24.10 подтверждён |
| W6-D4 | Делегация на блок | C | как W4: решения A и B, коммиты, цикл verify | каждый коммит ждёт «ок» на diff | да | коммиты | принято владельцем 29.10 15:35 UTC: «да» (планы и коммиты карточек без отдельного «ок») |
| W6-D5 | Процедура W5-T05b | B, пакеты C | шаги 0-13, пакеты П1-П9 | необратимые шаги без полного списка и копии | процедура да, шаги нет | W5-T05b | процедура принята, B, 29.10: `reviewer` «принять с замечаниями» по плану (круг 1; круг 0 «вернуть», высокое закрыто решением W6-D16), замечания круга 1 внесены; пакеты П1-П9 ждут «ок» |
| W6-D6 | 7 лишних parquet bronze | A | не трогать, записать в ADR-025 | удаление данных, которых нет в Kafka | да | ничего | принято исполнителем 27.10, A; записано в ADR-025 29.10 (W5-T05b) |
| W6-D7 | WAL слота на простое | B | только правило алерта | слот держит WAL без сигнала | да | W6-T05 | принято, B, 29.10: `reviewer` «принять с замечаниями» по коду W6-T05 (два прохода), коммит 610694d |
| W6-D8 | Цикл рестартов Spark | B | правило по рестартам `spark-bronze` | 15 рестартов за 5 мин без алерта на Spark | да | W6-T06 | принято, B, 29.10: `reviewer` «принять с замечаниями» по коду W6-T06 (два прохода), коммит 610694d |
| W6-D9 | `dq_checks` при стоящем CDC | C | покой с учётом источника и алерт; код и доказательства готовит агент | ложный `AirflowDagFailed` при каждом простое CDC | да | коммит W6-T07 | принято владельцем 29.10 ~17:40 UTC: «да» на diff (детектор по слоту после ревью круга 1); коммит 649cb68 |
| W6-D10 | `segment.ms` живого `oltp.message` | C | применить | «retention 1 h» неверен для живой системы | нет: retention удалит записи старше часа (топик пуст) | W6-T08 | принято владельцем 29.10 17:00 UTC: «да»; применено (W6-T08) |
| W6-D11 | Дашборд по gold | B | Grafana и плагин Trino datasource | нет дашборда по gold (DoD W6-T01) | да | W6-T01 | принято, B, 29.10: `reviewer` «принять с замечаниями» (второй проход) и живой шаг: плагин 1.4.1 на Grafana 13.2.2, 4 панели с данными, 276.7 MiB при 384M; коммит ab37157 |
| W6-D12 | Окно B6 | A, питание владельца | 24 ч во время доковой работы | «сутки зелёные» W3-T05 и покой W4-T05 не доказаны | да | W6-T09 | принято исполнителем 27.10, A; ждёт питания |
| W6-D13 | Бюджет реплея W6 | C | делегировать до 2 виртуальных дней порциями по 60 с | «ок» на каждую порцию | нет, виртуальное время тратится | W5-T05b шаг 12, живые проверки алертов | принято владельцем 29.10 15:35 UTC: «да» |
| W6-D14 | Диаграмма | A | Mermaid и экспорт SVG | SVG без исходника устаревает молча | да | ничего | принято исполнителем 27.10, A |
| W6-D15 | Говорят ли публичные документы, что проект построен агентами | C | да, отдельным разделом «How it was built» | процесс с агентами не виден читателю | да | раздел W6-T02 | принято владельцем 29.10 15:35 UTC: «да»; строку `AGENTS.md` «Язык и стиль» правил агент по «ок» владельца 29.10 (дважды, вторая редакция по ревью W6-T02) |
| W6-D16 | Точка отката JDBC (`iceberg_catalog`) при обслуживании | C | отпустить, копия префикса `warehouse/` до первого удаления | W5-T05b не выполнить, обслуживание живьём не доказано | нет: файлы старых снапшотов удаляются; откат только из копии | W5-T05b шаги 4-11 | принято владельцем 29.10 15:49 UTC: «да, с копией бакета первым шагом» |
| W6-D17 | Права пользователя `grafana` в Trino (нет аутентификации и access control; плагин выполняет любой SQL) | C | агент рекомендовал принять риск и записать; владелец выбрал ограничить | дашборд даёт путь к DDL/DML в lake из браузера | да | W6-T11 | принято владельцем 29.10 ~18:25 UTC: «ограничить права сейчас» (file-based access control, `grafana` только select на `lake.gold`); выполнено W6-T11, коммит 46f5282 (через каталог lake_ro read_only) |

**W6-D1. Источник образов MinIO и mc.** B.
- Зачем: образы удалены из реестров, smoke падает на `make bootstrap`; ADR-004 закрепил quay.
- Варианты: (a) сборка из исходников тех же тегов (`RELEASE.2025-09-07T16-13-09Z`, коммит
  `07c3a429bfed433e49018cb0f78a52145d4bedeb`; mc `RELEASE.2025-08-13T08-35-41Z`, коммит
  `7394ce0dd2a80935aded936b09fa12cbb3cb8096`; хеши `01ce918` и `d6541ea`, которые стояли здесь,
  это объекты аннотированных тегов, не коммиты: `git ls-remote` строка `^{}`) в
  `docker/minio/Dockerfile`, Go `1.24.6` по digest (официальные бинарники печатают
  `Runtime: go1.24.6`; в `go.mod` тегов `toolchain` 1.24.2 и 1.23.10 это нижняя граница),
  `CGO_ENABLED=0`, рантайм alpine (healthcheck через busybox `wget`, без `curl`); (b) tar в GHCR владельца;
  (c) форк `pgsty/silo` (живой, `RELEASE.2026-10-26`); (d) SeaweedFS, Garage, RustFS.
- Рекомендация: (a). Тот же код и формат тома, ничего не публикуется, воспроизводится из репо.
- Цена отказа: smoke красный, «чистый клон одной командой» недостижим, образы только в локальном
  хранилище Docker.
- Обратимость: полная, но блоком, а не строкой `image`: весь блок `minio` и `minio-init` в compose
  из git (`image: quay.io/...`, без `build:` и `pull_policy`, healthcheck на `curl -sf`); в образе
  upstream нет `wget`, и одна строка `image` оставит `minio` нездоровым. Том не меняется
  (ревью W6-T00, замечание 1).
- Последствия: Dockerfile с двумя target; сборка в CI дольше (не замерено); CVE тега 2025-09
  остаются, как и сейчас; upstream Dockerfile тега (`FROM minio/minio:latest`) не годится; ADR-026
  заменяет ADR-004.
- Владелец: нет. Варианты (b) публикация, (c) новый код на живом томе, (d) замена S3-слоя: это C.
- Блокирует: W6-T00.

**W6-D2. Расписание smoke.** A. Только `workflow_dispatch` до первого зелёного, расписание
возвращается коммитом W6-T00 после зелёного. Цена отказа: красный запуск каждый понедельник.
Обратимо. Ничего не блокирует.

**W6-D3. Push и запуск smoke.** C.
- Зачем: `AGENTS.md` требует «ок» на push, `NEXT_SESSION.md` 24.10 называл push разрешённым; push
  23-24.10 сделан без записанного «ок» (ревью п. 28); без push CI и smoke не видят новый код.
- Варианты: (a) постоянное разрешение: `git push origin main` без force и `gh workflow run smoke.yml
  --ref main` после каждой закрытой карточки с зелёными проверками и вердиктом `reviewer`, строка в
  журнал «ок»; (b) «ок» на каждый push.
- Рекомендация: (a).
- Цена отказа: каждая карточка ждёт владельца на последнем шаге, CI проверяет код с опозданием.
- Обратимость: публичная история необратима, поэтому force запрещён в обоих вариантах.
- Блокирует: часть 5 W6-T00 и закрытие карточек на GitHub; локальная работа идёт.
- Ответ владельца: «W6-D3: да; push 23-24.10 подтверждаю» или «W6-D3: нет».

**W6-D4. Делегация на блок.** C.
- Рекомендация: как W4 (память агента, 19.10): агент принимает решения A и B, коммитит каждую
  карточку после зелёных проверок и вердикта `reviewer`, гоняет цикл verify (пауза DAG, остановка
  scheduler, `make verify` с merge уже виденного bronze) без вопроса; класс C по «ок» или пакету.
- Альтернатива: «ок» на каждый коммит. Цена: владелец становится диспетчером.
- Обратимость: отзывается одной фразой.
- Блокирует: коммиты (работа идёт, изменения копятся по правилу `13-harness.md`, раздел 5).
- Вопрос владельцу включает `AGENTS.md`, «Цикл», шаги 3 и 6: нужен ли «ок» на план каждой карточки
  этого бэклога и на diff каждого коммита. Рекомендация: нет для обоих (план идёт в отчёт, diff
  смотрит `reviewer`), класс C остаётся по «ок».
- Ответ владельца: «W6-D4: да» (делегация, планы и коммиты карточек без отдельного «ок») или
  «W6-D4: нет». Без ответа действует `AGENTS.md` как есть: план и diff каждой карточки ждут «ок».

**W6-D5. Процедура W5-T05b.** Процедура B, каждый пакет C.
- Зачем: карточка W5 и W5-D13 нумеруют ступени по-разному; `make start` молча пересоздаёт
  `spark-bronze`; список orphans обрезан до 200; отката у `expire_snapshots` и orphans нет.
- Рекомендация: таблица шагов 0-13 (раздел 4, W5-T05b); процедуры вручную по таблицам; копия
  префикса `warehouse/` бакета на `/mnt/d/lakehouse-backup/` до первого удаления (шаг 3, W6-D16);
  `iceberg_maintenance` после лестницы без Spark-шагов по умолчанию; `iceberg_orphans` на паузе.
  Пакеты «ок»: редакция 29.10 после ревью плана, П1-П9 в карточке (копия бакета перенесена перед
  первым удалением, W6-D16). Это ступени W5-D13 плюс bronze из карточки W5.
- Альтернатива: карточка W5 как есть (trigger DAG по всем таблицам разом).
- Цена отказа: реальный orphans без полного списка и копии необратим (OPERATIONS «Maintenance»: «the lake has no backup»).
- Владелец: процедура нет, каждый пакет да.
- Блокирует: только W5-T05b.

**W6-D6. 7 лишних parquet bronze (534 против 527, 23.10).** A. Не трогать: данные bronze не
удаляются никогда (ADR-025), Kafka их уже не хранит. Записать в ADR-025 при закрытии W5-T05b.

**W6-D7. Слот держит WAL на простое.** B. Только правило алерта для активного слота, который
держит 64-512 MiB при молчащем источнике (W6-T05). `heartbeat.action.query` это миграция, новый
топик, правка коннектора и ADR-027: группа C, сейчас не рекомендуется (24 MB на простое ноутбука).

**W6-D8. Цикл рестартов Spark при остановленной Kafka.** B. Правило по рестартам `spark-bronze`
(`changes(...[10m]) > 2` по метрике `container-exporter`) с тестами promtool (W6-T06).

**W6-D9. `dq_checks` красный при стоящем CDC.** C.
- Рекомендация: покой с учётом источника (`confirmed_flush_lsn` слота против
  `pg_current_wal_lsn()` при записях в `shop`): тогда `in flight, no verdict` и алерт «bronze
  молчит, источник пишет».
- Почему C: правка меняет проверку, а ослабление проверок без «ок» запрещено `AGENTS.md`. Агент
  пишет код, тесты и доказательства без «ок»: расхождение при молчащем источнике по-прежнему
  красное; каждый случай, где раньше краснел `dq_checks` из-за стоящего CDC, теперь даёт алерт;
  вердикт `reviewer`. Коммит только после ответа владельца на готовый diff.
- Цена отказа: ложный `AirflowDagFailed` при каждом простое CDC.
- Ответ: «W6-D9: да» на присланный diff.

**W6-D10. `segment.ms` живого `oltp.message`.** C (retention живого топика). Рекомендация:
`segment.ms=3600000`, `--describe` до и после (W6-T08). Топик пуст, риск низкий. Цена отказа:
«retention 1 h» в доках неверен для живой системы. Ответ: «W6-D10: да». Блокирует только W6-T08.

**W6-D11. Дашборд по gold.** B. Grafana с плагином Trino datasource, версия закреплена, provisioning
из файлов; совместимость с Grafana 13.2.2 и память профиля `obs` проверить до правки. Не встаёт:
статичные графики из SQL в `docs/img/`. Superset (новый сервис) это C, не рекомендуется.

**W6-D12. Окно B6.** A: окно 24 ч идёт во время W6-T02, T03 (коммиты только Markdown не требуют
verify), без реплея и живых правок. Владелец обеспечивает питание (HANDOFF, «Действия владельца»).
Агент проверяет окно по `Heartbeat recovered` и событиям Kernel-Power 506 и 42.

**W6-D13. Бюджет реплея W6.** C (`AGENTS.md`: любой расход реплея с «ок»).
- Рекомендация: делегировать до 2 виртуальных дней порциями `make replay-burst SECONDS=60` (около
  12 виртуальных часов при SPEED 720) без отдельного «ок» на порцию, `virtual_now` до и после в
  HANDOFF; сценарии chaos остаются по «ок».
- Цена отказа: «ок» на каждую порцию (T05b шаг 12, живые проверки алертов).
- Ответ: «W6-D13: да».

**W6-D14. Диаграмма.** A. Mermaid в `ARCHITECTURE.md` (GitHub рисует сам, diff читаемый) и экспорт
в `docs/img/architecture.svg`.

**W6-D15. Говорят ли публичные документы, что проект построен агентами.** C.
- Зачем: цель проекта, по словам владельца 27.10, показать, что один инженер строит и эксплуатирует
  платформу силами агентов. `AGENTS.md` («Язык и стиль») запрещает в репо упоминания, что текст писал
  AI; `docs/agent-rules.md` («Что за проект») при этом пишет «Код пишет AI»; ревью п. 43 просило
  уточнить правило.
- Варианты: (a) раздел «How it was built» в `docs/evidence.md` и строка в README: агенты писали код
  и доки, владелец решал архитектуру, давал «ок» и принимал результат; ссылки на решения, ревью и
  журнал «ок»; сообщения коммитов по-прежнему без строк атрибуции; (b) ничего публично, данные
  процесса только в `docs/planning/`.
- Рекомендация: (a), иначе вторая половина цели проекта не видна читателю.
- Цена отказа: процесс с агентами не показан; правило стиля и цель проекта противоречат друг другу.
- Обратимость: полная (текст).
- Блокирует: только раздел «How it was built» в W6-T02.
- Ответ: «W6-D15: да» или «W6-D15: нет». При «да» владелец сам правит строку `AGENTS.md`
  («Язык и стиль»), агент правила о себе не меняет.

**W6-D16. Точка отката JDBC.** C. Найдено ревью плана W5-T05b 29.10 (замечание 1, высокое):
строки `iceberg_catalog` указывают на снапшоты до переключения 08.10, а expire, orphans и
`delete-after-commit` bronze удаляют файлы этих снапшотов. OPERATIONS обещал держать точку отката
до конца недели 3. Ответ владельца: отпустить, копия `warehouse/` до первого удаления (шаг 3
W5-T05b). Строки каталога остаются (удаление в blast radius, раздел 7).

## 3. Ограничения блока

- Раздел 3 `10-w5-spec.md` (версии, один писатель silver, цикл verify, сборка образа без
  пересоздания контейнера, стоп-правило памяти W4-D5) действует, кроме push и запуска workflow:
  по W6-D3.
- Классы действий и «ок»: `13-harness.md`, раздел 2. Реплей только по W6-D13, потраченное в HANDOFF.
- Docker недоступен: только часть A карточек и проверки без Docker (NEXT_SESSION).
- Стек простаивал с 24.10: после запуска Docker Desktop контейнеры с `restart: unless-stopped`
  поднимутся сами. Не трогать их до `make report` и `make verify-fast`. Kafka держит 24 ч, но
  источник не писал (реплей стоит), поэтому потерь не ждём; проверить `bronze_offsets_ok`.
- Чистый клон локально (одноразовый проект) не поднимать при живом стеке: вместе больше 10 GiB.
  Путь с чистого клона проверяет `smoke.yml` на GitHub.

## 4. Карточки

### W6-T00 Путь с чистого клона без образов MinIO из реестра

**Зачем.** Smoke красный, чистый клон не стартует, образы держатся только локально.
**Оценка** 4 ч. **Зависит от:** части 1-4 ни от чего (W6-D1 группы B решается вердиктом `reviewer`
в этой карточке, W6-D2 принято); часть 5 от W6-D3 и W5-T05b (живая смена образа после лестницы).
**Область коммита:** `infra`, `ci`.
**Вход.** `gh run view 40290595866 --log | grep -E 'minio|unauthorized'`; `docker/compose.yaml:145-183`;
`docker/minio/create-bucket.sh`; ADR-004 (`DECISIONS.md:48-66`); `ls -la ~/lakehouse-image-backup/`.
**Сделать.**
0. `scout`: флаги сборки тега из `Makefile` и `buildscripts/` репозиториев `minio/minio` и
   `minio/mc` на коммитах `07c3a429` и `7394ce0d` (теги `^{}`; `-ldflags`, `-tags`, `CGO_ENABLED`),
   digest образов `golang:1.24.6-bookworm` и рантайма alpine, база для рантайма с `sh` и `wget`.
   Источники с URL.
1. ADR-026 первым, статус `Proposed` (замена ADR-004): код против ADR не пишется (`AGENTS.md`).
2. Тест на отказ: `tests/unit/test_workflows.py` или `test_makefile.py` проверяет, что сервисы
   `minio` и `minio-init` собираются из `docker/minio/` и не ссылаются на `quay.io/minio`, а базовые
   образы закреплены `@sha256`.
3. `docker/minio/Dockerfile` (два target: `minio`, `mc`), `compose.yaml` с `build:` и `image:
   lakehouse/minio:<тег>`, `lakehouse/mc:<тег>`; hadolint в матрице `ci.yml`; `smoke.yml` по W6-D2;
   кэш слоёв сборки MinIO.
4. OPERATIONS, README «Quick start». ADR-026 `Accepted`, а у ADR-004 источник образа заменён
   (статус «accepted; image source superseded by ADR-026», как у ADR-005: остальное решение
   ADR-004 действует) только с вердиктом `reviewer` «принять» (W6-D1, группа B).
5. Живая часть. Агент сам (класс A, `13-harness.md`): копия `~/lakehouse-image-backup/minio-images.tar`
   в `/mnt/d/lakehouse-backup/` и `docker load -i` с проверкой, что digest образов до и после равны
   (не равны: стоп). По W6-D3: push, `gh workflow run smoke.yml --ref main`. По «ок» (C): на живом
   стеке в покое пересоздание `minio` и `minio-init` на новом образе.
**Готово, когда.** `docker run --rm lakehouse/minio:<тег> --version` печатает тег
`RELEASE.2025-09-07T16-13-09Z`; `make lint`, `make test` зелёные; smoke по кнопке зелёный (ссылка на
run); после пересоздания на живом стеке `make verify-fast` даёт `verify ok`, число объектов в бакете
до и после равно.
**Ловушки.** Upstream Dockerfile тега тянет `minio/minio:latest`, его не брать. Флаги сборки MinIO
(`-ldflags` с версией) сверить с `Makefile` тега, не по памяти. Не делать `docker image prune`.
`make start`, `make up` и `compose up` без `--no-deps` читают compose рабочего дерева: уже с правки
файла они собирают `minio` и `minio-init` (`make start` идёт с `--build`, `minio` зависимость
`spark-bronze`) и пересоздают их, когда id образа отличается от id запущенного. Это шаг части 5,
только по «ок»; до него `make start` не запускать.
**Blast radius и пайплайн.** Код: нет. Живое пересоздание `minio`: стек без S3 на десятки секунд,
bronze и DAG ретраят; том не меняется.
**Не входит.** Замена S3-слоя, переход на форк.

**Итог 27.10 (части 0-4; часть 5 не начата).**

```text
Критерий: «docker run --rm lakehouse/minio:<тег> --version» печатает тег RELEASE.2025-09-07T16-13-09Z; «make lint», «make test» зелёные (14-closeout-spec.md, W6-T00 «Готово, когда»); smoke и живой стек: часть 5
Изменение: 6e114af (10 файлов: docker/minio/Dockerfile, docker/compose.yaml, .github/workflows/ci.yml и smoke.yml, scripts/check-minio-images.sh, tests/unit/test_minio_image.py и test_workflows.py, DECISIONS.md ADR-026, OPERATIONS.md, README.md); исполнитель оркестратор, ADR и доки он же, тест и код он же (implementer не привлекался: одна карточка, связанные файлы), разведка scout, ревью reviewer
Проверка: docker run --rm lakehouse/minio:RELEASE.2025-09-07T16-13-09Z --version -> «minio version RELEASE.2025-09-07T16-13-09Z (commit-id=07c3a429bfed433e49018cb0f78a52145d4bedeb)», Runtime go1.24.6; mc -> «mc version RELEASE.2025-08-13T08-35-41Z (commit-id=7394ce0dd2a80935aded936b09fa12cbb3cb8096)»; bash scripts/check-minio-images.sh <оба образа> -> «minio images ok» (build info vcs.revision и vcs.modified=false, sh и wget, healthcheck compose, create-bucket.sh дважды, mc admin info: version 2025-09-07T16:13:09Z и commitID); uv run pytest tests/unit -q -> 581 passed, 83 skipped; make lint rc 0; hadolint 2.15.1 rc 0; server --help и mc --help идентичны официальным; make verify -> verify ok (full 2026-10-27T15:43:00Z, HEAD 5ca361a плюс дерево коммита), 27.10 UTC
Независимо: reviewer, два прохода: «принять с замечаниями» (1 высокое, 4 средних, 6 низких, все закрыты) и «принять» по изменённым строкам (5 низких, закрыты); W6-D1 остаётся группой B, ADR-026 Accepted. Мутации (скрипт в scratchpad) убиты тестами и скриптом проверки
Не проверено: smoke и job minio-images на GitHub (push по W6-D3: gh workflow run smoke.yml --ref main, gh run view <id>); время холодной сборки в CI; docker load архива (образы quay уже в хранилище с теми же digest: 14cea493... и a7fe349e...); живая смена образа minio и minio-init, make verify-fast после неё, число объектов в бакете до и после (часть 5, «ок» по шаблону); make test-spark, dags-check, alerts-test (diff их не задевает)
Риски: make start, make up и compose up читают compose рабочего дерева и пересоздадут minio и minio-init на новом образе (до части 5 не запускать); откат только блоком compose из git, не строкой image; остальные build-сервисы compose без pull_policy (раздел 7); теги lakehouse/minio:ci, lakehouse/mc:ci, lakehouse/minio:mut остались в хранилище (удаление образов класс C); часть 5 копия tar на /mnt/d/lakehouse-backup/ ещё не сделана (каталога нет)
```

**Итог 29.10 (часть 5).**

```text
Критерий: «smoke по кнопке зелёный (ссылка на run); после пересоздания на живом стеке make verify-fast даёт verify ok, число объектов в бакете до и после равно» (14-closeout-spec.md, W6-T00 «Готово, когда»)
Изменение: коммит ci (smoke.yml: расписание 0 3 * * 1 вернулось по W6-D2; test_workflows.py требует оба триггера и ровно один cron); живой шаг без кода; исполнитель implementer (код), оркестратор (push, smoke, живая смена по «ок»)
Проверка: gh run view 40907438614 -> smoke success (workflow_dispatch на 664a7e6, 29.10 16:01 UTC); тест до правки smoke.yml красный, после 7 passed; make check 761 passed, 83 skipped; /mnt/d/lakehouse-backup/minio-images.tar на месте (проба bind mount 29.10); живая смена 16:53 UTC по «ок»: minio и minio-init на lakehouse/minio и lakehouse/mc тех же тегов, minio healthy, minio-init код 0, пересозданы только они (Created), бакет 4045 объектов и 482 441 040 байт до и после (mc du --json), mc admin info version 2025-09-07T16:13:09Z до и после, spark-bronze 0 рестартов, make verify-fast verify ok
Независимо: reviewer по коду «принять с замечаниями» (1 средняя: README и OPERATIONS про расписание, исправлено; 2 низкие: SHA зелёного run 664a7e6, записано; permissions на уровне job тестом не закреплены, раздел 7)
Не проверено: первый запуск smoke по расписанию (понедельник 2026-11-02 03:00 UTC: gh run list --workflow smoke.yml); docker load архива minio-images.tar (образы quay в хранилище с теми же digest)
Риски: откат живой смены блоком compose из git до 6e114af; теги lakehouse/minio:ci, :mut и lakehouse/mc:ci остаются в хранилище (удаление образов класс C)
```

### W5-T05b Первые живые запуски обслуживания (поправки к `10-w5-spec.md:347-387`)

Карточка W5 действует, кроме шагов и критериев ниже (W6-D5, редакция 29.10 после ревью плана).
Каждая строка класса C это отдельное «ок» с числами «до». Необратимы шаги 2 (demo), 4, 6, 7, 8, 11:
их запрос несёт «обратимо: нет» и вердикт `reviewer` на план. Шаг 5 откатывается
(`rollback_to_snapshot`: снапшоты bronze не истекают, ADR-021), но коммиты после него теряются.
Шаги 5-11 идут по процедуре ручной записи: пауза `silver_upsert`, `dbt_build`, `dq_checks`, конец
запусков, остановка scheduler, команда, запуск scheduler, снятие паузы (как цикл verify,
`13-harness.md`, раздел 5, только вместо `make verify` команда шага). Таблицы: silver это
`MAINTENANCE_TABLES` (`airflow/dags/lakehouse/settings.py:33`: семь таблиц, `quarantine`,
`orders_per_minute`), gold это вывод `GOLD_BASE_TABLES` (`airflow/dags/lakehouse/sql.py:84`).

**Точка отката JDBC (W6-D16).** Строки `iceberg_catalog` (10 таблиц) указывают на снапшоты до
переключения 08.10 (OPERATIONS «Lakekeeper», «After the cutover»). Шаги 4, 6-8 и 11 удаляют файлы,
которые читают эти указатели: `delete-after-commit` bronze уберёт `metadata.json` указателя JDBC
примерно через 50 коммитов, expire снимет снапшоты 23.09. Владелец 29.10 отпустил точку отката
при условии, что копия префикса `warehouse/` снята до первого удаления (шаг 3). Строки
`iceberg_catalog` не удаляются (раздел 7). Каждый запрос «ок» шагов 4, 6-8, 11 называет это в
«Затронет».

**Допущение по `spark-orders-per-minute`.** Профиль `stateful` запущен и пишет
`silver.orders_per_minute`; процедура его не останавливает. Пока реплей стоит, входа нет и коммитов
нет: перед шагами 7 и 10-11 и после них `select max(committed_at) from
silver."orders_per_minute$snapshots"` равен; изменился: стоп и разбор (запись второго писателя).

| Шаг | Что | Класс | Стоп, если |
|---|---|---|---|
| 0 | Образ из HEAD, сверка кода в образе | B | дерево не чистое; diff не пуст |
| 1 | База: вход карточки W5 п. 1, числа в отчёт; `mc ls --recursive` по каталогу каждой таблицы | A | `verify-fast` красный |
| 2 | Песочница `demo.orders` | C | код не 0 |
| 3 | Копия префикса `warehouse/` бакета на `/mnt/d/lakehouse-backup/` | C | проба bind mount не видит `minio-images.tar`; места меньше двойного размера; на хосте число файлов (`find -type f`) не равно числу объектов без ключей на `/` (`mc ls --recursive --json`) или `du -sb --apparent-size` не равно `size` из `mc du --json` |
| 4 | Пересоздание только `spark-bronze` (`--no-deps`) | C | `Created` другого контейнера изменился; не `healthy` за 3 мин; рестарт по кругу; нет `Resuming at batch`; свойства нет |
| 5 | Компактация bronze | C | `bronze_caught_up` до шага не 0; `count(*)`, `max(kafka_offset)` или концы Kafka изменились |
| 6 | `silver.sellers` expire | C | `count(*)` изменился |
| 7 | Остальные silver | C | то же; допущение `orders_per_minute` нарушено |
| 8 | Gold | C | то же |
| 9 | Dry run orphans по четырём слоям (demo, silver, gold, bronze metadata), одно «ок» на пакет | C | `files_truncated: true`; кандидат моложе 7 дней по `mc ls`; кандидат найден в метаданных таблицы (ниже) |
| 10 | Разбор кандидатов | A | кандидат без объяснения |
| 11 | Реальный orphans только по разобранным таблицам, сразу после разбора (тот же час) | C | `files_truncated: true`; `removed` больше `candidates` dry run; набор `files` реального запуска не входит в набор dry run (тогда восстановление из копии шага 3) |
| 12 | Конвейер после: порция реплея (W6-D13), `silver_upsert`, `dbt_build`, `reconcile_values` | C | любой красный |
| 13 | Снять паузу `iceberg_maintenance` | C | следующий запуск выполнил Spark-шаг без conf; `optimize` красный; `reconcile` после него не 7 из 7 |

Пакеты «ок» (W6-D5): П1 шаг 2; П2 шаг 3; П3 шаг 4; П4 шаг 5; П5 шаги 6-7; П6 шаг 8; П7 шаг 9;
П8 шаг 11; П9 шаги 12-13.

Команды (`$COMPOSE` как в `13-harness.md`; в запросе «ок» он раскрыт, переменных-сокращений для
`spark-silver` не заводить: хук должен видеть команду целиком):

```bash
# 0
git status --short                                   # пусто
$COMPOSE --profile core build spark-bronze
diff <(docker run --rm --entrypoint sh lakehouse/spark:dev -c 'cd /opt/app && sha256sum spark_jobs/*.py') \
     <(cd streaming && sha256sum spark_jobs/*.py) && echo same
# 1: число объектов по каталогу каждой таблицы, bronze/cdc_events/data/ отдельно (одноразовый mc, без -v)
$COMPOSE --profile core run --rm --no-deps --entrypoint sh minio-init -c 'mc alias set lake "$S3_ENDPOINT" "$S3_ACCESS_KEY" "$S3_SECRET_KEY" >/dev/null && mc ls --recursive "lake/$S3_BUCKET/warehouse/<каталог>" | wc -l'
# 2
make iceberg-demo
$COMPOSE --profile core run --rm --no-deps spark-silver maintenance expire --days 7 demo.orders
# 3: проба bind mount (ожидается minio-images.tar), копия, сверка на хосте (стоп шага 3);
#    mc du --help до шага: есть ли --json
docker run --rm -v /mnt/d/lakehouse-backup:/b --entrypoint ls lakehouse/mc:RELEASE.2025-08-13T08-35-41Z /b
df -h /mnt/d
$COMPOSE --profile core run --rm --no-deps -v /mnt/d/lakehouse-backup/warehouse-<дата>:/backup --entrypoint sh minio-init -c 'mc alias set lake "$S3_ENDPOINT" "$S3_ACCESS_KEY" "$S3_SECRET_KEY" >/dev/null && mc mirror --preserve "lake/$S3_BUCKET/warehouse" /backup && mc du --json "lake/$S3_BUCKET/warehouse" && mc ls --recursive --json "lake/$S3_BUCKET/warehouse" | grep -vc "\"key\":\"[^\"]*/\""'
find /mnt/d/lakehouse-backup/warehouse-<дата> -type f | wc -l; du -sb --apparent-size /mnt/d/lakehouse-backup/warehouse-<дата>
# 4 (покой: bash -c '. scripts/chaos/lib.sh && bronze_caught_up' код 0)
docker ps -a --format '{{.Names}} {{.CreatedAt}}' > <scratchpad>/created-before.txt
# в «Затронет»: что ещё выкатывается; у старого образа нет метки коммита, сравнить код образов напрямую
diff <(docker run --rm --entrypoint sh $(docker inspect -f '{{.Image}}' lakehouse-spark-bronze-1) -c 'cd /opt/app && sha256sum run-job.sh spark_jobs/*.py') \
     <(docker run --rm --entrypoint sh lakehouse/spark:dev -c 'cd /opt/app && sha256sum run-job.sh spark_jobs/*.py')
$COMPOSE --profile core up -d --no-deps spark-bronze   # только spark-bronze: без --no-deps up пересоздал бы и minio
$COMPOSE logs --since 5m spark-bronze | grep 'Resuming at batch'
$COMPOSE exec -T trino trino --catalog lake --execute "select value from bronze.\"cdc_events\$properties\" where key = 'write.metadata.delete-after-commit.enabled'"   # "true"
# 5
$COMPOSE --profile core run --rm --no-deps spark-silver maintenance rewrite-data --before-today bronze.cdc_events
# 6, 7, 8: списки таблиц выписать полностью в запрос «ок»
$COMPOSE --profile core run --rm --no-deps spark-silver maintenance expire --days 7 silver.sellers
$COMPOSE --profile core run --rm --no-deps spark-silver maintenance expire --days 7 <остальные MAINTENANCE_TABLES>
$COMPOSE --profile core run --rm --no-deps spark-silver maintenance expire --days 7 <все GOLD_BASE_TABLES>
# 9: JSON каждого запуска в scratchpad
$COMPOSE --profile core run --rm --no-deps spark-silver maintenance orphans --dry-run demo.orders
$COMPOSE --profile core run --rm --no-deps spark-silver maintenance orphans --dry-run <silver>
$COMPOSE --profile core run --rm --no-deps spark-silver maintenance orphans --dry-run <gold>
$COMPOSE --profile core run --rm --no-deps spark-silver maintenance orphans --dry-run --location-suffix metadata bronze.cdc_events
# 10: кандидат не должен встречаться ни в одной метадата-таблице (Trino):
#   <t>."$all_entries".file_path, <t>."$all_manifests".path, <t>."$snapshots".manifest_list,
#   <t>."$metadata_log_entries".file; указатель JDBC (W6-D16) объясняет кандидата, но не останавливает;
#   путь начинается с location таблицы плюс «/»; возраст по mc ls
# 11
$COMPOSE --profile core run --rm --no-deps spark-silver maintenance orphans --no-dry-run <только разобранные таблицы>
# 13
$COMPOSE exec -T airflow-scheduler airflow dags unpause iceberg_maintenance
```

Флаги и порядок сверены с `streaming/spark_jobs/maintenance.py:43-55` (имя таблицы с `lake.` или без)
и `:220-252` (флаги подкоманды, затем таблицы); ревью плана 29.10 сверило снова. Реальный orphans
пересчитывает `older_than` от своего времени (`maintenance.py:296`): файлы, которым между dry run и
реальным запуском исполнилось 7 дней, тоже попадут в удаление, поэтому шаг 11 идёт в тот же час,
что и шаг 9, и сверяется набором, а не числом.

Поправки к «Готово, когда»:
- «кандидатов в `data/` bronze 0» заменяется на: число объектов под `bronze/cdc_events/data/` после
  шага 11 равно числу после шага 5 (orphans файлы данных bronze не трогает; код и так отказывает
  без `--location-suffix metadata`, `maintenance.py:80-96`, поэтому строка лога не доказательство);
- «не больше 1 снапшота старше 7 дней» засчитывается только для таблиц старше 7 дней по
  `committed_at` первого снапшота, для остальных пишется «неприменимо»;
- `silver.sellers`: оба снапшота (23.09 append 4 файла и 18.10 replace) старше 7 дней, поэтому
  expire удалит 4 файла данных снапшота 23.09 и их манифесты; `count(*)` равен до и после
  (`10-w5-spec.md:361` «ничего не должно исчезнуть» неверно);
- копия шага 3: число объектов и байт равны источнику, путь копии в HANDOFF;
- после шага 13 первый запуск `iceberg_maintenance` (возможен сразу: `catchup=False`, срок 03:30
  прошёл) показывает в логе `expire_and_compact=False`, skipped у Spark-задач и зелёный `optimize`
  через Trino (это запись в silver); после него `make reconcile` 7 из 7;
- `rewrite-position-deletes silver.orders` (ADR-025, падал 23.10) в лестницу не входит: «живьём не
  доказано» в итоге карточки.
Остальное как в W5.

**Итог 29.10 (шаги 0-13 выполнены; каждый пакет по «ок» владельца, журнал «ок» в HANDOFF).**

```text
Критерий: «Готово, когда» 10-w5-spec.md:378-385 с поправками этой карточки (bronze не больше 1/10 файлов прошлых суток, count и max(kafka_offset) равны; count каждой таблицы silver и gold равен, не больше 1 снапшота старше 7 дней; orphans по разобранному списку; demo в 10 раз; конвейер после; iceberg_maintenance без Spark-шагов)
Изменение: без кода; образ lakehouse/spark:dev 72e423bd из чистого HEAD 3a213c6, пересоздан spark-bronze; документация: OPERATIONS «Maintenance», ADR-025 (числа), этот итог; исполнитель оркестратор (живые шаги), docs-writer (OPERATIONS)
Проверка (29.10 UTC, сырые логи и JSON в scratchpad сессии, сводка t05b/FACTS.md):
 шаг 3 копия 4821 объект и 877 765 423 байт = источник; шаг 2 demo 21 файл в 1, expire код 0;
 шаг 4 Created изменился только у spark-bronze, Resuming at batch 171, delete-after-commit true;
 шаг 5 файлы прошлых суток 595 -> 30 (589 в 24), строки 558 629 и max offset 77 659 равны, концы Kafka md5 равны, bronze_offsets_ok;
 шаги 6-8 expire: count всех 18 таблиц равен, снапшотов старше 7 дней после не больше 1 (sellers: 4 файла 23.09, как ожидалось), make reconcile 7 из 7;
 шаг 9 dry run: silver, gold, demo 0 кандидатов; bronze metadata 21, files_truncated false;
 шаг 10 все 21 это metadata.json 00000-00020 от 22.09, ни одного в $metadata_log_entries, $snapshots.manifest_list, $all_manifests; указатель JDBC 00121 не среди них;
 шаг 11 removed 21, набор равен dry run; bronze data/ 619 объектов до и после; metadata.json 122 -> 101;
 шаг 12 replay-burst 60 с: virtual_now 2026-07-16 21:33:42 -> 2026-07-17 09:29:04 (233 события); silver_upsert, dbt_build, dq_checks 16:45 зелёные, reconcile_in_flight 0, все *_differing 0;
 шаг 13 первый запуск iceberg_maintenance: expire_and_compact=False, Spark-задачи skipped, optimize x8 success; make reconcile 7 из 7; make verify-fast verify ok
Независимо: reviewer по плану (круг 0 «вернуть», круг 1 «принять с замечаниями»); живые числа сняты одними и теми же командами до и после
Не проверено: rewrite-position-deletes silver.orders живьём; листинг orphans для silver.orders по префиксу (захват silver/orders_per_minute-*): все файлы opm моложе 7 дней, после 2026-10-30 17:45 UTC dry run silver.orders не должен содержать «orders_per_minute-»
Риски: iceberg_orphans на паузе, расписание за владельцем; точка отката JDBC отпущена (W6-D16), копия warehouse-20261029 на D:; остатки gold/mart_daily_sales__dbt_tmp-* вне таблиц (orphans их не видит)
```

### W6-T05 Алерт: слот держит WAL на простое

**Зачем.** Находка 18.10 и 23.10: слот не сдвигается без записей в `shop` (HANDOFF). Есть
`SlotWalRetainedHigh` (`observability/prometheus/alerts.yml:16-24`): неактивный слот больше 64 MiB или
любой больше 512 MiB. Не покрыт активный слот, который держит 64-512 MiB на простое источника.
**Оценка** 1 ч. **Зависит от:** W6-D7. **Область:** `obs`.
**Сделать.** Сначала случаи в `alerts_test.yml` (срабатывает при росте на простое, молчит при
трафике, не дублирует `SlotWalRetainedHigh`), потом правило в `alerts.yml`, строка в OPERATIONS
«Alerts», дополнить раннбук `docs/runbooks/slot-wal-growth.md`.
**Готово, когда.** `make alerts-test` зелёный, новые случаи падают на правиле без условия.

### W6-T06 Алерт: цикл рестартов `spark-bronze`

**Зависит от:** W6-D8. **Оценка** 1 ч. **Область:** `obs`.
**Сделать.** Случаи promtool: 15 рестартов за 5 мин; ряд `spark_streaming_last_batch_timestamp`
пропал на 4 мин 50 с; плановый одиночный рестарт молчит. Правило рядом с двумя `SparkNoBatch5m`
(`alerts.yml:27-38`), OPERATIONS «Alerts», дополнить раннбук `docs/runbooks/spark-stalled.md`.
**Готово, когда.** `make alerts-test` зелёный; при «ок» на chaos 8 (реплей) правило горит, иначе
«живьём не проверено».

**Итог 29.10 (W6-T05 и W6-T06 одним коммитом: те же два файла правил, решение A оркестратора).**

```text
Критерий: «make alerts-test зелёный, новые случаи падают на правиле без условия» (W6-T05); «make alerts-test зелёный; при «ок» на chaos 8 правило горит, иначе «живьём не проверено»» (W6-T06), 14-closeout-spec.md, разделы W6-T05, W6-T06
Изменение: 610694d (alerts.yml: SlotWalHeldIdle warn, SparkRestartLoop page; alerts_test.yml +9 случаев; OPERATIONS «Alerts» и запись chaos 8; раннбуки slot-wal-growth.md, spark-stalled.md); исполнитель implementer (код и круг исправлений), оркестратор (ретро-запросы TSDB, правки Markdown круга 2)
Проверка: make alerts-test -> «SUCCESS: 13 rules found», «SUCCESS»; make check -> 761 passed, 83 skipped; make verify -> verify ok, сверка 7 из 7 (full, цикл с паузой DAG и остановкой scheduler), 29.10 ~16:00 UTC, дерево коммита 610694d; мутации (убрать active==1, <=512 MiB, count_over_time, min_over_time -> ряд, [10m] -> [5m], >2 -> >1 и >0) все убиты тестами (implementer и reviewer повторно)
Независимо: reviewer, два прохода по коду: «принять с замечаниями» (1 средняя, 8 низких; исправлены implementer) и «принять с замечаниями» по изменённым строкам (1 средняя и 1 низкая исправлены оркестратором в OPERATIONS, 2 низкие в разделе 7); W6-D7 и W6-D8 приняты, B
Ретро на данных 23.10 (TSDB, query_range step 15s): выражение SparkRestartLoop истинно 17:11:15-17:24:15 UTC (max 15), первый рестарт 17:10:24; ALERTS SparkNoBatch5m cause=gone только pending ~17:10:49-17:15:34. Это прогон правила по записанным данным, не срабатывание загруженного правила
Не проверено: живое срабатывание обоих правил (правила не загружены в живой Prometheus до «ок» на docker kill -s HUP lakehouse-prometheus-1; затем curl -s 127.0.0.1:9090/api/v1/rules); SlotWalHeldIdle на реальном простое (около 2 суток выше 64 MiB); chaos 8 живьём (C)
Риски: SlotWalHeldIdle горит в долгом простое источника (так задумано, warn; сдвигает его только запись в shop, порция реплея); после цикла рестартов SparkRestartLoop держится до 10 мин
```

### W6-T07 `dq_checks`: покой с учётом источника

**Зависит от:** W6-D9. **Оценка** 3 ч. **Область:** `orchestrate`.
**Сделать.** Тест первым в `test_dags.py` или `test_reconcile.py`: «источник пишет, bronze молчит»
даёт `in flight, no verdict`, а «источник молчит, silver отличается» по-прежнему красный. Правка
`airflow/dags/lakehouse/checks.py` при паузе `dq_checks`; правило алерта; OPERATIONS.
**Готово, когда.** Оба теста зелёные; мутация условия покоя убивается тестом; в покое живой
`dq_checks` зелёный; при «ок» на chaos 6 или 8 запуск даёт `in flight`, алерт горит.
**Ловушки.** Не ослабить проверку: расхождение в покое обязано оставаться красным.

**Итог 29.10.**

```text
Критерий: «Оба теста зелёные; мутация условия покоя убивается тестом; в покое живой dq_checks зелёный; при «ок» на chaos 6 или 8 запуск даёт in flight, алерт горит» (14-closeout-spec.md, W6-T07)
Изменение: 649cb68 (checks.py: cdc_state, count_outcome, skip_source_values; sql.py CDC_PROGRESS; settings.py SHOP_SLOT, CDC_STATE_SEEN; dq_checks.py задача cdc_progress; alerts.yml CdcStalledSourceWrites; тесты; OPERATIONS); исполнитель implementer (две версии), дизайн детектора оркестратор после ревью, вход scout
Проверка: make check 806 passed, 83 skipped; 25 мутаций убиты (implementer), мутации-ослабления ревьюера убиты; make alerts-test SUCCESS; make dags-check 5 dags; make verify -> verify ok (цикл), 29.10 ~17:40 UTC, HEAD 649cb68; живой dq_checks 17:45 в покое зелёный, cdc_stalled 0; chaos 6 (make chaos-connect-pause, 17:43-18:22): коннектор стоял 17:47:02-18:17:06, dq_checks 18:00 и 18:15 success с «in flight: CDC stands, no verdict», cdc_stalled 1 с 18:01, CdcStalledSourceWrites firing 18:20:04, после возобновления «ok: nothing lost ... silver equals Postgres», rc 0, verify-fast ok
Независимо: reviewer: круг 0 «вернуть» (2 высоких: сверка значений отключалась при любой записи, связка DAG не покрыта тестами), круг 1 «принять с замечаниями» (1 средняя про chaos 8 в OPERATIONS исправлена оркестратором, 2 низкие); W6-D9 «да» владельца на diff
Не проверено: chaos 8 вживую (короче окна алерта 20 мин; первый запуск может быть красным, если слот сдвинулся до остановки Kafka, записано в OPERATIONS)
Риски: ложная остановка на один запуск при записи прямо перед запуском (Debezium подтверждает LSN по offset flush), алерт от неё не горит (окно 20 мин)
```

### W6-T08 `segment.ms` живого `oltp.message`

**Зависит от:** W6-D10. **Оценка** 0.5 ч. Без коммита кода; запись в OPERATIONS и HANDOFF.
**Сделать.** `kafka-configs.sh --describe` до, «ок», `--alter --add-config segment.ms=3600000`,
`--describe` после.

### W6-T01 Дашборд «Marketplace» по gold

**Зависит от:** W6-D11, W5-T05b. **Оценка** 3 ч. **Область:** `obs`.
**Сделать.** Четыре панели по `01-roadmap.md:109`: продажи по дням, топ категорий, SLA доставки по
штатам, отмены; запросы только к `lake.gold`; `check_dashboards.py` проверяет и их.
**Готово, когда.** Все панели с данными на живом стеке; скриншот в `docs/img/`; память `obs` в пределах лимита.

**Итог 29.10.**

```text
Критерий: «Все панели с данными на живом стеке; скриншот в docs/img/; память obs в пределах лимита» (14-closeout-spec.md, W6-T01)
Изменение: ab37157 (marketplace.json 4 панели только по lake.gold; provisioning trino.yml; compose grafana: GF_PLUGINS_PREINSTALL_SYNC=trino-datasource@1.4.1, лимит 384M; check_dashboards.py ветка Trino с дедлайном; тесты; OPERATIONS Dashboards и риск Trino; docs/img/marketplace-dashboard.png); исполнитель implementer (две версии), вход scout, живой шаг и скриншот оркестратор
Проверка: make check 825 passed, 83 skipped; check_dashboards.py marketplace.json -> queries ok: 4; сверки (select): заказы панели 96 163 = count(*) fct_orders (сумма по штатам mart 96 650 была бы задвоением), GMV по категориям 13 086 460.39 = sum(gmv) mart; живой шаг 18:27 UTC по «ок»: плагин trino-datasource 1.4.1 установлен за 13 с, grafana healthy, пересоздан только он, datasource trino «Data source is working», /api/ds/query: Daily sales 600 строк, GMV by category 10, Delivery SLA 27, Cancellations 600; docker stats 276.7 MiB / 384 MiB (при старом лимите 256M не помещалась бы); скриншот 18:44 (Playwright в разовом контейнере в сети lake); make verify -> verify ok (цикл), HEAD ab37157
Независимо: reviewer: круг 0 «вернуть» (1 высокое: задвоение заказов по штатам; 3 средних), круг 1 «принять с замечаниями» (3 низких, раздел 7 и OPERATIONS); W6-D11 принято, B
Не проверено: офлайн-старт Grafana с новым томом (синхронная установка без сети останавливает Grafana целиком, записано в OPERATIONS)
Риски: Trino без access control, пользователь grafana может писать в lake через Explore: W6-D17, карточка W6-T11; средняя доставка в таблице показана в неделях (автоформат единицы d)
```

### W6-T02 README как карта, ARCHITECTURE с диаграммой, страница доказательств

**Зависит от:** W6-T00 части 0-4, W5-T05b, W6-T05..T07. Чего к началу нет (T08, живой MinIO, ответ
W6-D15), README помечает `planned`. **Оценка** 4 ч. **Область:** `docs`.
Исполнитель `docs-writer`.
**Сделать.** README: что это, как запустить (одна команда), таблица статуса `done | measured |
planned` со ссылкой на доказательство у каждой строки, скриншоты. `ARCHITECTURE.md`: диаграмма по
W6-D14. `docs/evidence.md`: числа chaos 1-9, сверка, обслуживание до и после, CI и smoke run;
при «W6-D15: да» раздел «How it was built» по `13-harness.md`, раздел 11 (решения, ревью, журнал
«ок», без придуманных метрик).
**Готово, когда.** Каждая ссылка открывается (`grep -o '](.*)' | ...` проверка путей); утверждений
без ссылки нет; проверка стиля: нет длинного тире, имён владельца, упоминаний AI (кроме раздела
«How it was built» при «W6-D15: да» после правки `AGENTS.md` владельцем).

**Итог 29.10.**

```text
Критерий: «Каждая ссылка открывается; утверждений без ссылки нет; проверка стиля» (14-closeout-spec.md, W6-T02)
Изменение: коммит docs этой сессии (README.md, ARCHITECTURE.md с Mermaid, docs/img/architecture.svg, docs/evidence.md с «How it was built»; AGENTS.md «Язык и стиль» по «ок» владельца, две редакции; OPERATIONS: живое доказательство chaos 6 и CdcStalledSourceWrites); исполнитель docs-writer (две версии), OPERATIONS и AGENTS.md оркестратор
Проверка: скрипт ссылок docs-writer по README, ARCHITECTURE, evidence: все относительные ссылки и якоря разрешаются, кроме намеренно относительных ссылок GitHub на запуски Actions (`../../actions/runs/<id>`, без логина владельца); grep длинного тире пуст; reviewer сверил числа с источниками (make reconcile 19:09, gh run view восьми запусков, OPERATIONS, итоги карточек)
Независимо: reviewer по документу «принять с замечаниями» (3 средних, 11 низких); исправления по всем, кроме гигиены теста харнесса (раздел 7); повторного прохода по исправлениям не было (владелец попросил закрывать сессию)
Не проверено: открытие ссылок actions/runs на GitHub после push (открыть одну из README и одну из docs/evidence.md); повторное ревью исправлений
Риски: числа дашборда в evidence сняты до перехода панелей на lake_ro (помечено); CI на HEAD после этого коммита проверить gh run list
```

### W6-T03 `docs/interview-notes.md`

**Оценка** 3 ч. **Зависит от:** нет для черновика; сверка фактов после W6-T02. **Область:** `docs`.
30 вопросов и ответов по Kafka, Spark, Iceberg, CDC,
идемпотентности, DQ, каждый ответ с примером из проекта и ссылкой на файл. Мок-собес проходит
владелец (гейт).

### W6-T09 Окно B6

**Зависит от:** W6-D12; владелец выполнил действие «питание для B6» (HANDOFF, «Действия владельца»).
**Сделать.** Записать начало окна UTC; через 24 ч команды из `08-w3-plan/T05b-dags-dq-maintenance.md:620-634`,
`docker compose logs airflow-scheduler | grep -c 'Heartbeat recovered'` и события Windows за окно:
`cd /mnt/c && wevtutil.exe qe System "/q:*[System[(EventID=42 or EventID=506)]]" /c:20 /rd:true /f:text`
(дата каждого события вне окна).
**Готово, когда.** По нулю failed у четырёх DAG за окно, 0 строк `Heartbeat recovered`, 0 событий
42 и 506 внутри окна, `docker stats` записан.

### W6-T11 Trino: пользователь `grafana` только читает `lake.gold`

**Зачем.** W6-D17: ревью W6-T01 (замечание 4) нашло, что Trino без аутентификации и access control,
а плагин Grafana выполняет любой SQL; на Lakekeeper drop таблицы стирает файлы.
**Оценка** 2-3 ч. **Зависит от:** W6-T01 (коммит кода дашборда). **Область:** `infra`.
**Сделать.** Тест первым (правила разбираются unit-тестом: `grafana` только SELECT на `lake.gold`,
остальные клиенты с прежними правами); `docker/trino/etc/access-control.properties` и правила
(`access-control.name=file`); монтирование в compose; OPERATIONS «Dashboards» и риск в разделе
Trino. Живой шаг по «ок»: пересоздание `trino`.
**Готово, когда.** От `grafana` select по `lake.gold` проходит, create, insert и drop получают
отказ; `make dbt-build`, `make reconcile`, `make verify` и дашборды проходят как раньше; `make
check` зелёный; вердикт `reviewer`.

**Итог 29.10.**

```text
Критерий: «От grafana select по lake.gold проходит, create, insert и drop получают отказ; make dbt-build, make reconcile, make verify и дашборды проходят как раньше; make check зелёный; вердикт reviewer» (14-closeout-spec.md, W6-T11)
Изменение: 46f5282 (docker/trino/etc/access-control.properties, rules.json, catalog/lake_ro.properties с iceberg.security=read_only; панели Marketplace и check_dashboards на lake_ro.gold под пользователем grafana; тесты; OPERATIONS «Access control», Dashboards); отклонение от текста карточки: select идёт по lake_ro.gold, а не lake.gold, потому что file-based access control 483 не проверяет процедуры таблиц (ALTER TABLE EXECUTE), а каталог read_only их запрещает (решение A оркестратора по ревью); исполнитель implementer (две версии), вход scout
Проверка: разовый Trino 483 с правилами (memory-каталог): файлы разобраны, отказы grafana; живой шаг 19:14-19:16 UTC по «ок»: docker restart lakehouse-trino-1, healthy за 11 с, каталоги lake, lake_ro, system; grafana: select lake_ro.gold.fct_orders 96258, lake_ro.silver, каталог lake, system, create table, optimize через lake и lake_ro -> Access Denied; dbt через lake_ro optimize -> Access Denied (read_only); dbt, trino, airflow select lake.silver.orders 96258; make dbt-build PASS=68 WARN=4 ERROR=0; check_dashboards.py -> queries ok: 39; make check 890 passed, 83 skipped; make verify -> verify ok
Независимо: reviewer: круг 0 «вернуть» (1 высокое: процедуры таблиц обходят правила; 3 средних), круг 1 «принять с замечаниями» (1 средняя: дашборд до рестарта смотрел на несуществующий каталог, закрыто рестартом; 2 низкие исправлены в OPERATIONS)
Не проверено: drop от grafana (слово блокирует хук; покрыто create и read_only); поведение при битом rules.json (по документации)
Риски: без аутентификации Trino любой клиент с доступом к 8080 или сети lake может назваться dbt; админ Grafana может завести новый datasource с пользователем dbt (OPERATIONS «Access control»)
```

### W6-T10 Закрытие

**Оценка** 1 ч. **Область:** `docs`. HANDOFF итоговый, статусы в `01-roadmap.md`, `NEXT_SESSION.md`
на поддержку, раздел 6 этой спеки с доказательствами.

### Гейты владельца (агент не выполняет)

| Гейт | Что делает владелец | Что готовит агент |
|---|---|---|
| W1-T08 Kafka | `02-learning-gates.md:13-16` | стек жив, адреса файлов и команд |
| W2-T08 Spark, Iceberg; Modify W2-T07 | `:22-34`; шаги Modify в HANDOFF «Следующие шаги» п. 6 | «ок» на порции реплея, проверочные SQL |
| W3-T07 dbt, Airflow | `:39-52` | `make chaos-break-dbt-test` готов |
| W4-T07 observability | `:58-61`, Operate chaos 6 и 9 | времена из OPERATIONS «Alerts»; для Modify только файлы и подсказка (`09-w4-spec.md:401`) |
| Spark Operate (W5-D15) | `make watermark-demo`, `make watermark-live` | профиль `stateful` поднят по «ок» |
| Итоговый мок-собес | `:65` | W6-T03 |

## 5. Порядок и коммиты

| # | Задача | Область | Зависит от |
|---|---|---|---|
| 0 | Внедрение регламента: владелец применяет патч хука и коммитит (`13-harness.md`, раздел 10) | `infra` | владелец |
| 1 | Старт сессии; со стеком: проверка контейнеров, образов (MinIO на месте), версий, `verify-fast` | | Docker для живой части |
| 2 | W6-T00, части 0-4 (код, ADR-026) | `infra`, `ci` | ничего |
| 2a | Параллельно 2: черновик W6-T03 (`docs-writer`); набор для каждого гейта владельца (файлы, команды, предпосылки, без ответов) в HANDOFF | `docs` | ничего |
| 3 | W6-T05, W6-T06 (алерты) | `obs` | код без Docker; `make alerts-test` и коммит ждут Docker |
| 4 | W6-T07 | `orchestrate` | Docker (правка `airflow/dags/` только при живом Airflow и паузе DAG); коммит после ответа W6-D9 |
| 5 | W5-T05b, шаги 0-13 | `lake` | Docker, W6-D5 (B), W6-D16, пакеты «ок» П1-П9, W6-D13 для шага 12 |
| 6 | W6-T00, часть 5 (копия tar, push, smoke, живой MinIO) | | 2, 5, W6-D3 |
| 7 | W6-T08 | | W6-D10 |
| 8 | W6-T01 | `obs` | 5, W6-D11 (B) |
| 8a | W6-T11 | `infra` | 8, W6-D17 |
| 9 | W6-T02, итог W6-T03; параллельно W6-T09 | `docs` | 2, 3, 4, 5; питание для B6 |
| 10 | W6-T10 | `docs` | все |

**Первая задача:** строка 2, W6-T00 части 0-4: оркестратор пишет ADR-026 (`Proposed`), `scout`
собирает флаги сборки и digest, `implementer` пишет тест, Dockerfile, compose и `smoke.yml`,
`reviewer` смотрит diff и решение W6-D1. Параллельно строка 2a. Без Docker код пишется и ревьюится,
но сборка образа и коммит ждут Docker и полного verify; незакоммиченным держится не больше одной
карточки (`13-harness.md`, раздел 5), поэтому после кода W6-T00 без Docker только Markdown строки 2a,
затем стоп с просьбой запустить Docker. После коммита владельца с правкой хука (`13-harness.md`,
раздел 10) любой коммит агента, даже Markdown, ждёт первого полного `make verify`: он идёт первым
шагом после запуска Docker. Строки 3 и 4 идут, пока ждут пакеты «ок» строки 5.

## 6. Проверки и итоговая приёмка

Проект принят, когда у каждой строки есть запись по `13-harness.md`, раздел 6:

1. `smoke.yml` зелёный на `main` по кнопке (ссылка на run); `ci.yml` зелёный на итоговом HEAD.
2. Полный `make verify` на итоговом дереве: `verify ok`; `make reconcile` 7 из 7; `dq_checks`
   `reconcile_values` зелёный в покое; `make dbt-build` без ERROR.
3. W5-T05b: числа до и после в OPERATIONS «Maintenance» и ADR-025, без удаления вне одобренного списка.
4. W6-T05..T08: каждая находка исправлена с регрессионной проверкой или закрыта решением владельца
   с записью.
5. B6: окно 24 ч по W6-T09.
6. В покое не горит ни один алерт, кроме записанных; `make alerts-test` зелёный.
7. README, ARCHITECTURE, evidence, interview-notes, DECISIONS по W6-T02, T03; ссылки живые.
8. Гейты закрыты в `LEARNING.md` владельцем или явно отложены им с записью.
9. Гигиена: gitleaks чистый, нет длинного тире, имён владельца, упоминаний AI (кроме раздела по
   W6-D15); `git status` чистый;
   push с записью в журнале «ок».
10. Бюджет реплея посчитан в HANDOFF.
11. Холодный старт: новая сессия по `NEXT_SESSION.md` выдаёт верное состояние без подсказок.

## 7. Замечено и не входит

- Ревью п. 17 (`bronze_caught_up` против Kafka, а не источника), п. 27 (watermark в будущем), п. 39
  (actions по SHA), п. 36 (кейсы promtool `-init-`, `-migrate-`): кандидаты в буфер после W6-T10.
- Гейт коммита по индексу (ревью п. 23): правилом «один verify, один коммит», хук не меняется.
- JDBC-строки `iceberg_catalog`, два анонимных тома, лаб-топики `lab.orders.*`, `lake.demo.meta_probe`:
  удаление в blast radius, решение владельца.
- dbt 1.10.23 deprecated, S3FileIO и vended credentials, снятие запрета expire bronze (ADR-021).
- Ревью W6-T00, замечание 4: у остальных сервисов compose с собственным `build:` (`spark-bronze`,
  `kafka-connect`, `oltp-replayer`, `airflow-api-server`, `container-exporter`) тоже нет
  `pull_policy` (`yaml.safe_load` по `services`, 27.10), а `lakehouse` на Docker Hub чужой
  неймспейс; `spark-silver` и `spark-orders-per-minute` уже с `never`. Кандидат в буфер:
  `pull_policy: never` и тот же тест; `minio` и `minio-init` закрыты в W6-T00.
- Ревью харнесса v0.3, круг 1 (29.10, «принять с замечаниями», дерево `ea241e4`), не исправлено:
  владелец попросил закончить после часа работы агентов, а правка кода гейта требует ещё одного
  прохода `reviewer`. Кандидаты в следующую правку харнесса:
  - средняя: «вернуть» вне формата роли (`Итог. Вердикт: вернуть`, `Вердикт - вернуть`, предмет
    `план и код`) хук не узнаёт, и прежнее «принять» по тому же коду остаётся в силе; docstring
    `record_review` обещает больше («never leaves an earlier accepting verdict in force»).
    Предложение: строку предмета со словом «код» считать кодом, любую строку со словами «вердикт» и
    «вернуть» без годной строки вердикта считать отзывом. До правки держит формат роли `reviewer`;
  - низкая: `make check > /tmp/log 2>&1` получает ложный отказ (`REDIRECT` в `guard.py` не
    пропускает цель после голого `>`); писать вывод через `| tee` или читать хвост;
  - низкая, найдено на коммите v0.3: `bends_make_check` режет текст команды без учёта кавычек, и
    сообщение коммита со словами «make check» получает отказ; формулировать сообщение иначе
    (`AGENTS.md`, «Хуки»), в правке разбирать слова через `shlex`, как `reads_only`;
  - низкая, ревью правки часов теста expire (29.10, «принять с замечаниями»):
    `test_expire_leaves_one_snapshot_and_reports_deleted_files` проверяет только ключ
    `deleted_data_files_count` (значение 0), а expire удаляет 5 manifest lists; было так и до
    правки. Кандидат: `assert result["deleted_manifest_lists_count"] > 0`;
  - низкая: закрывающий текст после handback с повтором строки вердикта без дерева отзывает только
    что записанное «принять» (закрытый отказ, лишний проход); на 2.1.306 так же может сработать
    промежуточный `SubagentStop` (исправлено в 2.1.311).
- Ревью W6-T05/06 (29.10, два прохода «принять с замечаниями»), не исправлено: низкая, точка
  `eval_time: 13m` случая «Traffic moves the slot» молчит из-за `count_over_time` (53 < 200), то
  есть тривиально; мутацию «сырой ряд» ловят точки 73m и 118m. Порог 200 закреплён тестом только
  снизу. Низкая, найдено ревью круга 0: описание панели слота в
  `observability/grafana/dashboards/pipeline-health.json:222` не называет `SlotWalHeldIdle`.
- Ревью расписания smoke (29.10), низкая: `test_smoke_runs_on_demand_and_weekly_and_checks_verify_ok`
  проверяет `permissions` только на верхнем уровне; `contents: write` на уровне job тест не ловит
  (пробел был и раньше). Кандидат: ни у одного job нет `permissions` шире `contents: read`.
- Ревью W6-T01 (29.10, второй проход «принять с замечаниями»), не исправлено, низкие:
  `test_trino_query_stops_at_the_deadline_when_the_query_never_finishes` при снятой проверке
  дедлайна не падает, а виснет (заглушка всегда отдаёт nextUri, у pytest нет таймаута);
  размножение строк join в панели (CROSS JOIN) тестами не ловится, сверка сумм только ручная.
- Ревью W6-T07 (29.10, круг 1), низкая: ветка `rows[0][0] is None` в `cdc_progress` недостижима
  (`coalesce(..., 0)`), мутация её удаления эквивалентна.
- Ревью W6-T02 (29.10), низкая, гигиена раздела 6 п. 9: `tests/unit/test_agent_hooks.py:375` содержит
  путь с домашним каталогом владельца (`/home/<имя>/...`); заменить на `/home/user/...` (тест
  харнесса: правка с `make check` и ревью). `LEARNING.md:4` «task the AI with a change»: файл
  гейтов владельца, правит владелец.
- Процесс 29.10: второй прогон `make dbt-build` (19:17-19:18 UTC) запущен после снятия паузы с
  `dbt_build`, что нарушает условие класса A; пересечения не было (последний запуск `dbt_build`
  18:23). Ошибка оркестратора, записана.
- Харнесс, 29.10: `guard.py` отказывает («writes a gate stamp by hand») на составной команде,
  где чтение файла отметки или встроенный Python идут в одной строке с
  `scripts/agent_state.py show`, и на heredoc с текстом об отметках; по отдельности проходят.
  Кандидат в правку харнесса.
