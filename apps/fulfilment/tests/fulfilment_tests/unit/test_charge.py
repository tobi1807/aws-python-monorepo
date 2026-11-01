from __future__ import annotations

from decimal import Decimal

import pytest

from fulfilment import charge
from fulfilment_tests.conftest import API_KEY, FakeContext, make_order


def invoke(order_total: str) -> dict[str, str]:
    event = make_order(total=Decimal(order_total)).model_dump(mode="json")
    return charge.handler(event, FakeContext())  # type: ignore[arg-type]


@pytest.mark.usefixtures("aws")
def test_charges_order_using_secret_api_key() -> None:
    result = invoke("15.00")

    assert result["amount"] == "15.00"
    assert result["charge_id"] == charge.charge_order(make_order(), API_KEY)["charge_id"]
    assert result["charge_id"].startswith("ch_")


@pytest.mark.usefixtures("aws")
def test_charge_id_depends_on_the_secret() -> None:
    assert (
        charge.charge_order(make_order(), "key-a")["charge_id"]
        != charge.charge_order(make_order(), "key-b")["charge_id"]
    )


@pytest.mark.usefixtures("aws")
def test_limit_is_inclusive() -> None:
    assert invoke("1000.00")["amount"] == "1000.00"


@pytest.mark.usefixtures("aws")
def test_declines_orders_over_the_limit() -> None:
    with pytest.raises(charge.PaymentDeclined, match="exceeds limit"):
        invoke("1000.01")


@pytest.mark.usefixtures("aws")
def test_missing_secret_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYMENT_SECRET_ID", "nope")

    with pytest.raises(Exception, match="ResourceNotFoundException"):
        invoke("15.00")
