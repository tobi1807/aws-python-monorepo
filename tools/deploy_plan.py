#!/usr/bin/env python3
"""Deploy order from ``apps/<app>/deploy.toml`` manifests.

Each manifest lists deploy-time dependencies::

    depends_on = ["platform"]

``waves`` turns them into batches that can deploy in parallel: every app in
wave N only depends on apps in earlier waves. A PR stage runs on an empty
Floci, so it deploys the affected apps *plus* the closure of their
``depends_on`` (``with_deps=True``); prod already has everything, so it only
deploys the affected apps (``with_deps=False``) but still in dependency order.

Usage::

    python3 tools/deploy_plan.py --apps orders,catalog [--with-deps] [--json]
    python3 tools/deploy_plan.py --check      # CI: manifests match infra code
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from collections.abc import Iterable, Mapping
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

Manifests = Mapping[str, list[str]]

# import_param(self, ctx, "platform", "event-bus-name")  (any two positional args first)
_IMPORT_PARAM = re.compile(
    r"""\bimport_param\(\s*[^,()]+,\s*[^,()]+,\s*(?P<q>["'])(?P<from_app>[^"']+)(?P=q)"""
)


class PlanError(ValueError):
    """Invalid deploy manifests or selection."""


def load_manifests(root: Path = ROOT) -> dict[str, list[str]]:
    """``{app: depends_on}`` for every ``apps/*/deploy.toml``."""
    manifests: dict[str, list[str]] = {}
    for path in sorted((root / "apps").glob("*/deploy.toml")):
        app = path.parent.name
        try:
            data = tomllib.loads(path.read_text())
        except tomllib.TOMLDecodeError as exc:
            raise PlanError(f"{path.relative_to(root)}: invalid TOML: {exc}") from exc
        deps = data.get("depends_on", [])
        if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
            raise PlanError(f"{path.relative_to(root)}: depends_on must be a list of app names")
        manifests[app] = list(deps)
    return manifests


def _validate(manifests: Manifests, apps: Iterable[str]) -> None:
    for app in apps:
        if app not in manifests:
            known = ", ".join(sorted(manifests)) or "(none)"
            raise PlanError(f"unknown app {app!r} (no apps/{app}/deploy.toml). Known apps: {known}")


def _check_acyclic(manifests: Manifests, apps: Iterable[str]) -> None:
    """Raise PlanError naming the cycle, if any, among ``apps`` and everything they reach."""
    reachable = closure(manifests, apps)
    sorter = TopologicalSorter({app: manifests[app] for app in reachable})
    try:
        sorter.prepare()
    except CycleError as exc:
        cycle = " -> ".join(exc.args[1])
        raise PlanError(f"dependency cycle: {cycle}") from exc


def closure(manifests: Manifests, apps: Iterable[str]) -> set[str]:
    """``apps`` plus everything they transitively ``depends_on``."""
    apps = list(apps)
    _validate(manifests, apps)
    seen: set[str] = set()
    stack = list(apps)
    while stack:
        app = stack.pop()
        if app in seen:
            continue
        seen.add(app)
        for dep in manifests[app]:
            if dep not in manifests:
                raise PlanError(
                    f"app {app!r} depends on unknown app {dep!r} (no apps/{dep}/deploy.toml)"
                )
            stack.append(dep)
    return seen


def waves(manifests: Manifests, apps: Iterable[str], *, with_deps: bool) -> list[list[str]]:
    """Deploy waves for ``apps``; each wave is sorted and may deploy in parallel.

    With ``with_deps`` the dependency closure is added to the selection.
    Without, only ``apps`` deploy, but they are still ordered by their
    (transitive) dependencies on each other: order only constrains apps in the set.
    """
    apps = list(dict.fromkeys(apps))
    _validate(manifests, apps)
    _check_acyclic(manifests, apps)
    selected = closure(manifests, apps) if with_deps else set(apps)

    # Transitive dependencies restricted to the selection, so A -> B -> C with
    # B unselected still orders C before A.
    def selected_deps(app: str) -> set[str]:
        return (closure(manifests, [app]) - {app}) & selected

    sorter = TopologicalSorter({app: selected_deps(app) for app in selected})
    sorter.prepare()
    result: list[list[str]] = []
    while sorter.is_active():
        ready = sorted(sorter.get_ready())
        result.append(ready)
        sorter.done(*ready)
    return result


def check(root: Path = ROOT) -> list[str]:
    """Violations between manifests and infra code. Empty list means OK."""
    problems: list[str] = []
    apps_dir = root / "apps"
    try:
        manifests = load_manifests(root)
    except PlanError as exc:
        return [str(exc)]

    for app_dir in sorted(p for p in apps_dir.iterdir() if p.is_dir()):
        if (app_dir / "infra").is_dir() and app_dir.name not in manifests:
            problems.append(f"apps/{app_dir.name}: has infra/ but no deploy.toml")

    for app, deps in sorted(manifests.items()):
        manifest_rel = f"apps/{app}/deploy.toml"
        for dep in deps:
            if dep not in manifests:
                problems.append(f"{manifest_rel}: depends_on {dep!r} is not an app")
            elif dep == app:
                problems.append(f"{manifest_rel}: app depends on itself")

        for path in sorted((apps_dir / app / "infra").glob("**/*.py")):
            text = "\n".join(
                "" if line.lstrip().startswith("#") else line
                for line in path.read_text().splitlines()
            )
            for match in _IMPORT_PARAM.finditer(text):
                from_app = match["from_app"]
                if from_app == app or from_app in deps:
                    continue
                line_no = text.count("\n", 0, match.start()) + 1
                problems.append(
                    f"{path.relative_to(root)}:{line_no}: import_param from {from_app!r} "
                    f"but {from_app!r} is not in depends_on of {manifest_rel}"
                )

    if not problems:
        try:
            _check_acyclic(manifests, manifests)
        except PlanError as exc:
            problems.append(str(exc))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--apps", help="comma-separated app names")
    parser.add_argument("--with-deps", action="store_true", help="include depends_on closure")
    parser.add_argument("--json", action="store_true", help="print waves as JSON")
    parser.add_argument("--check", action="store_true", help="validate manifests vs infra code")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.check:
        problems = check(args.root)
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        if problems:
            return 1
        print(f"ok: {len(load_manifests(args.root))} deploy manifests consistent")
        return 0

    if not args.apps:
        parser.error("--apps is required (or use --check)")
    names = [a.strip() for a in args.apps.split(",") if a.strip()]
    try:
        plan = waves(load_manifests(args.root), names, with_deps=args.with_deps)
    except PlanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"waves": plan}))
    else:
        for number, wave in enumerate(plan, start=1):
            print(f"wave {number}: {', '.join(wave)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
