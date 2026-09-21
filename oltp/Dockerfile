FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# psycopg[binary] and pydantic ship wheels, so no build toolchain is needed in the image.
RUN pip install --no-cache-dir \
    "psycopg[binary]==3.3.6" \
    "pydantic-settings==2.15.0" \
    "prometheus-client==0.26.0"

COPY replayer/ ./replayer/
COPY migrations/ ./migrations/

# Matches the local layout: `replayer` is a top-level package and /app is the working root.
ENTRYPOINT ["python", "-m", "replayer"]
CMD ["start"]
