"""Infra unit tests: synthesize and assert on the template."""

from __future__ import annotations

import json

import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from cdk_constructs.stage import StageContext
from cdk_constructs.wiring import flags_env, shared_bus_name
from platform_infra.stack import FEATURES_FILE, PlatformStack


def synth(stage: str, target: str = "floci") -> tuple[Template, StageContext]:
    app = cdk.App(context={"stage": stage, "target": target})
    ctx = StageContext.of(app, "platform")
    stack = PlatformStack(app, f"{stage}-platform", ctx=ctx)
    return Template.from_stack(stack), ctx


def test_bus_named_by_stage() -> None:
    template, ctx = synth("pr-42")
    template.has_resource_properties("AWS::Events::EventBus", {"Name": "pr-42-shop-bus"})
    assert shared_bus_name(ctx) == "pr-42-shop-bus"


def test_catch_all_rule_logs_every_shop_event() -> None:
    template, _ = synth("dev-ada")
    template.has_resource_properties(
        "AWS::Events::Rule",
        {
            "EventPattern": {"source": [{"prefix": "shop."}]},
            "Targets": Match.array_with([Match.object_like({"Arn": Match.any_value()})]),
        },
    )
    template.has_resource_properties(
        "AWS::Logs::LogGroup", {"LogGroupName": "/shop/dev-ada/events", "RetentionInDays": 7}
    )


def test_log_retention_longer_outside_ephemeral_stages() -> None:
    template, _ = synth("prod")
    template.has_resource_properties(
        "AWS::Logs::LogGroup", {"LogGroupName": "/shop/prod/events", "RetentionInDays": 30}
    )


def test_appconfig_names_match_flags_env() -> None:
    template, ctx = synth("pr-7")
    names = flags_env(ctx)
    template.has_resource_properties(
        "AWS::AppConfig::Application", {"Name": names["FLAGS_APPLICATION"]}
    )
    template.has_resource_properties(
        "AWS::AppConfig::Environment", {"Name": names["FLAGS_ENVIRONMENT"]}
    )
    template.has_resource_properties(
        "AWS::AppConfig::ConfigurationProfile",
        {"Name": names["FLAGS_PROFILE"], "LocationUri": "hosted", "Type": "AWS.Freeform"},
    )


def test_hosted_configuration_is_the_shipped_features_file() -> None:
    template, _ = synth("prod")
    versions = template.find_resources("AWS::AppConfig::HostedConfigurationVersion")
    assert len(versions) == 1
    props = next(iter(versions.values()))["Properties"]
    assert props["ContentType"] == "application/json"
    assert json.loads(props["Content"]) == json.loads(FEATURES_FILE.read_text())


def test_deploys_all_at_once() -> None:
    template, _ = synth("prod")
    template.has_resource_properties(
        "AWS::AppConfig::DeploymentStrategy",
        {"DeploymentDurationInMinutes": 0, "GrowthFactor": 100, "FinalBakeTimeInMinutes": 0},
    )
    template.resource_count_is("AWS::AppConfig::Deployment", 1)


def test_exports_to_ssm() -> None:
    template, _ = synth("prod")
    for key in ("event-bus-name", "event-bus-arn", "flags-application"):
        template.has_resource_properties("AWS::SSM::Parameter", {"Name": f"/prod/platform/{key}"})
    template.has_resource_properties(
        "AWS::SSM::Parameter", {"Name": "/prod/platform/flags-application", "Value": "prod-shop"}
    )


def test_no_custom_resources() -> None:
    """Custom-resource Lambdas are heavy on Floci; the log policy is plain L1."""
    template, _ = synth("prod")
    assert not template.find_resources("AWS::Lambda::Function")
    template.has_resource_properties(
        "AWS::Logs::ResourcePolicy", {"PolicyName": "prod-platform-events-to-logs"}
    )
