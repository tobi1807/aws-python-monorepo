"""Entry-point helpers: one CDK app per microservice, one stack per stage."""

from __future__ import annotations

import os

import aws_cdk as cdk

from cdk_constructs.stage import StageContext


def create_app(app_name: str) -> tuple[cdk.App, StageContext]:
    cdk_app = cdk.App()
    ctx = StageContext.of(cdk_app, app_name)
    cdk.Tags.of(cdk_app).add("app", app_name)
    cdk.Tags.of(cdk_app).add("stage", ctx.stage)
    return cdk_app, ctx


def stack_name(ctx: StageContext) -> str:
    return f"{ctx.stage}-{ctx.app}"


def default_env() -> cdk.Environment:
    return cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT", "000000000000"),
        region=os.environ.get("CDK_DEFAULT_REGION", "eu-west-2"),
    )
