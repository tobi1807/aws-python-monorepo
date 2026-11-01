#!/usr/bin/env python3
"""Deploy apps: the one command developers and CI use.

    python3 tools/deploy.py --stage dev-ada --apps orders
    python3 tools/deploy.py --stage pr-42 --affected-since origin/main --with-deps \\
        --endpoint http://localhost:4566
    python3 tools/deploy.py --stage prod --affected-since $BEFORE_SHA \\
        --endpoint "$FLOCI_PROD_ENDPOINT"
    python3 tools/deploy.py --stage dev-ada --all --dry-run

Pipeline: resolve apps -> deploy waves (tools/deploy_plan.py) -> ONE
``pants package`` for everything -> stage Docker build contexts ->
``cdklocal bootstrap`` once -> per wave, in parallel per app:
synth -> hash gate (skip unchanged, see tools/artifact_hash.py) -> deploy -> record.
A failed app stops later waves.

Stage-only dependencies: ``boto3`` for tools/artifact_hash.py (the interpreter
running this script is used; override with DEPLOY_PYTHON).
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import affected
import deploy_plan

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_FLOCI_ENDPOINT = "http://localhost:4566"
# artifact_hash.py should-deploy exit code for "unchanged" (not imported: it needs boto3).
EXIT_SKIP = 10
REGION = "eu-west-2"
ACCOUNT = "000000000000"
STAGE_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,30}$")
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})

_print_lock = threading.Lock()


def log(message: str) -> None:
    with _print_lock:
        print(message, flush=True)


# --------------------------------------------------------------------------- planning


@dataclass(frozen=True)
class Plan:
    stage: str
    target: str  # "floci" | "aws"
    endpoint: str | None  # Floci endpoint as seen from this machine
    runtime_endpoint: str | None  # Floci endpoint as seen from Lambda containers
    requested: tuple[str, ...]
    waves: tuple[tuple[str, ...], ...]
    hotswap: bool = False
    force: bool = False
    dry_run: bool = False
    synth_only: bool = False
    parallel: int = 4
    root: Path = ROOT

    @property
    def apps(self) -> list[str]:
        return [app for wave in self.waves for app in wave]


@dataclass
class Result:
    app: str
    wave: int
    status: str  # deployed | skipped | failed | planned | not-run
    seconds: float = 0.0
    detail: str = ""


def package_name(app: str) -> str:
    """Python package directory for an app (kebab-case app names use underscores)."""
    return app.replace("-", "_")


def runtime_endpoint_for(endpoint: str, override: str | None = None) -> str:
    """How Lambda/ECS containers reach a Floci that this machine reaches at ``endpoint``."""
    if override:
        return override
    parts = urlsplit(endpoint)
    if parts.hostname in LOCAL_HOSTS:
        port = f":{parts.port}" if parts.port else ""
        return f"{parts.scheme}://host.docker.internal{port}"
    return endpoint


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and deploy apps to Floci (or AWS).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--stage", required=True, help="e.g. dev-ada, pr-42, prod")
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--apps", help="comma-separated app names")
    which.add_argument("--affected-since", metavar="REF", help="apps affected since this git ref")
    which.add_argument("--all", action="store_true", help="every app")
    parser.add_argument("--with-deps", action="store_true", help="also deploy depends_on closure")
    parser.add_argument(
        "--force", action="store_true", help="deploy even if the template is unchanged"
    )
    parser.add_argument("--hotswap", action="store_true", help="cdk --hotswap (dev stages only)")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and commands only")
    parser.add_argument(
        "--synth-only",
        action="store_true",
        help="build and synthesize, but don't bootstrap or deploy (fast infra validation)",
    )
    parser.add_argument("--target", choices=["floci", "aws"], default="floci")
    parser.add_argument(
        "--endpoint", help="Floci endpoint (default: $AWS_ENDPOINT_URL or localhost)"
    )
    parser.add_argument(
        "--runtime-endpoint",
        help="Floci endpoint as seen from Lambda containers (default: derived from --endpoint)",
    )
    parser.add_argument("--parallel", type=int, default=4, help="apps deployed at once per wave")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if not STAGE_PATTERN.match(args.stage):
        parser.error(f"invalid --stage {args.stage!r}: use lowercase letters, digits and '-'")
    if args.parallel < 1:
        parser.error("--parallel must be >= 1")
    if args.target == "aws" and (args.endpoint or args.runtime_endpoint):
        parser.error("--endpoint only applies to --target floci")
    if args.hotswap and args.stage == "prod":
        parser.error("--hotswap is for development stages; it is not allowed for prod")
    return args


def resolve_apps(args: argparse.Namespace) -> list[str]:
    if args.apps:
        return [a.strip() for a in args.apps.split(",") if a.strip()]
    if args.all:
        return affected.all_apps(args.root)
    return affected.affected_apps(args.affected_since, args.root)


def make_plan(args: argparse.Namespace) -> Plan:
    """Resolve the app set into deploy waves. Raises ``deploy_plan.PlanError``."""
    requested = resolve_apps(args)
    manifests = deploy_plan.load_manifests(args.root)
    wave_list = (
        deploy_plan.waves(manifests, requested, with_deps=args.with_deps) if requested else []
    )

    endpoint = runtime_endpoint = None
    if args.target == "floci":
        endpoint = args.endpoint or os.environ.get("AWS_ENDPOINT_URL") or DEFAULT_FLOCI_ENDPOINT
        runtime_endpoint = runtime_endpoint_for(endpoint, args.runtime_endpoint)

    return Plan(
        stage=args.stage,
        target=args.target,
        endpoint=endpoint,
        runtime_endpoint=runtime_endpoint,
        requested=tuple(requested),
        waves=tuple(tuple(w) for w in wave_list),
        hotswap=args.hotswap,
        force=args.force,
        dry_run=args.dry_run,
        synth_only=args.synth_only,
        parallel=args.parallel,
        root=args.root,
    )


# --------------------------------------------------------------------------- commands


def cdk_bin(plan: Plan) -> str:
    return "cdklocal" if plan.target == "floci" else "cdk"


def package_cmd(apps: list[str]) -> list[str]:
    # docker_image targets are excluded: CDK builds images from the staged
    # dist/docker/<app>/ context so the image hash lands in the template.
    return [
        "pants",
        "--filter-target-type=-docker_image",
        "package",
        *[f"apps/{app}::" for app in apps],
    ]


def bootstrap_cmd(plan: Plan) -> list[str] | None:
    """Floci starts empty, so bootstrap it. Real AWS accounts are bootstrapped out of band."""
    if plan.target != "floci":
        return None
    account = os.environ.get("CDK_DEFAULT_ACCOUNT", ACCOUNT)
    return ["npx", "cdklocal", "bootstrap", f"aws://{account}/{REGION}"]


def cdk_out(app: str) -> str:
    return f"cdk.out/{app}"


def synth_cmd(plan: Plan, app: str) -> list[str]:
    cmd = [
        "npx",
        "cdk",
        "synth",
        "--app",
        f"python3 dist/apps.{app}.infra/cdk_app.pex",
        "-c",
        f"stage={plan.stage}",
        "-c",
        f"target={plan.target}",
    ]
    if plan.runtime_endpoint:
        cmd += ["-c", f"runtime_endpoint_url={plan.runtime_endpoint}"]
    return [*cmd, "--quiet", "-o", cdk_out(app)]


def hash_python() -> str:
    return os.environ.get("DEPLOY_PYTHON", sys.executable)


def gate_cmd(plan: Plan, app: str) -> list[str]:
    return [
        hash_python(),
        "tools/artifact_hash.py",
        "should-deploy",
        "--app",
        app,
        "--stage",
        plan.stage,
        "--cdk-out",
        cdk_out(app),
    ]


def deploy_cmd(plan: Plan, app: str) -> list[str]:
    cmd = ["npx", cdk_bin(plan), "deploy", "--app", cdk_out(app), "--require-approval", "never"]
    if plan.hotswap:
        cmd.append("--hotswap")
    return cmd


def record_cmd(plan: Plan, app: str) -> list[str]:
    return [
        hash_python(),
        "tools/artifact_hash.py",
        "record",
        "--app",
        app,
        "--stage",
        plan.stage,
        "--cdk-out",
        cdk_out(app),
    ]


def deploy_env(plan: Plan) -> dict[str, str]:
    env = dict(os.environ)
    if plan.target == "floci" and plan.endpoint:
        env.update(
            AWS_ENDPOINT_URL=plan.endpoint,
            # cdklocal refuses to run without an explicit S3 endpoint (it uses
            # path-style S3 against it for asset publishing).
            AWS_ENDPOINT_URL_S3=plan.endpoint,
            AWS_ACCESS_KEY_ID="test",
            AWS_SECRET_ACCESS_KEY="test",
            AWS_DEFAULT_REGION=REGION,
            CDK_DEFAULT_REGION=REGION,
        )
    return env


# --------------------------------------------------------------------------- subprocesses


def run_cmd(
    cmd: list[str], *, env: dict[str, str] | None = None, cwd: Path = ROOT, stream: bool = False
) -> subprocess.CompletedProcess[str]:
    """The only place that spawns processes (monkeypatched in tests)."""
    if stream:
        return subprocess.run(cmd, cwd=cwd, env=env, text=True, check=False)
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def step(
    plan: Plan,
    label: str,
    cmd: list[str],
    *,
    env: dict[str, str] | None = None,
    stream: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run (or, in a dry run, just print) one command."""
    if plan.dry_run:
        log(f"  [{label}] $ {shlex.join(cmd)}")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    log(f"[{label}] $ {shlex.join(cmd)}")
    return run_cmd(cmd, env=env, cwd=plan.root, stream=stream)


