from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_appsync as appsync
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

from cdk_constructs.params import export_param
from cdk_constructs.service_function import ServiceFunction
from cdk_constructs.stage import StageContext

SRC = "apps/catalog/src/catalog"

# These files ship inside the cdk_app PEX (venv mode) as resources, so they sit
# next to this module on disk both in a checkout and when packaged.
MODULE_DIR = Path(__file__).parent
SCHEMA_PATH = MODULE_DIR / "schema.graphql"
RESOLVERS_DIR = MODULE_DIR / "resolvers"

# (type, field) -> template basename in RESOLVERS_DIR; DynamoDB unit resolvers.
VTL_RESOLVERS = {
    ("Query", "getProduct"): "Query.getProduct",
    ("Query", "listProducts"): "Query.listProducts",
    ("Mutation", "putProduct"): "Mutation.putProduct",
}


def vtl_template(basename: str, kind: str) -> Path:
    """Path of ``<basename>.req.vtl`` / ``<basename>.res.vtl``; ``kind`` is "req" or "res"."""
    return RESOLVERS_DIR / f"{basename}.{kind}.vtl"


class CatalogStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, ctx: StageContext, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        table = dynamodb.TableV2(
            self,
            "Products",
            table_name=ctx.name("products"),
            partition_key=dynamodb.Attribute(name="sku", type=dynamodb.AttributeType.STRING),
            billing=dynamodb.Billing.on_demand(),
            removal_policy=ctx.removal_policy,
        )

        images = s3.Bucket(
            self,
            "Images",
            bucket_name=ctx.name("images"),
            removal_policy=ctx.removal_policy,
            # Auto-delete uses a CDK custom-resource Lambda that can't reach Floci's S3.
            auto_delete_objects=ctx.is_ephemeral and not ctx.on_floci,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            cors=[
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.PUT],
                    allowed_origins=["*"],
                    allowed_headers=["*"],
                )
            ],
        )

        fx_api_key = secretsmanager.Secret(
            self,
            "FxApiKey",
            secret_name=ctx.name("fx-api-key"),
            description="API key for the FX rates provider (generated placeholder)",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                exclude_punctuation=True, password_length=32
            ),
            removal_policy=ctx.removal_policy,
        )

        api = appsync.GraphqlApi(
            self,
            "Graphql",
            name=ctx.name("graphql"),
            definition=appsync.Definition.from_file(str(SCHEMA_PATH)),
            authorization_config=appsync.AuthorizationConfig(
                default_authorization=appsync.AuthorizationMode(
                    authorization_type=appsync.AuthorizationType.API_KEY
                )
            ),
        )

        # Unit resolvers: DynamoDB data source + VTL templates (no Lambda in the hot path).
        products_source = api.add_dynamo_db_data_source("ProductsSource", table)
        for (type_name, field_name), basename in VTL_RESOLVERS.items():
            products_source.create_resolver(
                f"{type_name}{field_name[0].upper()}{field_name[1:]}Resolver",
                type_name=type_name,
                field_name=field_name,
                request_mapping_template=appsync.MappingTemplate.from_file(
                    str(vtl_template(basename, "req"))
                ),
                response_mapping_template=appsync.MappingTemplate.from_file(
                    str(vtl_template(basename, "res"))
                ),
            )

        # Direct Lambda resolvers for the computed Product fields.
        field_resolvers = ServiceFunction(
            self,
            "FieldResolvers",
            ctx=ctx,
            target_dir=SRC,
            target_name="field_resolvers",
            environment={
                "IMAGES_BUCKET": images.bucket_name,
                "FX_API_KEY_SECRET": fx_api_key.secret_name,
            },
        )
        images.grant_put(field_resolvers.function)
        fx_api_key.grant_read(field_resolvers.function)

        lambda_source = api.add_lambda_data_source("FieldResolversSource", field_resolvers.target)
        for field_name in ("priceIn", "imageUploadUrl"):
            lambda_source.create_resolver(
                f"Product{field_name[0].upper()}{field_name[1:]}Resolver",
                type_name="Product",
                field_name=field_name,
            )

        export_param(self, ctx, "graphql-url", api.graphql_url)
        export_param(self, ctx, "products-table", table.table_name)
        export_param(self, ctx, "images-bucket", images.bucket_name)

        cdk.CfnOutput(self, "GraphqlUrl", value=api.graphql_url)
        cdk.CfnOutput(self, "ApiKey", value=api.api_key or "")
