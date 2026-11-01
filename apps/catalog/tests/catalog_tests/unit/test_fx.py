from __future__ import annotations

from decimal import Decimal

import pytest

from catalog import fx


@pytest.mark.parametrize(
    ("amount", "source", "target", "expected"),
    [
        ("10.00", "GBP", "USD", "12.70"),
        ("10.00", "GBP", "EUR", "11.70"),
        ("10.00", "GBP", "GBP", "10.00"),
        ("12.70", "USD", "GBP", "10.00"),
        ("12.70", "USD", "EUR", "11.70"),
        ("10.00", "gbp", "usd", "12.70"),
        ("0", "GBP", "USD", "0.00"),
    ],
)
def test_convert(amount: str, source: str, target: str, expected: str) -> None:
    assert fx.convert(Decimal(amount), source, target) == Decimal(expected)


def test_identity_rounds_to_pennies() -> None:
    assert fx.convert(Decimal("1.005"), "EUR", "EUR") == Decimal("1.01")


@pytest.mark.parametrize(("source", "target"), [("GBP", "JPY"), ("JPY", "GBP")])
def test_unknown_currency_raises(source: str, target: str) -> None:
    with pytest.raises(fx.UnknownCurrencyError, match="JPY"):
        fx.convert(Decimal("1"), source, target)
