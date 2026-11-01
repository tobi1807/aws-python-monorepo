from __future__ import annotations

import json

import aws_cdk as cdk
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda_event_sources as event_sources
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_sqs as sqs
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
from constructs import Construct

from cdk_constructs.params import export_param, import_param
from cdk_constructs.service_function import ServiceFunction
from cdk_constructs.stage import StageContext
from cdk_constructs.wiring import grant_config_read, grant_put_events, shared_bus_name

SRC = "apps/fulfilment/src/fulfilment"

INTAKE_TIMEOUT = cdk.Duration.seconds(30)


class FulfilmentStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, ctx: StageContext, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        reservations = dynamodb.TableV2(
            self,
            "Reservations",
            table_name=ctx.name("reservations"),
            partition_key=dynamodb.Attribute(name="order_id", type=dynamodb.AttributeType.STRING),
            billing=dynamodb.Billing.on_demand(),
            removal_policy=ctx.removal_policy,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=ctx.is_prod
            ),
        )

        payment_secret_name = ctx.name("payment-provider")
        payment_secret = secretsmanager.Secret(
            self,
            "PaymentProvider",
            secret_name=payment_secret_name,
            description="Credentials for the (simulated) payment provider",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template=json.dumps({"provider": "acme-pay"}),
                generate_string_key="api_key",
                exclude_punctuation=True,
                password_length=32,
            ),
            removal_policy=ctx.removal_policy,
        )

        # --- Lambdas -------------------------------------------------------
        charge_fn = ServiceFunction(
            self,
            "Charge",
            ctx=ctx,
            target_dir=SRC,
            target_name="charge",
            environment={"PAYMENT_SECRET_ID": payment_secret_name},
        )
        payment_secret.grant_read(charge_fn.function)

        publish_fn = ServiceFunction(
            self,
            "PublishResult",
            ctx=ctx,
            target_dir=SRC,
            target_name="publish_result",
        )
        grant_put_events(publish_fn.function, ctx)
        grant_config_read(publish_fn.function, ctx)

        # --- State machine -------------------------------------------------
        def publish_task(state_id: str, payload: dict[str, object]) -> tasks.LambdaInvoke:
            return tasks.LambdaInvoke(
                self,
                state_id,
                lambda_function=publish_fn.target,
                payload=sfn.TaskInput.from_object(payload),
                payload_response_only=True,
                result_path=sfn.JsonPath.DISCARD,
            )

        publish_fulfilled = publish_task(
            "PublishFulfilled",
            {"mode": "fulfilled", "order": sfn.JsonPath.object_at("$.order")},
        )
        publish_failed = publish_task(
            "PublishFailed",
            {
                "mode": "failed",
                "order": sfn.JsonPath.object_at("$.order"),
                "error": sfn.JsonPath.object_at("$.error"),
            },
        )
        publish_failed.next(
            sfn.Fail(
                self,
                "FulfilmentFailed",
                error="FulfilmentFailed",
                cause="Order fulfilment failed; OrderFulfilmentFailed was published",
            )
        )

        reserve_stock = tasks.DynamoPutItem(
            self,
            "ReserveStock",
            table=reservations,
            item={
                "order_id": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.string_at("$.order.order_id")
                ),
                "customer_email": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.string_at("$.order.customer_email")
                ),
                "lines": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.json_to_string(sfn.JsonPath.object_at("$.order.lines"))
                ),
                "reserved_at": tasks.DynamoAttributeValue.from_string(
                    sfn.JsonPath.string_at("$$.State.EnteredTime")
                ),
            },
            condition_expression="attribute_not_exists(order_id)",
            result_path=sfn.JsonPath.DISCARD,
        )

        # Lambda service errors (throttling, 5xx) are retried by LambdaInvoke's
        # default retry; business errors such as PaymentDeclined are not.
        charge_payment = tasks.LambdaInvoke(
            self,
            "ChargePayment",
            lambda_function=charge_fn.target,
            payload=sfn.TaskInput.from_json_path_at("$.order"),
            result_selector={
                "charge_id.$": "$.Payload.charge_id",
                "amount.$": "$.Payload.amount",
            },
            result_path="$.payment",
            retry_on_service_exceptions=True,
        )

        # The invoicing app's ECS task is a deploy-time dependency (deploy.toml).
        cluster_arn = import_param(self, ctx, "invoicing", "cluster-arn")
        task_definition_arn = import_param(self, ctx, "invoicing", "task-definition-arn")
        subnet_ids = import_param(self, ctx, "invoicing", "subnet-ids")
        security_group_id = import_param(self, ctx, "invoicing", "security-group-id")
        container_name = import_param(self, ctx, "invoicing", "container-name")

        render_invoice = sfn.CustomState(
            self,
            "RenderInvoice",
            state_json={
                "Type": "Task",
                "Resource": "arn:aws:states:::ecs:runTask.sync",
                "Parameters": {
                    "LaunchType": "FARGATE",
                    "Cluster": cluster_arn,
                    "TaskDefinition": task_definition_arn,
                    "NetworkConfiguration": {
                        "AwsvpcConfiguration": {
                            # Split in ASL, not with cdk.Fn.split: a CFN list token
                            # inside a JSON definition makes CDK add a Lambda-backed
                            # custom resource (Custom::AWSCDKCfnJsonStringify).
                            "Subnets.$": f"States.StringSplit('{subnet_ids}', ',')",
                            "SecurityGroups": [security_group_id],
                            "AssignPublicIp": "ENABLED",
                        }
                    },
                    "Overrides": {
                        "ContainerOverrides": [
                            {
                                "Name": container_name,
                                "Environment": [
                                    {
                                        "Name": "ORDER_JSON",
                                        "Value.$": "States.JsonToString($.order)",
                                    }
                                ],
                            }
                        ]
                    },
                },
                "ResultPath": "$.invoice",
            },
        )

        failure_catch = {"errors": ["States.ALL"], "result_path": "$.error"}
        reserve_stock.add_catch(publish_failed, **failure_catch)
        charge_payment.add_catch(publish_failed, **failure_catch)
        render_invoice.add_catch(publish_failed, **failure_catch)

        definition = reserve_stock.next(charge_payment).next(render_invoice).next(publish_fulfilled)

        state_machine = sfn.StateMachine(
            self,
            "Fulfilment",
            state_machine_name=ctx.name("fulfilment"),
            state_machine_type=sfn.StateMachineType.STANDARD,
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            timeout=cdk.Duration.minutes(15),
            removal_policy=ctx.removal_policy,
        )

        # Permissions for ecs:runTask.sync (CustomState can't derive them).
        state_machine.add_to_role_policy(
            iam.PolicyStatement(actions=["ecs:RunTask"], resources=[task_definition_arn])
        )
        state_machine.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ecs:StopTask", "ecs:DescribeTasks"],
                resources=["*"],
            )
        )
        state_machine.add_to_role_policy(
            iam.PolicyStatement(
                actions=["iam:PassRole"],
                resources=["*"],
                conditions={"StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}},
            )
        )
        state_machine.add_to_role_policy(
            iam.PolicyStatement(
                actions=["events:PutTargets", "events:PutRule", "events:DescribeRule"],
                resources=[
                    cdk.Stack.of(self).format_arn(
                        service="events",
                        resource="rule",
                        resource_name="StepFunctionsGetEventsForECSTaskRule",
                    )
                ],
            )
        )

        # --- Intake: bus -> rule -> queue (+DLQ) -> Lambda -> StartExecution --
        dlq = sqs.Queue(
            self,
            "IntakeDlq",
            queue_name=ctx.name("intake-dlq"),
            retention_period=cdk.Duration.days(14),
            removal_policy=ctx.removal_policy,
        )
        queue = sqs.Queue(
            self,
            "IntakeQueue",
            queue_name=ctx.name("intake"),
            # >= 6x the consumer's timeout, as recommended for Lambda event sources.
            visibility_timeout=cdk.Duration.seconds(INTAKE_TIMEOUT.to_seconds() * 6),
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=dlq),
            removal_policy=ctx.removal_policy,
        )

        intake_fn = ServiceFunction(
            self,
            "Intake",
            ctx=ctx,
            target_dir=SRC,
            target_name="intake",
            timeout=INTAKE_TIMEOUT,
            environment={"STATE_MACHINE_ARN": state_machine.state_machine_arn},
        )
        state_machine.grant_start_execution(intake_fn.function)
        intake_fn.target.add_event_source(
            event_sources.SqsEventSource(queue, batch_size=10, report_batch_item_failures=True)
        )

        bus = events.EventBus.from_event_bus_name(self, "Bus", shared_bus_name(ctx))
        events.Rule(
            self,
            "OrderPlacedRule",
            rule_name=ctx.name("order-placed"),
            event_bus=bus,
            event_pattern=events.EventPattern(source=["shop.orders"], detail_type=["OrderPlaced"]),
            targets=[targets.SqsQueue(queue)],  # pyright: ignore[reportArgumentType]  (jsii protocol)
        )

        export_param(self, ctx, "state-machine-arn", state_machine.state_machine_arn)
        export_param(self, ctx, "queue-url", queue.queue_url)

        cdk.CfnOutput(self, "StateMachineArn", value=state_machine.state_machine_arn)