def docker_context_files(app: str, root: Path) -> tuple[Path, list[Path]] | None:
    """(Dockerfile, built pex files) for an app that ships a container, else None."""
    dockerfile = root / "apps" / app / "src" / package_name(app) / "Dockerfile"
    if not dockerfile.is_file():
        return None
    pex_dir = root / "dist" / f"apps.{app}.src.{package_name(app)}"
    return dockerfile, sorted(Path(p) for p in glob.glob(str(pex_dir / "*.pex")))


def stage_docker_contexts(plan: Plan) -> list[str]:
    """Copy Dockerfile + built pexes to ``dist/docker/<app>/`` for CDK's image assets."""
    staged = []
    for app in plan.apps:
        found = docker_context_files(app, plan.root)
        if found is None:
            continue
        dockerfile, pexes = found
        target = plan.root / "dist" / "docker" / app
        if plan.dry_run:
            names = ", ".join(["Dockerfile", *(p.name for p in pexes)]) or "Dockerfile"
            log(f"  [{app}] stage docker context -> dist/docker/{app}/ ({names})")
        else:
            shutil.rmtree(target, ignore_errors=True)
            target.mkdir(parents=True)
            for source in (dockerfile, *pexes):
                shutil.copy2(source, target / source.name)
            log(f"[{app}] staged docker context in dist/docker/{app}/")
        staged.append(app)
    return staged


