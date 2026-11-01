"""Order placement: pure-ish business logic, I/O injected via the modules below."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from contracts.orders import OrderPlaced
from orders import repository
from orders.models import PlaceOrderRequest
from runtime import events, flags

EXPRESS_FLAG = "express_checkout"


class ExpressCheckoutUnavailable(Exception):
    pass


def build_order_placed(
    request: PlaceOrderRequest,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    new_id: Callable[[], str] = lambda: f"ord-{uuid.uuid4().hex[:12]}",
) -> OrderPlaced:
    return OrderPlaced(
        order_id=new_id(),
        customer_email=str(request.customer_email),
        lines=request.lines,
        total=request.total,
        express=request.express,
        placed_at=now(),
    )


def place_order(request: PlaceOrderRequest) -> OrderPlaced:
    if request.express and not flags.is_enabled(
        EXPRESS_FLAG, context={"customer_email": str(request.customer_email)}
    ):
        raise ExpressCheckoutUnavailable()

    order = build_order_placed(request)
    repository.save(order)
    events.publish(order)
    return order
