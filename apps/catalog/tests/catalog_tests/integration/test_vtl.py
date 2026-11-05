"""Evaluate the VTL resolver templates against Floci's AppSync emulation.

A deliberate experiment in testing VTL locally: AppSync's ``EvaluateMappingTemplate``
API renders a template for a sample ``$ctx`` without deploying an API, so the
templates under ``catalog_infra/resolvers`` are tested as they ship.

Run: docker compose up -d floci && FLOCI_ENDPOINT=http://localhost:4566 pants --tag=floci test apps/catalog::

Finding (experiment 4): Floci doesn't implement ``EvaluateMappingTemplate`` yet,
so these tests skip with that reason on Floci. They run as-is against real AWS
or any emulator that adds the API, so keep them: the skip is self-detecting.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from catalog_infra.stack import VTL_RESOLVERS, vtl_template
from runtime.aws import client
from testkit.aws import fake_credentials, floci_endpoint, floci_required

pytestmark = floci_required()


@pytest.fixture
def appsync(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    fake_credentials(monkeypatch)
    with floci_endpoint(monkeypatch):
        appsync_client = client("appsync")
        try:
            appsync_client.evaluate_mapping_template(template="{}", context="{}")
        except appsync_client.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "UnknownOperationException":
                pytest.skip("this endpoint doesn't implement AppSync EvaluateMappingTemplate")
            raise
        yield appsync_client


def render(appsync: Any, basename: str, kind: str, context: dict[str, Any]) -> Any:
    response = appsync.evaluate_mapping_template(
        template=vtl_template(basename, kind).read_text(),
        context=json.dumps(context),
    )
    assert "error" not in response, response.get("error")
    return json.loads(response["evaluationResult"])


def request(appsync: Any, type_name: str, field_name: str, **arguments: Any) -> Any:
    basename = VTL_RESOLVERS[(type_name, field_name)]
    return render(appsync, basename, "req", {"arguments": arguments})


def test_get_product_request(appsync: Any) -> None:
    rendered = request(appsync, "Query", "getProduct", sku="TEA-001")

    assert rendered == {
        "version": "2018-05-29",
        "operation": "GetItem",
        "key": {"sku": {"S": "TEA-001"}},
    }


def test_list_products_request_defaults_limit(appsync: Any) -> None:
    rendered = request(appsync, "Query", "listProducts")

    assert rendered["operation"] == "Scan"
    assert rendered["limit"] == 20
    assert "nextToken" not in rendered


def test_list_products_request_passes_limit_and_next_token(appsync: Any) -> None:
    rendered = request(appsync, "Query", "listProducts", limit=5, nextToken="abc123")

    assert rendered["limit"] == 5
    assert rendered["nextToken"] == "abc123"


def test_list_products_request_caps_limit(appsync: Any) -> None:
    assert request(appsync, "Query", "listProducts", limit=5000)["limit"] == 100


def test_put_product_request_applies_defaults(appsync: Any) -> None:
    rendered = request(
        appsync,
        "Mutation",
        "putProduct",
        input={"sku": "TEA-001", "name": "Earl Grey", "price": 4.5},
    )

    assert rendered["operation"] == "PutItem"
    assert rendered["key"] == {"sku": {"S": "TEA-001"}}
    attributes = rendered["attributeValues"]
    assert attributes["name"] == {"S": "Earl Grey"}
    assert attributes["price"] == {"N": "4.5"}
    assert attributes["currency"] == {"S": "GBP"}
    assert attributes["stock"] == {"N": "0"}


def test_put_product_request_keeps_explicit_values(appsync: Any) -> None:
    rendered = request(
        appsync,
        "Mutation",
        "putProduct",
        input={"sku": "MUG-002", "name": "Mug", "price": 8, "currency": "EUR", "stock": 7},
    )

    attributes = rendered["attributeValues"]
    assert attributes["currency"] == {"S": "EUR"}
    assert attributes["stock"] == {"N": "7"}


def test_list_products_response_shapes_connection(appsync: Any) -> None:
    items = [{"sku": "TEA-001", "name": "Earl Grey", "price": 4.5, "currency": "GBP", "stock": 3}]
    context = {"arguments": {}, "result": {"items": items, "nextToken": "tok"}}

    rendered = render(appsync, VTL_RESOLVERS[("Query", "listProducts")], "res", context)

    assert rendered == {"items": items, "nextToken": "tok"}
