"""SQS consumer: fulfilment events -> customer message written to the outbox bucket.

Flow: EventBridge (shop.fulfilment) -> SQS -> this Lambda. Each SQS record body
is the full EventBridge envelope. Failures are reported per record so SQS only
retries (and eventually dead-letters) the messages that actually failed.
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

from contracts.fulfilment import OrderFulfilled
from notifications.messages import FulfilmentEvent, Message, outbox_key, parse_event, render
from runtime.aws import client
from runtime.config import get_config

logger = Logger()
processor = BatchProcessor(event_type=EventType.SQS)

INVOICE_URL_TTL_SECONDS = 7 * 24 * 3600


def invoice_url(event: OrderFulfilled) -> str:
    """Presigned GET for the invoice; the bucket is published by the invoicing app."""
    bucket = get_config("invoicing", "bucket-name")
    return client("s3").generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": event.invoice_key},
        ExpiresIn=INVOICE_URL_TTL_SECONDS,
    )


def build_message(event: FulfilmentEvent) -> Message:
    if isinstance(event, OrderFulfilled):
        return render(event, invoice_url=invoice_url(event))
    return render(event)


def send(message: Message, *, order_id: str, detail_type: str) -> str:
    """'Send' = write the message to the outbox bucket (stand-in for SES)."""
    key = outbox_key(order_id, detail_type)
    client("s3").put_object(
        Bucket=os.environ["OUTBOX_BUCKET"],
        Key=key,
        Body=json.dumps(message.to_dict()).encode(),
        ContentType="application/json",
    )
    return key


def process_envelope(envelope: dict[str, Any]) -> str:
    """Handle one EventBridge envelope; returns the outbox key written."""
    detail_type = envelope["detail-type"]
    event = parse_event(detail_type, envelope["detail"])
    key = send(build_message(event), order_id=event.order_id, detail_type=detail_type)
    logger.info("notification sent", extra={"order_id": event.order_id, "detail_type": detail_type})
    return key


def record_handler(record: SQSRecord) -> str:
    return process_envelope(json.loads(record.body))


@logger.inject_lambda_context
def handler(event: dict[str, Any], context: LambdaContext) -> PartialItemFailureResponse:
    return process_partial_response(
        event=event, record_handler=record_handler, processor=processor, context=context
    )
