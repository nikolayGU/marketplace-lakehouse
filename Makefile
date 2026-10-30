.DEFAULT_GOAL := help
COMPOSE := docker compose --env-file .env -f docker/compose.yaml
DOCKER ?= docker
PROFILE ?= core
SPEED ?= 720
comma := ,
PROFILE_FLAGS = $(foreach p,$(subst $(comma), ,$(PROFILE)),--profile $(p))

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-24s %s\n", $$1, $$2}'

# ---------------------------------------------------------------- setup
secrets: ## create .env from .env.example with generated passwords (never overwrites)
	uv run python scripts/make_env.py

hooks: ## install pre-commit hooks into .git
	uv run pre-commit install

data: ## download Olist dataset into data/raw
	uv run python scripts/fetch_data.py

migrate: ## apply oltp/migrations to the source database
	PYTHONPATH=oltp uv run python -m replayer.migrations

replay-load: ## shift dates, load the initial share, build the replay schedule
	PYTHONPATH=oltp uv run python -m replayer load

replay-start: ## run the replayer locally against 127.0.0.1 (ctrl-c to stop)
	PYTHONPATH=oltp uv run python -m replayer start

replay-reset: ## DESTRUCTIVE: empty shop and drop replay staging (asks first)
	@read -p "This empties every shop table. Type 'yes' to continue: " a && [ "$$a" = "yes" ]
	PYTHONPATH=oltp uv run python -m replayer reset --yes

# ---------------------------------------------------------------- lifecycle
start: ## core without the replayer container, plus trino (ADR-016)
	$(COMPOSE) --profile core --profile query up -d --build spark-bronze kafka-connect trino

up: ## start profiles other than core: make up PROFILE=orchestrate (core goes through make start)
	@case ",$(PROFILE)," in *,core,*) \
	  echo "PROFILE=$(PROFILE) includes core, whose oltp-replayer plays at REPLAY_SPEED;" \
	    "use make start (ADR-016)" >&2; exit 2;; esac
	$(COMPOSE) $(PROFILE_FLAGS) up -d --build

down: ## stop profiles (volumes kept): make down PROFILE=bi
	$(COMPOSE) $(PROFILE_FLAGS) down

status: ## compose ps with health
	$(COMPOSE) --profile '*' ps

logs: ## follow logs: make logs S=spark-bronze
	$(COMPOSE) logs -f --tail=200 $(S)

nuke: ## destroy everything including volumes, checkpoints and data (asks first)
	@read -p "This deletes all volumes and checkpoints. Type 'yes' to continue: " a && [ "$$a" = "yes" ]
	$(COMPOSE) --profile '*' down -v --remove-orphans

bootstrap: ## fresh clone to verified data: start, migrate, connector, load, verify, protect
	@bash scripts/bootstrap.sh

# ---------------------------------------------------------------- operate
verify: ## bronze holds every Kafka record once, silver matches Postgres on rows, keys, decimal sums and column values: prints verify ok
	@bash scripts/verify.sh

verify-fast: ## make verify without the silver merge: reads only, writes nothing to the lake
	@bash scripts/verify.sh --no-merge

reconcile: ## Postgres against live silver rows: count, set of primary keys, decimal sums, row fingerprint of every column
	@bash -c '. scripts/chaos/lib.sh && reconcile'

report: ## facts for a session report: git, the verify, check and review stamps, containers, replay clock; reads only
	@bash scripts/report.sh

replay-burst: ## play SECONDS of history on the host, then stop: make replay-burst SECONDS=60 [SPEED=720]
	@bash scripts/replay-burst.sh "$(SECONDS)" "$(SPEED)"

replay-live: ## spends the replay budget: the oltp-replayer container plays at REPLAY_SPEED until stopped
	$(COMPOSE) --profile core up -d --build oltp-replayer

replay-status: ## replayer position and virtual clock
	PYTHONPATH=oltp uv run python -m replayer status

psql: ## psql into the source database
	$(COMPOSE) exec postgres-oltp psql -U $${OLTP_USER:-shop} -d $${OLTP_DB:-shop}

trino: ## trino cli, catalog lake
	$(COMPOSE) exec trino trino --catalog lake

kafka-topics: ## topics with partitions
	$(COMPOSE) exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --describe

kafka-groups: ## consumer groups and lag
	$(COMPOSE) exec kafka /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --all-groups --describe

