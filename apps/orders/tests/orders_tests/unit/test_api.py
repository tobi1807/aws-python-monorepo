from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from orders import api, repository
from orders_tests.conftest import order_request_body


class FakeContext:
    function_name = "orders-api"
    memory_limit_in_mb = 512
    invoked_function_arn = "arn:aws:lambda:eu-west-2:000000000000:function:orders-api"
    aws_request_id = "req-1"


def http_event(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
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


def invoke(event: dict[str, Any]) -> tuple[int, Any]:
    response = api.handler(event, FakeContext())  # type: ignore[arg-type]
    return response["statusCode"], json.loads(response["body"]) if response["body"] else None


@pytest.mark.usefixtures("aws")
def test_place_order_stores_and_returns_201() -> None:
    status, body = invoke(http_event("POST", "/orders", order_request_body()))

    assert status == 201
    assert body["total"] == "15.00"
    stored = repository.get(body["order_id"])
    assert stored is not None
    assert stored["total"] == Decimal("15.00")


@pytest.mark.usefixtures("aws")
def test_get_order_round_trip() -> None:
    _, placed = invoke(http_event("POST", "/orders", order_request_body()))

    status, body = invoke(http_event("GET", f"/orders/{placed['order_id']}"))

    assert status == 200
    assert body["customer_email"] == "ada@example.com"


@pytest.mark.usefixtures("aws")
def test_unknown_order_is_404() -> None:
    status, _ = invoke(http_event("GET", "/orders/ord-missing"))
    assert status == 404


@pytest.mark.usefixtures("aws")
def test_invalid_body_is_400() -> None:
    status, _ = invoke(http_event("POST", "/orders", order_request_body(lines=[])))
    assert status == 400


@pytest.mark.usefixtures("aws")
def test_express_rejected_when_flag_off() -> None:
    status, body = invoke(http_event("POST", "/orders", order_request_body(express=True)))
    assert status == 400
    assert "Express" in body["message"]


@pytest.mark.usefixtures("aws")
def test_express_allowed_when_flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("orders.service.flags.is_enabled", lambda *a, **k: True)
    status, body = invoke(http_event("POST", "/orders", order_request_body(express=True)))
    assert status == 201
    assert body["express"] is True
