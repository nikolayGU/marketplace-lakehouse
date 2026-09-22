#!/usr/bin/env bash
# Usage: run-job.sh <job>, where <job> is a module in spark_jobs/.
# Driver memory is a spark-submit flag because in local mode the driver JVM is the whole job.
set -euo pipefail

job="${1:?usage: run-job.sh <job>}"

exec /opt/spark/bin/spark-submit \
  --master "${SPARK_MASTER:-local[2]}" \
  --driver-memory "${SPARK_DRIVER_MEMORY:-1500m}" \
  "/opt/app/spark_jobs/${job}.py"
