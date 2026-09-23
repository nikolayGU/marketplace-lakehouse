.DEFAULT_GOAL := help
COMPOSE := docker compose --env-file .env -f docker/compose.yaml
PROFILE ?= core
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
up: ## start profiles: make up PROFILE=core,query
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

# ---------------------------------------------------------------- operate
replay: ## register debezium connector and start the replayer
	bash connect/register.sh
	$(COMPOSE) exec oltp-replayer python -m replayer start

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

cdc-snapshot: ## incremental snapshot via signal table: make cdc-snapshot [TABLES="shop.orders shop.sellers"]
	bash connect/snapshot.sh $(TABLES)

connector-status: ## debezium connector state
	curl -s http://127.0.0.1:8083/connectors/shop-connector/status | python -m json.tool

iceberg-demo: ## snapshots, time travel, files before/after compaction
	bash scripts/iceberg/demo.sh

# ---------------------------------------------------------------- chaos (week 2+)
chaos-%: ## run a failure scenario: make chaos-spark-kill
	bash scripts/chaos/$*.sh

# ---------------------------------------------------------------- quality
lint: ## ruff, mypy, yamllint, sqlfluff, compose config
	uv run ruff check . && uv run ruff format --check .
	uv run mypy
	uv run yamllint -c .yamllint docker observability airflow .github
	@paths=$$(ls -d dbt/models oltp/migrations 2>/dev/null || true); \
	  [ -n "$$paths" ] && uv run sqlfluff lint $$paths || echo "no SQL directories yet"
	$(COMPOSE) --profile '*' config -q

test: ## unit tests (Spark ones skip on a host without Java)
	uv run pytest tests/unit -q

SPARK_TESTS := test_bronze_cdc_ingest.py test_contracts.py test_envelope.py

test-spark: ## the Spark unit tests, inside lakehouse/spark:dev because the host has no JVM
	docker run --rm --user root --entrypoint bash -v "$(CURDIR)":/repo:ro \
	  -e PYTHONPATH=/opt/spark/python:/opt/spark/python/lib/py4j-0.10.9.7-src.zip:/repo/streaming \
	  lakehouse/spark:dev -c 'pip install -q pytest jsonschema && cd /repo/tests/unit && \
	  python3 -m pytest -q -p no:cacheprovider --rootdir=/tmp $(SPARK_TESTS)'

dbt-parse: ## dbt parse without a warehouse
	cd dbt && uv run dbt parse --profiles-dir . --target ci

.PHONY: help secrets hooks data migrate replay-load replay-start replay-reset up down status logs nuke replay replay-status psql trino kafka-topics kafka-groups cdc-snapshot connector-status iceberg-demo lint test test-spark dbt-parse
