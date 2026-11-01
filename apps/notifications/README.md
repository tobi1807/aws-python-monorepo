# notifications

The notifications app reads fulfilment events from an SQS queue and writes each customer message to an S3 outbox bucket, which stands in for SES.

## AWS services

- Amazon EventBridge: the `fulfilment-events` rule on the shared bus, matching source `shop.fulfilment` with the `OrderFulfilled` and `OrderFulfilmentFailed` detail types, targeting the queue.
- Amazon SQS: the `events` queue (visibility timeout 90 seconds), with an `events-dlq` dead-letter queue (14-day retention, max receive count 3).
- AWS Lambda: the `notify` function (30 second timeout, SQS batches of 10 with partial batch responses), built with `ServiceFunction`.
- Amazon S3: the `outbox` bucket, with public access blocked, which `notify` writes to. The function also has `s3:GetObject` on `{stage}-invoicing-invoices/*` so it can presign invoice links.
- AWS Systems Manager Parameter Store: exports `outbox-bucket` and `queue-url`. Reads invoicing's bucket name at runtime.
- Amazon CloudWatch Logs and alarms: the function log group and its error alarm.

## How it works

1. EventBridge routes `OrderFulfilled` and `OrderFulfilmentFailed` events from the shared bus to the `events` queue.
2. `notify` parses each record's EventBridge envelope and validates its `detail` against the contract model. Records that fail to parse, or have an unknown detail type, are returned as batch item failures so SQS retries them.
3. For `OrderFulfilled`, the invoices bucket name is read from SSM and a presigned GET link to the invoice, valid for seven days, is created.
4. The message (`to`, `subject`, `body`) is written as JSON to `outbox/{order_id}/{detail_type}.json`.
5. After three receives without success, a message moves to the DLQ.

## Contracts

- Events consumed: `OrderFulfilled` and `OrderFulfilmentFailed` (source `shop.fulfilment`), from `libs/contracts/src/contracts/fulfilment.py`.
- Events published: None.
- Pacts: consumer of `pacts/notifications-fulfilment.json` (provider: fulfilment).

## Published config (SSM)

- `/{stage}/notifications/outbox-bucket`: name of the outbox bucket.
- `/{stage}/notifications/queue-url`: URL of the `events` queue.

## Dependencies

- `depends_on`: `platform`. `invoicing` is not listed because the bucket name is looked up at runtime.
- Runtime lookups: `get_config("invoicing", "bucket-name")`, made in `notify.invoice_url`.

## Commands

```
pants test apps/notifications::                                      # unit, infra, contract tests
FLOCI_ENDPOINT=http://localhost:4566 pants --tag=floci test apps/notifications::   # integration tests on Floci
python3 tools/deploy.py --stage dev-$USER --apps notifications --with-deps        # deploy to local Floci
```