# --------------------------------------------------------------------------- execution


def fail(result_args: tuple[str, int], started: float, detail: str, output: str = "") -> Result:
    app, wave = result_args
    if output:
        log(f"[{app}] output:\n{output.rstrip()}")
    log(f"[{app}] FAILED: {detail}")
    return Result(app, wave, "failed", time.monotonic() - started, detail)


def deploy_app(plan: Plan, app: str, wave: int, abort: threading.Event) -> Result:
    """synth -> gate -> deploy -> record for one app. Sets ``abort`` on failure."""
    started = time.monotonic()
    who = (app, wave)
    if abort.is_set():
        return Result(app, wave, "not-run", 0.0, "an earlier app in this wave failed")
    env = deploy_env(plan)

    def elapsed() -> float:
        return time.monotonic() - started

    try:
        synth = step(plan, app, synth_cmd(plan, app), env=env)
        if synth.returncode != 0:
            abort.set()
            return fail(who, started, "cdk synth failed", synth.stdout)
        if plan.synth_only:
            return Result(app, wave, "synthesized", elapsed(), str(cdk_out(app)))

        if not plan.force:
            gate = step(plan, app, gate_cmd(plan, app), env=env)
            if gate.returncode == EXIT_SKIP:
                log(f"[{app}] unchanged since last deploy; skipping")
                return Result(app, wave, "skipped", elapsed(), "template unchanged")
            if gate.returncode != 0:
                abort.set()
                return fail(who, started, "hash gate failed", gate.stdout)

        deploy = step(plan, app, deploy_cmd(plan, app), env=env)
        if deploy.returncode != 0:
            abort.set()
            return fail(who, started, "cdk deploy failed", deploy.stdout)

        recorded = step(plan, app, record_cmd(plan, app), env=env)
        detail = "" if recorded.returncode == 0 else "deployed, but hash was not recorded"
        if detail:
            log(f"[{app}] WARNING: {detail}\n{recorded.stdout.rstrip()}")
        return Result(app, wave, "planned" if plan.dry_run else "deployed", elapsed(), detail)
    except Exception as exc:
        abort.set()
        return fail(who, started, f"{type(exc).__name__}: {exc}")


