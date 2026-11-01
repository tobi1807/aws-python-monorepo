"""Integration tests against Floci (real S3/SSM APIs, no mocks).

Run: docker compose up -d floci && FLOCI_ENDPOINT=http://localhost:4566 pants --tag=floci test ::
Each test builds its own stage-prefixed resources, so it's safe against a shared Floci.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest

from notifications import notify
from notifications_tests.conftest import (
    FakeContext,
    body_of,
    create_bucket,
    failed_detail,
    fulfilled_detail,
    sqs_event,
)
from runtime.aws import client
from testkit.aws import fake_credentials, floci_endpoint, floci_required

pytestmark = floci_required()


@dataclass(frozen=True)
class Env:
    stage: str
    outbox: str
    invoices: str


@pytest.fixture
def floci(monkeypatch: pytest.MonkeyPatch) -> Iterator[Env]:
    stage = f"it-{uuid.uuid4().hex[:8]}"
    fake_credentials(monkeypatch, stage=stage)
    with floci_endpoint(monkeypatch):
        env = Env(
            stage=stage,
            outbox=f"{stage}-notifications-outbox",
            invoices=f"{stage}-invoicing-invoices",
        )
        monkeypatch.setenv("OUTBOX_BUCKET", env.outbox)
        create_bucket(env.outbox)
        create_bucket(env.invoices)
        client("s3").put_object(Bucket=env.invoices, Key="invoices/ord-123.html", Body=b"<html/>")
        client("ssm").put_parameter(
            Name=f"/{stage}/invoicing/bucket-name", Value=env.invoices, Type="String"
        )

        yield env

        for bucket in (env.outbox, env.invoices):
            for obj in client("s3").list_objects_v2(Bucket=bucket).get("Contents", []):
                client("s3").delete_object(Bucket=bucket, Key=obj["Key"])
            client("s3").delete_bucket(Bucket=bucket)
        client("ssm").delete_parameter(Name=f"/{stage}/invoicing/bucket-name")


def read_outbox(env: Env, key: str) -> dict[str, str]:
    return json.loads(client("s3").get_object(Bucket=env.outbox, Key=key)["Body"].read())


def test_notify_writes_outbox_messages(floci: Env) -> None:
    result = notify.handler(
        sqs_event(
            body_of("OrderFulfilled", fulfilled_detail()),
            body_of("OrderFulfilmentFailed", failed_detail()),
        ),
        FakeContext(),  # type: ignore[arg-type]
    )

    assert result == {"batchItemFailures": []}
    fulfilled = read_outbox(floci, "outbox/ord-123/OrderFulfilled.json")
    assert floci.invoices in fulfilled["body"]
    assert "invoices/ord-123.html" in fulfilled["body"]
    failed = read_outbox(floci, "outbox/ord-456/OrderFulfilmentFailed.json")
    assert "out of stock" in failed["body"]


def test_bad_record_reported_without_blocking_good_one(floci: Env) -> None:
    result = notify.handler(
        sqs_event("garbage", body_of("OrderFulfilmentFailed", failed_detail())),
        FakeContext(),  # type: ignore[arg-type]
    )

    assert result == {"batchItemFailures": [{"itemIdentifier": "m0"}]}
    assert (
        read_outbox(floci, "outbox/ord-456/OrderFulfilmentFailed.json")["to"] == "bob@example.com"
    )
