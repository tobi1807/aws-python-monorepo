"""The shipped flag config is valid and behaves as documented."""

from __future__ import annotations

import json
from typing import Any

import pytest
from aws_lambda_powertools.utilities.feature_flags import FeatureFlags
from aws_lambda_powertools.utilities.feature_flags.base import StoreProvider
from aws_lambda_powertools.utilities.feature_flags.schema import SchemaValidator

from platform_infra.stack import FEATURES_FILE


class StubStore(StoreProvider):
    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    def get_configuration(self) -> dict[str, Any]:
        return self._config

    @property
    def get_raw_configuration(self) -> dict[str, Any]:
        return self._config


@pytest.fixture(scope="module")
def config() -> dict[str, Any]:
    return json.loads(FEATURES_FILE.read_text())


@pytest.fixture
def flags(config: dict[str, Any]) -> FeatureFlags:
    return FeatureFlags(store=StubStore(config))


def test_features_json_matches_powertools_schema(config: dict[str, Any]) -> None:
    SchemaValidator(schema=config).validate()


def test_express_checkout_enabled_for_example_com(flags: FeatureFlags) -> None:
    assert flags.evaluate(
        name="express_checkout", context={"customer_email": "ada@example.com"}, default=False
    )


def test_express_checkout_off_for_other_customers(flags: FeatureFlags) -> None:
    assert not flags.evaluate(
        name="express_checkout", context={"customer_email": "ada@elsewhere.org"}, default=False
    )


def test_express_checkout_off_without_context(flags: FeatureFlags) -> None:
    assert not flags.evaluate(name="express_checkout", context={}, default=False)


def test_invoice_html_defaults_on(flags: FeatureFlags) -> None:
    assert flags.evaluate(name="invoice_html", context={}, default=False)
