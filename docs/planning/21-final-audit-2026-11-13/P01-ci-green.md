# P01. CI зелёный и закреплён; мета-тесты CI ловят снятый шаг
Статус: исполнен 17.11.2026, `a21020a` (ci 44175270540 и smoke 44176185272, «Итог»).

## Цель

CI на коммите пакета зелёный 12 из 12 и не краснеет от смены образа раннера: раннер, JDK, uv и
actions закреплены, actions на node24, checkout не оставляет git-учётку. Мета-тесты CI краснеют,
если из `lint-and-test` выпал шаг, у job появились свои права или Spark-файл выпал из
`SPARK_TESTS`. Один коммит кода: workflows, тесты, строки CI в OPERATIONS и незакоммиченная
правка владельца (шаг setup-java, её тест, строка OPERATIONS) как есть. Push и smoke по «ок».

## Находки пакета

| ID | серьёзность | суть | где подробности |
|---|---|---|---|
| IN-01 | высокая | CI красный на HEAD (`ubuntu-latest` = 26.04, Java 25, Spark 3.5); раннер, uv, actions плавают; checkout без `persist-credentials: false` (PF-14) | `reports/IN.md`, IN-01 |
| QA-01 | средняя | мета-тесты CI не ловят мутации K1..K5 (шаг pytest, права job, `SPARK_TESTS`, `dbt-parse`, gitleaks) | `reports/QA.md`, QA-01 и «Мутации» |
| DC-13 (часть) | средняя | строки CI в OPERATIONS; README и evidence с новым run делает P13 по «Итогу» этого пакета | `reports/DC.md`, DC-13 |

Закрывает также: PF-14 (часть checkout), раздел 7 спеки 14 «права job в smoke», HANDOFF H-1.

## Решения владельца и действия класса C

- **В-01** (рекомендация «да»): `runs-on: ubuntu-24.04` во всех job `ci.yml` и `smoke.yml`.
  Если «нет»: шаг 3а и тест раннера не делать; smoke на 26.04 тогда доказывает только шаг 8.
- **В-02** (рекомендация «да»), класс C, «ок» на точный текст в момент исполнения:
  1. `git push origin main` (коммит кода, шаг 7);
  2. `gh workflow run smoke.yml --ref main` (шаг 8);
  3. `git push origin main` (коммит `docs:` с «Итогом», шаг 9).
  Просить одним сообщением как поимённую последовательность (`13-harness.md`, «Как просить «ок»»).
  Если «нет»: шаги 7 и 8 не делать, коммиты остаются локальными; строки «Готово» о run CI и
  smoke закрываются записью в «Итог»: «не проверено на раннере, отказ В-02».
- Версия uv (0.12.17 против 0.13.8 зелёных run) решается исполнителем, группа A: см. «Риски».

## Зависимости

- Жёстких нет, пакет первый. Незакоммиченная правка владельца в `ci.yml`, `test_workflows.py`,
  `OPERATIONS.md` входит в коммит пакета: не откатывать, не переписывать.
- P07 потом добавит шаг shellcheck в `lint-and-test` и строку в тест шагов этого пакета.
- P13 берёт id зелёного run и smoke из «Итога» (README:156, README «Testing and CI», evidence
  «CI and smoke»). P10 снимает ID в комментариях `ci.yml` (`QA-01`, `W5-T03`); новые строки P01
  пишутся без ID карточек.
- В дереве лежат чужие незакоммиченные `docs/HANDOFF.md`, `docs/NEXT_SESSION.md` и папка аудита:
  в коммит кода только файлы пакета (`git add` с путями). Остальное (папка аудита, HANDOFF,
  NEXT_SESSION, `docs/planning/README.md`) идёт в коммит `docs:` шага 9 по «ок» владельца
  (README папки, раздел 5, п. 9).

## Вход

Сверить первым шагом (номера на `a8c1d49` плюс правка владельца; после других пакетов по цитате):
- `.github/workflows/ci.yml:19,75,98,108,124,149` и `smoke.yml:17`: `runs-on: ubuntu-latest`.
- `ci.yml:38,89,101,111,127,152`, `smoke.yml:22`: `actions/checkout@11d5960... # v4.4.0`;
  `ci.yml:42`, `smoke.yml:34`: `astral-sh/setup-uv@d0cc045... # v6.8.0` без `version`;
  `ci.yml:70`: `gitleaks/gitleaks-action@ff98106... # v2.3.9`; все три `using: node20`.
