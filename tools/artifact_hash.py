#!/usr/bin/env python3
"""Skip deploys whose output didn't change.

``template_hash`` fingerprints a synthesized cloud assembly. The last deployed
fingerprint of every (stage, app) lives in SSM Parameter Store at
``/deploy-hashes/{stage}/{app}``, in the very environment the app is deployed
to, so the record can't drift from reality the way a CI-side cache could.

Usage::

    artifact_hash.py should-deploy --app orders --stage prod [--cdk-out cdk.out/orders]
        prints "deploy" (exit 0) or "skip" (exit 10)
    artifact_hash.py record --app orders --stage prod [--cdk-out cdk.out/orders]

boto3 reads the endpoint from ``AWS_ENDPOINT_URL``, so the same command works
against Floci and real AWS.

Caveat: the hash says "this template was deployed once", not "the stack still
exists". If someone deletes a stack by hand, use ``tools/deploy.py --force``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import boto3

EXIT_SKIP = 10
DEFAULT_REGION = "eu-west-2"
PARAM_PREFIX = "/deploy-hashes"


class NoTemplatesError(FileNotFoundError):
    """The directory isn't a synthesized cloud assembly."""


def template_files(cdk_out_dir: Path | str) -> list[Path]:
    """All stack templates in the assembly: top level plus nested ``assembly-*`` dirs."""
    root = Path(cdk_out_dir)
    files = [*root.glob("*.template.json"), *root.glob("assembly-*/*.template.json")]
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def template_hash(cdk_out_dir: Path | str) -> str:
    """sha256 over every ``*.template.json`` of a synthesized cloud assembly.

    Templates alone are enough to decide "did anything change?":

    * Lambda code and Docker images are CDK *assets*. Their content hash is
      embedded in the template (the S3 key ``<hash>.zip`` / the image tag), so
      rebuilt-but-identical artifacts produce the same template and a real code
      change produces a different one.
    * Everything else that could change what CloudFormation does lives in the
      template body itself (including stage names and context-derived values).

    ``cdk.out/manifest.json``, ``tree.json`` and the asset directories are
    deliberately excluded: they contain absolute paths and tooling metadata
    that vary between machines without affecting the deployment.

    Each template is re-serialized with sorted keys and compact separators, so
    key order and whitespace never change the hash; file name is part of the
    input, so renaming a stack does.
    """
    files = template_files(cdk_out_dir)
    if not files:
        raise NoTemplatesError(f"no *.template.json found in {cdk_out_dir}")
    root = Path(cdk_out_dir)
    digest = hashlib.sha256()
    for path in files:
        document = json.loads(path.read_text())
        canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(canonical.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def param_name(stage: str, app: str) -> str:
    return f"{PARAM_PREFIX}/{stage}/{app}"


def ssm_client() -> Any:
    region = os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION") or DEFAULT_REGION
    return boto3.client("ssm", region_name=region)


def fetch_hash(stage: str, app: str, client: Any | None = None) -> str | None:
    """Last deployed hash, or None if this (stage, app) was never recorded."""
    ssm = client if client is not None else ssm_client()
    try:
        return ssm.get_parameter(Name=param_name(stage, app))["Parameter"]["Value"]
    except ssm.exceptions.ParameterNotFound:
        return None


def store_hash(stage: str, app: str, value: str, client: Any | None = None) -> None:
    ssm = client if client is not None else ssm_client()
    ssm.put_parameter(Name=param_name(stage, app), Value=value, Type="String", Overwrite=True)


def should_deploy(app: str, stage: str, cdk_out_dir: Path | str, client: Any | None = None) -> bool:
    return template_hash(cdk_out_dir) != fetch_hash(stage, app, client)


def record(app: str, stage: str, cdk_out_dir: Path | str, client: Any | None = None) -> str:
    value = template_hash(cdk_out_dir)
    store_hash(stage, app, value, client)
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("should-deploy", "record"):
        p = sub.add_parser(name)
        p.add_argument("--app", required=True)
        p.add_argument("--stage", required=True)
        p.add_argument("--cdk-out", help="default: cdk.out/<app>")
    args = parser.parse_args(argv)
    cdk_out = Path(args.cdk_out or f"cdk.out/{args.app}")

    if args.command == "should-deploy":
        try:
            needed = should_deploy(args.app, args.stage, cdk_out)
        except NoTemplatesError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:
            # Fail open: if we can't read the record, deploying is always safe.
            print(f"warning: could not read deploy hash ({exc}); deploying", file=sys.stderr)
            needed = True
        print("deploy" if needed else "skip")
        return 0 if needed else EXIT_SKIP

    try:
        value = record(args.app, args.stage, cdk_out)
    except NoTemplatesError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"recorded {param_name(args.stage, args.app)} = {value[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
