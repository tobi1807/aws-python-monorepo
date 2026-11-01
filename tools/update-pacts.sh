#!/usr/bin/env bash
# Regenerate the committed pact files (pacts/*.json) from the consumer contract tests.
#
#   tools/update-pacts.sh
#   PYTHON=/path/to/python tools/update-pacts.sh
#
# Consumers own their expectations: when a consumer test changes, run this and
# commit the pact diff. The provider's verification test depends on the pact
# file, so CI re-verifies exactly the affected providers. Review the diff:
# pact changes need the provider team's approval (see CODEOWNERS).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Prefer the Pants export venv (pants export --resolve=python-default): it has
# the exact pinned dependencies. Fall back to whatever python3 is on PATH.
if [ -z "${PYTHON:-}" ]; then
  for candidate in "$ROOT"/dist/export/python/virtualenvs/python-default/*/bin/python; do
    if [ -x "$candidate" ]; then
      PYTHON="$candidate"
      break
    fi
  done
  PYTHON="${PYTHON:-python3}"
fi
export PYTHON

shopt -s nullglob
consumer_tests=("$ROOT"/apps/*/tests/*_tests/contract/test_*_consumer.py)
if [ "${#consumer_tests[@]}" -eq 0 ]; then
  echo "No consumer contract tests found (apps/*/tests/*_tests/contract/test_*_consumer.py)."
  exit 0
fi

echo "Updating pacts with ${PYTHON} from ${#consumer_tests[@]} consumer test file(s)"
PACT_UPDATE=1 REPO_ROOT="$ROOT" "$ROOT/tools/dev-pytest.sh" "${consumer_tests[@]}"
echo "Done. Review and commit: git diff pacts/"