def run_wave(plan: Plan, number: int, apps: tuple[str, ...]) -> list[Result]:
    abort = threading.Event()
    workers = 1 if plan.dry_run else max(1, min(plan.parallel, len(apps)))
    log(f"== wave {number}: {', '.join(apps)}")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(deploy_app, plan, app, number, abort) for app in apps]
        return [future.result() for future in futures]


def build(plan: Plan) -> bool:
    """One pants invocation for every app that will be deployed, then Docker contexts."""
    cmd = package_cmd(plan.apps)
    result = step(plan, "build", cmd, env=dict(os.environ), stream=True)
    if result.returncode != 0:
        log("pants package failed")
        return False
    stage_docker_contexts(plan)
    return True


def bootstrap(plan: Plan) -> bool:
    cmd = bootstrap_cmd(plan)
    if cmd is None:
        return True
    result = step(plan, "bootstrap", cmd, env=deploy_env(plan))
    if result.returncode != 0:
        log(f"cdklocal bootstrap failed:\n{result.stdout.rstrip()}")
        return False
    return True


def execute(plan: Plan) -> list[Result]:
    results: list[Result] = []
    not_run = "build or bootstrap failed"

    def mark_remaining(start_wave: int, why: str) -> None:
        for number, wave in enumerate(plan.waves[start_wave - 1 :], start=start_wave):
            results.extend(Result(app, number, "not-run", 0.0, why) for app in wave)

    if not build(plan) or (not plan.synth_only and not bootstrap(plan)):
        mark_remaining(1, not_run)
        return results

    for number, wave in enumerate(plan.waves, start=1):
        wave_results = run_wave(plan, number, wave)
        results.extend(wave_results)
        if any(r.status == "failed" for r in wave_results):
            mark_remaining(number + 1, f"wave {number} failed")
            break
    return results


# --------------------------------------------------------------------------- output


def describe_plan(plan: Plan) -> str:
    where = plan.endpoint or "AWS"
    mode = " (dry run)" if plan.dry_run else ""
    lines = [f"Deploy plan{mode}: stage={plan.stage} target={plan.target} endpoint={where}"]
    for number, wave in enumerate(plan.waves, start=1):
        names = ", ".join(a if a in plan.requested else f"{a} (dependency)" for a in wave)
        lines.append(f"  wave {number}: {names}")
    flags = [
        f
        for f, on in (
            ("force", plan.force),
            ("hotswap", plan.hotswap),
            ("synth-only", plan.synth_only),
        )
        if on
    ]
    lines.append(f"  parallel={plan.parallel}" + (f" {' '.join(flags)}" if flags else ""))
    return "\n".join(lines)


def summary_table(results: list[Result]) -> str:
    rows = [("app", "wave", "result", "seconds", "detail")]
    rows += [(r.app, str(r.wave), r.status, f"{r.seconds:.1f}", r.detail) for r in results]
    widths = [max(len(row[i]) for row in rows) for i in range(5)]
    lines = [
        "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip() for row in rows
    ]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        plan = make_plan(args)
    except deploy_plan.PlanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not plan.apps:
        log("No apps to deploy.")
        return 0
    log(describe_plan(plan))

    started = time.monotonic()
    results = execute(plan)
    log("")
    log(summary_table(results))
    log(f"total {time.monotonic() - started:.1f}s")
    return 1 if any(r.status in ("failed", "not-run") for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
