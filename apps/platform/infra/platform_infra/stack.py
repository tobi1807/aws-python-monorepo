"""Shared foundations: the event bus, feature flags (AppConfig) and baseline config.

Every other app finds these by naming convention (``cdk_constructs.wiring``) or
through the SSM parameters exported here, never through CloudFormation imports.
"""

from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_appconfig as appconfig
from aws_cdk import aws_events as events
from aws_cdk import aws_logs as logs
from constructs import Construct

from cdk_constructs.params import export_param
from cdk_constructs.stage import StageContext
from cdk_constructs.wiring import flags_env, shared_bus_name

FEATURES_FILE = Path(__file__).parent / "flags" / "features.json"


class PlatformStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, ctx: StageContext, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        bus = self._event_bus(ctx)
        flags_application = self._feature_flags(ctx)

        export_param(self, ctx, "event-bus-name", bus.event_bus_name)
        export_param(self, ctx, "event-bus-arn", bus.event_bus_arn)
        export_param(self, ctx, "flags-application", flags_application)

        cdk.CfnOutput(self, "EventBusName", value=bus.event_bus_name)

    def _event_bus(self, ctx: StageContext) -> events.EventBus:
        bus = events.EventBus(self, "Bus", event_bus_name=shared_bus_name(ctx))

        # Debugging aid: every shop.* event lands in a log group.
        log_group = logs.LogGroup(
            self,
            "EventLog",
            log_group_name=f"/shop/{ctx.stage}/events",
            retention=logs.RetentionDays.ONE_WEEK
            if ctx.is_ephemeral
            else logs.RetentionDays.ONE_MONTH,
            removal_policy=ctx.removal_policy,
        )
        # L1 on purpose: the L2 log-group target synthesizes a custom-resource Lambda to
        # manage the resource policy, which is heavy and fragile on Floci.
        policy = logs.CfnResourcePolicy(
            self,
            "EventLogPolicy",
            policy_name=ctx.name("events-to-logs"),
            policy_document=self.to_json_string(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {
                                "Service": ["events.amazonaws.com", "delivery.logs.amazonaws.com"]
                            },
                            "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                            "Resource": f"{log_group.log_group_arn}:*",
                        }
                    ],
                }
            ),
        )
        rule = events.CfnRule(
            self,
            "CatchAll",
            name=ctx.name("catch-all"),
            event_bus_name=bus.event_bus_name,
            event_pattern={"source": [{"prefix": "shop."}]},
            targets=[events.CfnRule.TargetProperty(id="log-group", arn=log_group.log_group_arn)],
        )
        rule.add_dependency(policy)
        return bus

    def _feature_flags(self, ctx: StageContext) -> str:
        """AppConfig hosted freeform profile, in the Powertools Feature Flags schema.

        Names must match ``cdk_constructs.wiring.flags_env`` (the contract with
        every consumer of ``runtime.flags``).
        """
        names = flags_env(ctx)

        application = appconfig.CfnApplication(self, "FlagsApp", name=names["FLAGS_APPLICATION"])
        environment = appconfig.CfnEnvironment(
            self,
            "FlagsEnv",
            application_id=application.ref,
            name=names["FLAGS_ENVIRONMENT"],
        )
        profile = appconfig.CfnConfigurationProfile(
            self,
            "FlagsProfile",
            application_id=application.ref,
            name=names["FLAGS_PROFILE"],
            location_uri="hosted",
            type="AWS.Freeform",
        )
        version = appconfig.CfnHostedConfigurationVersion(
            self,
            "FlagsVersion",
            application_id=application.ref,
            configuration_profile_id=profile.ref,
            content=FEATURES_FILE.read_text(),
            content_type="application/json",
        )
        strategy = appconfig.CfnDeploymentStrategy(
            self,
            "AllAtOnce",
            name=ctx.name("all-at-once"),
            deployment_duration_in_minutes=0,
            growth_factor=100,
            final_bake_time_in_minutes=0,
            replicate_to="NONE",
        )
        appconfig.CfnDeployment(
            self,
            "FlagsDeployment",
            application_id=application.ref,
            environment_id=environment.ref,
            configuration_profile_id=profile.ref,
            configuration_version=version.ref,
            deployment_strategy_id=strategy.ref,
        )
        return names["FLAGS_APPLICATION"]
