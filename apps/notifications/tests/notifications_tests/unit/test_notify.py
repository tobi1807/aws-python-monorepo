from __future__ import annotations

import json
from typing import Any

import pytest

from notifications import notify
from notifications_tests.conftest import (
    OUTBOX,
    FakeContext,
    body_of,
    failed_detail,
    fulfilled_detail,
    sqs_event,
)
from runtime.aws import client


def invoke(*bodies: str) -> dict[str, Any]:
    return notify.handler(sqs_event(*bodies), FakeContext())  # type: ignore[arg-type]


def outbox_message(key: str) -> dict[str, str]:
    return json.loads(client("s3").get_object(Bucket=OUTBOX, Key=key)["Body"].read())


def outbox_keys() -> list[str]:
    listing = client("s3").list_objects_v2(Bucket=OUTBOX)
    return sorted(obj["Key"] for obj in listing.get("Contents", []))


@pytest.mark.usefixtures("aws")
def test_fulfilled_writes_message_with_presigned_invoice_url() -> None:
    result = invoke(body_of("OrderFulfilled", fulfilled_detail()))

    assert result == {"batchItemFailures": []}
    message = outbox_message("outbox/ord-123/OrderFulfilled.json")
    assert message["to"] == "ada@example.com"
    assert "ord-123" in message["subject"]
    assert "test-invoicing-invoices" in message["body"]
    assert "invoices/ord-123.html" in message["body"]
    assert "Signature" in message["body"] or "X-Amz-Signature" in message["body"]


@pytest.mark.usefixtures("aws")
def test_failed_writes_message_with_reason() -> None:
    result = invoke(body_of("OrderFulfilmentFailed", failed_detail()))

    assert result == {"batchItemFailures": []}
    message = outbox_message("outbox/ord-456/OrderFulfilmentFailed.json")
    assert message["to"] == "bob@example.com"
    assert "out of stock: TEA-001" in message["body"]


@pytest.mark.usefixtures("aws")
def test_bad_record_is_reported_but_good_one_still_sent() -> None:
    malformed = body_of("OrderFulfilled", {"order_id": "ord-bad"})  # missing required fields
    good = body_of("OrderFulfilmentFailed", failed_detail())

    result = invoke(malformed, good)

    assert result == {"batchItemFailures": [{"itemIdentifier": "m0"}]}
    assert outbox_keys() == ["outbox/ord-456/OrderFulfilmentFailed.json"]


@pytest.mark.usefixtures("aws")
def test_unparseable_and_unknown_records_are_reported() -> None:
    result = invoke(
        "not json", body_of("OrderPlaced", {}), body_of("OrderFulfilled", fulfilled_detail())
    )

    assert result == {"batchItemFailures": [{"itemIdentifier": "m0"}, {"itemIdentifier": "m1"}]}
    assert outbox_keys() == ["outbox/ord-123/OrderFulfilled.json"]


@pytest.mark.usefixtures("aws")
def test_missing_invoicing_config_fails_the_record_only() -> None:
    client("ssm").delete_parameter(Name="/test/invoicing/bucket-name")

    result = invoke(
        body_of("OrderFulfilled", fulfilled_detail()),
        body_of("OrderFulfilmentFailed", failed_detail()),
    )

    assert result == {"batchItemFailures": [{"itemIdentifier": "m0"}]}
    assert outbox_keys() == ["outbox/ord-456/OrderFulfilmentFailed.json"]
