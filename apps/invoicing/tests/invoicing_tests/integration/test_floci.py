"""Integration test against Floci S3.

Run: docker compose up -d floci && FLOCI_ENDPOINT=http://localhost:4566 pants --tag=floci test ::
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator

import pytest

from invoicing import render
from invoicing_tests.conftest import make_order
from runtime.aws import client
from testkit.aws import fake_credentials, floci_endpoint, floci_required

pytestmark = floci_required()


@pytest.fixture
def floci(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Isolated stage on Floci with its own invoice bucket."""
    stage = f"it-{uuid.uuid4().hex[:8]}"
    fake_credentials(monkeypatch, stage=stage)
    with floci_endpoint(monkeypatch):
        bucket = f"{stage}-invoicing-invoices"
        monkeypatch.setenv("INVOICE_BUCKET", bucket)
        client("s3").create_bucket(
            Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": "eu-west-2"}
        )

        yield bucket

        for obj in client("s3").list_objects_v2(Bucket=bucket).get("Contents", []):
            client("s3").delete_object(Bucket=bucket, Key=obj["Key"])
        client("s3").delete_bucket(Bucket=bucket)


def test_main_writes_invoice_to_s3(
    floci: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    order = make_order(order_id=f"ord-{uuid.uuid4().hex[:8]}")
    monkeypatch.setenv("ORDER_JSON", order.to_detail())

    render.main()

    key = json.loads(capsys.readouterr().out)["key"]
    assert key == f"invoices/{order.order_id}.html"
    body = client("s3").get_object(Bucket=floci, Key=key)["Body"].read().decode()
    assert order.order_id in body
