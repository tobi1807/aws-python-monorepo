"""Test fixtures helpers shared by every app."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from runtime import aws, config, flags, secrets

TEST_REGION = "eu-west-2"


def fake_credentials(monkeypatch: pytest.MonkeyPatch, stage: str = "test") -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", TEST_REGION)
    monkeypatch.setenv("STAGE", stage)
    monkeypatch.delenv("FLAGS_APPLICATION", raising=False)


def reset_runtime_caches() -> None:
    aws.reset_clients()
    config.clear_cache()
    secrets.clear_cache()
    flags.reset()


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
