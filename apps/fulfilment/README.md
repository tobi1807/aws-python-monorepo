# fulfilment

The fulfilment app turns each `OrderPlaced` event into a Step Functions workflow. The workflow records a reservation, charges the customer through a simulated payment provider, has an invoice rendered, and publishes `OrderFulfilled` or `OrderFulfilmentFailed`.

## AWS services

- Amazon SQS: the `intake` queue (visibility timeout 180 seconds), with an `intake-dlq` dead-letter queue (14-day retention, max receive count 3).
- Amazon EventBridge: the `order-placed` rule on the shared bus, which routes `OrderPlaced` to the intake queue. The publish step uses `events:PutEvents`.
- AWS Lambda: `intake` (30 second timeout, SQS batches of 10 with partial batch responses), `charge` and `publish_result`, all built with `ServiceFunction`.
- AWS Step Functions: a standard state machine, `fulfilment`, with a 15-minute timeout.
- Amazon ECS on AWS Fargate: a `runTask.sync` step that runs invoicing's task definition in invoicing's cluster.
- Amazon DynamoDB: the `reservations` table, partition key `order_id`, with a conditional put and point-in-time recovery in prod only.
- AWS Secrets Manager: the `payment-provider` secret, with a generated `api_key`. Only the `charge` function can read it.
- AWS Systems Manager Parameter Store: exports `state-machine-arn` and `queue-url`.
- Amazon CloudWatch Logs and alarms: the function log groups and their error alarms.

## How it works

1. EventBridge delivers each `OrderPlaced` event from the shared bus to the intake queue.
2. `intake` reads each record and starts an execution named after the order ID. A redelivered message finds that the execution already exists and is skipped.
3. `ReserveStock` writes a reservation record to the `reservations` table with a conditional put, so an order can only be reserved once.
4. `ChargePayment` invokes `charge`. Orders over 1000 are declined with `PaymentDeclined`. Otherwise the function returns a `charge_id` and the amount. Lambda service errors are retried.
5. `RenderInvoice` runs the invoicing Fargate task with the order JSON in `ORDER_JSON`. The task writes `invoices/{order_id}.html` to the invoices bucket.
6. `PublishFulfilled` puts `OrderFulfilled` on the shared bus. An error in `ReserveStock`, `ChargePayment` or `RenderInvoice` goes to `PublishFailed`, which puts `OrderFulfilmentFailed` on the bus and ends the execution in a `Fail` state.

## Contracts

- Events consumed: `OrderPlaced` (source `shop.orders`), delivered through the intake queue.
- Events published: `OrderFulfilled` and `OrderFulfilmentFailed` (source `shop.fulfilment`), from `libs/contracts/src/contracts/fulfilment.py`.
- Pacts: consumer of `pacts/fulfilment-orders.json` (provider: orders). Provider for `pacts/notifications-fulfilment.json` (consumer: notifications).

## Published config (SSM)

- `/{stage}/fulfilment/state-machine-arn`: ARN of the fulfilment state machine.
- `/{stage}/fulfilment/queue-url`: URL of the intake queue.

## Dependencies

- `depends_on`: `platform`, `invoicing`.
- Deploy-time imports from invoicing (`import_param`): `cluster-arn`, `task-definition-arn`, `subnet-ids`, `security-group-id` and `container-name`.
- Runtime lookups: `get_config("platform", "event-bus-name")`, made by `runtime.events.publish` in `publish_result`.

## Commands

```
pants test apps/fulfilment::                                      # unit, infra, contract tests
FLOCI_ENDPOINT=http://localhost:4566 pants --tag=floci test apps/fulfilment::   # integration tests on Floci
python3 tools/deploy.py --stage dev-$USER --apps fulfilment --with-deps        # deploy to local Floci
```
