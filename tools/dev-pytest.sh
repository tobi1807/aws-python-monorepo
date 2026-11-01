#!/usr/bin/env bash
# Fast path for running pytest outside Pants (e.g. in an IDE or a quick loop).
# Pants remains the source of truth in CI: `pants test ::`.
#   tools/dev-pytest.sh apps/orders/tests
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY_PATH=""
for d in "$ROOT"/apps/*/src "$ROOT"/apps/*/infra "$ROOT"/apps/*/tests "$ROOT"/libs/*/src "$ROOT"/libs/*/tests "$ROOT"/tools; do
  [ -d "$d" ] && PY_PATH="$PY_PATH:$d"
done
export PYTHONPATH="${PY_PATH#:}"
export PACT_DO_NOT_TRACK=true
cd "$ROOT"
exec "${PYTHON:-python3}" -m pytest -q "$@"
