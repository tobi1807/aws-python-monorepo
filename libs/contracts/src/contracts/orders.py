"""Events produced by the orders app."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from contracts.base import DomainEvent


class OrderLine(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    sku: str
    quantity: int = Field(gt=0)
    unit_price: Decimal = Field(ge=0)


class OrderPlaced(DomainEvent):
    SOURCE: ClassVar[str] = "shop.orders"
    DETAIL_TYPE: ClassVar[str] = "OrderPlaced"

    order_id: str
    customer_email: str
    lines: list[OrderLine]
    total: Decimal
    express: bool = False
    placed_at: datetime
