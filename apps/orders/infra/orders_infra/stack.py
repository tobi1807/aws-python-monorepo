from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_dynamodb as dynamodb
from constructs import Construct

from cdk_constructs.params import export_param
from cdk_constructs.service_function import ServiceFunction
from cdk_constructs.stage import StageContext
from cdk_constructs.wiring import flags_env, grant_config_read, grant_flags_read, grant_put_events

SRC = "apps/orders/src/orders"


class OrdersStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, ctx: StageContext, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        table = dynamodb.TableV2(
            self,
            "Orders",
            table_name=ctx.name("orders"),
            partition_key=dynamodb.Attribute(name="order_id", type=dynamodb.AttributeType.STRING),
            billing=dynamodb.Billing.on_demand(),
            removal_policy=ctx.removal_policy,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=ctx.is_prod
            ),
        )

        api_fn = ServiceFunction(
            self,
            "Api",
            ctx=ctx,
            target_dir=SRC,
            target_name="api",
            environment={"ORDERS_TABLE": table.table_name},
            flags=flags_env(ctx),
        )
        table.grant_read_write_data(api_fn.function)
        grant_put_events(api_fn.function, ctx)
        grant_config_read(api_fn.function, ctx)
        grant_flags_read(api_fn.function)

        http_api = apigw.HttpApi(self, "HttpApi", api_name=ctx.name("api"))
        integration = integrations.HttpLambdaIntegration("ApiIntegration", api_fn.target)
        http_api.add_routes(
            path="/orders", methods=[apigw.HttpMethod.POST], integration=integration
        )
        http_api.add_routes(
            path="/orders/{order_id}", methods=[apigw.HttpMethod.GET], integration=integration
        )

        export_param(self, ctx, "api-url", http_api.api_endpoint)
        export_param(self, ctx, "table-name", table.table_name)

        cdk.CfnOutput(self, "ApiUrl", value=http_api.api_endpoint)
