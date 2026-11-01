from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from contracts.fulfilment import OrderFulfilled, OrderFulfilmentFailed
from fulfilment import publish_result
from fulfilment_tests.conftest import BUS, FakeContext, make_order
from runtime.aws import client

NOW = datetime(2026, 1, 2, 9, 30, tzinfo=UTC)


def invoke(event: dict[str, Any]) -> dict[str, str]:
    return publish_result.handler(event, FakeContext())  # type: ignore[arg-type]


@pytest.fixture
def captured(aws: None) -> list[dict[str, Any]]:
    """Capture what lands on the bus by wrapping put_events on the cached client."""
    puts: list[dict[str, Any]] = []
    events = client("events")
    original = events.put_events

    def spy(**kwargs: Any) -> Any:
        puts.extend(kwargs["Entries"])
        return original(**kwargs)

    events.put_events = spy
    return puts


def test_build_fulfilled_points_at_the_invoice() -> None:
    event = publish_result.build_fulfilled(make_order(), now=lambda: NOW)

    assert event == OrderFulfilled(
        order_id="ord-123",
        customer_email="ada@example.com",
        invoice_key="invoices/ord-123.html",
        fulfilled_at=NOW,
    )


def test_build_failed_uses_the_lambda_error_message() -> None:
    error = {
        "Error": "PaymentDeclined",
        "Cause": json.dumps({"errorMessage": "too much", "errorType": "PaymentDeclined"}),
    }

    event = publish_result.build_failed(make_order(), error, now=lambda: NOW)

    assert event == OrderFulfilmentFailed(
        order_id="ord-123",
        customer_email="ada@example.com",
        reason="PaymentDeclined: too much",
        failed_at=NOW,
    )


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (None, "unknown error"),
        ({}, "unknown error"),
        ({"Error": "States.TaskFailed"}, "States.TaskFailed"),
        (
            {"Error": "States.TaskFailed", "Cause": "container exited 1"},
            "States.TaskFailed: container exited 1",
        ),
        ({"Cause": "plain"}, "Error: plain"),
    ],
)
def test_failure_reason(error: dict[str, Any] | None, reason: str) -> None:
    assert publish_result.failure_reason(error) == reason


def test_fulfilled_publishes_order_fulfilled(captured: list[dict[str, Any]]) -> None:
    result = invoke({"mode": "fulfilled", "order": make_order().model_dump(mode="json")})

    assert result["detail_type"] == "OrderFulfilled"
    assert result["event_id"]
    (entry,) = captured
    assert entry["EventBusName"] == BUS
    assert entry["Source"] == "shop.fulfilment"
    assert entry["DetailType"] == "OrderFulfilled"
    detail = json.loads(entry["Detail"])
    assert detail["order_id"] == "ord-123"
    assert detail["invoice_key"] == "invoices/ord-123.html"
    OrderFulfilled.model_validate(detail)


def test_failed_publishes_order_fulfilment_failed(captured: list[dict[str, Any]]) -> None:
    invoke(
        {
            "mode": "failed",
            "order": make_order().model_dump(mode="json"),
            "error": {"Error": "States.TaskFailed", "Cause": "container exited 1"},
        }
    )

    (entry,) = captured
    assert entry["DetailType"] == "OrderFulfilmentFailed"
    detail = OrderFulfilmentFailed.model_validate_json(entry["Detail"])
    assert detail.reason == "States.TaskFailed: container exited 1"


@pytest.mark.usefixtures("aws")
def test_unknown_mode_is_an_error() -> None:
    with pytest.raises(ValueError, match="Unknown mode"):
        invoke({"mode": "shrug", "order": make_order().model_dump(mode="json")})
