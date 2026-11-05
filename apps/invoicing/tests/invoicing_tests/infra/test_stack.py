"""Infra unit tests: synthesize with stubbed assets and assert on the template."""

from __future__ import annotations

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from cdk_constructs.stage import StageContext
from invoicing_infra.stack import STUB_IMAGE, InvoicingStack


def synth(stage: str, target: str = "floci") -> Template:
    app = cdk.App(context={"stage": stage, "target": target})
    ctx = StageContext.of(app, "invoicing")
    stack = InvoicingStack(app, f"{stage}-invoicing", ctx=ctx)
    return Template.from_stack(stack)


@pytest.fixture(autouse=True)
def stub_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CDK_STUB_ASSETS", "1")


def test_bucket_and_cluster_named_by_stage() -> None:
    template = synth("pr-42")
    template.has_resource_properties("AWS::S3::Bucket", {"BucketName": "pr-42-invoicing-invoices"})
    template.has_resource_properties(
        "AWS::ECS::Cluster", {"ClusterName": "pr-42-invoicing-cluster"}
    )


def test_task_definition_is_small_arm_fargate() -> None:
    synth("prod").has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {
            "Family": "prod-invoicing-render",
            "Cpu": "256",
            "Memory": "512",
            "RequiresCompatibilities": ["FARGATE"],
            "NetworkMode": "awsvpc",
            "RuntimePlatform": {"CpuArchitecture": "X86_64", "OperatingSystemFamily": "LINUX"},
        },
    )


def test_container_uses_stub_image_and_gets_runtime_env() -> None:
    synth("prod").has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {
            "ContainerDefinitions": [
                Match.object_like(
                    {
                        "Name": "render",
                        "Image": STUB_IMAGE,
                        "Environment": Match.array_with(
                            [
                                {"Name": "STAGE", "Value": "prod"},
                                {"Name": "AWS_ENDPOINT_URL", "Value": Match.any_value()},
                                {"Name": "INVOICE_BUCKET", "Value": Match.any_value()},
                            ]
                        ),
                    }
                )
            ]
        },
    )


def test_task_role_can_write_to_the_bucket() -> None:
    synth("prod").has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {"Action": Match.array_with(["s3:PutObject"]), "Effect": "Allow"}
                        )
                    ]
                )
            }
        },
    )


def test_vpc_has_no_nat_gateway_and_one_public_subnet() -> None:
    template = synth("prod")
    template.resource_count_is("AWS::EC2::NatGateway", 0)
    template.resource_count_is("AWS::EC2::Subnet", 1)
    template.has_resource_properties("AWS::EC2::Subnet", {"MapPublicIpOnLaunch": True})


def test_logs_retention_depends_on_stage() -> None:
    synth("pr-1").has_resource_properties(
        "AWS::Logs::LogGroup",
        {"LogGroupName": "/ecs/pr-1-invoicing-render", "RetentionInDays": 7},
    )
    synth("prod").has_resource_properties(
        "AWS::Logs::LogGroup",
        {"LogGroupName": "/ecs/prod-invoicing-render", "RetentionInDays": 30},
    )


@pytest.mark.parametrize(
    "key",
    [
        "bucket-name",
        "cluster-arn",
        "task-definition-arn",
        "subnet-ids",
        "security-group-id",
        "container-name",
    ],
)
def test_publishes_wiring_params(key: str) -> None:
    synth("prod").has_resource_properties("AWS::SSM::Parameter", {"Name": f"/prod/invoicing/{key}"})


def test_container_name_param_matches_container() -> None:
    synth("prod").has_resource_properties(
        "AWS::SSM::Parameter", {"Name": "/prod/invoicing/container-name", "Value": "render"}
    )


def test_ephemeral_aws_stage_empties_bucket_on_delete() -> None:
    synth("pr-7", target="aws").resource_count_is("Custom::S3AutoDeleteObjects", 1)
    synth("pr-7", target="floci").resource_count_is("Custom::S3AutoDeleteObjects", 0)
    synth("prod", target="aws").resource_count_is("Custom::S3AutoDeleteObjects", 0)
