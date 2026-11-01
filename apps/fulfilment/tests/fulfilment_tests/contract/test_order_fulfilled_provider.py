"""Provider side of the OrderFulfilled / OrderFulfilmentFailed message contracts.

Verifies that the events fulfilment actually publishes satisfy every consumer's
committed pact. Consumers: notifications.

The notifications pact is written by the notifications app; until it is
committed to pacts/ this test is skipped.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pact import Verifier
from pact.types import Message

from contracts.base import DomainEvent
from fulfilment.publish_result import build_failed, build_fulfilled
from fulfilment_tests.conftest import make_order
from testkit.pact import committed_pact

CONSUMERS = ["notifications"]

NOW = datetime(2026, 1, 2, 9, 30, tzinfo=UTC)


def message(event: DomainEvent) -> Message:
    return {
        "contents": event.to_detail().encode(),
        "metadata": {"detail-type": event.DETAIL_TYPE, "source": event.SOURCE},
        "content_type": "application/json",
    }


def produce_order_fulfilled(*_args: Any, **_kwargs: Any) -> Message:
    """Build the event with the same code path production uses."""
    return message(build_fulfilled(make_order(order_id="ord-123"), now=lambda: NOW))


def produce_order_fulfilment_failed(*_args: Any, **_kwargs: Any) -> Message:
    error = {"Error": "PaymentDeclined", "Cause": "Order ord-123 total 5000.00 exceeds limit 1000"}
    return message(build_failed(make_order(order_id="ord-123"), error, now=lambda: NOW))


@pytest.mark.parametrize("consumer", CONSUMERS)
def test_fulfilment_satisfies_consumer_pacts(consumer: str) -> None:
    pact_file = committed_pact(consumer, "fulfilment")
    if not pact_file.exists():
        pytest.skip(f"{pact_file} not committed yet")
    (
        Verifier("fulfilment")
        .message_handler(
            {
                "an OrderFulfilled event": produce_order_fulfilled,
                "an OrderFulfilmentFailed event": produce_order_fulfilment_failed,
            }
        )
        .add_source(pact_file)
        .verify()
    )
