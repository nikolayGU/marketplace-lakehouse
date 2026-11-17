# IN. Инфраструктура, CI, безопасность

Аудит только чтением на HEAD `a8c1d49` плюс незакоммиченная правка владельца (ci.yml, test_workflows.py, OPERATIONS.md). В репозитории и на стенде ничего не менялось. Копии логов: `scratchpad/audit/IN-work/` (`fail.log`: `gh run view 43423260590 --log-failed`, `pf.txt`).

## Оценки

- Платформа, DevOps: 4 из 5. Чистый клон до `verify ok` одной командой доказан smoke (последний зелёный 42872707771, 10.11), образы и actions закреплены тестом. Минус: CI красный на HEAD, раннер и uv плавают.
- Безопасность: 4 из 5. Порты только на `127.0.0.1` (`${BIND_IP:?}` обязателен), история чистая (gitleaks: 148 коммитов, 0 находок), push protection включён. Минус: общие суперпользовательские учётки, сервисы без аутентификации, модель угроз нигде не записана одним абзацем.
- Новый инженер (первый запуск): 4 из 5. Путь README проходит на чистом раннере (smoke), но хост-зависимости (`python3` ≥ 3.11, `envsubst`, JDK) не названы, и на типичных машинах падает последний шаг или `make check`.

## Сильные стороны

- Закрепление всего, что тянется извне, и тест на это. Образы compose и `FROM` по `@sha256`, actions по SHA с версией в комментарии, `pip ==`, promtool из того же digest, что Prometheus: `tests/unit/test_pinning.py:77-309`. SHA всех 9 actions сверены с тегами через `gh api repos/<r>/git/ref/tags/<t>`, совпали.
- MinIO и mc собираются из исходников с проверкой, что тег указывает на записанный коммит (`docker/minio/Dockerfile:16-18,40-42`). CI запускает собранные образы (`scripts/check-minio-images.sh`, job `minio-images`).
- Защита от ложного зелёного в CI. `FAIL_ON_SKIP=1` превращает любой skip в провал (`tests/unit/conftest.py:9-29`). Postgres-сверка идёт на сервисе того же digest, что `postgres-oltp` (`ci.yml:25-36,64-67`). Матрица hadolint сверяется тестом с файлами (`test_workflows.py:18-22`).
- Секреты. `make secrets` генерирует их и никогда не переписывает существующий `.env`, только дописывает недостающие ключи (`scripts/make_env.py:57-78`). Пароли уходят в curl через stdin, а не через argv (`connect/register.sh:62-65`, `scripts/lakekeeper/bootstrap.sh:32-35`). gitleaks стоит в CI и pre-commit. GitHub secret scanning и push protection включены (`gh api repos/.../ security_and_analysis`).
- Bash: все 26 скриптов в strict mode (`set -euo pipefail` или через `lib.sh:3`; `report.sh` без `-e` намеренно). У проб Trino, Lakekeeper и MinIO в `verify` есть лимит и внятная причина отказа (`scripts/chaos/lib.sh:57-105`).
- Идемпотентный старт доказан. Smoke делает второй `make bootstrap` и требует `replay state exists, load skipped` и `verify ok` (`smoke.yml:55-60`).
- Версии инструментов совпадают в pre-commit и `uv.lock`: ruff 0.16.8, yamllint 1.37.1 (`.pre-commit-config.yaml:17,23`).

## Старый бэклог

