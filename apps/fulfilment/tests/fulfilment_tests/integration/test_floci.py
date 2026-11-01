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
from dataclasses import dataclass
from typing import Any

import pytest

from contracts.fulfilment import OrderFulfilled, OrderFulfilmentFailed
from fulfilment import intake, publish_result
from fulfilment_tests.conftest import (
    PASS_DEFINITION,
    FakeContext,
    eventbridge_envelope,
    make_order,
    sqs_event,
)
from runtime.aws import client
from testkit.aws import fake_credentials, floci_endpoint, floci_required

pytestmark = floci_required()

ACCOUNT_ID = "000000000000"


@dataclass(frozen=True)
class Resources:
    stage: str
    state_machine_arn: str
    capture_queue_url: str


@pytest.fixture
def floci(monkeypatch: pytest.MonkeyPatch) -> Iterator[Resources]:
    """Isolated stage on Floci: bus + SSM wiring, a capture queue, a trivial state machine."""
    stage = f"it-{uuid.uuid4().hex[:8]}"
    fake_credentials(monkeypatch, stage=stage)
    with floci_endpoint(monkeypatch):
        bus = f"{stage}-shop-bus"
        client("events").create_event_bus(Name=bus)
        client("ssm").put_parameter(
            Name=f"/{stage}/platform/event-bus-name", Value=bus, Type="String"
        )

        queue_url = client("sqs").create_queue(QueueName=f"{stage}-capture")["QueueUrl"]
        queue_arn = client("sqs").get_queue_attributes(
            QueueUrl=queue_url, AttributeNames=["QueueArn"]
        )["Attributes"]["QueueArn"]
        client("events").put_rule(
            Name=f"{stage}-capture",
            EventBusName=bus,
            EventPattern=json.dumps({"source": ["shop.fulfilment"]}),
        )
        client("events").put_targets(
            Rule=f"{stage}-capture", EventBusName=bus, Targets=[{"Id": "q", "Arn": queue_arn}]
        )

        state_machine_arn = client("stepfunctions").create_state_machine(
            name=f"{stage}-fulfilment-fulfilment",
            definition=PASS_DEFINITION,
            roleArn=f"arn:aws:iam::{ACCOUNT_ID}:role/{stage}-sfn",
        )["stateMachineArn"]
        monkeypatch.setenv("STATE_MACHINE_ARN", state_machine_arn)

        yield Resources(stage, state_machine_arn, queue_url)

        client("stepfunctions").delete_state_machine(stateMachineArn=state_machine_arn)
        client("sqs").delete_queue(QueueUrl=queue_url)
        client("events").remove_targets(Rule=f"{stage}-capture", EventBusName=bus, Ids=["q"])
        client("events").delete_rule(Name=f"{stage}-capture", EventBusName=bus)
        client("events").delete_event_bus(Name=bus)


def receive_one(queue_url: str) -> dict[str, Any]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        messages = (
            client("sqs").receive_message(QueueUrl=queue_url, WaitTimeSeconds=1).get("Messages", [])
        )
        if messages:
            return json.loads(messages[0]["Body"])
    pytest.fail("No event reached the capture queue")


def test_intake_starts_a_named_execution(floci: Resources) -> None:
    order = make_order(order_id=f"ord-{uuid.uuid4().hex[:8]}")
    body = json.dumps(eventbridge_envelope(order))

    response = intake.handler(sqs_event(body), FakeContext())  # type: ignore[arg-type]
    # Redelivery of the same message must not fail the batch.
    again = intake.handler(sqs_event(body), FakeContext())  # type: ignore[arg-type]

    assert response == again == {"batchItemFailures": []}
    executions = client("stepfunctions").list_executions(stateMachineArn=floci.state_machine_arn)[
        "executions"
    ]
    assert [e["name"] for e in executions] == [order.order_id]
    described = client("stepfunctions").describe_execution(
        executionArn=executions[0]["executionArn"]
    )
    assert json.loads(described["input"])["order"]["order_id"] == order.order_id


def test_publish_result_puts_fulfilled_event_on_the_bus(floci: Resources) -> None:
    order = make_order(order_id=f"ord-{uuid.uuid4().hex[:8]}")

    publish_result.handler(
        {"mode": "fulfilled", "order": order.model_dump(mode="json")},
        FakeContext(),  # type: ignore[arg-type]
    )

    envelope = receive_one(floci.capture_queue_url)
    assert envelope["detail-type"] == "OrderFulfilled"
    assert envelope["source"] == "shop.fulfilment"
    event = OrderFulfilled.model_validate(envelope["detail"])
    assert event.invoice_key == f"invoices/{order.order_id}.html"


def test_publish_result_puts_failed_event_on_the_bus(floci: Resources) -> None:
    order = make_order(order_id=f"ord-{uuid.uuid4().hex[:8]}")

    publish_result.handler(
        {
            "mode": "failed",
            "order": order.model_dump(mode="json"),
            "error": {"Error": "PaymentDeclined", "Cause": "too much"},
        },
        FakeContext(),  # type: ignore[arg-type]
    )

    envelope = receive_one(floci.capture_queue_url)
    assert envelope["detail-type"] == "OrderFulfilmentFailed"
    event = OrderFulfilmentFailed.model_validate(envelope["detail"])
    assert event.reason == "PaymentDeclined: too much"
