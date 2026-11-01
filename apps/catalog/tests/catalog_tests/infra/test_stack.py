"""Infra unit tests: synthesize with stubbed assets and assert on the template."""

from __future__ import annotations

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from catalog_infra.stack import RESOLVERS_DIR, SCHEMA_PATH, VTL_RESOLVERS, CatalogStack
from cdk_constructs.stage import StageContext


def synth(stage: str, target: str = "floci") -> Template:
    app = cdk.App(context={"stage": stage, "target": target})
    ctx = StageContext.of(app, "catalog")
    stack = CatalogStack(app, f"{stage}-catalog", ctx=ctx)
    return Template.from_stack(stack)


@pytest.fixture(autouse=True)
def stub_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CDK_STUB_ASSETS", "1")


def test_table_named_by_stage() -> None:
    synth("pr-42").has_resource_properties(
        "AWS::DynamoDB::GlobalTable",
        {
            "TableName": "pr-42-catalog-products",
            "KeySchema": [{"AttributeName": "sku", "KeyType": "HASH"}],
            "BillingMode": "PAY_PER_REQUEST",
        },
    )


def test_bucket_named_by_stage_and_auto_deleted_outside_prod() -> None:
    dev = synth("pr-42")
    dev.has_resource_properties("AWS::S3::Bucket", {"BucketName": "pr-42-catalog-images"})
    dev.resource_count_is("Custom::S3AutoDeleteObjects", 1)

    prod = synth("prod")
    prod.has_resource_properties("AWS::S3::Bucket", {"BucketName": "prod-catalog-images"})
    prod.resource_count_is("Custom::S3AutoDeleteObjects", 0)


def test_prod_retains_stateful_resources() -> None:
    template = synth("prod")
    for resource_type in ("AWS::DynamoDB::GlobalTable", "AWS::S3::Bucket"):
        for resource in template.find_resources(resource_type).values():
            assert resource["DeletionPolicy"] == "Retain"


def test_graphql_api_uses_api_key_auth_and_schema() -> None:
    template = synth("dev-ada")
    template.has_resource_properties(
        "AWS::AppSync::GraphQLApi",
        {"Name": "dev-ada-catalog-graphql", "AuthenticationType": "API_KEY"},
    )
    template.resource_count_is("AWS::AppSync::ApiKey", 1)
    template.has_resource_properties(
        "AWS::AppSync::GraphQLSchema",
        {"Definition": Match.string_like_regexp(r"type Product \{")},
    )


def test_three_vtl_resolvers_on_dynamodb_source() -> None:
    template = synth("dev-ada")
    for (type_name, field_name), basename in VTL_RESOLVERS.items():
        template.has_resource_properties(
            "AWS::AppSync::Resolver",
            {
                "TypeName": type_name,
                "FieldName": field_name,
                "Kind": "UNIT",
                "RequestMappingTemplate": (RESOLVERS_DIR / f"{basename}.req.vtl").read_text(),
                "ResponseMappingTemplate": (RESOLVERS_DIR / f"{basename}.res.vtl").read_text(),
            },
        )
    template.has_resource_properties("AWS::AppSync::DataSource", {"Type": "AMAZON_DYNAMODB"})


def test_lambda_data_source_resolves_computed_product_fields() -> None:
    template = synth("dev-ada")
    template.has_resource_properties("AWS::AppSync::DataSource", {"Type": "AWS_LAMBDA"})
    for field_name in ("priceIn", "imageUploadUrl"):
        template.has_resource_properties(
            "AWS::AppSync::Resolver",
            {"TypeName": "Product", "FieldName": field_name, "Kind": "UNIT"},
        )
    # 3 VTL + 2 Lambda
    template.resource_count_is("AWS::AppSync::Resolver", 5)


def test_field_resolver_function_environment() -> None:
    synth("dev-ada").has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Runtime": "python3.13",
            "Environment": {
                "Variables": Match.object_like(
                    {
                        "STAGE": "dev-ada",
                        "IMAGES_BUCKET": Match.any_value(),
                        "FX_API_KEY_SECRET": Match.any_value(),
                    }
                )
            },
        },
    )


def test_fx_secret_has_generated_value() -> None:
    synth("pr-7").has_resource_properties(
        "AWS::SecretsManager::Secret",
        {
            "Name": "pr-7-catalog-fx-api-key",
            "GenerateSecretString": Match.object_like({"PasswordLength": 32}),
        },
    )


def test_publishes_config_to_ssm() -> None:
    template = synth("prod")
    for key in ("graphql-url", "products-table", "images-bucket"):
        template.has_resource_properties("AWS::SSM::Parameter", {"Name": f"/prod/catalog/{key}"})


def test_schema_and_templates_exist_on_disk() -> None:
    assert SCHEMA_PATH.is_file()
    for basename in VTL_RESOLVERS.values():
        assert (RESOLVERS_DIR / f"{basename}.req.vtl").is_file()
        assert (RESOLVERS_DIR / f"{basename}.res.vtl").is_file()