| ID | статус сейчас | делать / не делать | причина |
|---|---|---|---|
| Красный CI | открыт: run 43423260590 на `a8c1d49`, `Image: ubuntu-26.04`, `1926 passed, 97 skipped, 49 errors`, `getSubject is not supported` | делать (IN-01) | красный CI на первой странице |
| R-03 | открыт: `scripts/chaos/lib.sh:317`, `scripts/chaos/break-dbt-test.sh:24` | делать (IN-05) | молчаливый обрыв сценария, правка в одну строку |
| R-04 (скрипты) | открыт: `spark-kill.sh:6`, `late.sh:14-15`, `connect-restart.sh:9`, `connect/snapshot.sh:33` | делать (IN-06) | в `lib.sh:153-158` уже есть `service_healthy` по id. Часть про алерты (`alerts.yml:58,157`) ведёт область OB |
| R-09 (`_AIRFLOW_DB_MIGRATE`) | открыт: `docker/airflow/airflow.env:19` | не делать | scheduler и dag-processor ждут healthy api-server (`compose.yaml:604-606,634-636`), миграции идут последовательно. Правка env пересоздаёт три контейнера Airflow (C) без видимой пользы |
| R-09 (`make help`) | открыт: `Makefile:10`, регэксп без `%`; цели с `##` 43, вместе с `chaos-%` 44 | делать (IN-09) | chaos-сценарии нужно показывать, правка в один символ |
| R-21 | открыт (интервалы healthcheck) | не делать | экономия CPU в покое, читатель её не увидит; пересоздаёт `kafka`, `airflow-scheduler`, `airflow-dag-processor` (C) |
| R-22 | открыт: `.env.example:51` `TRINO_XMX=2500m`, ручной `TRINO_XMX=2g` в `OPERATIONS.md:596-603` | делать (IN-13) | у нового клона уходит ловушка; `.env` владельца не трогается, стенд не пересоздаётся |
| R-41 | открыт (дубли env трёх Spark-сервисов `compose.yaml:308-326,368-387,426-439`) | делать после R-40 (IN-14) | равенство проверяется: `config --hash '*'` до и после. Без R-40 треть дублей уйдёт сама |
| R-43 | открыт: копия SQL `bronze_offsets_ok` в `spark-kill.sh:69-77`, `fail()` в 5 файлах, токен REST в `silver-kill.sh:24-29` против `lib.sh:335-337`, CI повторяет `make lint` (`ci.yml:51-58,68-69` против `Makefile:138-145`), shellcheck нет | делать (IN-06, IN-07, IN-08) | проверка exactly-once должна жить в одном месте; shellcheck для 2100 строк bash стандарт |
| R-01 | закрыт `9ea802d` (Connect 1792M, Grafana 512M, exporter 128M: `compose.yaml:149,707,803`) | закрыт | |
| PF-02 | закрыт `22a8748`: `postgres-meta` только в `core` (`compose.yaml:544`); `--profile orchestrate config --services` даёт 3 сервиса Airflow | закрыт | |
| PF-03 | открыт: у `BIND_IP` нет предупреждения (`.env.example:4`), в README нет модели безопасности (`grep -n -i "security model" README.md` пусто) | делать (IN-04) | репозиторий публичный |
| PF-04 | открыт: «last community» в `README.md:51`, `compose.yaml:154`, `docker/minio/Dockerfile:1`, `DECISIONS.md:11`; при этом `gh api repos/minio/minio/tags` даёт `RELEASE.2025-10-15T17-29-55Z` новее закреплённого, репозиторий archived | делать текст (IN-12), тег не менять | ложное утверждение. CVE здесь недостижимы (PF-04, файл 18) |
| PF-05 | закрыт: smoke 42606043447 и 42872707771 | закрыт | |
| PF-10 | открыт (DockerOperator тянет образ) | область OR | |
| PF-11 | открыт: пароль Debezium литералом в Connect REST (`connect/register.sh:58-65`) | не делать код, назвать в IN-04 | нужны перерегистрация и ротация (C); порт на loopback |
| PF-12 | открыт: `SUPERSET_SECRET_KEY` без `:?` (`compose.yaml:825,863,904`) | не делать | `make secrets` пишет ключ; пустой ключ падает громко на входе, а не молча |
| PF-13 | открыт: `git check-ignore -q .env.bak` ничего не находит (`.gitignore:1`) | делать (IN-11) | дешёвая защита от утечки копии `.env` |
| PF-14 | открыт: `persist-credentials` нигде (`grep -n persist-credentials .github/workflows/*.yml` пусто) | делать в IN-01; `--freeze` для pre-commit не делать | токен read-only, но его видит код зависимостей при `uv sync` и `pytest`; pre-commit работает только локально |
| PF-15 | открыт (root у minio, lakekeeper; нет `cap_drop`) | не делать, назвать в IN-04 | пересоздание почти всех сервисов (C) ради ноутбука на loopback |
| PF-16 | открыт (нет CVE-сканирования) | не делать, строка в IN-04 и в «Not covered» (`OPERATIONS.md:1220-1224`) | новая зависимость и шум в замороженном проекте |
| PF-17 | открыт: суперпользователь META у Airflow, Superset, Lakekeeper, Spark, Trino; root-ключи MinIO у 8 сервисов | не делать, назвать в IN-04 | роли создаются только на пустом томе (`oltp/init`, `docker/postgres-meta/init`), C. Часть уйдёт с R-40 (DP) |
| PF-25, PF-54 | открыты | область OB | |
| PF-26 | открыт | область HS (`report.sh`) | |
| PF-36 | открыт: `compose.yaml:470,473`. `DATA_DIR=./data` считается от каталога compose, отсюда пустой root-овый `docker/data` (`ls -la docker/data`: root, 21.09) | делать (IN-10) | мёртвый и неверный mount на виду у читателя |
| PF-46 | закрыт `9ea802d`: `compose.yaml:872-873` | закрыт | |
| PF-64 | открыт: `git ls-remote --heads origin` даёт `w3-fernet-replay-data` | решение владельца | запись в remote (C) |
| F-08, F-09, F-21..F-27, F-31 | сведены в PF-17, PF-11, PF-04, PF-15, PF-16, PF-36, PF-13, PF-54, PF-25, PF-14 | как у PF | |
| Б7 | закрыт `8fafdbb` (`test_pinning.py`) | закрыт | |
| Б20 | закрыт `a3a56f8` (`grep -n TODO docker/compose.yaml` пусто) | закрыт | |
| Б6 | открыт (учения восстановления) | разрыв с продом, область OB | |
| Спека 14, раздел 7: тест прав smoke на уровне job | открыт: `test_workflows.py:56` смотрит только верхний уровень | делать в IN-01 | одна строка теста |
| Спека 14, раздел 7: `pull_policy` у сборок, actions по SHA | закрыты `8fafdbb` | закрыт | |

