"""Events produced by the fulfilment app."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from contracts.base import DomainEvent


class OrderFulfilled(DomainEvent):
    SOURCE: ClassVar[str] = "shop.fulfilment"
    DETAIL_TYPE: ClassVar[str] = "OrderFulfilled"

    order_id: str
    customer_email: str
    invoice_key: str
    """S3 object key of the rendered invoice in the invoicing bucket."""
    fulfilled_at: datetime


class OrderFulfilmentFailed(DomainEvent):
    SOURCE: ClassVar[str] = "shop.fulfilment"
    DETAIL_TYPE: ClassVar[str] = "OrderFulfilmentFailed"

    order_id: str
    customer_email: str
    reason: str
    failed_at: datetime
