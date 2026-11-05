# invoicing

The invoicing app renders an HTML invoice for each order in a one-off ECS Fargate task and writes it to S3.

## AWS services

- Amazon ECS on AWS Fargate: the `{stage}-invoicing-cluster` cluster and the `{stage}-invoicing-render` task definition (0.25 vCPU, 512 MiB, x86_64), with one container named `render`.
- Amazon VPC: one VPC with a single public subnet, no NAT gateway, and a security group that allows outbound traffic only.
- Amazon S3: the `invoices` bucket, with public access blocked. The task role can write to it.
- Amazon ECR: on real deploys, CDK builds the container image from the staged Docker context in `dist/docker/invoicing` and publishes it as an image asset. With `CDK_STUB_ASSETS=1`, a stub Python image is used instead.
- Amazon CloudWatch Logs: the `/ecs/{stage}-invoicing-render` log group.
- AWS Systems Manager Parameter Store: exports the values that fulfilment and notifications use.

## How it works

1. Fulfilment's state machine starts the task with `runTask.sync` and passes the `OrderPlaced` JSON in the `ORDER_JSON` environment variable.
2. `render.main()` parses the order, renders the HTML with all values escaped, and uploads it to `invoices/{order_id}.html` in the bucket named by `INVOICE_BUCKET`.
3. The container prints the bucket and key to stdout and exits. ECS reports completion to the state machine.

## Contracts

- Events published: None.
- Events consumed: None. The task reads the `OrderPlaced` JSON that fulfilment passes in `ORDER_JSON`.
- Pacts: None.

## Published config (SSM)

- `/{stage}/invoicing/bucket-name`: name of the invoices bucket. Notifications reads it at runtime.
- `/{stage}/invoicing/cluster-arn`: ARN of the ECS cluster. Fulfilment imports it at deploy time.
- `/{stage}/invoicing/task-definition-arn`: ARN of the Fargate task definition. Fulfilment imports it at deploy time.
- `/{stage}/invoicing/subnet-ids`: comma-separated public subnet IDs. Fulfilment imports it at deploy time.
- `/{stage}/invoicing/security-group-id`: ID of the task security group. Fulfilment imports it at deploy time.
- `/{stage}/invoicing/container-name`: container name, `render`. Fulfilment imports it at deploy time.

## Dependencies

- `depends_on`: `platform`.
- Deploy-time imports by other apps: fulfilment.
- Runtime lookups: none.

## Commands

```
pants test apps/invoicing::                                      # unit, infra, contract tests
FLOCI_ENDPOINT=http://localhost:4566 pants --tag=floci test apps/invoicing::   # integration tests on Floci
python3 tools/deploy.py --stage dev-$USER --apps invoicing --with-deps        # deploy to local Floci
```
