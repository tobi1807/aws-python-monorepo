"""Shapes owned by the catalog app (exposed over its AppSync API)."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class Product(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    sku: str
    name: str
    price: Decimal = Field(ge=0)
    currency: str = "GBP"
    stock: int = Field(ge=0, default=0)
