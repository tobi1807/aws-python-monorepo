"""Infra unit tests: synthesize with stubbed assets and assert on the template."""

from __future__ import annotations

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from cdk_constructs.stage import StageContext
from orders_infra.stack import OrdersStack


def synth(stage: str, target: str = "floci") -> Template:
    app = cdk.App(context={"stage": stage, "target": target})
    ctx = StageContext.of(app, "orders")
    stack = OrdersStack(app, f"{stage}-orders", ctx=ctx)
    return Template.from_stack(stack)


@pytest.fixture(autouse=True)
def stub_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CDK_STUB_ASSETS", "1")


def test_table_named_by_stage() -> None:
    synth("pr-42").has_resource_properties(
        "AWS::DynamoDB::GlobalTable", {"TableName": "pr-42-orders-orders"}
    )


def test_function_points_at_floci_and_has_flags() -> None:
    synth("prod").has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Runtime": "python3.13",
            "Environment": {
                "Variables": Match.object_like(
                    {
                        "STAGE": "prod",
                        "AWS_ENDPOINT_URL": Match.any_value(),
                        "FLAGS_APPLICATION": "prod-shop",
                    }
                )
            },
        },
    )


def test_publishes_config_to_ssm() -> None:
    template = synth("prod")
    template.has_resource_properties("AWS::SSM::Parameter", {"Name": "/prod/orders/api-url"})
    template.has_resource_properties("AWS::SSM::Parameter", {"Name": "/prod/orders/table-name"})


def test_canary_only_in_real_aws_prod() -> None:
    synth("prod", target="floci").resource_count_is("AWS::CodeDeploy::DeploymentGroup", 0)
    synth("prod", target="aws").resource_count_is("AWS::CodeDeploy::DeploymentGroup", 1)
    synth("pr-1", target="aws").resource_count_is("AWS::CodeDeploy::DeploymentGroup", 0)
