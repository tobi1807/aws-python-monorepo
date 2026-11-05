#!/usr/bin/env bash
# One entry point for running Floci (the AWS emulator) locally.
#
#   tools/floci.sh up [--prod]      start Floci (waits until healthy); --prod = persistent "prod" on :4567
#   tools/floci.sh down [--prod]    stop and remove it
#   tools/floci.sh reset            wipe state: restart the in-memory dev Floci
#   tools/floci.sh status           what's running, and is it answering?
#   tools/floci.sh logs [-f]        Floci logs
#   tools/floci.sh env              print exports; use:  eval "$(tools/floci.sh env)"
#   tools/floci.sh deploy [args]    deploy to local Floci (default: --stage dev-$USER --all); args go to tools/deploy.py
#   tools/floci.sh test [args]      Floci integration tests (default: all `floci`-tagged tests); args go to pants
#   tools/floci.sh doctor           check prerequisites (docker, compose, node deps, pants)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

cmd="${1:-help}"; shift || true
SERVICE=floci; PORT=4566; COMPOSE=(docker compose)
if [ "${1:-}" = "--prod" ]; then SERVICE=floci-prod; PORT=4567; COMPOSE=(docker compose --profile prod); shift; fi
ENDPOINT="http://localhost:$PORT"

need_docker() {
  command -v docker >/dev/null || { echo "docker not found: install Docker Desktop / Docker Engine first." >&2; exit 1; }
  docker info >/dev/null 2>&1 || { echo "Docker daemon isn't running: start Docker and retry." >&2; exit 1; }
}

case "$cmd" in
  up)
    need_docker
    "${COMPOSE[@]}" up -d "$SERVICE"
    tools/wait-for-floci.sh "$ENDPOINT"
    echo "Floci ($SERVICE) is ready at $ENDPOINT"
    [ "$SERVICE" = floci ] && flag="" || flag=" --prod"
    echo "Point your shell at it with:  eval \"\$(tools/floci.sh env$flag)\""
    ;;
  down)
    need_docker
    "${COMPOSE[@]}" rm -sf "$SERVICE"
    ;;
  reset)
    need_docker
    docker compose rm -sf floci
    exec "$0" up
    ;;
  status)
    need_docker
    docker compose --profile prod ps floci floci-prod
    for p in 4566 4567; do
      code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "http://localhost:$p/_localstack/health" || true)"
      [ "$code" != "000" ] && echo ":$p answering (HTTP $code)" || echo ":$p not answering"
    done
    ;;
  logs)
    need_docker
    exec "${COMPOSE[@]}" logs --tail 200 "$@" "$SERVICE"
    ;;
  env)
    cat <<ENVVARS
export AWS_ENDPOINT_URL=$ENDPOINT
export FLOCI_ENDPOINT=$ENDPOINT
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=eu-west-2
export STAGE=\${STAGE:-dev-${USER:-me}}
ENVVARS
    ;;
  deploy)
    need_docker
    [ -d node_modules ] || npm ci
    python3 -c 'import boto3' 2>/dev/null || python3 -m pip install --quiet "boto3>=1.40,<2"
    [ "$#" -gt 0 ] || set -- --stage "dev-${USER:-me}" --all
    exec python3 tools/deploy.py "$@" --endpoint "$ENDPOINT" --runtime-endpoint "http://$SERVICE:4566"
    ;;
  test)
    eval "$("$0" env)"
    tools/wait-for-floci.sh "$ENDPOINT" >/dev/null || { echo "Floci isn't running: tools/floci.sh up" >&2; exit 1; }
    [ "$#" -gt 0 ] || set -- ::
    exec pants --tag=floci --tag=-e2e test "$@"
    ;;
  doctor)
    ok=1
    for t in docker node npm python3 pants; do
      if command -v "$t" >/dev/null; then echo "ok   $t"; else echo "MISSING $t"; ok=0; fi
    done
    docker info >/dev/null 2>&1 && echo "ok   docker daemon" || { echo "MISSING running docker daemon"; ok=0; }
    [ -d node_modules ] && echo "ok   node_modules" || echo "note: run npm ci (done automatically by 'deploy')"
    [ "$ok" = 1 ] || exit 1
    ;;
  help|*)
    sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
    ;;
esac