## Находки «делать»

### IN-01 [высокая] CI красный на HEAD; правка в дереве верна, но раннер и инструменты продолжают плавать

Где: `.github/workflows/ci.yml:19,75,98,108,124,149` (`runs-on: ubuntu-latest`), `smoke.yml:17`; `ci.yml:42`, `smoke.yml:34` (setup-uv без `version`); `ci.yml:38,89,101,111,127,152`, `smoke.yml:22` (checkout v4.4.0); `ci.yml:70` (gitleaks v2.3.9); незакоммиченные `ci.yml:45-49`, `tests/unit/test_workflows.py:101-113`.

Факт:
- `gh run view 43423260590 --log-failed`: `Image: ubuntu-26.04`, `1926 passed, 97 skipped, 49 errors`, `java.lang.UnsupportedOperationException: getSubject is not supported` в `JavaSparkContext.<init>`. Последний зелёный run 43400391213 прошёл на `Image: ubuntu-24.04`.
- Остальные 11 job того же красного run зелёные на ubuntu-26.04.
- По README образа ubuntu-26.04 Java по умолчанию 25.0.5, установлены 11, 17, 21, 25. Spark 3.5 поддерживает Java 8/11/17 (spark.apache.org/docs/3.5.7). GitHub переводит `ubuntu-latest` на 26.04 с 19.10 по 19.11.2026, а workflow с `ubuntu-24.04` остаются на прежнем образе (github.blog/changelog 2026-09-17).
- Аннотация каждого run: «Node.js 20 is deprecated ... forced to run on Node.js 24: actions/checkout@11d5960, astral-sh/setup-uv@d0cc045». Node 20 убран с раннеров 23.09.2026 (github.blog/changelog 2025-09-19).
- `uv --version` локально 0.12.17. setup-uv без `version` ставит последний uv, потому что в `pyproject.toml` нет `required-version`. OPERATIONS сам признаёт это в `:1223`.

Оценка правки в дереве. Она верна и достаточна, чтобы позеленеть: setup-java ставит `JAVA_HOME` и `PATH` до `uv sync`, pyspark берёт JVM из `JAVA_HOME`. Тест закрепляет версию 17, дистрибутив temurin и порядок шагов. `uv run --no-sync pytest tests/unit/test_workflows.py tests/unit/test_pinning.py -q` даёт `22 passed`. SHA `77dd5b2...` сверен: это тег v6.2.0, node24. Не хватает трёх вещей: раннер по-прежнему плавает (следующая смена образа сломает другое: Docker 29.4, Compose 5.1, Python системы), uv не закреплён, smoke ни разу не шёл на 26.04 (следующий плановый запуск 16.11 03:00 UTC).

Чем плохо: красный CI на первой странице репозитория. Через неделю красным может стать и smoke на новом образе.

Правка (тесты первыми, в `tests/unit/test_workflows.py`):
1. Тест: ни в одном workflow нет `ubuntu-latest`, у каждого job `runs-on == "ubuntu-24.04"`. Тест: у каждого шага `astral-sh/setup-uv@` есть `with.version == "0.12.17"`. Тест: ни у одного job нет `permissions`, кроме `contents: read` и `pull-requests: read` (раздел 7 спеки 14). Тест: у каждого `actions/checkout@` есть `with.persist-credentials: false`. Сначала все четыре красные.
2. `runs-on: ubuntu-24.04` во всех 6 job `ci.yml` и в `smoke.yml`. Это образ, на котором прошли все 12 job и smoke до 13.11.
3. Оставить правку владельца, то есть setup-java temurin `"17"`: JDK не зависит от образа и равен JDK образа Spark. Патч-версию не закреплять, линия LTS 17.
4. setup-uv: `version: "0.12.17"` в обоих workflow.
5. Обновить actions на node24 минимальным шагом:
   - `actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v5.1.0` (единственное изменение: node24);
   - `astral-sh/setup-uv@37802adc94f370d6bfd71619e3f0bf239e1f3b78 # v7.6.0` (удалён вход `server-url`, здесь он не используется);
   - `gitleaks/gitleaks-action@e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e # v3.0.0` (только node24, «No changes to inputs, outputs, or behavior»).
   SHA сверить через `gh api repos/<r>/git/ref/tags/<t>` (на 13.11 тип `commit`).
6. `with: persist-credentials: false` у всех checkout. gitleaks-action берёт историю из `fetch-depth: 0` и API через `GITHUB_TOKEN`, git-учётка ему не нужна.
7. Документы: `OPERATIONS.md:1141-1149` (раннер ubuntu-24.04, JDK 17, uv 0.12.17); строку `:1223` про uv убрать; `README.md:156` и `docs/evidence.md` «CI and smoke»: новый зелёный run.

Проверка:
- `uv run pytest tests/unit/test_workflows.py tests/unit/test_pinning.py -q`: все passed.
- `grep -rn "ubuntu-latest" .github/` пусто.
- После push (C, «ок» владельца): `gh run watch <id> --exit-status` даёт success 12 из 12. `gh run view <id> --log | grep -E "Image: |getSubject|Node.js 20"` выдаёт только `Image: ubuntu-24.04`. В итоге pytest `0 errors`.
- Затем `gh workflow run smoke.yml --ref main` (C), success.

