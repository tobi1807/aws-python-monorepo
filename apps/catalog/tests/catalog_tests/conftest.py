from __future__ import annotations

from collections.abc import Iterator

import pytest
from moto import mock_aws

from runtime.aws import client
from testkit.aws import fake_credentials, reset_runtime_caches

SECRET = "test-catalog-fx-api-key"
BUCKET = "test-catalog-images"


@pytest.fixture
def aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """moto-backed AWS with the secret and bucket the field resolvers expect."""
    fake_credentials(monkeypatch)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    monkeypatch.setenv("FX_API_KEY_SECRET", SECRET)
    monkeypatch.setenv("IMAGES_BUCKET", BUCKET)
    reset_runtime_caches()
    with mock_aws():
        client("secretsmanager").create_secret(Name=SECRET, SecretString="generated-key-123")
        client("s3").create_bucket(
            Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "eu-west-2"}
        )
        yield
    reset_runtime_caches()


def product_item(**overrides: object) -> dict[str, object]:
    """A Product as AppSync hands it to a field resolver (the DynamoDB item as JSON)."""
    item: dict[str, object] = {
        "sku": "TEA-001",
        "name": "Earl Grey",
        "price": 10.0,
        "currency": "GBP",
        "stock": 12,
    }
    item.update(overrides)
    return item
