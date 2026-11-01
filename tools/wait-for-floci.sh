#!/usr/bin/env bash
# Block until Floci answers HTTP (any response counts), or fail after ~60s.
#   tools/wait-for-floci.sh [endpoint]      default http://localhost:4566
set -euo pipefail
ENDPOINT="${1:-${AWS_ENDPOINT_URL:-http://localhost:4566}}"
if curl -s -o /dev/null --retry 60 --retry-delay 1 --retry-connrefused --max-time 5 "$ENDPOINT/_localstack/health"; then
  echo "Floci is up at $ENDPOINT"
else
  echo "Floci did not come up at $ENDPOINT" >&2
  exit 1
fi
