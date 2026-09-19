#!/bin/sh
set -eu
mc alias set lake "$S3_ENDPOINT" "$S3_ACCESS_KEY" "$S3_SECRET_KEY"
mc mb --ignore-existing "lake/$S3_BUCKET"
mc mb --ignore-existing "lake/$S3_BUCKET/warehouse"
mc mb --ignore-existing "lake/$S3_BUCKET/checkpoints"
