from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from contracts.fulfilment import OrderFulfilled
from contracts.orders import OrderLine, OrderPlaced


def order() -> OrderPlaced:
    return OrderPlaced(
        order_id="ord-1",
        customer_email="ada@example.com",
        lines=[OrderLine(sku="TEA-001", quantity=2, unit_price=Decimal("3.50"))],
        total=Decimal("7.00"),
        placed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_round_trip_through_detail_json() -> None:
    original = order()
    assert OrderPlaced.model_validate_json(original.to_detail()) == original


def test_decimals_serialise_as_strings() -> None:
    detail = json.loads(order().to_detail())
    assert detail["total"] == "7.00"
    assert detail["lines"][0]["unit_price"] == "3.50"


def test_consumers_tolerate_unknown_fields() -> None:
    detail = json.loads(order().to_detail()) | {"added_in_v2": "ignored"}
    assert OrderPlaced.model_validate(detail).order_id == "ord-1"


def test_routing_metadata() -> None:
    assert (OrderPlaced.SOURCE, OrderPlaced.DETAIL_TYPE) == ("shop.orders", "OrderPlaced")
    assert OrderFulfilled.SOURCE == "shop.fulfilment"


def test_quantity_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        OrderLine(sku="X", quantity=0, unit_price=Decimal("1"))
