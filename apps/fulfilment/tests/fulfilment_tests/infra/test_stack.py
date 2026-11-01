"""Infra unit tests: synthesize with stubbed assets and assert on the template."""

from __future__ import annotations

import json
from typing import Any

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from cdk_constructs.stage import StageContext
from fulfilment_infra.stack import FulfilmentStack


def synth(stage: str, target: str = "floci") -> Template:
    app = cdk.App(context={"stage": stage, "target": target})
    ctx = StageContext.of(app, "fulfilment")
    stack = FulfilmentStack(app, f"{stage}-fulfilment", ctx=ctx)
    return Template.from_stack(stack)


@pytest.fixture(autouse=True)
def stub_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CDK_STUB_ASSETS", "1")


def definition(template: Template) -> dict[str, Any]:
    """The state machine definition with CloudFormation tokens replaced by '<token>'."""
    (resource,) = template.find_resources("AWS::StepFunctions::StateMachine").values()
    raw = resource["Properties"]["DefinitionString"]
    text = (
        raw
        if isinstance(raw, str)
        else "".join(part if isinstance(part, str) else "<token>" for part in raw["Fn::Join"][1])
    )
    return json.loads(text)


def test_state_machine_is_standard_and_named_by_stage() -> None:
    synth("pr-42").has_resource_properties(
        "AWS::StepFunctions::StateMachine",
        {"StateMachineName": "pr-42-fulfilment-fulfilment", "StateMachineType": "STANDARD"},
    )


def test_state_machine_flow() -> None:
    states = definition(synth("prod"))["States"]

    assert definition(synth("prod"))["StartAt"] == "ReserveStock"
    assert states["ReserveStock"]["Next"] == "ChargePayment"
    assert states["ChargePayment"]["Next"] == "RenderInvoice"
    assert states["RenderInvoice"]["Next"] == "PublishFulfilled"
    assert states["PublishFulfilled"]["End"] is True
    assert states["PublishFailed"]["Next"] == "FulfilmentFailed"
    assert states["FulfilmentFailed"]["Type"] == "Fail"


def test_reserve_stock_is_a_conditional_dynamodb_put() -> None:
    state = definition(synth("prod"))["States"]["ReserveStock"]

    assert "states:::dynamodb:putItem" in state["Resource"]
    assert state["Parameters"]["ConditionExpression"] == "attribute_not_exists(order_id)"
    assert state["Parameters"]["Item"]["order_id"] == {"S.$": "$.order.order_id"}
    assert state["ResultPath"] is None  # input (incl. $.order) passes through untouched


def test_reservations_table() -> None:
    template = synth("prod")
    template.has_resource_properties(
        "AWS::DynamoDB::GlobalTable",
        {
            "TableName": "prod-fulfilment-reservations",
            "KeySchema": [{"AttributeName": "order_id", "KeyType": "HASH"}],
        },
    )
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [Match.object_like({"Action": "dynamodb:PutItem", "Effect": "Allow"})]
                )
            }
        },
    )