Размер: S. Класс B, push и запуск smoke класса C, нужно «ок» владельца.
Старый ID: красный CI; PF-14; раздел 7 спеки 14.

### IN-02 [средняя] Локальные Spark-тесты проверяют только наличие `java`: на хосте с JDK 21 или 25 `make test` и `make check` красные

Где: `tests/unit/test_bronze_cdc_ingest.py:38`, `test_contracts.py:31`, `test_maintenance.py:42`, `test_iceberg_sink.py:20`, `test_orders_per_minute.py:21`, `test_iceberg_demo.py:17`, `test_silver_upsert.py:43`: везде `shutil.which("java")`. `Makefile:153` («Spark ones skip on a host without Java»).

Факт: ровно эти тесты дали 49 errors на раннере с Java 25. Вывод: у инженера с `default-jdk` новее 17 (Ubuntu 26.04, Fedora, Homebrew) `make check` упадёт так же.

Чем плохо: первый `make check` нового инженера красный по причине, которой нет в README. Проект выглядит сломанным.

Правка: один помощник в `tests/unit/conftest.py` или `tests/unit/spark_jvm.py`: «есть JVM, на которой работает Spark 3.5» = `java -version` с major 17 (11 допустимо), иначе skip с причиной «local SparkSession needs Java 17 (Spark 3.5 runs on 8/11/17); CI and the image have it». Заменить им 7 копий. Тест первым: разбор вывода `java -version` (`openjdk version "25.0.5"` даёт 25, `"17.0.21"` даёт 17, `"1.8.0_392"` даёт 8). Ложного зелёного не будет: в CI эти файлы целиком идут в job `spark-tests` с `FAIL_ON_SKIP=1` (`Makefile:159-170`), а setup-java 17 закреплён тестом из IN-01. В README, «Requirements» (`README.md:48-49`), одна фраза: Java на хосте не нужна; если она есть, локальные Spark-тесты идут только на 17.

Проверка: `uv run pytest tests/unit -q` на хосте без Java: число skipped прежнее (146). Тест разбора passed. CI зелёный.
Размер: M. Класс B.
Старый ID: нет.

### IN-03 [средняя] Последний шаг `make verify` и `make bootstrap` зависит от системного `python3` ≥ 3.11 и от git; хост-зависимости не названы в README

Где:
- `scripts/verify.sh:67` (`python3 "$ROOT/scripts/agent_state.py" stamp ...`), `scripts/chaos/lib.sh:252`, `scripts/report.sh:14`, `Makefile:157`;
- `scripts/agent_state.py:25` (`from datetime import UTC`, есть только с 3.11) и `:109-112` (`git read-tree HEAD`);
- `connect/register.sh:58` (`envsubst`);
- `README.md:48-49` (Requirements: только WSL2, Docker, диск, «Python 3.12 with uv»).

Факт: скрипты уже используют Python из venv uv в `scripts/bootstrap.sh:18` и `lib.sh:170` (`.venv/bin/python`), а в местах выше вызывают системный `python3`.

Вывод:
- на Ubuntu 22.04 (системный Python 3.10) `make verify` пройдёт все проверки и упадёт на отметке с `ImportError`, без `verify ok`. Вместе с ним падает конец `make bootstrap`;
- на дереве не из git (скачанный ZIP) отметка падает на `git read-tree`.

Не проверено: запуск на 3.10. Проверит `docker run --rm -v "$PWD":/r:ro python:3.10-slim python -c "from datetime import UTC"` (по «ок»).

Чем плохо: проверка данных прошла, а пользователь видит traceback харнесса агентов в публичной команде.

Правка:
1. Все хостовые вызовы перевести на `"$ROOT/.venv/bin/python"`, как в `bootstrap.sh:18`. venv создаёт уже `make secrets` через `uv run`.
2. Отметку в `verify.sh:67` сделать необязательной: `... stamp ... || echo "verify: tree not stamped (needs a git work tree); the checks above passed" >&2`. Гейт коммита без отметки и так отказывает, то есть остаётся fail-closed.
3. `README.md:48-49`: host tools `make`, `git`, `curl`, `envsubst` (gettext-base); свободные порты, ссылка на `OPERATIONS.md#ports-all-on-127001`; пример `.wslconfig` (`memory=12GB`).

Тест первым: в `tests/unit/test_verify_script.py`, на фейковом окружении по образцу существующих проб, сделать так, чтобы шаг отметки падал. Ожидание: последняя строка `verify ok`, код 0.

Проверка: `uv run pytest tests/unit/test_verify_script.py -q` passed. `grep -nE '(^|[^/])python3 "\$ROOT' scripts -r` пусто.
Размер: S. Класс B.
Старый ID: нет.

### IN-04 [средняя] Нет модели безопасности: у `BIND_IP` нет предупреждения, общие учётки и сервисы без входа не названы в одном месте

