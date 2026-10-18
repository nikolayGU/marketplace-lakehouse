.DEFAULT_GOAL := help
COMPOSE := docker compose --env-file .env -f docker/compose.yaml
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
verify: ## bronze holds every Kafka record once and silver equals Postgres: prints verify ok
	@bash scripts/verify.sh

verify-fast: ## make verify without the silver merge: reads only, writes nothing to the lake
	@bash scripts/verify.sh --no-merge

reconcile: ## Postgres against live silver rows: count, set of primary keys, decimal sums
	@bash -c '. scripts/chaos/lib.sh && reconcile'

report: ## facts for a session report: git, verify stamp, containers, replay clock; reads only
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

silver: ## merge everything bronze committed since the last run into silver, then exit
	$(COMPOSE) --profile core run --rm --no-deps spark-silver

cdc-snapshot: ## incremental snapshot via signal table: make cdc-snapshot [TABLES="shop.orders shop.sellers"]
	bash connect/snapshot.sh $(TABLES)

connector-status: ## debezium connector state
	curl -s http://127.0.0.1:8083/connectors/shop-connector/status | python3 -m json.tool

iceberg-demo: ## snapshots, time travel, rollback, compaction, expiration on lake.demo.orders
	$(COMPOSE) --profile core run --rm --no-deps spark-silver iceberg_demo

lakekeeper-bootstrap: ## bootstrap Lakekeeper and create its warehouse (safe to re-run)
	$(COMPOSE) --profile core run --rm lakekeeper-bootstrap

# ---------------------------------------------------------------- chaos (week 2+)
chaos-%: ## run a failure scenario: make chaos-spark-kill
	bash scripts/chaos/$*.sh

# ---------------------------------------------------------------- quality
lint: ## ruff, mypy, yamllint, sqlfluff, compose config
	uv run ruff check . && uv run ruff format --check .
	uv run mypy
	uv run yamllint -c .yamllint docker observability airflow .github
	uv run sqlfluff lint oltp/migrations
	cd dbt && uv run sqlfluff lint models macros tests
	$(COMPOSE) --profile '*' config -q

test: ## unit tests (Spark ones skip on a host without Java)
	uv run pytest tests/unit -q

SPARK_TESTS := test_bronze_cdc_ingest.py test_contracts.py test_envelope.py test_iceberg_demo.py \
  test_iceberg_sink.py test_silver_upsert.py

test-spark: ## the Spark unit tests, inside lakehouse/spark:dev because the host has no JVM
	docker run --rm --user root --entrypoint bash -v "$(CURDIR)":/repo:ro \
	  -e PYTHONPATH=/opt/spark/python:/opt/spark/python/lib/py4j-0.10.9.7-src.zip:/repo/streaming \
	  lakehouse/spark:dev -c 'pip install -q pytest jsonschema && cd /repo/tests/unit && \
	  python3 -m pytest -q -p no:cacheprovider --rootdir=/tmp $(SPARK_TESTS)'

dbt-parse: ## dbt parse without a warehouse
	cd dbt && uv run dbt parse --profiles-dir . --target ci

dbt-build: ## seed, run and test lake.gold through Trino on 127.0.0.1:8080 (needs make start)
	cd dbt && uv run dbt build --profiles-dir . --target dev

dbt-docs: ## dbt docs generate into dbt/target (needs Trino)
	cd dbt && uv run dbt docs generate --profiles-dir . --target dev

.PHONY: help secrets hooks data migrate replay-load replay-start replay-reset start up down status logs nuke bootstrap verify verify-fast reconcile report replay-burst replay-live replay-status silver psql trino kafka-topics kafka-groups cdc-snapshot connector-status iceberg-demo lakekeeper-bootstrap lint test test-spark dbt-parse dbt-build dbt-docs
