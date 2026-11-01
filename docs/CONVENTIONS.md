# Conventions

How every app in this monorepo is shaped. `apps/orders` is the reference
implementation; copy its patterns.

## Layout of an app

```
apps/<app>/
  deploy.toml                  # deploy-time dependencies (depends_on = [...])
  README.md
  src/<app>/                   # runtime code (Lambda handlers, container entry points)
    BUILD                      # python_sources() + one python_aws_lambda_function per handler
  infra/
    BUILD                      # pex_binary(name="cdk_app", entry_point="<app>_infra/app.py")
    <app>_infra/app.py         # create_app("<app>") -> one stack named f"{stage}-<app>"
    <app>_infra/stack.py
  tests/<app>_tests/           # package name is app-prefixed: no module collisions
    conftest.py                # moto fixtures (python_test_utils)
    unit/                      # moto, no network
    infra/                     # CDK assertions with CDK_STUB_ASSETS=1
    contract/                  # Pact message tests
    integration/               # needs Floci; BUILD: python_tests(tags=["floci"])
```

Every directory with Python files has an `__init__.py` and a `BUILD` file.
Source roots (pants.toml): `apps/*/src`, `apps/*/infra`, `apps/*/tests`,
`libs/*/src`, `libs/*/tests`, `tools`.

## Shared libs (import, don't copy)

| Lib | Use for |
|---|---|
| `contracts.<producer>` | Pydantic event models. One module per producing app. `__init__.py` stays empty. |
| `runtime.aws.client(name)` | Cached boto3 clients. Honours `AWS_ENDPOINT_URL` (Floci). |
| `runtime.config.get_config(app, key)` | Runtime SSM lookup of another app's published value (`/{stage}/{app}/{key}`, baseline fallback). |
| `runtime.secrets.get_secret(_json)` | Secrets Manager with cache. |
| `runtime.events.publish(event)` | Put a `DomainEvent` on the shared bus. |
| `runtime.flags.is_enabled(name)` | AppConfig feature flags (Powertools schema). |
| `cdk_constructs.app.create_app / stack_name / default_env` | CDK entry point. |
| `cdk_constructs.stage.StageContext` | `ctx.name(resource)` → `{stage}-{app}-{resource}`, `ctx.removal_policy`, `ctx.runtime_env()`. |
| `cdk_constructs.service_function.ServiceFunction` | Every Lambda. Wire callers to `.target` (the `live` alias). |
| `cdk_constructs.params.export_param / import_param` | Publish values to SSM / deploy-time import (must be in `depends_on`). |
| `cdk_constructs.wiring.*` | Bus name, flags env, IAM grants by naming convention. |
| `cdk_constructs.assets.lambda_code / container_context` | Pants-built artifacts. |
| `testkit.aws` | `fake_credentials`, `reset_runtime_caches`, `floci_endpoint`, `floci_required`. |
| `testkit.pact` | `check_consumer_pact`, `committed_pact`. |

## Rules

1. **No cross-app CloudFormation references.** Apps publish what others need
   with `export_param` and read it at runtime with `runtime.config.get_config`.
   Only use `import_param` when CloudFormation itself needs the value, and add
   the providing app to `deploy.toml` `depends_on`.
2. **Shared bus** is `{stage}-shop-bus`, owned by `platform`. Reference it with
   `events.EventBus.from_event_bus_name(self, "Bus", shared_bus_name(ctx))`.
3. **Physical names** always via `ctx.name(...)`.
4. **Environment-agnostic code.** Never branch on Floci vs AWS in app code;
   `AWS_ENDPOINT_URL` handles it. Infra may check `ctx.on_floci` for things
   Floci lacks (e.g. CodeDeploy).
5. **Contracts.** Producers construct events with `contracts.*` models;
   consumers parse with them. Additive changes only.
6. **Pact.** Consumers write message pacts with `Pact(consumer, provider).with_specification("V4")`,
   `upon_receiving("<description>", "Async").with_body({...matchers...}, "application/json")`,
   `pact.verify(handler, "Async")` where `handler` is the real parsing code,
   then `check_consumer_pact(pact, tmp_path)`. Pact files live in `pacts/`
   (`<consumer>-<provider>.json`) and are committed. Providers verify with
   `Verifier("<provider>").message_handler({"<description>": producer_fn}).add_source(committed_pact(consumer, provider)).verify()`.
   Both sides' test BUILD targets depend on `pacts:<consumer>-<provider>`.
7. **Tests.** Unit tests use moto via a `conftest.py` fixture. Infra tests set
   `CDK_STUB_ASSETS=1` and use `aws_cdk.assertions.Template`. Integration tests
   use `testkit.aws.floci_endpoint` and are tagged `floci`.
8. **Lambda targets.** `python_aws_lambda_function(name=..., handler="<file>.py:handler", runtime="python3.13", architecture="arm64")`.
   CDK: `ServiceFunction(..., target_dir="apps/<app>/src/<app>", target_name="<name>")`.

## Running things

- Fast loop: `tools/dev-pytest.sh apps/<app>/tests` (plain pytest, all source roots on PYTHONPATH).
- Source of truth: `pants test apps/<app>::`, `pants lint check ::`.
- Floci tests: `docker compose up -d floci` then `FLOCI_ENDPOINT=http://localhost:4566 pants --tag=floci test ::`.
- Deploy: `tools/deploy.py --stage dev-<you> --apps <app>` (see README).
