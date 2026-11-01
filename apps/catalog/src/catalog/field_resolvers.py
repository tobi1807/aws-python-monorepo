"""Lambda resolver for the Product fields that need more than a DynamoDB lookup.

Wired as an AppSync *direct* Lambda resolver (no VTL): AppSync passes the parent
``Product`` as ``source`` and the field arguments as ``arguments``.
"""

from __future__ import annotations

import os
from typing import Any

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import AppSyncResolver
from aws_lambda_powertools.utilities.typing import LambdaContext

from catalog import fx
from contracts.catalog import Product
from runtime import secrets
from runtime.aws import client

logger = Logger()
app = AppSyncResolver()

UPLOAD_URL_TTL_SECONDS = 900


def _source_product() -> Product:
    event = app.current_event
    assert event is not None, "called outside an AppSync request"
    return Product.model_validate(event.source or {})


def _require_fx_api_key() -> None:
    """The FX provider key lives in Secrets Manager; fail loudly if it is missing/empty."""
    key = secrets.get_secret(os.environ["FX_API_KEY_SECRET"])
    if not key.strip():
        raise RuntimeError("FX API key secret is empty")


@app.resolver(type_name="Product", field_name="priceIn")
def price_in(currency: str) -> float:
    product = _source_product()
    _require_fx_api_key()
    return float(fx.convert(product.price, product.currency, currency))


@app.resolver(type_name="Product", field_name="imageUploadUrl")
def image_upload_url() -> str:
    product = _source_product()
    return client("s3").generate_presigned_url(
        "put_object",
        Params={"Bucket": os.environ["IMAGES_BUCKET"], "Key": f"products/{product.sku}.jpg"},
        ExpiresIn=UPLOAD_URL_TTL_SECONDS,
    )


@logger.inject_lambda_context
def handler(event: dict[str, Any], context: LambdaContext) -> Any:
    return app.resolve(event, context)
