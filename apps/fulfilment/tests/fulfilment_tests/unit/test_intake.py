from __future__ import annotations

import json
import os
from typing import Any

import pytest
from aws_lambda_powertools.utilities.batch.exceptions import BatchProcessingError

from fulfilment import intake
from fulfilment_tests.conftest import FakeContext, eventbridge_envelope, make_order, sqs_event
from runtime.aws import client


def invoke(*bodies: str) -> dict[str, Any]:
    return intake.handler(sqs_event(*bodies), FakeContext())  # type: ignore[arg-type]


def executions() -> list[dict[str, Any]]:
    return client("stepfunctions").list_executions(stateMachineArn=os.environ["STATE_MACHINE_ARN"])[
        "executions"
    ]


def body_for(order_id: str) -> str:
    return json.dumps(eventbridge_envelope(make_order(order_id=order_id)))


def test_parse_envelope_reads_detail() -> None:
    order = intake.parse_envelope(body_for("ord-7"))

    assert order.order_id == "ord-7"
    assert order.total == make_order().total
    assert [line.sku for line in order.lines] == ["TEA-001", "MUG-002"]


def test_parse_order_accepts_str_bytes_and_dict() -> None:
    detail = make_order().to_detail()

    assert intake.parse_order(detail) == intake.parse_order(detail.encode())
    assert intake.parse_order(detail) == intake.parse_order(json.loads(detail))


def test_execution_input_nests_order_under_order_key() -> None:
    payload = json.loads(intake.execution_input(make_order()))

    assert list(payload) == ["order"]
    assert payload["order"]["order_id"] == "ord-123"
    assert payload["order"]["total"] == "15.00"
    assert payload["order"]["lines"][0] == {"sku": "TEA-001", "quantity": 2, "unit_price": "3.50"}
    # Round-trips back into the contract model: this is what the Lambdas parse.
    assert intake.parse_order(payload["order"]) == make_order()


@pytest.mark.usefixtures("aws")
def test_starts_one_execution_per_order_named_by_order_id() -> None:
    response = invoke(body_for("ord-1"), body_for("ord-2"))

    assert response == {"batchItemFailures": []}
    assert sorted(e["name"] for e in executions()) == ["ord-1", "ord-2"]


@pytest.mark.usefixtures("aws")
def test_execution_receives_wrapped_order() -> None:
    invoke(body_for("ord-1"))

    described = client("stepfunctions").describe_execution(
        executionArn=executions()[0]["executionArn"]
    )
    assert json.loads(described["input"])["order"]["order_id"] == "ord-1"


@pytest.mark.usefixtures("aws")
def test_redelivered_message_is_idempotent() -> None:
    invoke(body_for("ord-1"))

    response = invoke(body_for("ord-1"))

    assert response == {"batchItemFailures": []}
    assert len(executions()) == 1


@pytest.mark.usefixtures("aws")
def test_execution_already_exists_is_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real Step Functions raises this when a *closed* execution has the same name."""
    sfn = client("stepfunctions")

    def already_exists(**_kwargs: Any) -> None:
        raise sfn.exceptions.ExecutionAlreadyExists(
            {"Error": {"Code": "ExecutionAlreadyExists", "Message": "exists"}}, "StartExecution"
        )

    monkeypatch.setattr(sfn, "start_execution", already_exists)

    assert intake.start_fulfilment(make_order()) is False
    assert invoke(body_for("ord-1")) == {"batchItemFailures": []}


@pytest.mark.usefixtures("aws")
def test_start_fulfilment_reports_that_it_started() -> None:
    assert intake.start_fulfilment(make_order(order_id="ord-9")) is True


@pytest.mark.usefixtures("aws")
def test_bad_message_fails_alone() -> None:
    response = invoke(body_for("ord-1"), "not json", json.dumps({"detail": {"order_id": "x"}}))

    assert response == {
        "batchItemFailures": [{"itemIdentifier": "msg-1"}, {"itemIdentifier": "msg-2"}]
    }
    assert [e["name"] for e in executions()] == ["ord-1"]


@pytest.mark.usefixtures("aws")
def test_start_execution_error_fails_the_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "STATE_MACHINE_ARN", "arn:aws:states:eu-west-2:123456789012:stateMachine:missing"
    )

    # Every record failed: Powertools raises so the whole batch is retried.
    with pytest.raises(BatchProcessingError):
        invoke(body_for("ord-1"))