Где: `.env.example:4`; `README.md:76-80` («Every port is bound to 127.0.0.1...»); `OPERATIONS.md:289-350` (Access control только про Trino).

Факт: без аутентификации работают Airflow (все админы, `airflow.env:11-12`), Trino, Kafka (с хоста можно писать в `oltp.shop.*`), Connect (GET config отдаёт пароль Debezium), Lakekeeper (allow-all), MCP с правами Superset Admin. У scheduler и container-exporter есть `docker.sock`, это root на хосте (`compose.yaml:611-616,791-793`). Суперпользователь `META_USER` у Airflow, Superset, Lakekeeper, трёх Spark и Trino. Суперпользователь `OLTP_USER` у реплеера, `postgres-exporter` (`compose.yaml:740`) и `dq_checks` (`airflow.env:46-50`). Root-ключи MinIO у 8 сервисов. CVE-сканирования нет. `grep -n -i "security model" README.md` ничего не находит.

Чем плохо: публичный репозиторий. Кто-то поставит `BIND_IP=0.0.0.0`, чтобы открыть Grafana с телефона, и откроет Airflow без входа с `docker.sock`, то есть root на хосте. Ревьюер по безопасности не найдёт честного списка компромиссов.

Правка (текст, без кода):
- комментарий над `.env.example:4`: «loopback only: Airflow, Trino, Kafka, Connect, Lakekeeper and the Superset MCP have no authentication, and the Airflow scheduler holds the Docker socket»;
- в README раздел «Security model» до 10 строк, со ссылкой на OPERATIONS. В нём: граница одна (loopback); список сервисов без входа; общие учётки (PF-17); пароль Debezium в Connect REST (PF-11); `docker.sock` (ADR-011, ADR-023); root-процессы (PF-15); закреплённый тег MinIO 2025-09 с принятыми CVE (PF-04); нет сканирования CVE (PF-16);
- в «Not covered» (`OPERATIONS.md:1220-1224`) строка про CVE.

Проверка: `grep -n -i "security model" README.md` и `grep -n -B1 "^BIND_IP" .env.example` дают текст. Проверка ссылок скриптом области DC.
Размер: S. Класс A (`docs-writer`).
Старый ID: PF-03, PF-11, PF-15, PF-16, PF-17 (часть про документ).

### IN-05 [низкая] `run_dag` и `break-dbt-test.sh` молча обрываются при сбое `dags list-runs`

Где: `scripts/chaos/lib.sh:317` (`state=$(dag_run_state "$dag" "$run")`), `scripts/chaos/break-dbt-test.sh:24`.

Факт: `dag_run_state` состоит из конвейера `airflow_cli ... 2>/dev/null | python3` (`lib.sh:294-302`) при `pipefail`. `merge_silver` вызывает `run_dag` без `||` (`lib.sh:145`). Его зовут голым `connect-pause.sh:65,82`, `poison-event.sh:15,24`, `kafka-down.sh:45`, `connect-restart.sh:75`, `postgres-restart.sh:43`, `late.sh:24`, `duplicates.sh:48`. В `silver-kill.sh:186` то же место уже исправлено: `|| state=unknown`.

Чем плохо: сбой `docker compose exec` во время сценария при живом Airflow обрывает его кодом 1 без сообщения: stderr подавлен. Дежурный не поймёт, сценарий провален или сломан.

Правка: `|| state=unknown` в обоих местах, как в `silver-kill.sh:186`. Тест первым: bash-тест по образцу `tests/unit/test_makefile.py:131-140`. Сначала `source lib.sh` с фейковым `airflow_cli`: `trigger` проходит, `list-runs` падает. Затем `RUN_DAG_WAIT=1 run_dag d r`. Ожидание: код 1 и строка `still unknown after 1 s` в stderr. Сейчас тест красный, потому что скрипт выходит без строки.

Проверка: `uv run pytest tests/unit/test_reconcile_shell.py tests/unit/test_makefile.py -q` (или новый файл) passed; `bash -n` чист.
Размер: S. Класс B. Живые chaos не запускать.
Старый ID: R-03.

### IN-06 [низкая] Chaos-скрипты: зашитое имя проекта и копии проверок

Где:
- `scripts/chaos/spark-kill.sh:6` и `scripts/chaos/connect-restart.sh:9` (`container=lakehouse-...-1`), `late.sh:14-15`, `connect/snapshot.sh:33`;
- `spark-kill.sh:69-77`: копия `bronze_offsets_ok` (`lib.sh:219-227`);
- `fail()` в `connect-pause.sh:8`, `silver-kill.sh:12`, `kafka-down.sh:7`, `postgres-restart.sh:7`, `demo/watermark.sh:15`;
- токен REST Airflow: `silver-kill.sh:24-29` против `lib.sh:335-337`.

Факт: `lib.sh:153-158` (`service_healthy`) уже ищет контейнер по id «under any COMPOSE_PROJECT_NAME».

Чем плохо: проверка exactly-once, главное доказательство сценария 1, описана дважды и может разойтись (PF-32: семантику SQL тест не держит). При другом `COMPOSE_PROJECT_NAME` сценарии 1, 2 и 4 бьют не в тот контейнер или не находят его.

