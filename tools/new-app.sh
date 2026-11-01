#!/usr/bin/env bash
# Scaffold a new app from templates/app (needs `uv`; copier runs via uvx).
#
#   tools/new-app.sh invoicing
#   tools/new-app.sh order-items "Splits orders into items" order-items-team
set -euo pipefail
if [ "$#" -lt 1 ] || [ "$#" -gt 3 ]; then
  echo "usage: tools/new-app.sh <app_name> [description] [owner_team]" >&2
  exit 2
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NAME="$1"
cd "$ROOT"

if [ -e "apps/$NAME" ]; then
  echo "apps/$NAME already exists" >&2
  exit 1
fi

data=(--data "app_name=$NAME")
[ -n "${2:-}" ] && data+=(--data "description=$2")
[ -n "${3:-}" ] && data+=(--data "owner_team=$3")

uvx copier copy --trust --defaults templates/app "apps/$NAME" "${data[@]}"

cat <<MSG

Created apps/$NAME. Next:
  1. Add an ownership line to CODEOWNERS:  /apps/$NAME/ @org/<team>
  2. tools/dev-pytest.sh apps/$NAME/tests
  3. pants tailor :: && pants lint check test apps/$NAME::
  4. tools/deploy.py --stage dev-\$USER --apps $NAME --with-deps
MSG
