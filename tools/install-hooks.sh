#!/usr/bin/env bash
# One-time setup per clone: use the versioned hooks in .githooks/.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath .githooks
chmod +x .githooks/*
echo "Git hooks enabled (core.hooksPath=.githooks). Remove with: git config --unset core.hooksPath"
