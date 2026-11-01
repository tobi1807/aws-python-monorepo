"""HTTP API (API Gateway HTTP API -> one Lambda, Powertools router)."""

from __future__ import annotations

from typing import Any

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver, Response, content_types
from aws_lambda_powertools.event_handler.exceptions import BadRequestError, NotFoundError
from aws_lambda_powertools.utilities.typing import LambdaContext
from pydantic import ValidationError

from orders import repository, service
from orders.models import PlaceOrderRequest

logger = Logger()
app = APIGatewayHttpResolver()


@app.post("/orders")
def place_order() -> Response:
    try:
        request = PlaceOrderRequest.model_validate(app.current_event.json_body or {})
    except ValidationError as exc:
        raise BadRequestError(exc.json(include_url=False)) from exc

    try:
        order = service.place_order(request)
    except service.ExpressCheckoutUnavailable as exc:
        raise BadRequestError("Express checkout is not available") from exc

    logger.info("order placed", extra={"order_id": order.order_id, "total": str(order.total)})
    return Response(
        status_code=201,
        content_type=content_types.APPLICATION_JSON,
        body=order.model_dump_json(),
    )


@app.get("/orders/<order_id>")
def get_order(order_id: str) -> dict[str, Any]:
    item = repository.get(order_id)
    if item is None:
        raise NotFoundError(f"Order {order_id} not found")
    return item


@logger.inject_lambda_context
def handler(event: dict[str, Any], context: LambdaContext) -> dict[str, Any]:
    return app.resolve(event, context)
