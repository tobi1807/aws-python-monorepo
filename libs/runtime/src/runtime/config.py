"""Runtime configuration lookups.

Apps find each other's resources (bus names, table names, URLs) at *runtime*
via SSM, never via CloudFormation references baked in at deploy time. That's
what lets every app deploy independently and in parallel, with no global
deploy order.

Parameter layout: ``/{stage}/{app}/{key}``. If the stage-specific parameter is
missing we fall back to ``/baseline/{app}/{key}``, so a PR stage that only
deployed the changed apps can still find the unchanged ones.
"""

from __future__ import annotations

import os
import time

from runtime.aws import client

BASELINE_STAGE = "baseline"
_CACHE_TTL_SECONDS = 300
_cache: dict[str, tuple[float, str]] = {}


class ConfigNotFound(LookupError):
    pass


def current_stage() -> str:
    try:
        return os.environ["STAGE"]
    except KeyError as exc:
        raise RuntimeError("STAGE environment variable is not set") from exc


def param_path(stage: str, app: str, key: str) -> str:
    return f"/{stage}/{app}/{key}"


def get_config(app: str, key: str, *, stage: str | None = None) -> str:
    """Resolve ``key`` published by ``app``, with baseline fallback and caching."""
    stage = stage or current_stage()
    candidates = [param_path(stage, app, key)]
    if stage != BASELINE_STAGE:
        candidates.append(param_path(BASELINE_STAGE, app, key))

    now = time.monotonic()
    for path in candidates:
        cached = _cache.get(path)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]
        try:
            value = client("ssm").get_parameter(Name=path)["Parameter"]["Value"]
        except client("ssm").exceptions.ParameterNotFound:
            continue
        _cache[path] = (now, value)
        return value

    raise ConfigNotFound(f"None of {candidates} exist")


def clear_cache() -> None:
    _cache.clear()
