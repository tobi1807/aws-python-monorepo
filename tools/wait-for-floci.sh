#!/usr/bin/env bash
# Block until Floci answers HTTP (any status counts), or fail after ~90s.
#   tools/wait-for-floci.sh [endpoint]      default http://localhost:4566
#
# An explicit loop rather than `curl --retry`: while a container starts,
# Docker's port proxy accepts connections and then resets them, which curl
# doesn't treat as retryable.
set -uo pipefail
ENDPOINT="${1:-${AWS_ENDPOINT_URL:-http://localhost:4566}}"
for _ in $(seq 1 90); do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$ENDPOINT/_localstack/health")"
  if [ "$code" != "000" ]; then
    echo "Floci is up at $ENDPOINT (HTTP $code)"
    exit 0
  fi
  sleep 1
done
echo "Floci did not come up at $ENDPOINT" >&2
exit 1
