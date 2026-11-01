"""Consumer side of the fulfilment message contract (notifications <- fulfilment).

Declares exactly the fields notify reads, and runs the real parsing and
rendering code against the example messages. The generated pact is committed
to pacts/notifications-fulfilment.json for fulfilment to verify.
"""

from __future__ import annotations

import json
from pathlib import Path

from pact import Pact, match

from notifications.messages import parse_event, render
from testkit.pact import check_consumer_pact

ISO_TIMESTAMP = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
ANY_EMAIL = r"^[^@\s]+@[^@\s]+$"


def timestamp(example: str):
    return match.regex(example, regex=ISO_TIMESTAMP)


def handle(body: str | bytes | None, metadata: dict[str, object]) -> None:
    """What notify does with a message, minus AWS I/O: parse with the contract, render."""
    assert body is not None
    event = parse_event(str(metadata["detail-type"]), json.loads(body))
    message = render(event, invoice_url="https://invoices.example.test/signed")
    assert message.to == event.customer_email
    assert event.order_id in message.subject


def test_notifications_consumes_fulfilment_events(tmp_path: Path) -> None:
    pact = Pact("notifications", "fulfilment").with_specification("V4")

    (
        pact.upon_receiving("an OrderFulfilled event", "Async")
        .with_metadata({"detail-type": "OrderFulfilled"})
        .with_body(
            {
                "order_id": match.str("ord-123"),
                "customer_email": match.regex("ada@example.com", regex=ANY_EMAIL),
                "invoice_key": match.str("invoices/ord-123.html"),
                "fulfilled_at": timestamp("2026-01-01T12:00:00Z"),
            },
            "application/json",
        )
    )
    (
        pact.upon_receiving("an OrderFulfilmentFailed event", "Async")
        .with_metadata({"detail-type": "OrderFulfilmentFailed"})
        .with_body(
            {
                "order_id": match.str("ord-456"),
                "customer_email": match.regex("bob@example.com", regex=ANY_EMAIL),
                "reason": match.str("out of stock: TEA-001"),
                "failed_at": timestamp("2026-01-01T13:30:00Z"),
            },
            "application/json",
        )
    )

    pact.verify(handle, "Async")
    check_consumer_pact(pact, tmp_path)
