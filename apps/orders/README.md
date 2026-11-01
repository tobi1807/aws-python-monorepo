# orders

The orders app takes customer orders over HTTP, stores them in DynamoDB and publishes an `OrderPlaced` event to the shared bus.

## AWS services

- Amazon API Gateway (HTTP API): `POST /orders` and `GET /orders/{order_id}`, both routed to one Lambda function.
- AWS Lambda: the `api` function, built with the shared `ServiceFunction` construct (Python 3.13, ARM64, `live` alias, error alarm, CodeDeploy canary in real AWS prod only).
- Amazon DynamoDB: the `orders` table, partition key `order_id`, on-demand billing, point-in-time recovery in prod only.
- Amazon EventBridge: publishes `OrderPlaced` to the shared bus.
- AWS AppConfig: reads the `express_checkout` flag.
- AWS Systems Manager Parameter Store: exports `api-url` and `table-name`. The function's role can read `/{stage}/*` and `/baseline/*` parameters.
- Amazon CloudWatch Logs and alarms: the function log group and its error alarm.

## How it works

1. `POST /orders` reaches the Lambda function. The body is validated against `PlaceOrderRequest` (a valid email and at least one line). An invalid body returns 400.
2. If `express` is true, the `express_checkout` flag is checked in AppConfig for the customer's email. If the flag is off, the request returns 400.
3. The total is calculated from the lines, and the order gets an ID of the form `ord-` followed by 12 hex characters.
4. The order is written to DynamoDB with a conditional put, which fails if the ID already exists.
5. An `OrderPlaced` event is published to the shared bus, and the response is 201 with the order as JSON.
6. `GET /orders/{order_id}` reads the item from DynamoDB and returns it, or 404 if it does not exist.

## Contracts

- Events published: `OrderPlaced` (source `shop.orders`, from `libs/contracts/src/contracts/orders.py`).
- Events consumed: None.
- Pacts: provider for `pacts/fulfilment-orders.json` (consumer: fulfilment).

## Published config (SSM)

- `/{stage}/orders/api-url`: endpoint URL of the HTTP API.
- `/{stage}/orders/table-name`: name of the `orders` DynamoDB table.

## Dependencies

- `depends_on`: `platform`.
- Runtime lookups: `get_config("platform", "event-bus-name")`, made by `runtime.events.publish` when an order is placed.

## Commands

```
pants test apps/orders::                                      # unit, infra, contract tests
FLOCI_ENDPOINT=http://localhost:4566 pants --tag=floci test apps/orders::   # integration tests on Floci
python3 tools/deploy.py --stage dev-$USER --apps orders --with-deps        # deploy to local Floci
```
