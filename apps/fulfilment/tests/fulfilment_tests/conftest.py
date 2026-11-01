from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from moto import mock_aws

from contracts.orders import OrderLine, OrderPlaced
from runtime.aws import client
from testkit.aws import fake_credentials, reset_runtime_caches

BUS = "test-shop-bus"
SECRET = "test-fulfilment-payment-provider"
API_KEY = "sk-test-123"
STATE_MACHINE_NAME = "test-fulfilment-fulfilment"
PASS_DEFINITION = json.dumps({"StartAt": "Done", "States": {"Done": {"Type": "Pass", "End": True}}})


class FakeContext:
    function_name = "fulfilment-fn"
    memory_limit_in_mb = 512
    invoked_function_arn = "arn:aws:lambda:eu-west-2:123456789012:function:fulfilment-fn"
    aws_request_id = "req-1"


def make_order(**overrides: object) -> OrderPlaced:
    fields: dict[str, object] = {
        "order_id": "ord-123",
        "customer_email": "ada@example.com",
        "lines": [
            OrderLine(sku="TEA-001", quantity=2, unit_price=Decimal("3.50")),
            OrderLine(sku="MUG-002", quantity=1, unit_price=Decimal("8.00")),
        ],
        "total": Decimal("15.00"),
        "express": False,
        "placed_at": datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    }
    fields.update(overrides)
    return OrderPlaced(**fields)  # type: ignore[arg-type]


def eventbridge_envelope(order: OrderPlaced) -> dict[str, Any]:
    """What EventBridge puts in the SQS message body for an OrderPlaced event."""
    return {
        "version": "0",
        "id": "11111111-2222-3333-4444-555555555555",
        "detail-type": order.DETAIL_TYPE,
        "source": order.SOURCE,
        "account": "123456789012",
        "time": "2026-01-01T12:00:00Z",
        "region": "eu-west-2",
        "resources": [],
        "detail": json.loads(order.to_detail()),
    }


def sqs_event(*bodies: str) -> dict[str, Any]:
    """An SQS -> Lambda event with one record per body."""
    return {
        "Records": [
            {
                "messageId": f"msg-{i}",
                "receiptHandle": f"handle-{i}",
                "body": body,
                "attributes": {
                    "ApproximateReceiveCount": "1",
                    "SentTimestamp": "1767268800000",
                    "SenderId": "AIDAEXAMPLE",
                    "ApproximateFirstReceiveTimestamp": "1767268800001",
                },
                "messageAttributes": {},
                "md5OfBody": "ignored",
                "eventSource": "aws:sqs",
                "eventSourceARN": "arn:aws:sqs:eu-west-2:123456789012:test-fulfilment-intake",
                "awsRegion": "eu-west-2",
            }
            for i, body in enumerate(bodies)
        ]
    }


@pytest.fixture
def aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """moto-backed AWS with the resources the fulfilment app expects."""
    fake_credentials(monkeypatch)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    monkeypatch.setenv("PAYMENT_SECRET_ID", SECRET)
    reset_runtime_caches()
    with mock_aws():
        client("events").create_event_bus(Name=BUS)
        client("ssm").put_parameter(Name="/test/platform/event-bus-name", Value=BUS, Type="String")
        client("secretsmanager").create_secret(
            Name=SECRET, SecretString=json.dumps({"provider": "acme-pay", "api_key": API_KEY})
        )
        arn = client("stepfunctions").create_state_machine(
            name=STATE_MACHINE_NAME,
            definition=PASS_DEFINITION,
            roleArn="arn:aws:iam::123456789012:role/test",
        )["stateMachineArn"]
        monkeypatch.setenv("STATE_MACHINE_ARN", arn)
        yield
    reset_runtime_caches()
