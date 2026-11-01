from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from constructs import Construct

from cdk_constructs.assets import container_context, stubbed
from cdk_constructs.params import export_param
from cdk_constructs.stage import StageContext

# Staged by the deploy tool: Dockerfile + the packaged render.pex.
CONTAINER_BUILD_DIR = "dist/docker/invoicing"
STUB_IMAGE = "public.ecr.aws/docker/library/python:3.13-slim"
CONTAINER_NAME = "render"


class InvoicingStack(cdk.Stack):
    @property
    def availability_zones(self) -> list[str]:
        """Fixed AZ list: avoids a synth-time AWS lookup, so synth stays offline
        and deterministic (there's no AWS account; Floci plays every stage)."""
        return [f"{self.region}a"]

    def __init__(self, scope: Construct, construct_id: str, *, ctx: StageContext, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        bucket = s3.Bucket(
            self,
            "Invoices",
            bucket_name=ctx.name("invoices"),
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=ctx.removal_policy,
            # Ephemeral stages on real AWS must be deletable while non-empty.
            auto_delete_objects=ctx.is_ephemeral and not ctx.on_floci,
        )

        # Tasks only need to reach S3 and pull their image: one public subnet,
        # public IPs, no NAT gateway (the expensive part of a default VPC).
        vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=1,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24
                )
            ],
        )
        security_group = ec2.SecurityGroup(
            self,
            "TaskSecurityGroup",
            vpc=vpc,
            description=f"{ctx.name('render')} task: outbound only",
            allow_all_outbound=True,
        )

        cluster = ecs.Cluster(self, "Cluster", cluster_name=ctx.name("cluster"), vpc=vpc)

        task_definition = ecs.FargateTaskDefinition(
            self,
            "RenderTask",
            family=ctx.name("render"),
            cpu=256,
            memory_limit_mib=512,
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.ARM64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
        )

        if stubbed():
            image = ecs.ContainerImage.from_registry(STUB_IMAGE)
        else:
            image = ecs.ContainerImage.from_asset(
                str(container_context(CONTAINER_BUILD_DIR)),
                platform=ecr_assets.Platform.LINUX_ARM64,
            )

        log_group = logs.LogGroup(
            self,
            "Logs",
            log_group_name=f"/ecs/{ctx.name('render')}",
            retention=logs.RetentionDays.ONE_WEEK
            if ctx.is_ephemeral
            else logs.RetentionDays.ONE_MONTH,
            removal_policy=ctx.removal_policy,
        )

        task_definition.add_container(
            CONTAINER_NAME,
            container_name=CONTAINER_NAME,
            image=image,
            environment={**ctx.runtime_env(), "INVOICE_BUCKET": bucket.bucket_name},
            logging=ecs.LogDrivers.aws_logs(stream_prefix="render", log_group=log_group),
        )
        bucket.grant_write(task_definition.task_role)

        export_param(self, ctx, "bucket-name", bucket.bucket_name)
        export_param(self, ctx, "cluster-arn", cluster.cluster_arn)
        export_param(self, ctx, "task-definition-arn", task_definition.task_definition_arn)
        export_param(
            self,
            ctx,
            "subnet-ids",
            cdk.Fn.join(",", [subnet.subnet_id for subnet in vpc.public_subnets]),
        )
        export_param(self, ctx, "security-group-id", security_group.security_group_id)
        export_param(self, ctx, "container-name", CONTAINER_NAME)

        cdk.CfnOutput(self, "BucketName", value=bucket.bucket_name)
