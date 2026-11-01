"""Secrets Manager access with a short in-process cache."""

from __future__ import annotations

import json
import time
from typing import Any

from runtime.aws import client

_CACHE_TTL_SECONDS = 300
_cache: dict[str, tuple[float, str]] = {}


def get_secret(secret_id: str) -> str:
    now = time.monotonic()
    cached = _cache.get(secret_id)
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]
    value = client("secretsmanager").get_secret_value(SecretId=secret_id)["SecretString"]
    _cache[secret_id] = (now, value)
    return value


def get_secret_json(secret_id: str) -> dict[str, Any]:
    return json.loads(get_secret(secret_id))


def clear_cache() -> None:
    _cache.clear()
