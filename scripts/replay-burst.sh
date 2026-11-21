#!/usr/bin/env bash
# make replay-burst SECONDS=<n> [SPEED=720]: play <n> real seconds of the replay schedule on the
# host, then stop. The virtual clock before and after shows what the burst spent of the replay
# budget (ADR-016).
set -euo pipefail
seconds=${1:-}
speed=${2:-720}
if ! [[ $seconds =~ ^[1-9][0-9]*$ && $speed =~ ^[1-9][0-9]*$ ]]; then
  echo "usage: make replay-burst SECONDS=<n> [SPEED=720], both positive integers" >&2
  exit 2
fi
. "$(dirname "$0")/chaos/lib.sh"

no_other_replayer
before=$(virtual_now)
echo "virtual_now before: $before"
CHAOS_REPLAY_SPEED=$speed replay_burst "$seconds"
after=$(virtual_now)
echo "virtual_now after:  $after"
