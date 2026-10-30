# Airflow 3.3.2 on Python 3.12, the Python of the host and CI (ADR-011). The bare 3.3.2 tag is
# Python 3.13. The docker provider is part of the image's extras.
FROM apache/airflow:3.3.2-python3.12@sha256:9df9c8be4096b9cc626bd7cb1f2b8c712eef66c59c615f8c7e6200871ca10bd1

# Clients the DAG package imports. The versions are the ones the constraints of the base image
# carry (pip refuses a different one, so a new base image means new numbers here).
RUN pip install --no-cache-dir --constraint "${HOME}/constraints.txt" \
      "apache-airflow==3.3.2" "pydantic-settings==2.15.0" "trino==0.339.0" "psycopg[binary]==3.3.5"

# dbt in Airflow's environment would fight Airflow over shared dependencies: a venv of its own,
# pinned to the versions in uv.lock.
USER root
RUN python -m venv /opt/dbt-venv \
    && /opt/dbt-venv/bin/pip install --no-cache-dir \
         dbt-core==1.10.23 dbt-trino==1.10.4 dbt-adapters==1.24.5 dbt-common==1.39.0
USER airflow