- Правка владельца: `ci.yml:45-49` (setup-java v6.2.0, `"17"`, temurin),
  `tests/unit/test_workflows.py:101-113` (`test_ci_pins_java_17_before_the_first_pytest_step`),
  `OPERATIONS.md:1143` («Temurin 17 (as the Spark image)...»). `git diff --stat` по трём файлам.
- `test_workflows.py:59-71`: `test_ci_runs_the_checks_it_claims` проверяет 4 job из 5, у
  `lint-and-test` ничего. `Makefile:159-160`: `SPARK_TESTS` из 8 файлов.
- `OPERATIONS.md:1223`: «`rev:` ... is a tag, and no uv version is pinned for `setup-uv`;».
- `gh run list --limit 3`: `43423260590 ci failure a8c1d49`, `43420783131 ci failure 4adbab9`,
  `43400391213 ci success da7ad2f`. `gh run view 43423260590 --log-failed | grep -E 'Image: |
  getSubject'`: `Image: ubuntu-26.04`, `getSubject is not supported`. В зелёном 43400391213:
  `Image: ubuntu-24.04`, `Successfully installed uv version 0.13.8` (setup-uv без `version` берёт
  последний); smoke 42872707771 (10.11): `ubuntu-24.04`, uv 0.13.7. `uv --version`: 0.12.17.
- SHA новых actions, сверено 13.11.2026. Тег: `gh api repos/<r>/git/ref/tags/<t> --jq
  '.object.type + " " + .object.sha'` даёт `commit <sha>` (теги лёгкие; у аннотированного
  разыменовать `git/tags/<sha>`). Runtime: `gh api "repos/<r>/contents/action.yml?ref=<sha>"
  --jq .content | base64 -d | grep using:`. Перед правкой сверить ещё раз, тег мог уехать:

| action | тег | SHA | runtime |
|---|---|---|---|
| `actions/checkout` | v5.1.0 | `fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09` | node24 |
| `astral-sh/setup-uv` | v7.6.0 | `37802adc94f370d6bfd71619e3f0bf239e1f3b78` | node24 |
| `gitleaks/gitleaks-action` | v3.0.0 | `e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e` | node24 |
| `actions/setup-java` (владелец) | v6.2.0 | `77dd5b2ce225ea11469928ac317850245a74ae78` | node24 |

  Остальные actions уже node24 (`setup-buildx` v4.4.1, `build-push` v7.4.0, `upload-artifact`
  v7.0.2) или docker (`hadolint-action`). `grep -rn pull_request_target .github` пуст.
- База: `uv run --no-sync pytest tests/unit/test_workflows.py tests/unit/test_makefile.py
  tests/unit/test_pinning.py -q` -> `46 passed`.

## Границы

- Менять можно: `.github/workflows/ci.yml`, `.github/workflows/smoke.yml`,
  `tests/unit/test_workflows.py`, `tests/unit/test_makefile.py`, `OPERATIONS.md` (только раздел
  `## CI`: абзац после таблицы job и строка «Not covered» про uv).
- Нельзя: текст шага и теста владельца; состав и порядок прочих шагов CI (IN-08 не делаем,
  README, раздел 6); `Makefile` (если тест Spark-набора красный на дереве, стоп и вопрос);
  `pyproject.toml` (`required-version` не вводить); README, evidence (P13).
- Живой стек: только цикл verify раздела 5 `13-harness.md` перед коммитом.

## Шаги

