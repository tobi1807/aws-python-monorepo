from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda_event_sources as event_sources
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sqs as sqs
from constructs import Construct

from cdk_constructs.params import export_param
from cdk_constructs.service_function import ServiceFunction
from cdk_constructs.stage import StageContext
from cdk_constructs.wiring import grant_config_read, shared_bus_name

SRC = "apps/notifications/src/notifications"
FULFILMENT_EVENTS = ["OrderFulfilled", "OrderFulfilmentFailed"]


class NotificationsStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, ctx: StageContext, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Stand-in for SES: "sent" messages are written here as JSON.
        outbox = s3.Bucket(
            self,
            "Outbox",
            bucket_name=ctx.name("outbox"),
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=ctx.removal_policy,
        )

        dlq = sqs.Queue(
            self,
            "Dlq",
            queue_name=ctx.name("events-dlq"),
            retention_period=cdk.Duration.days(14),
        )
        queue = sqs.Queue(
            self,
            "Queue",
            queue_name=ctx.name("events"),
            visibility_timeout=cdk.Duration.seconds(90),
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=dlq),
        )

        bus = events.EventBus.from_event_bus_name(self, "Bus", shared_bus_name(ctx))
        events.Rule(
            self,
            "FulfilmentEvents",
            rule_name=ctx.name("fulfilment-events"),
            event_bus=bus,
            event_pattern=events.EventPattern(
                source=["shop.fulfilment"], detail_type=FULFILMENT_EVENTS
            ),
            targets=[targets.SqsQueue(queue)],  # pyright: ignore[reportArgumentType]  (jsii protocol)
        )

        notify = ServiceFunction(
            self,
            "Notify",
            ctx=ctx,
            target_dir=SRC,
            target_name="notify",
            environment={"OUTBOX_BUCKET": outbox.bucket_name},
            timeout=cdk.Duration.seconds(30),
        )
        outbox.grant_put(notify.function)
        grant_config_read(notify.function, ctx)
        # The invoicing app's bucket is found at runtime; its name follows the
        # convention {stage}-invoicing-invoices, which is enough to presign GETs.
        notify.function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[f"arn:aws:s3:::{ctx.stage}-invoicing-invoices/*"],
            )
        )
        notify.function.add_event_source(
            event_sources.SqsEventSource(queue, batch_size=10, report_batch_item_failures=True)
        )

        export_param(self, ctx, "outbox-bucket", outbox.bucket_name)
        export_param(self, ctx, "queue-url", queue.queue_url)

        cdk.CfnOutput(self, "OutboxBucket", value=outbox.bucket_name)
