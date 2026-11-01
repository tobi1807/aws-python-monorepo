"""Integration tests against Floci (fast, local, real AWS APIs).

Run: docker compose up -d floci && FLOCI_ENDPOINT=http://localhost:4566 pants --tag=floci test ::
These create their own resources with a unique prefix, so they're safe to run
in parallel and against a shared Floci.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator

import pytest

from orders import repository, service
from orders.models import PlaceOrderRequest
from orders_tests.conftest import order_request_body
from runtime.aws import client
from testkit.aws import fake_credentials, floci_endpoint, floci_required

pytestmark = floci_required()


@pytest.fixture
def floci(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Isolated stage on Floci: table, bus, a capture queue, and SSM wiring."""
    stage = f"it-{uuid.uuid4().hex[:8]}"
    fake_credentials(monkeypatch, stage=stage)
    with floci_endpoint(monkeypatch):
        table = f"{stage}-orders-orders"
        bus = f"{stage}-shop-bus"
        monkeypatch.setenv("ORDERS_TABLE", table)

        client("dynamodb").create_table(
            TableName=table,
            KeySchema=[{"AttributeName": "order_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "order_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        client("events").create_event_bus(Name=bus)
        client("ssm").put_parameter(Name=f"/{stage}/platform/event-bus-name", Value=bus, Type="String")

        queue_url = client("sqs").create_queue(QueueName=f"{stage}-capture")["QueueUrl"]
        queue_arn = client("sqs").get_queue_attributes(
            QueueUrl=queue_url, AttributeNames=["QueueArn"]
        )["Attributes"]["QueueArn"]
        client("events").put_rule(
            Name=f"{stage}-capture", EventBusName=bus, EventPattern=json.dumps({"source": ["shop.orders"]})
        )
        client("events").put_targets(
            Rule=f"{stage}-capture", EventBusName=bus, Targets=[{"Id": "q", "Arn": queue_arn}]
        )

        yield queue_url

        client("dynamodb").delete_table(TableName=table)
        client("sqs").delete_queue(QueueUrl=queue_url)


def test_place_order_persists_and_emits_event(floci: str) -> None:
    order = service.place_order(PlaceOrderRequest.model_validate(order_request_body()))

    assert repository.get(order.order_id) is not None

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        messages = client("sqs").receive_message(QueueUrl=floci, WaitTimeSeconds=1).get("Messages", [])
        if messages:
            envelope = json.loads(messages[0]["Body"])
            assert envelope["detail-type"] == "OrderPlaced"
            assert envelope["detail"]["order_id"] == order.order_id
            return
    pytest.fail("OrderPlaced never reached the capture queue")
