"""The standard Lambda function for every app.

Gives every function the same baseline: Pants-built code, Python 3.13 on ARM,
stage env, structured logging config, a ``live`` alias, an error alarm, and
CodeDeploy canary shifting with automatic rollback in real-AWS prod.
"""

from __future__ import annotations

from collections.abc import Mapping

import aws_cdk as cdk
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_codedeploy as codedeploy
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

from cdk_constructs.assets import lambda_code, lambda_handler
from cdk_constructs.stage import StageContext


class ServiceFunction(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        ctx: StageContext,
        target_dir: str,
        target_name: str,
        environment: Mapping[str, str] | None = None,
        memory_size: int = 512,
        timeout: cdk.Duration | None = None,
        flags: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(scope, construct_id)

        env = {**ctx.runtime_env(), **(environment or {}), **(flags or {})}
        function_name = ctx.name(construct_id.lower())

        log_group = logs.LogGroup(
            self,
            "Logs",
            log_group_name=f"/aws/lambda/{function_name}",
            retention=logs.RetentionDays.ONE_WEEK
            if ctx.is_ephemeral
            else logs.RetentionDays.ONE_MONTH,
            removal_policy=ctx.removal_policy,
        )

        self.function = lambda_.Function(
            self,
            "Fn",
            function_name=function_name,
            runtime=lambda_.Runtime.PYTHON_3_13,
            architecture=lambda_.Architecture.ARM_64,
            code=lambda_code(target_dir, target_name),
            handler=lambda_handler(),
            memory_size=memory_size,
            timeout=timeout or cdk.Duration.seconds(15),
            environment=env,
            logging_format=lambda_.LoggingFormat.JSON,
            log_group=log_group,
        )

        self.alias = lambda_.Alias(
            self, "Live", alias_name="live", version=self.function.current_version
        )

        self.errors_alarm = cloudwatch.Alarm(
            self,
            "Errors",
            metric=self.alias.metric_errors(period=cdk.Duration.minutes(1)),
            threshold=1,
            evaluation_periods=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        if ctx.use_canary:
            codedeploy.LambdaDeploymentGroup(
                self,
                "Deploy",
                alias=self.alias,
                deployment_config=codedeploy.LambdaDeploymentConfig.CANARY_10_PERCENT_5_MINUTES,
                alarms=[self.errors_alarm],
            )

    @property
    def target(self) -> lambda_.IFunction:
        """What callers (API routes, event sources, Step Functions) should invoke."""
        return self.alias
