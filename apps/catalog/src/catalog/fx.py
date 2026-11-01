"""Currency conversion with a small in-code rate table.

Rates are expressed against GBP (the catalog's base currency). A real
implementation would call the FX provider with the API key from Secrets Manager;
here the key is only checked for presence (see ``field_resolvers``).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

# Units of each currency per 1 GBP.
RATES_PER_GBP: dict[str, Decimal] = {
    "GBP": Decimal("1"),
    "USD": Decimal("1.27"),
    "EUR": Decimal("1.17"),
}

_CENT = Decimal("0.01")


class UnknownCurrencyError(ValueError):
    """Raised for a currency we have no rate for; surfaces as a GraphQL error."""

    def __init__(self, currency: str) -> None:
        super().__init__(
            f"Unsupported currency: {currency!r}. Supported: {', '.join(sorted(RATES_PER_GBP))}"
        )
        self.currency = currency


def _rate(currency: str) -> Decimal:
    try:
        return RATES_PER_GBP[currency.upper()]
    except KeyError:
        raise UnknownCurrencyError(currency) from None


def convert(amount: Decimal, from_currency: str, to_currency: str) -> Decimal:
    """Convert ``amount`` between supported currencies, rounded to 2 decimal places."""
    source, target = _rate(from_currency), _rate(to_currency)
    if from_currency.upper() == to_currency.upper():
        return amount.quantize(_CENT, rounding=ROUND_HALF_UP)
    return (amount / source * target).quantize(_CENT, rounding=ROUND_HALF_UP)