Правка:
- в `lib.sh` добавить `container_of() { "${COMPOSE[@]}" ps -q "$1"; }` и использовать его вместо литералов;
- `spark-kill.sh:69-77` заменить на `bronze_offsets_ok || { echo "FAIL: ..." >&2; exit 1; }`;
- один `fail()` и один `airflow_api_get` в `lib.sh`.

Поведение не меняется. Тест первым: `tests/unit/test_reconcile_shell.py` или новый тест, что `spark-kill.sh` вызывает `bronze_offsets_ok`. Лучше через AST bash или фейковый `trino_value`, чем по подстроке.

Проверка: `grep -rnE "lakehouse-[a-z-]+-1" scripts connect | grep -v '^\S*:\s*#'` пусто. `bash -n` на всех `*.sh`. `make test`. Живые chaos не запускать: расход реплея (C).
Размер: M. Класс B.
Старый ID: R-04 (скрипты), R-43.

### IN-07 [низкая] Bash без shellcheck

Где: `Makefile:140` и `ci.yml:52`, только `bash -n`. 26 скриптов, около 2100 строк (`wc -l`).

Факт: shellcheck на хосте нет. Попытку `uvx --from shellcheck-py shellcheck --version` отклонил классификатор режима auto. Сводки по классам ошибок нет (см. «Не проверено»).

Чем плохо: для «как для прода» статический анализ bash ожидается по умолчанию. `bash -n` ловит только синтаксис.

Правка: dev-зависимость `shellcheck-py==0.11.0.1` (PyPI, последняя на 13.11) через `uv add --group dev`, версия попадёт в `uv.lock`. В `make lint`: `uv run shellcheck -x -S warning $(git ls-files '*.sh')`. Первый прогон до правок, число находок записать в «Итог». Находки чинить или подавлять `# shellcheck disable=SCxxxx` с причиной. Если больше примерно 40, то `-S error` и отдельная строка в «Не сделано».

Проверка: `make lint` exit 0; в CI это работает через IN-08.
Размер: M (объём неизвестен). Класс B.
Старый ID: R-43.

### IN-08 [низкая] CI дублирует `make lint`

Где: `ci.yml:51-58,68-69` против `Makefile:138-145`.

Факт: те же 8 команд записаны дважды. Шаг `make lint`, добавленный в Makefile, в CI не попадёт.

Правка: в `lint-and-test` один шаг `cp .env.example .env && make lint` вместо шагов ruff, bash -n, mypy, yamllint, sqlfluff и compose config. В `test_ci_runs_the_checks_it_claims` (`test_workflows.py:58-70`) добавить `assert "make lint" in runs["lint-and-test"]`. Тест сначала красный.

Проверка: `uv run pytest tests/unit/test_workflows.py -q`; CI зелёный.
Размер: S. Класс B. Делать вместе с IN-01 в одном пакете.
Старый ID: R-43.

### IN-09 [низкая] `make help` не показывает `chaos-%`

Где: `Makefile:10`.

Факт: `grep -cE '^[a-zA-Z_-]+:.*?## ' Makefile` даёт 43, с `%` в классе символов 44.

Правка: `[a-zA-Z_%-]`. Тест в `tests/unit/test_makefile.py`: вывод `make help` (или тот же grep в Python) содержит `chaos-%`. Сначала красный.

Проверка: `uv run pytest tests/unit/test_makefile.py -q`.
Размер: S. Класс B.
Старый ID: R-09.

### IN-10 [низкая] Мёртвый и неверный mount у `oltp-replayer`

Где: `docker/compose.yaml:470` (`DATA_DIR: /data`), `:473` (`${DATA_DIR}:/data:ro`).

Факт: контейнер запускает только `start` (`oltp/Dockerfile:19`, `Makefile:77-78`), данные читает один `load` (`oltp/replayer/load.py:115`), а он идёт на хосте. `DATA_DIR=./data` compose считает от каталога `docker/`. Отсюда пустой `docker/data`, владелец root, дата 21.09 (`ls -la docker/data`). Это вывод: `config` без `-q` по правилам не запускался.

Правка: удалить обе строки. В `tests/unit/test_compose.py` тест, что у `oltp-replayer` нет `volumes`. Сначала красный.

Проверка: `docker compose --env-file .env.example -f docker/compose.yaml --profile '*' config -q`; `make test`.

Пересоздание: только `oltp-replayer`, при следующем `make replay-live` (сейчас не запущен, `docker ps`). Пустой `docker/data` (root) удаляет владелец (`sudo rmdir docker/data`, C).
Размер: S. Класс B.
Старый ID: PF-36, F-24.

### IN-11 [низкая] `.gitignore` закрывает только `.env`

Где: `.gitignore:1`.

Факт: `git check-ignore -q .env.bak` ничего не находит.

Правка: `.env.*` и `!.env.example`.

Проверка: `git check-ignore -q .env.bak && ! git check-ignore -q .env.example && echo ok`.
Размер: S. Класс A.
Старый ID: PF-13, F-25.

