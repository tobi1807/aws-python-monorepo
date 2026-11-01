from __future__ import annotations

from collections.abc import Iterator

import pytest
from moto import mock_aws

from runtime.aws import client
from testkit.aws import fake_credentials, reset_runtime_caches

TABLE = "test-orders-orders"
BUS = "test-shop-bus"


@pytest.fixture
def aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """moto-backed AWS with the resources the orders app expects."""
    fake_credentials(monkeypatch)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    monkeypatch.setenv("ORDERS_TABLE", TABLE)
    reset_runtime_caches()
    with mock_aws():
        client("dynamodb").create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "order_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "order_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        client("events").create_event_bus(Name=BUS)
        client("ssm").put_parameter(Name="/test/platform/event-bus-name", Value=BUS, Type="String")
        yield
    reset_runtime_caches()


def order_request_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "customer_email": "ada@example.com",
        "lines": [
            {"sku": "TEA-001", "quantity": 2, "unit_price": "3.50"},
            {"sku": "MUG-002", "quantity": 1, "unit_price": "8.00"},
        ],
    }
    body.update(overrides)
    return body
