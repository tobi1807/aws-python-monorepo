"""Wire an app's compute to platform-owned resources by naming convention.

These helpers avoid deploy-time imports: names follow conventions the platform
app guarantees, so consuming apps don't need the platform stack's outputs.
"""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import aws_iam as iam

from cdk_constructs.stage import StageContext


def flags_env(ctx: StageContext) -> dict[str, str]:
    """Names follow the platform app's convention, so no deploy-time lookup is needed."""
    return {
        "FLAGS_APPLICATION": f"{ctx.stage}-shop",
        "FLAGS_ENVIRONMENT": ctx.stage,
        "FLAGS_PROFILE": "features",
    }


def grant_flags_read(grantee: iam.IGrantable) -> None:
    grantee.grant_principal.add_to_principal_policy(
        iam.PolicyStatement(
            actions=["appconfig:StartConfigurationSession", "appconfig:GetLatestConfiguration"],
            resources=["*"],
        )
    )


def grant_config_read(grantee: iam.IGrantable, ctx: StageContext) -> None:
    """Let runtime code read any app's published SSM config (and the baseline fallback)."""
    prefix = f"arn:aws:ssm:{cdk.Aws.REGION}:{cdk.Aws.ACCOUNT_ID}:parameter"
    grantee.grant_principal.add_to_principal_policy(
        iam.PolicyStatement(
            actions=["ssm:GetParameter"],
            resources=[f"{prefix}/{ctx.stage}/*", f"{prefix}/baseline/*"],
        )
    )


def grant_put_events(grantee: iam.IGrantable, ctx: StageContext) -> None:
    """Publish to the shared bus. ARN built from the naming convention (no deploy-time import)."""
    grantee.grant_principal.add_to_principal_policy(
        iam.PolicyStatement(
            actions=["events:PutEvents"],
            resources=[
                f"arn:aws:events:{cdk.Aws.REGION}:{cdk.Aws.ACCOUNT_ID}:event-bus/{ctx.stage}-shop-bus",
                f"arn:aws:events:{cdk.Aws.REGION}:{cdk.Aws.ACCOUNT_ID}:event-bus/baseline-shop-bus",
            ],
        )
    )


def shared_bus_name(ctx: StageContext) -> str:
    """Bus name convention owned by the platform app."""
    return f"{ctx.stage}-shop-bus"
