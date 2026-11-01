from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from moto import mock_aws

from contracts.orders import OrderLine, OrderPlaced
from runtime import config, events, flags, secrets
from runtime.aws import client
from testkit.aws import fake_credentials, reset_runtime_caches


@pytest.fixture(autouse=True)
def aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    fake_credentials(monkeypatch, stage="pr-7")
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    reset_runtime_caches()
    with mock_aws():
        yield
    reset_runtime_caches()


def put(name: str, value: str) -> None:
    client("ssm").put_parameter(Name=name, Value=value, Type="String", Overwrite=True)


def test_get_config_prefers_stage_value() -> None:
    put("/pr-7/orders/api-url", "https://pr")
    put("/baseline/orders/api-url", "https://baseline")
    assert config.get_config("orders", "api-url") == "https://pr"


def test_get_config_falls_back_to_baseline() -> None:
    put("/baseline/orders/api-url", "https://baseline")
    assert config.get_config("orders", "api-url") == "https://baseline"


def test_get_config_missing_raises() -> None:
    with pytest.raises(config.ConfigNotFound):
        config.get_config("orders", "nope")


def test_get_config_is_cached() -> None:
    put("/pr-7/orders/api-url", "first")
    assert config.get_config("orders", "api-url") == "first"
    put("/pr-7/orders/api-url", "second")
    assert config.get_config("orders", "api-url") == "first"


def test_get_secret_json() -> None:
    client("secretsmanager").create_secret(Name="s", SecretString=json.dumps({"k": "v"}))
    assert secrets.get_secret_json("s") == {"k": "v"}


def test_publish_puts_event_on_bus_from_config() -> None:
    client("events").create_event_bus(Name="pr-7-shop-bus")
    put("/pr-7/platform/event-bus-name", "pr-7-shop-bus")
    event = OrderPlaced(
        order_id="ord-1",
        customer_email="ada@example.com",
        lines=[OrderLine(sku="A", quantity=1, unit_price=Decimal("1.00"))],
        total=Decimal("1.00"),
        placed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert events.publish(event)


def test_flags_default_without_appconfig() -> None:
    assert flags.is_enabled("anything") is False
    assert flags.is_enabled("anything", default=True) is True