def test_charge_retries_only_lambda_service_errors_and_failures_are_caught() -> None:
    state = definition(synth("prod"))["States"]["ChargePayment"]

    retried = {error for retry in state["Retry"] for error in retry["ErrorEquals"]}
    assert retried
    assert all(error.startswith("Lambda.") for error in retried)
    assert state["Catch"] == [
        {"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "PublishFailed"}
    ]
    assert state["ResultPath"] == "$.payment"
    assert state["Parameters"]["Payload.$"] == "$.order"


def test_render_invoice_runs_the_invoicing_task_with_run_task_sync() -> None:
    state = definition(synth("prod"))["States"]["RenderInvoice"]
    params = state["Parameters"]

    assert state["Resource"] == "arn:aws:states:::ecs:runTask.sync"
    assert params["LaunchType"] == "FARGATE"
    network = params["NetworkConfiguration"]["AwsvpcConfiguration"]
    assert network["AssignPublicIp"] == "ENABLED"
    assert network["Subnets.$"].startswith("States.StringSplit(")
    (override,) = params["Overrides"]["ContainerOverrides"]
    assert override["Environment"] == [
        {"Name": "ORDER_JSON", "Value.$": "States.JsonToString($.order)"}
    ]
    assert state["ResultPath"] == "$.invoice"
    assert state["Catch"][0]["Next"] == "PublishFailed"


def test_state_machine_definition_mentions_run_task_sync() -> None:
    template = synth("prod")
    (resource,) = template.find_resources("AWS::StepFunctions::StateMachine").values()
    assert "ecs:runTask.sync" in json.dumps(resource["Properties"]["DefinitionString"])


def test_invoicing_wiring_is_imported_at_deploy_time() -> None:
    template = synth("prod")
    for key in (
        "cluster-arn",
        "task-definition-arn",
        "subnet-ids",
        "security-group-id",
        "container-name",
    ):
        template.has_parameter(
            "*",
            {"Type": "AWS::SSM::Parameter::Value<String>", "Default": f"/prod/invoicing/{key}"},
        )


def test_no_custom_resources_are_needed() -> None:
    # A CFN list token inside the JSON definition would add a Lambda-backed custom resource.
    template = synth("prod")
    assert not [
        name
        for name in template.to_json()["Resources"].values()
        if name["Type"].startswith("Custom::")
    ]


def test_state_machine_role_can_run_the_task_and_wait_for_it() -> None:
    statements = [
        statement
        for policy in synth("prod").find_resources("AWS::IAM::Policy").values()
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
    ]

    def statement_for(*actions: str) -> dict[str, Any]:
        (match,) = [
            s
            for s in statements
            if sorted(s["Action"] if isinstance(s["Action"], list) else [s["Action"]])
            == sorted(actions)
        ]
        return match

    assert statement_for("ecs:RunTask")["Effect"] == "Allow"
    assert statement_for("ecs:StopTask", "ecs:DescribeTasks")["Resource"] == "*"
    assert statement_for("iam:PassRole")["Condition"] == {
        "StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}
    }
    events_statement = statement_for("events:PutTargets", "events:PutRule", "events:DescribeRule")
    assert "StepFunctionsGetEventsForECSTaskRule" in json.dumps(events_statement["Resource"])


def test_publish_task_receives_error_in_failure_mode() -> None:
    states = definition(synth("prod"))["States"]

    assert states["PublishFulfilled"]["Parameters"] == {"mode": "fulfilled", "order.$": "$.order"}
    assert states["PublishFailed"]["Parameters"] == {
        "mode": "failed",
        "order.$": "$.order",
        "error.$": "$.error",
    }


def test_rule_matches_order_placed_on_the_shared_bus() -> None:
    synth("pr-42").has_resource_properties(
        "AWS::Events::Rule",
        {
            "Name": "pr-42-fulfilment-order-placed",
            "EventBusName": "pr-42-shop-bus",
            "EventPattern": {"source": ["shop.orders"], "detail-type": ["OrderPlaced"]},
            "Targets": [Match.object_like({"Arn": Match.any_value()})],
        },
    )


def test_queue_has_dlq_after_three_receives() -> None:
    template = synth("prod")
    template.has_resource_properties(
        "AWS::SQS::Queue",
        {
            "QueueName": "prod-fulfilment-intake",
            "RedrivePolicy": {"deadLetterTargetArn": Match.any_value(), "maxReceiveCount": 3},
        },
    )
    template.has_resource_properties("AWS::SQS::Queue", {"QueueName": "prod-fulfilment-intake-dlq"})


def test_intake_consumes_queue_with_partial_batch_responses() -> None:
    template = synth("prod")
    template.has_resource_properties(
        "AWS::Lambda::EventSourceMapping",
        {"FunctionResponseTypes": ["ReportBatchItemFailures"], "BatchSize": 10},
    )
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": "prod-fulfilment-intake",
            "Environment": {
                "Variables": Match.object_like({"STATE_MACHINE_ARN": Match.any_value()})
            },
        },
    )
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [Match.object_like({"Action": "states:StartExecution", "Effect": "Allow"})]
                )
            }
        },
    )


def test_lambdas_are_service_functions_with_stage_env() -> None:
    template = synth("prod")
    for name in ("intake", "charge", "publishresult"):
        template.has_resource_properties(
            "AWS::Lambda::Function",
            {
                "FunctionName": f"prod-fulfilment-{name}",
                "Runtime": "python3.13",
                "Architectures": ["arm64"],
                "Environment": {
                    "Variables": Match.object_like(
                        {"STAGE": "prod", "AWS_ENDPOINT_URL": Match.any_value()}
                    )
                },
            },
        )


def test_payment_secret_is_generated_and_readable_only_by_charge() -> None:
    template = synth("prod")
    template.has_resource_properties(
        "AWS::SecretsManager::Secret",
        {
            "Name": "prod-fulfilment-payment-provider",
            "GenerateSecretString": Match.object_like({"GenerateStringKey": "api_key"}),
        },
    )
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": "prod-fulfilment-charge",
            "Environment": {
                "Variables": Match.object_like(
                    {"PAYMENT_SECRET_ID": "prod-fulfilment-payment-provider"}
                )
            },
        },
    )
    readers = [
        policy
        for policy in template.find_resources("AWS::IAM::Policy").values()
        if "secretsmanager:GetSecretValue" in json.dumps(policy)
    ]
    assert len(readers) == 1
    assert "ChargeFnServiceRole" in json.dumps(readers[0]["Properties"]["Roles"])


def test_publish_result_can_put_events_and_read_config() -> None:
    policies = [
        json.dumps(policy)
        for policy in synth("prod").find_resources("AWS::IAM::Policy").values()
        if "PublishResultFnServiceRole" in json.dumps(policy["Properties"]["Roles"])
    ]
    assert any("events:PutEvents" in p and "ssm:GetParameter" in p for p in policies)


def test_publishes_wiring_params() -> None:
    template = synth("prod")
    template.has_resource_properties(
        "AWS::SSM::Parameter", {"Name": "/prod/fulfilment/state-machine-arn"}
    )
    template.has_resource_properties("AWS::SSM::Parameter", {"Name": "/prod/fulfilment/queue-url"})
