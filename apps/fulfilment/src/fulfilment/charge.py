"""Charge the customer (simulated payment provider).

Invoked by the state machine with the ``OrderPlaced`` JSON. The provider key
lives in Secrets Manager (``PAYMENT_SECRET_ID``). Orders over the limit are
declined by raising ``PaymentDeclined``; the state machine catches it and
reports a failed fulfilment.

Environment:
  PAYMENT_SECRET_ID  name/ARN of the JSON secret holding ``api_key``
"""

from __future__ import annotations

import hashlib
import os
from decimal import Decimal
from typing import Any

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext

from contracts.orders import OrderPlaced
from runtime import secrets

logger = Logger()

DECLINE_ABOVE = Decimal("1000")


class PaymentDeclined(Exception):
    pass


def charge_order(order: OrderPlaced, api_key: str) -> dict[str, str]:
    if order.total > DECLINE_ABOVE:
        raise PaymentDeclined(
            f"Order {order.order_id} total {order.total} exceeds limit {DECLINE_ABOVE}"
        )
    # Stand-in for a real provider call: deterministic, so retries are idempotent.
    digest = hashlib.sha256(f"{api_key}:{order.order_id}".encode()).hexdigest()
    return {"charge_id": f"ch_{digest[:16]}", "amount": str(order.total)}


@logger.inject_lambda_context
def handler(event: dict[str, Any], context: LambdaContext) -> dict[str, str]:
    order = OrderPlaced.model_validate(event)
    api_key = secrets.get_secret_json(os.environ["PAYMENT_SECRET_ID"])["api_key"]
    result = charge_order(order, api_key)
    logger.info("payment charged", extra={"order_id": order.order_id, **result})
    return result
