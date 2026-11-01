"""SQS -> Step Functions intake.

EventBridge delivers ``OrderPlaced`` events to an SQS queue; this function
starts one fulfilment execution per order. Messages are processed with
Powertools' ``BatchProcessor`` so one bad message doesn't fail the whole batch
(partial batch responses): failures return to the queue and, after
``maxReceiveCount`` attempts, land in the DLQ.

Environment:
  STATE_MACHINE_ARN  the fulfilment state machine
"""

from __future__ import annotations

import json
import os
from typing import Any

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.batch import (
    BatchProcessor,
    EventType,
    process_partial_response,
)
from aws_lambda_powertools.utilities.batch.types import PartialItemFailureResponse
from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
from aws_lambda_powertools.utilities.typing import LambdaContext

from contracts.orders import OrderPlaced
from runtime.aws import client

logger = Logger()
processor = BatchProcessor(event_type=EventType.SQS)


def parse_order(detail: str | bytes | dict[str, Any]) -> OrderPlaced:
    """Parse an ``OrderPlaced`` event body (the EventBridge ``detail``)."""
    if isinstance(detail, dict):
        return OrderPlaced.model_validate(detail)
    return OrderPlaced.model_validate_json(detail)


def parse_envelope(body: str | bytes) -> OrderPlaced:
    """Parse an SQS message body: the full EventBridge envelope around ``detail``."""
    envelope = json.loads(body)
    return parse_order(envelope["detail"])


def execution_input(order: OrderPlaced) -> str:
    """State machine input. The order stays at ``$.order`` for the whole run."""
    return json.dumps({"order": order.model_dump(mode="json")})


def start_fulfilment(order: OrderPlaced) -> bool:
    """Start the execution for ``order``. Returns False if it already exists.

    The execution name is the order id, so redelivered messages (SQS is
    at-least-once) can't start a second fulfilment.
    """
    sfn = client("stepfunctions")
    try:
        sfn.start_execution(
            stateMachineArn=os.environ["STATE_MACHINE_ARN"],
            name=order.order_id,
            input=execution_input(order),
        )
    except sfn.exceptions.ExecutionAlreadyExists:
        logger.info("fulfilment already started", extra={"order_id": order.order_id})
        return False
    return True


def record_handler(record: SQSRecord) -> None:
    order = parse_envelope(record.body)
    started = start_fulfilment(order)
    logger.info("order intake", extra={"order_id": order.order_id, "started": started})


@logger.inject_lambda_context
def handler(event: dict[str, Any], context: LambdaContext) -> PartialItemFailureResponse:
    return process_partial_response(
        event=event,
        record_handler=record_handler,
        processor=processor,
        context=context,
    )
