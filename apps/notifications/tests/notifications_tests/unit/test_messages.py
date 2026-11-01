from __future__ import annotations

import pytest

from contracts.fulfilment import OrderFulfilled, OrderFulfilmentFailed
from notifications import messages
from notifications_tests.conftest import failed_detail, fulfilled_detail


def test_parse_dispatches_on_detail_type() -> None:
    assert isinstance(messages.parse_event("OrderFulfilled", fulfilled_detail()), OrderFulfilled)
    assert isinstance(
        messages.parse_event("OrderFulfilmentFailed", failed_detail()), OrderFulfilmentFailed
    )


def test_parse_ignores_unknown_fields() -> None:
    event = messages.parse_event("OrderFulfilled", fulfilled_detail(carrier="DHL"))
    assert event.order_id == "ord-123"


def test_parse_rejects_unknown_detail_type() -> None:
    with pytest.raises(messages.UnsupportedEvent):
        messages.parse_event("OrderPlaced", {})


def test_parse_rejects_missing_fields() -> None:
    detail = fulfilled_detail()
    del detail["invoice_key"]
    with pytest.raises(ValueError, match="invoice_key"):
        messages.parse_event("OrderFulfilled", detail)


def test_render_fulfilled_includes_invoice_link() -> None:
    event = messages.parse_event("OrderFulfilled", fulfilled_detail())
    message = messages.render(event, invoice_url="https://example.test/invoice")

    assert message.to == "ada@example.com"
    assert "ord-123" in message.subject
    assert "https://example.test/invoice" in message.body
    assert "01 January 2026 at 12:00" in message.body


def test_render_fulfilled_requires_invoice_url() -> None:
    event = messages.parse_event("OrderFulfilled", fulfilled_detail())
    with pytest.raises(ValueError, match="invoice_url"):
        messages.render(event)


def test_render_failed_states_reason() -> None:
    event = messages.parse_event("OrderFulfilmentFailed", failed_detail())
    message = messages.render(event)

    assert message.to == "bob@example.com"
    assert "ord-456" in message.subject
    assert "out of stock: TEA-001" in message.body


def test_outbox_key() -> None:
    assert messages.outbox_key("ord-1", "OrderFulfilled") == "outbox/ord-1/OrderFulfilled.json"
