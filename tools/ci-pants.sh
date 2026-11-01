#!/usr/bin/env bash
# Run pants for "what this change affects", or for everything when a file Pants
# can't see (pants.toml, lockfiles, workflows, ...) changed.
#
#   tools/ci-pants.sh origin/main --tag=-floci lint check test
#
# Global flags such as --tag must come before the goals; flags after a goal
# are scoped to that goal and Pants rejects them.
set -euo pipefail
BASE="$1"; shift
cd "$(dirname "$0")/.."

if [ "$(python3 tools/affected.py --since "$BASE" --check-global)" = "true" ]; then
  echo "Global config changed: running against the whole repo"
  exec pants "$@" ::
fi
exec pants --changed-since="$BASE" --changed-dependents=transitive "$@"
