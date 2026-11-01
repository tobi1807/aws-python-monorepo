# platform

The platform app owns the shared EventBridge bus, the AppConfig feature-flag application and the SSM parameters that other apps use to find them.

## AWS services

- Amazon EventBridge: the shared bus `{stage}-shop-bus`, and a catch-all rule that matches every source starting with `shop.`.
- Amazon CloudWatch Logs: the `/shop/{stage}/events` log group, which the catch-all rule writes to. A resource policy lets EventBridge write to it.
- AWS AppConfig: a freeform application, an environment named after the stage and the `features` profile. The hosted version is built from `flags/features.json` and deployed all at once.
- AWS Systems Manager Parameter Store: the exported bus and AppConfig values.

## How it works

1. Deploying the stack creates the shared bus.
2. Each `shop.*` event on the bus matches the catch-all rule and is written to `/shop/{stage}/events`.
3. The contents of `flags/features.json` are stored as a hosted AppConfig version and deployed to the stage's environment.
4. The bus name, bus ARN and AppConfig application name are written to SSM, where other apps read them at runtime.

## Contracts

- Events published: None.
- Events consumed: None. The catch-all rule logs `shop.*` events without parsing them.
- Pacts: None.

## Published config (SSM)

- `/{stage}/platform/event-bus-name`: name of the shared bus, `{stage}-shop-bus`.
- `/{stage}/platform/event-bus-arn`: ARN of the shared bus.
- `/{stage}/platform/flags-application`: AppConfig application name, `{stage}-shop`.

## Dependencies

- `depends_on`: none. The platform app deploys first.
- Runtime lookups: none.

## Commands

```
pants test apps/platform::                                      # unit, infra, contract tests
FLOCI_ENDPOINT=http://localhost:4566 pants --tag=floci test apps/platform::   # integration tests on Floci
python3 tools/deploy.py --stage dev-$USER --apps platform --with-deps        # deploy to local Floci
```
