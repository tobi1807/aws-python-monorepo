"""End-to-end checks against a *deployed* orders stage.

Invokes the deployed Lambda with an API Gateway HTTP API event rather than
calling the HTTP endpoint, so the test doesn't depend on how the emulator
formats API URLs. It still exercises the real deployed function, its IAM
role, the DynamoDB table and the shared bus.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from orders_tests.conftest import order_request_body
from runtime.aws import client

pytestmark = pytest.mark.skipif(
    not (os.environ.get("STAGE") and os.environ.get("AWS_ENDPOINT_URL")),
    reason="needs a deployed stage: set STAGE and AWS_ENDPOINT_URL",
)


def stage() -> str:
    return os.environ["STAGE"]


def invoke_api(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    event = {
        "version": "2.0",
        "routeKey": f"{method} {path}",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {"content-type": "application/json"},
        "requestContext": {
            "http": {"method": method, "path": path, "sourceIp": "127.0.0.1"},
            "stage": "$default",
        },
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
    }
    response = client("lambda").invoke(
        FunctionName=f"{stage()}-orders-api:live", Payload=json.dumps(event).encode()
    )
    payload = json.loads(response["Payload"].read())
    assert "FunctionError" not in response, payload
    return payload


def test_stage_published_its_config() -> None:
    ssm = client("ssm")
    table = ssm.get_parameter(Name=f"/{stage()}/orders/table-name")["Parameter"]["Value"]
    assert table == f"{stage()}-orders-orders"
    assert ssm.get_parameter(Name=f"/{stage()}/orders/api-url")["Parameter"]["Value"]


def test_place_and_fetch_order_through_deployed_lambda() -> None:
    placed = invoke_api("POST", "/orders", order_request_body())
    assert placed["statusCode"] == 201, placed
    order = json.loads(placed["body"])

    fetched = invoke_api("GET", f"/orders/{order['order_id']}")
    assert fetched["statusCode"] == 200, fetched
    assert json.loads(fetched["body"])["customer_email"] == "ada@example.com"
