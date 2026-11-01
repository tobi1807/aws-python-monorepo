"""Infra unit tests: synthesize with stubbed assets and assert on the template."""

from __future__ import annotations

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from cdk_constructs.stage import StageContext
from notifications_infra.stack import NotificationsStack


def synth(stage: str, target: str = "floci") -> Template:
    app = cdk.App(context={"stage": stage, "target": target})
    ctx = StageContext.of(app, "notifications")
    stack = NotificationsStack(app, f"{stage}-notifications", ctx=ctx)
    return Template.from_stack(stack)


@pytest.fixture(autouse=True)
def stub_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CDK_STUB_ASSETS", "1")


def test_outbox_bucket_named_by_stage() -> None:
    synth("pr-42").has_resource_properties(
        "AWS::S3::Bucket", {"BucketName": "pr-42-notifications-outbox"}
    )


def test_queue_redrives_to_dlq_after_three_receives() -> None:
    template = synth("prod")
    template.has_resource_properties(
        "AWS::SQS::Queue",
        {
            "QueueName": "prod-notifications-events",
            "RedrivePolicy": {
                "maxReceiveCount": 3,
                "deadLetterTargetArn": Match.any_value(),
            },
        },
    )
    template.has_resource_properties(
        "AWS::SQS::Queue", {"QueueName": "prod-notifications-events-dlq"}
    )


def test_rule_on_shared_bus_matches_fulfilment_events() -> None:
    synth("pr-7").has_resource_properties(
        "AWS::Events::Rule",
        {
            "EventBusName": "pr-7-shop-bus",
            "EventPattern": {
                "source": ["shop.fulfilment"],
                "detail-type": ["OrderFulfilled", "OrderFulfilmentFailed"],
            },
            "Targets": Match.array_with([Match.object_like({"Arn": Match.any_value()})]),
        },
    )


def test_notify_function_wired_to_outbox_and_queue() -> None:
    template = synth("prod")
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": "prod-notifications-notify",
            "Runtime": "python3.13",
            "Environment": {
                "Variables": Match.object_like(
                    {"STAGE": "prod", "OUTBOX_BUCKET": Match.any_value()}
                )
            },
        },
    )
    template.has_resource_properties(
        "AWS::Lambda::EventSourceMapping",
        {"FunctionResponseTypes": ["ReportBatchItemFailures"], "BatchSize": 10},
    )


def test_can_read_invoices_by_naming_convention() -> None:
    synth("prod").has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": "s3:GetObject",
                                "Resource": "arn:aws:s3:::prod-invoicing-invoices/*",
                            }
                        )
                    ]
                )
            }
        },
    )


def test_can_read_runtime_config() -> None:
    synth("prod").has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with([Match.object_like({"Action": "ssm:GetParameter"})])
            }
        },
    )


def test_publishes_config_to_ssm() -> None:
    template = synth("prod")
    template.has_resource_properties(
        "AWS::SSM::Parameter", {"Name": "/prod/notifications/outbox-bucket"}
    )
    template.has_resource_properties(
        "AWS::SSM::Parameter", {"Name": "/prod/notifications/queue-url"}
    )
