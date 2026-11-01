"""Consumer side of the OrderPlaced message contract (fulfilment <- orders).

Declares every field the intake function reads, with matchers (shape, not
values), and runs the *real* intake parsing code against the example message.
Regenerate the committed pact with PACT_UPDATE=1 (see testkit.pact).
"""

from __future__ import annotations

import json
from pathlib import Path

from pact import Pact, match

from contracts.orders import OrderPlaced
from fulfilment import intake
from testkit.pact import check_consumer_pact

# pydantic serialises Decimal as a JSON string ("3.50") and UTC datetimes as
# "2026-01-01T12:00:00Z".
DECIMAL_STRING = r"^\d+(\.\d+)?$"
ISO_TIMESTAMP = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})$"


def handle_order_placed(body: str | bytes | None, metadata: dict[str, object]) -> None:
    """What the consumer does with the message: the real intake parsing."""
    assert body is not None
    order = intake.parse_order(body)
    assert isinstance(order, OrderPlaced)
    assert order.order_id
    assert order.customer_email
    assert order.lines
    assert all(line.quantity > 0 and line.sku for line in order.lines)
    assert order.total >= 0

    # The same body must also survive the EventBridge -> SQS envelope path.
    envelope = {"detail-type": metadata.get("detail-type"), "detail": json.loads(body)}
    assert intake.parse_envelope(json.dumps(envelope)) == order


def test_fulfilment_consumes_order_placed(tmp_path: Path) -> None:
    pact = Pact("fulfilment", "orders").with_specification("V4")
    (
        pact.upon_receiving("an OrderPlaced event", "Async")
        .with_body(
            {
                "order_id": match.str("ord-123"),
                "customer_email": match.str("ada@example.com"),
                "lines": match.each_like(
                    {
                        "sku": match.str("TEA-001"),
                        "quantity": match.int(2),
                        "unit_price": match.regex("3.50", regex=DECIMAL_STRING),
                    },
                    min=1,
                ),
                "total": match.regex("7.00", regex=DECIMAL_STRING),
                "express": match.bool(False),
                "placed_at": match.regex("2026-01-01T12:00:00Z", regex=ISO_TIMESTAMP),
            },
            "application/json",
        )
        .with_metadata({"detail-type": "OrderPlaced", "source": "shop.orders"})
    )

    pact.verify(handle_order_placed, "Async")
    check_consumer_pact(pact, tmp_path)
