from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from contracts.orders import OrderLine


class PlaceOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_email: EmailStr
    lines: list[OrderLine] = Field(min_length=1)
    express: bool = False

    @property
    def total(self) -> Decimal:
        return sum((line.unit_price * line.quantity for line in self.lines), Decimal("0"))