silver: ## merge everything bronze committed since the last run into silver, then exit (refuses while the Airflow scheduler runs or a container of Airflow's merge exists)
	@ids=$$($(COMPOSE) --profile '*' ps -q airflow-scheduler) || { \
	  echo "docker compose ps failed: cannot tell whether airflow-scheduler runs, not merging" >&2; \
	  exit 2; \
	}; \
	if [ -n "$$ids" ]; then \
	  echo "airflow-scheduler is running and may merge silver at the same time: pause silver_upsert and stop the scheduler first, or trigger the DAG (OPERATIONS.md, Airflow)" >&2; \
	  exit 2; \
	fi
	@found=$$($(DOCKER) ps -a --filter 'name=^/lakehouse-silver-merge$$' --format '{{.Names}}: {{.Status}}') || { \
	  echo "docker ps failed: cannot tell whether a container of Airflow's merge exists, not merging" >&2; \
	  exit 2; \
	}; \
	if [ -n "$$found" ]; then \
	  echo "found $$found (the container silver_upsert's merge task starts, any status)" >&2; \
	  echo "Up: a live writer of the silver checkpoint, wait until it exits. Exited: a leftover of a killed merge, remove it with 'docker rm lakehouse-silver-merge' (needs the owner's ok), then run make silver again." >&2; \
	  exit 2; \
	fi
	$(COMPOSE) --profile core run --rm --no-deps spark-silver

cdc-snapshot: ## incremental snapshot via signal table: make cdc-snapshot [TABLES="shop.orders shop.sellers"]
	bash connect/snapshot.sh $(TABLES)

connector-status: ## debezium connector state
	curl -s http://127.0.0.1:8083/connectors/shop-connector/status | python3 -m json.tool

iceberg-demo: ## snapshots, time travel, rollback, compaction, expiration on lake.demo.orders
	$(COMPOSE) --profile core run --rm --no-deps spark-silver iceberg_demo

lakekeeper-bootstrap: ## bootstrap Lakekeeper and create its warehouse (safe to re-run)
	$(COMPOSE) --profile core run --rm lakekeeper-bootstrap

airflow-init: ## pools lake_writers and gold_writers, 1 slot each (safe to re-run)
	$(COMPOSE) exec airflow-scheduler airflow pools set lake_writers 1 \
	  "silver writers: the silver_upsert merge and iceberg_maintenance optimize (ADR-010)"
	$(COMPOSE) exec airflow-scheduler airflow pools set gold_writers 1 \
	  "gold writers: dbt_build and the gold maintenance (W5-D11)"

# ---------------------------------------------------------------- chaos (week 2+)
chaos-%: ## run a failure scenario: make chaos-spark-kill
	bash scripts/chaos/$*.sh

# ---------------------------------------------------------------- quality
lint: ## ruff, mypy, yamllint, sqlfluff, compose config, bash -n on the shell scripts
	uv run ruff check . && uv run ruff format --check .
	for script in $$(git ls-files '*.sh'); do bash -n "$$script" || exit 1; done
	uv run mypy
	uv run yamllint -c .yamllint docker observability airflow .github
	uv run sqlfluff lint oltp/migrations
	cd dbt && uv run sqlfluff lint models macros tests
	$(COMPOSE) --profile '*' config -q

alerts-test: ## promtool: check the alert rules and run observability/prometheus/alerts_test.yml
	docker run --rm -v "$(CURDIR)/observability/prometheus:/etc/prometheus:ro" --entrypoint promtool prom/prometheus:v3.14.0 check rules /etc/prometheus/alerts.yml
	docker run --rm -v "$(CURDIR)/observability/prometheus:/etc/prometheus:ro" --entrypoint promtool prom/prometheus:v3.14.0 test rules /etc/prometheus/alerts_test.yml

test: ## unit tests (Spark ones skip on a host without Java)
	uv run pytest tests/unit -q

check: ## make lint and make test, then stamps the tree they passed on for the commit gate (.check-stamp)
	@python3 scripts/agent_state.py check "$(CURDIR)"

SPARK_TESTS := test_bronze_cdc_ingest.py test_contracts.py test_envelope.py test_iceberg_demo.py \
  test_iceberg_sink.py test_silver_upsert.py test_orders_per_minute.py test_maintenance.py

SPARK_IMAGE ?= lakehouse/spark:dev
# Versions of the test tools inside the image; tests/unit/test_makefile.py compares them with uv.lock.
SPARK_TEST_PIP := pytest==9.1.1 jsonschema==4.26.0