### IN-12 [низкая] «Last community release» для MinIO неверно

Где: `README.md:51`, `docker/compose.yaml:154`, `docker/minio/Dockerfile:1`, `DECISIONS.md:11` и текст ADR-026.

Факт: `gh api "repos/minio/minio/tags?per_page=5"` даёт `RELEASE.2025-10-15T17-29-55Z` выше закреплённого `RELEASE.2025-09-07T16-13-09Z`; `archived: true`. Для `mc` формулировка верна: последний тег `RELEASE.2025-08-13T08-35-41Z`.

Правка: «a pinned community release (MinIO 2025-09-07; a later 2025-10-15 tag exists and was not taken, ADR-026), mc 2025-08-13, the last mc tag». В ADR-026 строка с датой: почему тег не меняли. Комментарии в compose и Dockerfile не меняют ни config hash, ни слои.

Проверка: `grep -rn "last community" README.md DECISIONS.md docker` даёт только строку про `mc`.
Размер: S. Класс A.
Старый ID: PF-04, F-21.

### IN-13 [низкая] `TRINO_XMX=2500m` по умолчанию требует ручного `TRINO_XMX=2g` при Airflow

Где: `.env.example:51`; `OPERATIONS.md:8-9,594-603`; `README.md:60-61`.

Факт: все профили работали вместе на 2g (`README.md:60-61`, 10.11). `dbt_build` в Airflow всегда идёт при 2g, потому что так требует `OPERATIONS.md:601`. `query.max-memory=1GB` рассчитан и на 2g (`docker/trino/etc/config.properties:5-7`).

Правка: `.env.example:51` заменить на `TRINO_XMX=2g`, абзац `OPERATIONS.md:601-603` и префиксы `TRINO_XMX=2g` в `:9,596` убрать. Одна строка: «an existing `.env` keeps its value; set 2g there to drop the prefix».

Проверка: `grep -n "TRINO_XMX=2g make" OPERATIONS.md README.md` пусто. `uv run pytest tests/unit/test_compose.py -q`.

Пересоздание: нет. `make secrets` не переписывает существующий ключ (`make_env.py:57-68`), `.env` владельца остаётся 2500m. Правку собственного `.env` делает владелец, при следующем `make start` это пересоздаст `trino` (C).
Размер: S. Класс A.
Старый ID: R-22.

### IN-14 [низкая] Якоря compose для общих блоков, после R-40

Где: `compose.yaml:308-326,368-387,426-439` (env трёх Spark), `:825-829,863-866,904-907` (Superset), `networks: [lake]` у 27 сервисов.

Факт: прототип 10.11 на якорях: `config --hash '*'` совпал у 27 из 27, минус 75 строк (файл 19, R-41).

Правка: `x-spark-env: &spark-env` и `<<: *spark-env`, такие же для Superset. Делать после R-40 (область DP): удаление `CATALOG_JDBC_*` само сократит блоки.

Проверка: `docker compose --env-file .env -f docker/compose.yaml --profile '*' config --hash '*' > before` до правки и `after` после; `diff before after` пуст. Хэши, не значения: печать секретов не нужна.

Пересоздание: нет, если `diff` пуст. Иначе стоп: сервисы с новым хэшем пересоздаются (C).
Размер: M. Класс B.
Старый ID: R-41.

### IN-15 [низкая] «Every Monday» у smoke перестанет быть правдой после заморозки

Где: `README.md:218-219`, `docs/evidence.md:168`, `OPERATIONS.md:1150`, `.github/workflows/smoke.yml:9-10`.

Факт: GitHub отключает расписание в публичном репозитории после 60 дней без активности (docs.github.com, «Disabling and enabling a workflow»).

Правка: формулировка «weekly while the repository is active (GitHub pauses schedules after 60 idle days); last green run: <id>, <date>».

Проверка: `grep -n "every Monday" README.md` даёт новую формулировку.
Размер: S. Класс A. Связано с решением владельца 3.
Старый ID: нет.

## Находки «не делать»