1. **Вход.** Сверить факты выше; любой не сошёлся: шаг с ним не делать, записать в «Итог».
2. **Тесты первыми** (`implementer`, `tests/unit/test_workflows.py`, `tests/unit/test_makefile.py`;
   типы под `mypy --strict`, тесты в его `files`):
   - `test_every_job_runs_on_the_pinned_runner_image`: у каждого job каждого `*.yml`
     `runs-on == "ubuntu-24.04"`;
   - `test_setup_uv_installs_the_pinned_uv`: у каждого шага `astral-sh/setup-uv@`
     `with.version == "0.12.17"`, таких шагов 2;
   - `test_checkout_leaves_no_git_credentials_behind`: у каждого `actions/checkout@`
     `with["persist-credentials"] is False`, таких шагов не меньше 7;
   - `test_no_job_widens_the_read_only_permissions`: ни у одного job ключа `permissions`
     (верхний уровень уже держат `test_ci_reads_the_repo_and_nothing_more` и smoke-тест);
   - `test_lint_and_test_runs_every_check_it_claims`: среди `run` шагов `lint-and-test` точные
     строки `uv sync --locked --group dev`, `uv run ruff check . && uv run ruff format --check .`,
     `uv run mypy`, `uv run sqlfluff lint oltp/migrations`, `uv run sqlfluff lint models macros
     tests`, `make dbt-parse`, `uv run pytest tests/unit -q`; строка цикла `bash -n`, начало
     `uv run yamllint `, конец `--profile '*' config -q`; шаг `uses: gitleaks/gitleaks-action@`;
   - в том же тесте, отдельного теста нет (новых тестов шесть): файлы `tests/unit/test_*.py` со
     строкой `RECONCILE_TEST_DSN` входят в `run` шагов
     `lint-and-test` с `env.FAIL_ON_SKIP == "1"` (общее правило к
     `test_reconcile_postgres.py:343-361`);
   - в `test_makefile.py` `test_every_test_file_that_needs_spark_runs_in_test_spark`: файлы
     `tests/unit/test_*.py`, где `ast` находит `import pyspark` или `from pyspark...`, это
     подмножество имён `test_*.py` из `make -n test-spark` (хелпер `make()` файла); каждое имя из
     списка существует. Равенство не требовать: `test_envelope.py` в наборе без импорта pyspark.
     По импорту, а не по `shutil.which("java")`: P06 заменит эти проверки общим хелпером.
   Сейчас красные 3 (раннер, uv, checkout); права, шаги и Spark-набор зелёные и доказываются
   мутациями шага 5. Прототип этих тестов в копии дерева дал `52 passed` после шага 3.
3. **Workflows** (`implementer`): а) `runs-on: ubuntu-24.04` в 6 job `ci.yml` и в `smoke.yml`;
   б) setup-uv на SHA v7.6.0 и `version: "0.12.17"` рядом с `python-version`; в) checkout на SHA
   v5.1.0 и `persist-credentials: false` (у `lint-and-test` рядом с `fetch-depth: 0`, у прочих
   новый `with:`); г) gitleaks на SHA v3.0.0, `env` без изменений. Комментарий версии `# vX.Y.Z`
   у каждого SHA (`test_pinning.py:194-210`). Шаг setup-java владельца не трогать.
   Проверка: `uv run --no-sync pytest tests/unit/test_workflows.py tests/unit/test_makefile.py
   tests/unit/test_pinning.py tests/unit/test_reconcile_postgres.py -q` без failed;
   `uv run yamllint -c .yamllint .github` пуст.
4. **OPERATIONS** (`docs-writer`, по-английски, раздел `## CI`): после таблицы job абзац: все job
   и smoke на `ubuntu-24.04`, потому что `ubuntu-latest` стал `ubuntu-26.04` с Java 25, на
   которой Spark 3.5 падает (`getSubject is not supported`); setup-uv ставит uv 0.12.17, ту, что
   пишет `uv.lock`; checkout без git-учётки (`persist-credentials: false`). Строку `:1223` свести
   к «`rev:` in `.pre-commit-config.yaml` is a tag;». Без ID карточек и без номера run.
5. **Мутации** (оркестратор, только копия в scratchpad): копия дерева после шагов 2-4
   (`git ls-files -co --exclude-standard -z | xargs -0 cp --parents -t <scratchpad>/copy`);
   раннер `work/QA/mutate.py.txt` -> `<scratchpad>/mutate.py`, `<repo>` заменить корнем
   репозитория; `work/QA/mutations3.json.txt`, у K2 `ubuntu-latest` -> `ubuntu-24.04` в `old` и
   `new`, у K5 строка gitleaks нового SHA и `# v3.0.0`. Плюс две свои: K8 (`smoke.yml`:
   `runs-on: ubuntu-24.04` -> `ubuntu-latest`), K9 (строка `version: "0.12.17"` в `smoke.yml`
   удалена), поле `tests` как у K2. Запуск: `uv run --no-sync python <scratchpad>/mutate.py
   <scratchpad>/mutations.json K1 K2 K3 K4 K5 K8 K9` -> у каждой `RED (caught)`. Прототип 13.11
   дал RED на всех семи.
