"""Publish domain events to the shared EventBridge bus."""

from __future__ import annotations

from contracts.base import DomainEvent
from runtime.aws import client
from runtime.config import get_config


class PublishFailed(RuntimeError):
    pass


def bus_name() -> str:
    """The shared bus is owned by the platform app and resolved at runtime."""
    return get_config("platform", "event-bus-name")


def publish(event: DomainEvent, *, bus: str | None = None) -> str:
    response = client("events").put_events(
        Entries=[
            {
                "EventBusName": bus or bus_name(),
                "Source": event.SOURCE,
                "DetailType": event.DETAIL_TYPE,
                "Detail": event.to_detail(),
            }
        ]
    )
    if response.get("FailedEntryCount", 0):
        raise PublishFailed(str(response["Entries"]))
    return response["Entries"][0]["EventId"]
