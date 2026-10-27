#!/usr/bin/env bash
# What the built MinIO and mc images (ADR-026) must do, run against the images and not the source:
# the release and the commit they print, the commit Go recorded while building (the clone, not the
# ARG the ldflags were given), the tools the runtime has, MinIO starting and answering the compose
# healthcheck, the Version and commit the server reports, and `create-bucket.sh` (the minio-init of
# compose) running twice. The server is one throwaway container with a random password and no
# published port, so a live stack is not touched. CI runs it on every push (ci.yml, job
# minio-images); by hand:
#   bash scripts/check-minio-images.sh lakehouse/minio:<tag> lakehouse/mc:<tag>
set -euo pipefail
if [ "$#" -ne 2 ]; then
  echo "usage: check-minio-images.sh <minio image> <mc image>" >&2
  exit 2
fi
minio_image=$1
mc_image=$2
root="$(cd "$(dirname "$0")/.." && pwd)"
dockerfile="$root/docker/minio/Dockerfile"
arg() { sed -n "s/^ARG $1=//p" "$dockerfile"; }
# RELEASE.2025-09-07T16-13-09Z -> 2025-09-07T16:13:09Z, what the server calls its version.
rfc3339() { printf '%s' "${1#RELEASE.}" | sed -E 's/T([0-9]{2})-([0-9]{2})-([0-9]{2})Z/T\1:\2:\3Z/'; }

name="minio-check-$$"
user="check$(od -An -N6 -tx1 /dev/urandom | tr -d ' \n')"
password="$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
# No --rm on the server: when MinIO dies, `docker logs` below still has something to read.
cleanup() { docker rm -f -v "$name" >/dev/null 2>&1 || true; }
trap cleanup EXIT

expect() { # <what> <expected> <actual>
  if [ "$2" != "$3" ]; then
    printf 'FAIL %s\n  expected: %s\n  got:      %s\n' "$1" "$2" "$3" >&2
    exit 1
  fi
  echo "ok   $1: $3"
}
# The Go build info of the binary, one line per fact, in a throwaway container of the image.
built_from() { # <image> <binary> <commit>
  expect "$2 build info of $1" "vcs.modified=false vcs.revision=$3" \
    "$(docker run --rm --entrypoint sh "$1" -c "grep -a -o -e 'vcs.revision=[0-9a-f]*' -e 'vcs.modified=[a-z]*' $2" \
      | sort -u | tr '\n' ' ' | sed 's/ $//')"
}

minio_tag="$(arg MINIO_TAG)"
minio_commit="$(arg MINIO_COMMIT)"
mc_tag="$(arg MC_TAG)"
mc_commit="$(arg MC_COMMIT)"

expect "minio --version" \
  "minio version $minio_tag (commit-id=$minio_commit)" \
  "$(docker run --rm "$minio_image" --version | head -n 1)"
expect "mc --version" \
  "mc version $mc_tag (commit-id=$mc_commit)" \
  "$(docker run --rm "$mc_image" --version | head -n 1)"
built_from "$minio_image" /usr/bin/minio "$minio_commit"
built_from "$mc_image" /usr/bin/mc "$mc_commit"

for image in "$minio_image" "$mc_image"; do
  for tool in sh wget; do
    docker run --rm --entrypoint sh "$image" -c "command -v $tool" >/dev/null \
      || { echo "FAIL $image has no $tool" >&2; exit 1; }
  done
  echo "ok   $image has sh and wget"
done

# `server /data` is the command of compose; the memory limit is the one of compose too.
docker run -d --name "$name" --memory 512m \
  -e MINIO_ROOT_USER="$user" -e MINIO_ROOT_PASSWORD="$password" \
  "$minio_image" server /data >/dev/null
healthy=
for _ in $(seq 1 30); do
  if docker exec "$name" sh -c 'wget -q --spider http://localhost:9000/minio/health/live' 2>/dev/null; then
    healthy=1
    break
  fi
  sleep 1
done
[ -n "$healthy" ] || { docker logs "$name" >&2; echo "FAIL minio did not turn healthy in 30 s" >&2; exit 1; }
echo "ok   minio answers the compose healthcheck"

# The same script, image entrypoint and variables as minio-init, twice: it must be re-runnable.
for run in 1 2; do
  docker run --rm --network "container:$name" --entrypoint /bin/sh \
    -v "$root/docker/minio:/init:ro" \
    -e S3_ENDPOINT=http://localhost:9000 -e S3_ACCESS_KEY="$user" -e S3_SECRET_KEY="$password" \
    -e S3_BUCKET=lakehouse \
    "$mc_image" /init/create-bucket.sh >/dev/null
  echo "ok   create-bucket.sh run $run"
done

mc_lake() { # <command with mc and the alias lake>
  docker run --rm --network "container:$name" --entrypoint /bin/sh \
    -e S3_ACCESS_KEY="$user" -e S3_SECRET_KEY="$password" "$mc_image" \
    -c "mc alias set lake http://localhost:9000 \"\$S3_ACCESS_KEY\" \"\$S3_SECRET_KEY\" >/dev/null && $1"
}
expect "bucket lakehouse" "lakehouse/" \
  "$(mc_lake 'mc ls --json lake' | sed -n 's/.*"key":"\([^"]*\)".*/\1/p')"
# `Version` shows only here (--version prints the release tag): a wrong -X flag would pass above.
expect "version and commit the server reports" \
  "\"commitID\":\"$minio_commit\" \"version\":\"$(rfc3339 "$minio_tag")\"" \
  "$(mc_lake 'mc admin info --json lake' | grep -o -e '"version":"[^"]*"' -e '"commitID":"[^"]*"' | sort -u | tr '\n' ' ' | sed 's/ $//')"
echo "minio images ok"
