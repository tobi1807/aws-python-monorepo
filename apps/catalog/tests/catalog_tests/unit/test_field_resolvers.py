from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import pytest

from catalog import field_resolvers, fx
from catalog_tests.conftest import BUCKET, SECRET, product_item
from runtime.aws import client


class FakeContext:
    function_name = "catalog-fieldresolvers"
    memory_limit_in_mb = 512
    invoked_function_arn = "arn:aws:lambda:eu-west-2:000000000000:function:catalog-fieldresolvers"
    aws_request_id = "req-1"


def appsync_event(
    field_name: str, source: dict[str, Any], arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    """An AppSync direct Lambda resolver payload for a field on ``Product``."""
    return {
        "arguments": arguments or {},
        "identity": None,
        "source": source,
        "request": {
            "headers": {"x-api-key": "da2-fakekey", "content-type": "application/json"},
            "domainName": None,
        },
        "info": {
            "fieldName": field_name,
            "parentTypeName": "Product",
            "variables": {},
            "selectionSetList": [],
            "selectionSetGraphQL": "",
        },
        "prev": None,
        "stash": {},
    }


def invoke(event: dict[str, Any]) -> Any:
    return field_resolvers.handler(event, FakeContext())  # type: ignore[arg-type]


@pytest.mark.usefixtures("aws")
@pytest.mark.parametrize(("currency", "expected"), [("USD", 12.7), ("EUR", 11.7), ("GBP", 10.0)])
def test_price_in(currency: str, expected: float) -> None:
    event = appsync_event("priceIn", product_item(), {"currency": currency})
    assert invoke(event) == expected


@pytest.mark.usefixtures("aws")
def test_price_in_from_non_gbp_product() -> None:
    event = appsync_event("priceIn", product_item(price=12.7, currency="USD"), {"currency": "EUR"})
    assert invoke(event) == 11.7


@pytest.mark.usefixtures("aws")
def test_price_in_unknown_currency_is_an_error() -> None:
    event = appsync_event("priceIn", product_item(), {"currency": "JPY"})
    with pytest.raises(fx.UnknownCurrencyError):
        invoke(event)


@pytest.mark.usefixtures("aws")
def test_price_in_fails_when_fx_key_is_blank() -> None:
    client("secretsmanager").put_secret_value(SecretId=SECRET, SecretString="  ")
    event = appsync_event("priceIn", product_item(), {"currency": "USD"})
    with pytest.raises(RuntimeError, match="empty"):
        invoke(event)


@pytest.mark.usefixtures("aws")
def test_image_upload_url_is_a_presigned_put_for_the_sku_key() -> None:
    url = invoke(appsync_event("imageUploadUrl", product_item(sku="MUG-002")))

    parsed = urlparse(url)
    assert BUCKET in url
    assert parsed.path.endswith("products/MUG-002.jpg")
    assert "X-Amz-Signature" in parsed.query
    assert "X-Amz-Expires=900" in parsed.query


@pytest.mark.usefixtures("aws")
def test_presigned_url_target_is_writable_key() -> None:
    """The URL is signed for PUT only: a GET on the same URL would be a signature mismatch."""
    url = invoke(appsync_event("imageUploadUrl", product_item()))
    assert "X-Amz-SignedHeaders=host" in url
