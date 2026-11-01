"""Locate artifacts built by Pants.

Pants writes ``python_aws_lambda_function`` zips to
``dist/<spec.path.with.dots>/<target-name>.zip``. CDK only *references* them;
it never builds Python. CDK hashes the asset, so an unchanged zip means no
Lambda update.

Set ``CDK_STUB_ASSETS=1`` to synthesize without built artifacts (infra unit
tests, quick ``cdk synth`` while editing stacks).
"""

from __future__ import annotations

import os
from pathlib import Path

from aws_cdk import aws_lambda as lambda_

# Pants generates a top-level shim that re-exports the configured handler.
PANTS_LAMBDA_HANDLER = "lambda_function.handler"


def repo_root() -> Path:
    if root := os.environ.get("REPO_ROOT"):
        return Path(root)
    here = Path.cwd()
    for candidate in (here, *here.parents):
        if (candidate / "pants.toml").exists():
            return candidate
    raise RuntimeError("Can't find repo root (no pants.toml above cwd); set REPO_ROOT")


def stubbed() -> bool:
    return os.environ.get("CDK_STUB_ASSETS") == "1"


def lambda_zip_path(target_dir: str, target_name: str) -> Path:
    """``target_dir`` is the BUILD file's directory, e.g. ``apps/orders/src/orders``."""
    return repo_root() / "dist" / target_dir.strip("/").replace("/", ".") / f"{target_name}.zip"


def lambda_code(target_dir: str, target_name: str) -> lambda_.Code:
    if stubbed():
        return lambda_.Code.from_inline("def handler(event, context):\n    return None\n")
    path = lambda_zip_path(target_dir, target_name)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Build it first: pants package {target_dir}:{target_name}"
        )
    return lambda_.Code.from_asset(str(path))


def lambda_handler() -> str:
    return "index.handler" if stubbed() else PANTS_LAMBDA_HANDLER


def container_context(build_dir: str) -> Path:
    """Docker build context for a container image staged by tools/deploy.py."""
    return repo_root() / build_dir
