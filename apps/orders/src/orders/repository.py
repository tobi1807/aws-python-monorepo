from __future__ import annotations

import os
from typing import Any

from contracts.orders import OrderPlaced
from runtime.aws import client
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

_serializer = TypeSerializer()
_deserializer = TypeDeserializer()


def table_name() -> str:
    return os.environ["ORDERS_TABLE"]


def save(order: OrderPlaced) -> None:
    item = order.model_dump(mode="json")
    item["total"] = order.total
    for line in item["lines"]:
        line["unit_price"] = next(
            original.unit_price for original in order.lines if original.sku == line["sku"]
        )
    client("dynamodb").put_item(
        TableName=table_name(),
        Item={k: _serializer.serialize(v) for k, v in item.items()},
        ConditionExpression="attribute_not_exists(order_id)",
    )


def get(order_id: str) -> dict[str, Any] | None:
    response = client("dynamodb").get_item(
        TableName=table_name(), Key={"order_id": {"S": order_id}}
    )
    raw = response.get("Item")
    if raw is None:
        return None
    return {k: _deserializer.deserialize(v) for k, v in raw.items()}