test-spark: ## the Spark unit tests, inside $(SPARK_IMAGE) because the host has no JVM; any skip fails
	docker run --rm --user root --entrypoint bash -v "$(CURDIR)":/repo:ro \
	  -e FAIL_ON_SKIP=1 -e PYTHONPATH=/opt/spark/python:/opt/spark/python/lib/py4j-0.10.9.7-src.zip:/repo/streaming \
	  $(SPARK_IMAGE) -c 'pip install -q $(SPARK_TEST_PIP) && cd /repo/tests/unit && \
	  python3 -m pytest -q -p no:cacheprovider -p no:skipping --rootdir=/tmp $(SPARK_TESTS)'

AIRFLOW_IMAGE ?= lakehouse/airflow:dev

dags-check: ## every DAG file imports in $(AIRFLOW_IMAGE), offline, with docker/airflow/airflow.env; every DAG and task has a timeout that fits its retries, every Docker task removes its container with force
	docker run --rm --network none -v "$(CURDIR)/airflow/dags":/opt/airflow/dags:ro \
	  --env-file docker/airflow/airflow.env -e PYTHONPATH=/opt/airflow/dags \
	  -e AIRFLOW__METRICS__STATSD_ON=False --entrypoint python $(AIRFLOW_IMAGE) -c \
	  "from airflow.models.dagbag import DagBag; \
	  from airflow.providers.docker.operators.docker import DockerOperator; \
	  b = DagBag('/opt/airflow/dags'); \
	  assert not b.import_errors, b.import_errors; \
	  pairs = [(d, t) for d in b.dags.values() for t in d.tasks]; \
	  kw = lambda t: getattr(t, 'partial_kwargs', None) or vars(t); \
	  docker = [(d, t) for d, t in pairs if issubclass(getattr(t, 'operator_class', type(t)), DockerOperator)]; \
	  bad = [d.dag_id + ': no dagrun_timeout' for d in b.dags.values() if not d.dagrun_timeout]; \
	  bad += [d.dag_id + '.' + t.task_id + ': no execution_timeout' for d, t in pairs if not t.execution_timeout]; \
	  bad += [d.dag_id + '.' + t.task_id + ': execution_timeout above dagrun_timeout' for d, t in pairs if d.dagrun_timeout and t.execution_timeout and t.execution_timeout > d.dagrun_timeout]; \
	  bad += [d.dag_id + '.' + t.task_id + ': all attempts do not fit in dagrun_timeout' for d, t in pairs if d.dagrun_timeout and t.execution_timeout and (t.retries + 1) * t.execution_timeout + t.retries * t.retry_delay >= d.dagrun_timeout]; \
	  bad += [d.dag_id + '.' + t.task_id + ': auto_remove is not force' for d, t in docker if kw(t).get('auto_remove') != 'force']; \
	  bad += [d.dag_id + '.merge: no container_name' for d, t in pairs if (d.dag_id, t.task_id) == ('silver_upsert', 'merge') and not t.container_name]; \
	  assert not bad, bad; \
	  print(len(b.dags), 'dags import, timeouts, retry budget and force removal checked:', sorted(b.dags))"

watermark-demo: ## orders_per_minute on a lab topic: inside the watermark updates, behind it drops (needs make start)
	bash scripts/demo/watermark.sh

watermark-live: ## re-send a very late and the newest real order to the running orders_per_minute service
	bash scripts/demo/watermark.sh live

dbt-parse: ## dbt parse without a warehouse
	cd dbt && uv run dbt parse --profiles-dir . --target ci

dbt-build: ## seed, run and test lake.gold through Trino on 127.0.0.1:8080 (needs make start)
	cd dbt && uv run dbt build --profiles-dir . --target dev

dbt-docs: ## dbt docs generate into dbt/target (needs Trino)
	cd dbt && uv run dbt docs generate --profiles-dir . --target dev

.PHONY: alerts-test dags-check watermark-demo watermark-live help secrets hooks data migrate replay-load replay-start replay-reset start up down status logs nuke bootstrap verify verify-fast reconcile report replay-burst replay-live replay-status silver psql trino kafka-topics kafka-groups cdc-snapshot connector-status iceberg-demo lakekeeper-bootstrap airflow-init lint test check test-spark dbt-parse dbt-build dbt-docs