6. **Проверки и ревью.** `make check`; `reviewer` (предмет `код`, diff всех пяти файлов, этот
   «Готово, когда», вывод шагов 3 и 5); замечания чинит `implementer`, не больше двух кругов;
   цикл verify и коммит по разделу 5 `13-harness.md`, как он действует на момент исполнения.
   Сообщение: `ci: runner image, uv and node24 actions pinned, java 17 for the spark tests, meta
   tests for the ci steps`.
7. **Push** (C, В-02.1) и CI: `gh run list --workflow ci.yml --limit 1 --json databaseId,headSha`
   -> id на HEAD; `gh run watch <id> --exit-status`; `gh run view <id> --log | grep -E 'Image: |
   getSubject|Node.js 20 is deprecated|Successfully installed uv version'`.
8. **Smoke** (C, В-02.2): `gh run list --workflow smoke.yml --limit 1 --json databaseId,headSha`
   -> id на HEAD; `gh run watch <id> --exit-status`.
9. **Итог** по разделу 6 `13-harness.md`, строка P01 в таблице раздела 4 README папки, верх
   HANDOFF; коммит `docs:`; push (C, В-02.3). Id run шагов 7 и 8 в «Итог» отдельной строкой для P13.

## Готово, когда

- [x] `uv run --no-sync pytest tests/unit/test_workflows.py tests/unit/test_makefile.py
      tests/unit/test_pinning.py -q` -> `52 passed` (46 + 6 новых) или больше, без failed
- [x] `grep -rn 'ubuntu-latest\|11d5960\|d0cc045\|ff98106' .github/` -> пусто
- [x] мутации K1, K2, K3, K4, K5, K8, K9 -> `RED (caught)` каждая (шаг 5)
- [x] `grep -n 'no uv version is pinned' OPERATIONS.md` -> пусто; `grep -n 'ubuntu-24.04'
      OPERATIONS.md` -> строка раздела `## CI`
- [x] `make check` -> зелёный; вердикт `reviewer` «принять» или «принять с замечаниями»;
      `make verify` -> последняя строка `verify ok`
- [x] `gh run watch <ci id> --exit-status` -> exit 0; `gh run view <ci id> --json jobs --jq
      '[.jobs[].conclusion] | unique'` -> `["success"]`, job 12
- [x] лог ci-run: только `Image: ubuntu-24.04`, `uv version 0.12.17`, нет `getSubject` и
      `Node.js 20 is deprecated`; в `lint-and-test` строка pytest без `errors`
- [x] `gh run watch <smoke id> --exit-status` -> exit 0, `headSha` равен HEAD коммита кода
- [x] «Итог» заполнен, id обоих run в нём (или отказ В-02 вместо трёх строк выше)

## Не входит

- IN-08 (шаги lint в CI на `make lint`): не делаем, README папки, раздел 6.
- IN-02 (Spark-тесты на хосте с Java новее 17): P06. README и evidence (числа, run): P13.
- ID карточек в комментариях `ci.yml` и OPERATIONS (`QA-01`, `W5-T03`): P10, P11.
- `required-version` в `pyproject.toml`, `pre-commit autoupdate --freeze`, branch protection,
  обновление прочих actions, закрепление патч-версии Java.

## Риски и откат

- uv 0.12.17: зелёные run 13.11 шли на 0.13.8 (фолбэк на последнюю), 0.12.17 в CI не доказана.
  Выбор: та же версия, что пишет `uv.lock` и гоняет `make check` локально. Если шаг 7 красный
  на `uv sync --locked`: стоп, вопрос владельцу, вариант `version: "0.13.8"` (доказана зелёным
  run 43400391213) с тем же тестом.
- checkout v5.1.0: «BREAKING» касается только `pull_request_target` (в репозитории его нет).
  setup-uv v7: удалён вход `server-url` (не используется), uv качается с `releases.astral.sh`;
  для версии без известной контрольной суммы проверка пропускается (как и сейчас).
