#!/usr/bin/env bash
# Start Floci for a CI job that deploys to it (the PR stage).
#
# Why not a GitHub Actions service container: Floci must sit on a user-defined
# Docker network that the containers it spawns also join:
#   - its ECR backing registry is reached by container name, which Docker's
#     default bridge network can't resolve (symptom: ECR returns 503);
#   - Lambda/ECS containers reach Floci itself as http://floci:4566
#     (FLOCI_HOSTNAME), so pass --runtime-endpoint http://floci:4566 to deploy.py.
# Path-style ECR URIs (localhost:4566/<account>/<region>/<repo>) avoid Docker
# treating *.localhost registries as HTTPS, so no daemon reconfiguration.
#
#   tools/ci-start-floci.sh [region]
set -euo pipefail
REGION="${1:-eu-west-2}"
NETWORK=floci-net

docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK"

docker run -d --name floci \
  --network "$NETWORK" \
  -p 4566:4566 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e FLOCI_STORAGE_MODE=memory \
  -e FLOCI_DEFAULT_REGION="$REGION" \
  -e FLOCI_HOSTNAME=floci \
  -e FLOCI_SERVICES_DOCKER_NETWORK="$NETWORK" \
  -e FLOCI_SERVICES_ECR_URI_STYLE=path \
  floci/floci:latest

"$(dirname "$0")/wait-for-floci.sh" http://localhost:4566
