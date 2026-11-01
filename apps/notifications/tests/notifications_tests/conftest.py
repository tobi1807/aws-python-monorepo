from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from moto import mock_aws

from runtime.aws import client
from testkit.aws import TEST_REGION, fake_credentials, reset_runtime_caches

OUTBOX = "test-notifications-outbox"
INVOICES = "test-invoicing-invoices"
INVOICE_KEY = "invoices/ord-123.html"


def create_bucket(name: str) -> None:
    client("s3").create_bucket(
        Bucket=name, CreateBucketConfiguration={"LocationConstraint": TEST_REGION}
    )


@pytest.fixture
def aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """moto-backed AWS with the resources the notifications app expects."""
    fake_credentials(monkeypatch)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    monkeypatch.setenv("OUTBOX_BUCKET", OUTBOX)
    reset_runtime_caches()
    with mock_aws():
        create_bucket(OUTBOX)
        create_bucket(INVOICES)
        client("s3").put_object(Bucket=INVOICES, Key=INVOICE_KEY, Body=b"<html>invoice</html>")
        client("ssm").put_parameter(
            Name="/test/invoicing/bucket-name", Value=INVOICES, Type="String"
        )
        yield
    reset_runtime_caches()


def fulfilled_detail(**overrides: object) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "order_id": "ord-123",
        "customer_email": "ada@example.com",
        "invoice_key": INVOICE_KEY,
        "fulfilled_at": "2026-01-01T12:00:00Z",
    }
    detail.update(overrides)
    return detail


def failed_detail(**overrides: object) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "order_id": "ord-456",
        "customer_email": "bob@example.com",
        "reason": "out of stock: TEA-001",
        "failed_at": "2026-01-01T13:30:00Z",
    }
    detail.update(overrides)
    return detail


def envelope(detail_type: str, detail: dict[str, Any]) -> dict[str, Any]:
    """An EventBridge event envelope, as delivered inside an SQS message body."""
    return {
        "version": "0",
        "id": "evt-1",
        "detail-type": detail_type,
        "source": "shop.fulfilment",
        "account": "000000000000",
        "time": "2026-01-01T12:00:01Z",
        "region": TEST_REGION,
        "resources": [],
        "detail": detail,
    }


def sqs_record(message_id: str, body: str) -> dict[str, Any]:
    return {
        "messageId": message_id,
        "receiptHandle": f"rh-{message_id}",
        "body": body,
        "attributes": {
            "ApproximateReceiveCount": "1",
            "SentTimestamp": "1767268800000",
            "SenderId": "AIDAEXAMPLE",
            "ApproximateFirstReceiveTimestamp": "1767268800001",
        },
        "messageAttributes": {},
        "md5OfBody": "x",
        "eventSource": "aws:sqs",
        "eventSourceARN": f"arn:aws:sqs:{TEST_REGION}:000000000000:test-notifications-events",
        "awsRegion": TEST_REGION,
    }


def sqs_event(*bodies: str) -> dict[str, Any]:
    return {"Records": [sqs_record(f"m{i}", body) for i, body in enumerate(bodies)]}


def body_of(detail_type: str, detail: dict[str, Any]) -> str:
    return json.dumps(envelope(detail_type, detail))


class FakeContext:
    function_name = "notifications-notify"
    memory_limit_in_mb = 512
    invoked_function_arn = "arn:aws:lambda:eu-west-2:000000000000:function:notifications-notify"
    aws_request_id = "req-1"
