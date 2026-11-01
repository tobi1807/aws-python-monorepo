"""Cached boto3 clients.

Endpoint selection is left to botocore: when ``AWS_ENDPOINT_URL`` is set (as it
is on every Lambda/ECS task deployed to Floci, and in local tests), every client
talks to that endpoint. Application code never branches on "Floci vs AWS".
"""

from __future__ import annotations

from functools import cache
from typing import Any

import boto3


@cache
def client(service: str) -> Any:
    return boto3.client(service)  # type: ignore[call-overload]


def reset_clients() -> None:
    """Drop cached clients (tests switch endpoints/mocks between cases)."""
    client.cache_clear()
