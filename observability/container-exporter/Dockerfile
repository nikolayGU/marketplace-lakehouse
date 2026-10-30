FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN pip install --no-cache-dir \
    "pydantic-settings==2.15.0" \
    "prometheus-client==0.26.0"

COPY container_exporter/ ./container_exporter/

# The docker socket's group comes from compose (group_add), the process itself is not root.
USER 65534
ENTRYPOINT ["python", "-m", "container_exporter"]
