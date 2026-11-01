from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from moto import mock_aws

from contracts.orders import OrderLine, OrderPlaced
from runtime.aws import client
from testkit.aws import fake_credentials, reset_runtime_caches

BUCKET = "test-invoicing-invoices"


@pytest.fixture
def aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """moto-backed S3 with the invoice bucket; yields the bucket name."""
    fake_credentials(monkeypatch)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    monkeypatch.setenv("INVOICE_BUCKET", BUCKET)
    reset_runtime_caches()
    with mock_aws():
        client("s3").create_bucket(
            Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "eu-west-2"}
        )
        yield BUCKET
    reset_runtime_caches()


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
