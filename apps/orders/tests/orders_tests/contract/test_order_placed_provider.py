"""Provider side of the OrderPlaced message contract.

Verifies that the events orders actually publishes satisfy every consumer's
committed pact. Consumers: fulfilment.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from pact import Verifier

from contracts.orders import OrderLine
from orders.models import PlaceOrderRequest
from orders.service import build_order_placed
from testkit.pact import committed_pact

CONSUMERS = ["fulfilment"]


def produce_order_placed(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """Build the event with the same code path production uses."""
    request = PlaceOrderRequest(
        customer_email="ada@example.com",
        lines=[OrderLine(sku="TEA-001", quantity=2, unit_price=Decimal("3.50"))],
    )
    event = build_order_placed(
        request,
        now=lambda: datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        new_id=lambda: "ord-123",
    )
    return {
        "contents": event.to_detail().encode(),
        "metadata": {"detail-type": event.DETAIL_TYPE, "source": event.SOURCE},
        "content_type": "application/json",
    }


@pytest.mark.parametrize("consumer", CONSUMERS)
def test_orders_satisfies_consumer_pacts(consumer: str) -> None:
    (
        Verifier("orders")
        .message_handler({"an OrderPlaced event": produce_order_placed})
        .add_source(committed_pact(consumer, "orders"))
        .verify()
    )
