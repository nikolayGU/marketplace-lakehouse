#!/usr/bin/env bash
# Bootstrap Lakekeeper once and create the warehouse on MinIO. Safe to re-run: it checks state
# first and never changes an existing warehouse. Clients keep their own S3 keys: no STS, no
# remote signing (ADR-005). Runs as the compose one-shot `lakekeeper-bootstrap`
# (make lakekeeper-bootstrap); every value comes from the environment.
set -euo pipefail
: "${LAKEKEEPER_API:?}" "${LAKEKEEPER_WAREHOUSE:?}" "${S3_BUCKET:?}" "${S3_ENDPOINT:?}"
: "${S3_ACCESS_KEY:?}" "${S3_SECRET_KEY:?}"
api=$LAKEKEEPER_API

bootstrapped=$(curl -sS --fail-with-body --max-time 30 "$api/management/v1/info" |
  python3 -c 'import json, sys; print(json.load(sys.stdin)["bootstrapped"])')
case $bootstrapped in
  True) ;;
  False)
    curl -sS --fail-with-body --max-time 30 -X POST "$api/management/v1/bootstrap" \
      -H 'Content-Type: application/json' -d '{"accept-terms-of-use": true}'
    echo "bootstrapped"
    ;;
  *) echo "unexpected bootstrapped value: $bootstrapped" >&2; exit 1 ;;
esac

exists=$(curl -sS --fail-with-body --max-time 30 "$api/management/v1/warehouse" |
  python3 -c 'import json, os, sys
names = [w["name"] for w in json.load(sys.stdin)["warehouses"]]
print(os.environ["LAKEKEEPER_WAREHOUSE"] in names)')
if [ "$exists" = True ]; then
  echo "warehouse $LAKEKEEPER_WAREHOUSE exists"
  exit 0
fi

# The request goes through stdin so the S3 secret never shows up in a process list. curl prints
# the response: the warehouse id, or the error body on failure.
python3 - <<'EOF' | curl -sS --fail-with-body --max-time 30 -w '\n' \
  -X POST "$api/management/v1/warehouse" -H 'Content-Type: application/json' --data @-
import json
import os

print(json.dumps({
    "warehouse-name": os.environ["LAKEKEEPER_WAREHOUSE"],
    "storage-profile": {
        "type": "s3",
        # The bucket Spark writes to: registered tables keep their files where they are.
        "bucket": os.environ["S3_BUCKET"],
        # Existing tables live under s3a://<bucket>/warehouse/; registration checks the sub-path.
        "key-prefix": "warehouse",
        # In-network address: Lakekeeper reads metadata files itself (register, validation).
        "endpoint": os.environ["S3_ENDPOINT"],
        # Required by Lakekeeper; us-east-1 is the MinIO default.
        "region": "us-east-1",
        # No MINIO_DOMAIN here, so MinIO serves buckets only as a path, not as a subdomain.
        "path-style-access": True,
        # MinIO, not AWS: the AWS-only STS rules (role ARN, partition) do not apply.
        "flavor": "s3-compat",
        # No vended credentials: Spark and Trino keep their own S3 keys.
        "sts-enabled": False,
        # No remote signing either: clients sign S3 requests with those keys themselves.
        "remote-signing-enabled": False,
        # Spark wrote every existing table under s3a://; registering them needs this.
        "allow-alternative-protocols": True,
        # true would turn expire_snapshots and remove_orphan_files into no-ops on S3FileIO.
        "push-s3-delete-disabled": False,
        # warehouse/<ns>/<table>-<uuid>/: readable in MinIO, the uuid avoids soft-deleted paths.
        "storage-layout": {
            "type": "full-hierarchy", "namespace": "{name}", "tabular": "{name}-{uuid}",
        },
    },
    "storage-credential": {
        "type": "s3",
        "credential-type": "access-key",
        "access-key-id": os.environ["S3_ACCESS_KEY"],
        "secret-access-key": os.environ["S3_SECRET_KEY"],
    },
    # A dropped table keeps its files for 7 days and can be undropped. Not after Spark
    # DROP ... PURGE: Spark deletes the files itself at once, and undrop brings back no data.
    "delete-profile": {"type": "soft", "expiration-seconds": 604800},
}))
EOF
echo "warehouse $LAKEKEEPER_WAREHOUSE created"