| ID | что | почему не делать |
|---|---|---|
| R-09 (миграция) | `_AIRFLOW_DB_MIGRATE` во всех трёх контейнерах | старт последовательный через healthy api-server; правка пересоздаёт три контейнера Airflow (C) |
| R-21 | интервалы healthcheck | только CPU в покое; пересоздаёт `kafka`, `airflow-scheduler`, `airflow-dag-processor` (C) |
| PF-11 | `EnvVarConfigProvider` для пароля Debezium | перерегистрация и ротация (C), старые записи остаются в `connect-configs`; называется в IN-04 |
| PF-12 | `:?` у `SUPERSET_SECRET_KEY` | `make secrets` пишет ключ; пустой ключ падает громко |
| PF-14 (часть) | `pre-commit autoupdate --freeze` | хук только локальный, автообновление заодно поднимет версии |
| PF-15, PF-17 | `cap_drop`, роли на сервис | пересоздание почти всего стенда и роли только на пустых томах (C); честный текст в IN-04 |
| PF-16 | trivy, pip-audit, Dependabot | новая зависимость и шум в замороженном проекте; строка «Not covered» |
| нет | jar Spark сверяются с `.sha1` того же источника (`streaming/Dockerfile:26`) | правка требует пересборки образа Spark и пересоздания `spark-bronze` (C); уже названо в `OPERATIONS.md:1221` |
| нет | транзитивные pip без хэшей в образах | пересборка всех образов; названо в `OPERATIONS.md:1222` |
| нет | `make_env.py:75-76`: файл создаётся с umask, потом `chmod 600` | однопользовательский хост, окно в микросекунды |
| нет | `.dockerignore` | BuildKit передаёт только файлы из `COPY`; в контекстах нет секретов |
| нет | `make psql` берёт `OLTP_USER` из окружения хоста (`Makefile:84`) | верно при значениях `.env.example` |
| нет | закрепить `java-version` до патча | линия LTS 17; патч образа Spark с ней не связан |
| нет | branch protection на `main` | один автор, заморозка |
| нет | `DOCKER_GID` заполнять в `make_env.py` | рецепт с `stat -c %g` есть в `OPERATIONS.md:572-576`; профиль orchestrate необязателен |

## Первый запуск на чистой машине

Путь README (`README.md:25-34`): `make secrets`, затем `sed` `REPLAY_DATA=sample`, `make bootstrap`, `make replay-burst SECONDS=60`, `make verify`. На чистом раннере ubuntu-24.04 он доказан smoke (42872707771, 10.11, 10 мин 47 с). Чтением найдено:

1. Не названы хост-инструменты: `make`, `git`, `curl`, `envsubst` (`connect/register.sh:58`), `python3` ≥ 3.11 (`agent_state.py:25`, вызывается из `verify.sh:67`). На Ubuntu 22.04 `verify` и `bootstrap` падают последним шагом (IN-03).
2. JDK на хосте не 17: `make check` красный, 49 errors (IN-02).
3. Занятые порты: локальный Postgres на 5432 или что угодно на 8080 и 3000 рушат `make start`. Список портов есть только в OPERATIONS (`:38-62`), Quick start его не упоминает (IN-03, п. 3).
4. `.wslconfig` упомянут (`README.md:49`), но примера нет. Размер 12 GB взят из локальной настройки автора (файл 19, раздел 7) (IN-03, п. 3).
5. Первая сборка MinIO и mc из исходников требует GitHub и Go proxy (`README.md:51-56`, описано). Риск будущего: `minio/minio` archived. Если GitHub уберёт репозиторий, сборка встанет; образа-копии в репозитории нет, а откат ссылается на локальный `~/lakehouse-image-backup/minio-images.tar` (`OPERATIONS.md:1254-1255`). Принять как разрыв с продом.
6. Первый `make secrets` через `uv run` ставит всю группу dev (pyspark, dbt, kaggle). Это долго, но работает; README не предупреждает. Не делать.
7. Airflow на Linux требует `DOCKER_GID` (`OPERATIONS.md:572-576`); README ведёт в OPERATIONS. Достаточно.
8. Скачанный ZIP вместо clone: `verify` падает на отметке (IN-03, п. 2).
9. Пустой `docker/data` появляется от мёртвого mount (IN-10); у автора он уже есть.

## Разрыв с продом

- Аутентификации и TLS нет нигде. Граница одна: loopback.
- Общие суперпользовательские учётки Postgres и root-ключи MinIO у всех клиентов. Нет хранилища секретов и ротации.
- `docker.sock` у scheduler и экспортера (root на хосте) вместо исполнителя в кластере.
- Нет сканирования CVE, SBOM, Renovate. Digest обновляются вручную. MinIO собирается из archived upstream с принятыми CVE.
- Всё в одном узле: Kafka RF=1, один Postgres, compose вместо оркестратора, нет IaC.
- CI не доходит до gold. Нет staging и CD; smoke раз в неделю и только до silver.
- Восстановление из бэкапа не отрабатывалось (Б6, область OB).

## Не проверено

- shellcheck: не установлен; `uvx --from shellcheck-py shellcheck` отклонён классификатором. Проверит `uv run --with shellcheck-py==0.11.0.1 shellcheck -x -S warning $(git ls-files '*.sh')`.
- Правка CI на настоящем раннере: нужен push (C). Smoke на ubuntu-26.04 и на новых pins: `gh workflow run smoke.yml` (C).
- Минимальная версия Compose для `depends_on.required` и `--profile '*'` (по памяти около 2.20): проверить в документации Compose (context7).
- Python 3.10 на хосте: падение выведено из кода, не запускалось (команда в IN-03).
- Путь `docker/data` от `${DATA_DIR}`: вывод из семантики относительных путей и root-каталога 21.09; `config` без `-q` по правилам не запускался.
- Равенство `config --hash` для R-41 на текущем дереве: взято из файла 19.
- hadolint локально (нет бинаря); в CI зелёный во всех 7 матрицах run 43423260590.
- Порядок и полнота CI-документа `OPERATIONS.md:1136-1260` по существу ведёт OB (R-63): там история коммитов («On a running stack this commit...», `:1189-1218`).