- `persist-credentials: false`: gitleaks читает историю локально (`fetch-depth: 0`) и API через
  `GITHUB_TOKEN` из `env`; smoke git-учётка не нужна. Красный gitleaks из-за учётки: стоп.
- `ubuntu-24.04` когда-нибудь снимут с раннеров: тест раннера покажет место правки.
- Откат: `git revert <коммит кода>`, push по «ок»; CI вернётся к красному на 26.04.

## Расхождения с отчётом аудита

- IN-01: «сначала все четыре теста красные» неверно: у job сейчас нет `permissions`, тест прав
  зелёный и ловит мутацию K2. Красных до правки 3.
- IN-01: node20 кроме checkout и setup-uv ещё у gitleaks v2.3.9 (`action.yml`: `using:
  "node20"`; предупреждение job `lint-and-test` run 43400391213 называет все три).
- IN-01: «uv локально 0.12.17» верно, но зелёные run ставили 0.13.8 и 0.13.7, а не 0.12.17.
- QA-01 (3): «множество файлов ... равно `SPARK_TESTS`» невыполнимо: `test_envelope.py` в наборе
  без маркеров и импорта pyspark; правило подмножества по импорту pyspark.
- QA-01: мутации K2 и K5 в `work/QA/mutations3.json.txt` ссылаются на старый текст
  (`ubuntu-latest`, SHA v2.3.9), после шага 3 дадут `SETUP-ERROR`: исправить по шагу 5.
- DC-13 и IN-01 п. 7 (README:156, README:213, evidence:177-181) по README папки делает P13.

## Итог

Исполнен 17.11.2026 (UTC), коммит кода `a21020a`. Решения владельца в начале сессии (вопрос с
вариантами, 20:3x UTC): В-01 «да», В-02 «да, все три», рутина (два цикла verify и два коммита)
«да». Кто писал: тесты и workflows `implementer` (два брифа), OPERATIONS и правки второго круга
ревью оркестратор (Markdown и одна строка комментария), ревью `reviewer` (Opus) в три прохода.

**Id run для P13:** ci `44175270540` (push, `a21020a`, success, 12 job); smoke `44176185272`
(`workflow_dispatch`, `a21020a`, попытка 1 failure от HTTP 429 Maven Central, попытка 2 success).

| Критерий («Готово, когда») | Проверка, вывод (17.11 UTC, HEAD `a21020a`) |
|---|---|
| карточный набор `52 passed` или больше | `uv run --no-sync pytest tests/unit/test_workflows.py tests/unit/test_makefile.py tests/unit/test_pinning.py -q` -> до правки `46 passed`; после тестов и до workflows `3 failed, 49 passed` (раннер, uv, checkout); после `52 passed` |
| grep старых пинов пуст | `grep -rn 'ubuntu-latest\|11d5960\|d0cc045\|ff98106' .github/` -> пусто, exit 1 |
| мутации K1-K5, K8, K9 красные | раннер `work/QA/mutate.py.txt` на копии дерева после правок, набор по шагу 5 плюс X1 (`continue-on-error` у pytest), X2 (`if: false` у gitleaks) -> все 9 `RED (caught)`, каждая своим тестом; контроль без мутаций `55 passed, 59 skipped` |
| OPERATIONS | `grep -n 'no uv version is pinned' OPERATIONS.md` -> пусто; `grep -n 'ubuntu-24.04' OPERATIONS.md` -> абзац после таблицы job раздела `## CI` |
| `make check`, ревью, `make verify` | `make check` -> `1933 passed, 146 skipped` (трижды, последний 20:59Z); `reviewer`: «принять с замечаниями» (1 средняя, 4 низких), круг 1 «принять с замечаниями» (1 средняя, 1 низкая), круг 2 «принять» (дерево `23ee905`); полный цикл verify (пауза трёх DAG, running пусто, stop scheduler) -> `verify ok`, 7 из 7: rows, keys, sums, values ok, отметка `full` 21:02:03Z |
| CI 12 из 12 | `gh run watch 44175270540 --exit-status` -> exit 0; `gh run view 44175270540 --json jobs --jq '[.jobs[].conclusion] \| unique'` -> `["success"]`, `.jobs \| length` -> 12 |
| лог CI | `gh run view 44175270540 --log`: `Image: ubuntu-24.04` 12 раз и других нет; `Successfully installed uv version 0.12.17`; `getSubject` 0; `Node.js 20 is deprecated` 0; pytest `lint-and-test` `1982 passed, 97 skipped, 71 warnings`, errors нет |
| smoke | `gh workflow run smoke.yml --ref main` -> run 44176185272, `headSha` `a21020a`; попытка 1 (21:05Z) failure на шаге bootstrap: `curl: (22) The requested URL returned error: 429` на первом jar Maven Central при сборке образа Spark (`streaming/Dockerfile:12`), причина вне пакета; `gh run rerun 44176185272 --failed` по отдельному «ок» -> `gh run watch 44176185272 --exit-status` exit 0, попытка 2 success 21:21:17Z; в логе `Image: ubuntu-24.04`, `Successfully installed uv version 0.12.17`, `verify ok` (оба bootstrap), `replay state exists, load skipped` |

