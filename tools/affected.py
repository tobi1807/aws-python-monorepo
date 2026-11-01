#!/usr/bin/env python3
"""Which apps does a change touch?

Pants knows the dependency graph (libs -> apps -> tests), so the heavy lifting
is ``pants --changed-since=<ref> --changed-dependents=transitive list``. This
module turns those addresses into app names and adds the two things Pants
cannot see:

* files that invalidate everything (``pants.toml``, lockfiles, workflows, ...):
  every app is affected;
* ``apps/<app>/deploy.toml``: not owned by any Pants target, but changing it
  changes the deploy order, so the app is affected.

Usage::

    python3 tools/affected.py --since origin/main [--format json|lines]
    python3 tools/affected.py --since origin/main --check-global   # "true" / "false"

JSON output (GitHub Actions matrix friendly): ``{"apps": ["orders"], "count": 1}``.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ``apps/orders/src/orders/api.py``, ``apps/orders/src/orders:api``,
# ``//apps/orders/infra:cdk_app``, ``apps/orders/tests/x:tests#test_foo.py``.
_APP_ADDRESS = re.compile(r"^(?://)?apps/(?P<app>[^/:#@\s]+)(?:[/:#@]|$)")
_DEPLOY_TOML = re.compile(r"^apps/(?P<app>[^/]+)/deploy\.toml$")

# Files whose change invalidates everything Pants can't attribute to a target.
GLOBAL_CONFIG_EXACT = frozenset(
    {
        "pants.toml",
        "pants.ci.toml",
        "package.json",
        "package-lock.json",
        "ruff.toml",
        "pyproject.toml",
    }
)
GLOBAL_CONFIG_GLOBS = (
    ".github/workflows/*",
    # Lockfiles change resolved versions without touching requirements.txt.
    "3rdparty/*.lock",
)


def apps_from_addresses(addresses: Iterable[str]) -> list[str]:
    """Sorted unique app names from Pants addresses / file paths. Non-app addresses are ignored."""
    apps: set[str] = set()
    for raw in addresses:
        match = _APP_ADDRESS.match(raw.strip())
        if match:
            apps.add(match["app"])
    return sorted(apps)


def apps_from_changed_files(changed_files: Iterable[str]) -> list[str]:
    """Apps whose ``deploy.toml`` changed (invisible to Pants)."""
    apps: set[str] = set()
    for path in changed_files:
        match = _DEPLOY_TOML.match(path.strip())
        if match:
            apps.add(match["app"])
    return sorted(apps)


def touches_global_config(changed_files: Iterable[str]) -> bool:
    for path in changed_files:
        path = path.strip().removeprefix("./")
        if path in GLOBAL_CONFIG_EXACT:
            return True
        if any(fnmatch.fnmatchcase(path, glob) for glob in GLOBAL_CONFIG_GLOBS):
            return True
    return False


def all_apps(root: Path = ROOT) -> list[str]:
    """Every deployable app: a directory under ``apps/`` that has a ``deploy.toml``."""
    return sorted(p.parent.name for p in (root / "apps").glob("*/deploy.toml"))


def pants_changed_addresses(since: str, root: Path = ROOT) -> list[str]:
    result = subprocess.run(
        [
            "pants",
            f"--changed-since={since}",
            "--changed-dependents=transitive",
            "list",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        raise SystemExit(f"pants list failed with exit code {result.returncode}")
    return [line for line in result.stdout.splitlines() if line.strip()]


def git_changed_files(since: str, root: Path = ROOT) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{since}...HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(f"git diff failed with exit code {result.returncode}")
    return [line for line in result.stdout.splitlines() if line.strip()]


def affected_apps(since: str, root: Path = ROOT) -> list[str]:
    """Deployable apps affected by the changes between ``since`` and HEAD."""
    deployable = all_apps(root)
    changed_files = git_changed_files(since, root)
    if touches_global_config(changed_files):
        return deployable
    touched = set(apps_from_addresses(pants_changed_addresses(since, root)))
    touched.update(apps_from_changed_files(changed_files))
    # A deleted app, or one without a deploy.toml yet, isn't deployable.
    return sorted(touched & set(deployable))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--since", required=True, help="git ref to compare against")
    parser.add_argument("--format", choices=["json", "lines"], default="json")
    parser.add_argument(
        "--check-global",
        action="store_true",
        help='print "true" if a global config file changed (CI then runs everything), else "false"',
    )
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.check_global:
        changed = touches_global_config(git_changed_files(args.since, args.root))
        print("true" if changed else "false")
        return 0

    apps = affected_apps(args.since, args.root)
    if args.format == "json":
        print(json.dumps({"apps": apps, "count": len(apps)}))
    else:
        print("\n".join(apps))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
