"""Pure message logic: parse fulfilment events and render customer messages.

No I/O here, so it is trivially unit-testable and shared with the Pact
consumer test (which must exercise the real parsing and rendering code).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from contracts.fulfilment import OrderFulfilled, OrderFulfilmentFailed

FulfilmentEvent = OrderFulfilled | OrderFulfilmentFailed

EVENT_MODELS: dict[str, type[OrderFulfilled] | type[OrderFulfilmentFailed]] = {
    model.DETAIL_TYPE: model for model in (OrderFulfilled, OrderFulfilmentFailed)
}


class UnsupportedEvent(ValueError):
    pass


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    body: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def parse_event(detail_type: str, detail: dict[str, Any]) -> FulfilmentEvent:
    """Validate an EventBridge ``detail`` against the producer's contract model."""
    try:
        model = EVENT_MODELS[detail_type]
    except KeyError as exc:
        raise UnsupportedEvent(f"Unsupported detail-type {detail_type!r}") from exc
    return model.model_validate(detail)


def render_fulfilled(event: OrderFulfilled, invoice_url: str) -> Message:
    return Message(
        to=event.customer_email,
        subject=f"Your order {event.order_id} is on its way",
        body=(
            f"Good news! Order {event.order_id} was fulfilled on "
            f"{event.fulfilled_at:%d %B %Y at %H:%M} UTC.\n\n"
            f"Your invoice: {invoice_url}\n"
        ),
    )


def render_failed(event: OrderFulfilmentFailed) -> Message:
    return Message(
        to=event.customer_email,
        subject=f"We couldn't fulfil your order {event.order_id}",
        body=(
            f"Sorry, we were unable to fulfil order {event.order_id} "
            f"(as of {event.failed_at:%d %B %Y at %H:%M} UTC).\n\n"
            f"Reason: {event.reason}\n\n"
            "You have not been charged. Please contact support if you have questions.\n"
        ),
    )


def render(event: FulfilmentEvent, *, invoice_url: str | None = None) -> Message:
    """Render the customer message for an event. ``invoice_url`` is required for OrderFulfilled."""
    if isinstance(event, OrderFulfilled):
        if invoice_url is None:
            raise ValueError("invoice_url is required to render OrderFulfilled")
        return render_fulfilled(event, invoice_url)
    return render_failed(event)


def outbox_key(order_id: str, detail_type: str) -> str:
    return f"outbox/{order_id}/{detail_type}.json"