Изменение: `a21020a`, 5 файлов: `.github/workflows/ci.yml` (6 job на `ubuntu-24.04`; checkout
v5.1.0 `fbc6f39` с `persist-credentials: false`; setup-uv v7.6.0 `37802ad` с `version: "0.12.17"`;
gitleaks-action v3.0.0 `e0c47f4`; шаг setup-java владельца как был), `.github/workflows/smoke.yml`
(то же для одного job), `tests/unit/test_workflows.py` (тест владельца как был и 5 новых),
`tests/unit/test_makefile.py` (1 новый), `OPERATIONS.md` (строка `lint-and-test` владельца, абзац
после таблицы job, строка «Not covered»). SHA тегов и runtime node24 сверены `gh api` 17.11.

Замечания ревью: №1 (средняя, шаг с `if:` или `continue-on-error` тест считал на месте) исправлено
и закреплено мутациями X1, X2; №2 (`bash -n`, yamllint, compose config по префиксу) сравниваются
точной строкой; №3 (комментарий Spark-набора) переписан; №4 и круг 1 №1 (абзац OPERATIONS: причина
Java 25 только у `lint-and-test`, образ под меткой GitHub обновляет без коммита, uv хоста ничем не
связан с CI) переписан; круг 1 №2 (комментарий «above») исправлен; №5 частично, см. ниже.

Не проверено и не покрыто:
- возврат action на node20 тесты не ловят (мутация ревьюера X7, gitleaks обратно на v2.3.9,
  зелёная); держит только grep «Готово» и предупреждение в логе run;
- `test_envelope.py`, убранный из `SPARK_TESTS`, тест не ловит (мутация X5): карточка требует
  подмножество по импорту pyspark, а не равенство;
- контрольной суммы uv 0.12.17 нет в `known-checksums.ts` setup-uv v7.6.0 (ревьюер, grep 0
  совпадений): загрузка не сверяется с суммой, как было и до пакета.

Замечено вне пакета (одной строкой каждое):
- плановый smoke 43851911392 (16.11, `a8c1d49`) прошёл зелёным уже на `ubuntu-26.04` с uv 0.13.8:
  Java 25 ломает только SparkSession-тесты `lint-and-test`;
- `make report` пишет у `check` «stale» после правки только Markdown, хотя гейт такую отметку
  принимает (коммит `a21020a` прошёл): строка отчёта строже гейта (P02);
- jar Maven Central в `streaming/Dockerfile:12-27` качаются `curl -fsSL` без повтора: один ответ
  429 роняет холодную сборку (smoke 44176185272, попытка 1); в реестре такой находки нет;
- хук pre-commit `trailing-whitespace` при коммите `docs:` убрал пробел в пустых строках контекста
  `work/HG/slim-proto.diff.txt`, `step1-main.diff.txt`, `tests-inprocess-proto.diff.txt`; `git
  apply --check` до и после одинаков (первый и третий не применяются на HEAD в обоих вариантах,
  второй применяется); патчи P03 всё равно собирает заново.

Риски: `ubuntu-24.04` снимут с раннеров, тест раннера покажет место правки; uv на хосте обновят,
а `version` в двух workflows нет (абзац OPERATIONS это называет). Откат: `git revert a21020a`.
