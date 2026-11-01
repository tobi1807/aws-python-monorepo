"""Test fixtures helpers shared by every app."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from runtime import aws

TEST_REGION = "eu-west-2"


def fake_credentials(monkeypatch: pytest.MonkeyPatch, stage: str = "test") -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", TEST_REGION)
    monkeypatch.setenv("STAGE", stage)
    monkeypatch.delenv("FLAGS_APPLICATION", raising=False)


# Reset caches only for runtime modules the code under test actually loaded.
# Deliberately NOT imported here: Pants infers dependencies from imports, so
# importing them would make every app's tests depend on every runtime module
# (and a change to runtime/flags.py would mark every app as affected).
_CACHE_RESETTERS = {
    "runtime.config": "clear_cache",
    "runtime.secrets": "clear_cache",
    "runtime.flags": "reset",
}


def reset_runtime_caches() -> None:
    aws.reset_clients()
    for module_name, resetter in _CACHE_RESETTERS.items():
        module = sys.modules.get(module_name)
        if module is not None:
            getattr(module, resetter)()


@contextmanager
def floci_endpoint(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Point every boto3 client at Floci for the duration of a test.

    Skips the test when FLOCI_ENDPOINT isn't set (e.g. a plain `pants test ::`).
    """
    endpoint = os.environ.get("FLOCI_ENDPOINT")
    if not endpoint:
        pytest.skip("FLOCI_ENDPOINT not set (start Floci: docker compose up -d floci)")
    monkeypatch.setenv("AWS_ENDPOINT_URL", endpoint)
    reset_runtime_caches()
    try:
        yield endpoint
    finally:
        reset_runtime_caches()


def floci_required() -> pytest.MarkDecorator:
    return pytest.mark.skipif(not os.environ.get("FLOCI_ENDPOINT"), reason="FLOCI_ENDPOINT not set")
