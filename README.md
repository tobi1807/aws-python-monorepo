# aws-python-monorepo

An experiment in the "gold standard" setup for a monorepo of Python AWS
microservices: **Pants** builds and tests, **one CDK app per service**,
affected-only CI, contract tests with **Pact**, and **Floci** (an open-source
AWS emulator) standing in for every environment, including production.

Six services exercise a broad slice of AWS: AppSync with VTL resolvers, API
Gateway, Lambda, Step Functions, ECS Fargate, EventBridge, SQS, DynamoDB, S3,
SSM, Secrets Manager and AppConfig.

## The system

```
                  ┌──────────── platform ────────────┐
                  │ EventBridge bus · AppConfig flags │
                  └───────────────┬──────────────────┘
 HTTP ─► orders (API GW + Lambda) │
           │  OrderPlaced ────────┤
           ▼                      ▼
        DynamoDB          fulfilment: SQS ─► intake λ ─► Step Functions
                              ReserveStock (DynamoDB) → ChargePayment (λ + Secrets Manager)
                              → RenderInvoice (ECS Fargate task from invoicing → S3)
                              → PublishResult (λ)
                                  │  OrderFulfilled / OrderFulfilmentFailed
                                  ▼
                          notifications: SQS ─► notify λ ─► S3 outbox (+ presigned invoice link)

 GraphQL ─► catalog (AppSync: VTL resolvers → DynamoDB, Lambda field resolvers, S3 uploads)
```

| App | What it shows | Deploy-time deps |
|---|---|---|
| `platform` | Shared bus, AppConfig feature flags | — |
| `orders` | API Gateway HTTP API, Powertools router, DynamoDB, feature flag, publishes `OrderPlaced` | platform |
| `catalog` | AppSync, VTL resolvers, Lambda resolvers, Secrets Manager, presigned S3 | platform |
| `invoicing` | ECS Fargate task built from a Pants pex, S3 | platform |
| `fulfilment` | EventBridge → SQS → Lambda → Step Functions (DynamoDB, Lambda, ECS `.sync`) | platform, invoicing |
| `notifications` | EventBridge → SQS → Lambda batch processing, S3 | platform |

Each app has its own README.

## Quick start

Needs Python 3.13, Node 22, Docker.

```bash
curl --proto '=https' --tlsv1.2 -fsSL https://static.pantsbuild.org/setup/get-pants.sh | bash
npm ci
tools/install-hooks.sh                    # pre-push: lint/check/test what you changed

pants test ::                             # everything (Floci tests skip)
docker compose up -d floci                # local Floci on :4566
FLOCI_ENDPOINT=http://localhost:4566 pants --tag=floci test ::

python3 tools/deploy.py --stage dev-$USER --all       # deploy everything to local Floci
```

## Repo layout

```
apps/<app>/          one microservice: src/ (runtime), infra/ (its own CDK app), tests/, deploy.toml
libs/contracts       Pydantic event models — one module per producer
libs/runtime         boto3 clients, SSM config, secrets, events, feature flags
libs/cdk_constructs  StageContext, ServiceFunction, SSM wiring, Pants asset lookup
libs/testkit         moto/Floci fixtures, brokerless Pact helpers
pacts/               committed consumer contracts (<consumer>-<provider>.json)
tools/               affected detection, deploy planner, hash gate, deploy orchestrator
templates/app        copier template for new services (tools/new-app.sh <name>)
docs/                CONVENTIONS.md, EXPERIMENTS.md
```

## Key decisions

- **One Pants resolve.** Every app runs the same dependency versions
  (`3rdparty/python/requirements.txt`). Pants dependency inference works per
  file, so the graph is narrow: editing `contracts/fulfilment.py` affects only
  `fulfilment` and `notifications`.
- **One CDK app per service.** Each app's CDK code is a Pants `pex_binary`
  that the CDK CLI runs. CDK never builds Python: it points at Pants-built
  zips in `dist/`.
- **No cross-app CloudFormation references.** Apps publish values to SSM
  (`/{stage}/{app}/{key}`) and look each other up at runtime. That makes most
  apps independently deployable. The rare deploy-time dependency (e.g.
  fulfilment's Step Functions needs invoicing's ECS task) uses `import_param`
  and must be declared in `deploy.toml`; `tools/deploy_plan.py --check` enforces this.
- **Deploy order is computed, not maintained.** `deploy.toml` manifests become
  parallel waves via `graphlib` (`tools/deploy_plan.py`).
- **Affected ≠ deployed.** `tools/affected.py` finds candidates. The hash gate
  (`tools/artifact_hash.py`) skips any app whose synthesized template didn't
  change. Asset hashes live in the template, so this also catches code changes.
- **Pact without a broker.** Pact files are committed. Each one is a Pants
  target that both consumer and provider tests depend on, so changing a
  consumer's expectations re-runs the provider's verification in the same PR.
- **Floci is every environment.** `dev-<you>` is your local Floci. A PR stage
  is a fresh Floci service container in the CI job (affected apps plus their
  `depends_on` closure). `prod` is a long-lived Floci with persistent storage
  (`docker compose --profile prod up -d`, port 4567). Application code never
  branches on Floci vs AWS; `AWS_ENDPOINT_URL` handles it. Infra only checks
  `ctx.on_floci` for things Floci lacks (CodeDeploy canaries are on only for `--target aws`).

## CI

| Workflow | Jobs |
|---|---|
| `pr.yml` (PRs + merge queue) | `plan` (affected apps) · `checks` (lint, pyright, unit/infra/contract tests for affected targets) · `synth` (build + synth affected apps) · `floci-tests` · `pr-stage` (deploy affected + deps to a throwaway Floci, then e2e tests) |
| `main.yml` (push to main) | checks, then deploy affected apps to prod Floci on a self-hosted runner, with the hash gate |

Remote caching: `pants.ci.toml` uses the GitHub Actions cache. `pants.cache.toml`
plus `docker compose --profile cache up -d` runs bazel-remote **backed by S3**
(Floci's S3, standing in for a real bucket). This is the AWS-native option to
benchmark (docs/EXPERIMENTS.md #3).

## Day-to-day commands

| Task | Command |
|---|---|
| Test one app | `pants test apps/orders::` |
| Watch mode | `pants --loop test apps/orders::` |
| What does my branch affect? | `python3 tools/affected.py --since origin/main --format lines` |
| Deploy one app (+ deps) to your stage | `python3 tools/deploy.py --stage dev-$USER --apps fulfilment --with-deps` |
| Fast code-only redeploy | `python3 tools/deploy.py --stage dev-$USER --apps orders --hotswap` |
| Validate infra without deploying | `python3 tools/deploy.py --stage dev-$USER --all --synth-only` |
| Update committed pacts | `tools/update-pacts.sh` |
| New service | `tools/new-app.sh payments` |
| IDE virtualenv | `pants export --resolve=python-default` |

## Status of this experiment

Verified here: `pants tailor --check`, `lint`, `check` (pyright) and `test`
are all green (265 tests). All six CDK apps build and synthesize. Pact
verification passes in both directions. Affected detection was measured
(docs/EXPERIMENTS.md #1).

Not yet verified, because it needs a Docker daemon: anything running *on*
Floci. That covers deploys, the `floci`/`e2e`-tagged tests, VTL evaluation,
ECS `.sync` from Step Functions, and the S3-backed cache. Run experiment 4
first; it tells you which parts of Floci to trust.
