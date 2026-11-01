"""Publish the outcome of a fulfilment run on the shared bus.

Invoked by the state machine in one of two modes:
  {"mode": "fulfilled", "order": <OrderPlaced>}
  {"mode": "failed",    "order": <OrderPlaced>, "error": {"Error": ..., "Cause": ...}}

The ``build_*`` functions are the single place these events are constructed
(the Pact provider verification for notifications uses them too).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

from contracts.fulfilment import OrderFulfilled, OrderFulfilmentFailed
from contracts.orders import OrderPlaced
from runtime import events

logger = Logger()

Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def invoice_key(order_id: str) -> str:
    """Where the invoicing app writes the invoice (``invoices/{order_id}.html``)."""
    return f"invoices/{order_id}.html"


def failure_reason(error: dict[str, Any] | None) -> str:
    """Human-readable reason from a Step Functions error (``Error``/``Cause``).

    For Lambda failures ``Cause`` is itself JSON with an ``errorMessage``.
    """
    if not error:
        return "unknown error"
    name = str(error.get("Error") or "Error")
    cause = error.get("Cause")
    if isinstance(cause, str):
        try:
            parsed = json.loads(cause)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict) and parsed.get("errorMessage"):
            cause = parsed["errorMessage"]
    return f"{name}: {cause}" if cause else name


def build_fulfilled(order: OrderPlaced, *, now: Clock = _utcnow) -> OrderFulfilled:
    return OrderFulfilled(
        order_id=order.order_id,
        customer_email=order.customer_email,
        invoice_key=invoice_key(order.order_id),
        fulfilled_at=now(),
    )


def build_failed(
    order: OrderPlaced, error: dict[str, Any] | None = None, *, now: Clock = _utcnow
) -> OrderFulfilmentFailed:
    return OrderFulfilmentFailed(
        order_id=order.order_id,
        customer_email=order.customer_email,
        reason=failure_reason(error),
        failed_at=now(),
    )


@logger.inject_lambda_context
def handler(event: dict[str, Any], context: LambdaContext) -> dict[str, str]:
    order = OrderPlaced.model_validate(event["order"])
    mode = event["mode"]
    if mode == "fulfilled":
        outcome: OrderFulfilled | OrderFulfilmentFailed = build_fulfilled(order)
    elif mode == "failed":
        outcome = build_failed(order, event.get("error"))
    else:
        raise ValueError(f"Unknown mode {mode!r}")

    event_id = events.publish(outcome)
    logger.info("published", extra={"order_id": order.order_id, "type": outcome.DETAIL_TYPE})
    return {"event_id": event_id, "detail_type": outcome.DETAIL_TYPE}
