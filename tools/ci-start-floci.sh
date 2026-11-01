#!/usr/bin/env bash
# Start Floci for a CI job that deploys container images (the PR stage).
#
# Floci's ECR registry (<account>.dkr.ecr.<region>.localhost:4566) speaks plain
# HTTP, and Docker only allows that for registries listed as insecure. Changing
# that list means restarting the Docker daemon, which would kill a GitHub
# Actions service container, so this script configures Docker first and then
# starts Floci itself.
#
#   tools/ci-start-floci.sh [account] [region]
set -euo pipefail
ACCOUNT="${1:-000000000000}"
REGION="${2:-eu-west-2}"
REGISTRY="${ACCOUNT}.dkr.ecr.${REGION}.localhost:4566"
DAEMON_JSON=/etc/docker/daemon.json

current='{}'
if [ -s "$DAEMON_JSON" ]; then current="$(sudo cat "$DAEMON_JSON")"; fi
jq --arg reg "$REGISTRY" '.["insecure-registries"] = ((.["insecure-registries"] // []) + [$reg] | unique)' \
  <<<"$current" | sudo tee "$DAEMON_JSON" >/dev/null
sudo systemctl restart docker
echo "Docker trusts $REGISTRY over HTTP"

docker run -d --name floci \
  -p 4566:4566 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e FLOCI_STORAGE_MODE=memory \
  -e FLOCI_DEFAULT_REGION="$REGION" \
  floci/floci:latest

"$(dirname "$0")/wait-for-floci.sh" http://localhost:4566
