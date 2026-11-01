# catalog

The catalog app serves a GraphQL API for products, backed by DynamoDB, with two computed fields resolved by a Lambda function and an S3 bucket for product images.

## AWS services

- AWS AppSync: a GraphQL API with API key authorisation.
- AppSync VTL resolvers: `Query.getProduct` (GetItem), `Query.listProducts` (Scan) and `Mutation.putProduct` (PutItem), all on a DynamoDB data source with no Lambda in the path.
- AppSync Lambda resolvers: `Product.priceIn` and `Product.imageUploadUrl`.
- Amazon DynamoDB: the `products` table, partition key `sku`, on-demand billing.
- AWS Lambda: the `field_resolvers` function, built with the shared `ServiceFunction` construct (CodeDeploy canary in real AWS prod only).
- Amazon S3: the `images` bucket, with public access blocked and a CORS rule that allows PUT from any origin.
- AWS Secrets Manager: the `fx-api-key` secret, a generated 32-character placeholder.
- AWS Systems Manager Parameter Store: exports `graphql-url`, `products-table` and `images-bucket`.
- Amazon CloudWatch Logs and alarms: the function log group and its error alarm.

## How it works

1. A GraphQL request reaches AppSync and is authorised with an API key.
2. `getProduct` and `putProduct` run against DynamoDB directly from VTL templates. `putProduct` defaults `currency` to `GBP` and `stock` to `0`.
3. `listProducts` runs a Scan with a default limit of 20, capped at 100, and passes `nextToken` through.
4. `Product.priceIn(currency)` invokes the Lambda function. It checks that the FX key secret is not blank, then converts the price using rates fixed in code (GBP, USD, EUR). An unknown currency returns an error.
5. `Product.imageUploadUrl` invokes the Lambda function, which returns a presigned S3 PUT URL for `products/{sku}.jpg`, valid for 900 seconds.

## Contracts

- Events published: None.
- Events consumed: None.
- Pacts: None.

The `Product` model in `libs/contracts/src/contracts/catalog.py` is the shape the Lambda resolver validates against. It is not an event.

## Published config (SSM)

- `/{stage}/catalog/graphql-url`: AppSync GraphQL endpoint URL.
- `/{stage}/catalog/products-table`: name of the `products` table.
- `/{stage}/catalog/images-bucket`: name of the images bucket.

## Dependencies

- `depends_on`: `platform`. It is declared for ordering only. Catalog reads nothing from other apps at deploy time.
- Runtime lookups: none.

## Commands

```
pants test apps/catalog::                                      # unit, infra, contract tests
FLOCI_ENDPOINT=http://localhost:4566 pants --tag=floci test apps/catalog::   # integration tests on Floci
python3 tools/deploy.py --stage dev-$USER --apps catalog --with-deps        # deploy to local Floci
```
