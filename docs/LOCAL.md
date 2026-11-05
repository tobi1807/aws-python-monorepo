# Running Floci locally

Floci is the AWS emulator that stands in for every environment (dev, PR stage, "prod").
Everything below goes through one script: `tools/floci.sh`.

> Prefer short commands? `just --list` shows wrappers (`just up`, `just deploy`, `just e2e`...). Each is one line calling the scripts below.

## Prerequisites
- Docker (Desktop or Engine) running. Floci spawns Lambda/ECS/ECR as real containers via the Docker socket.
- Node 22 + `npm ci` (CDK CLI), Python 3.13, `pants` (installed via the Pants launcher).
- Check it all: `tools/floci.sh doctor`

## 60-second loop
```bash
tools/floci.sh up                    # Floci on http://localhost:4566, in-memory (clean slate each `up`)
eval "$(tools/floci.sh env)"         # AWS_ENDPOINT_URL, dummy creds, region eu-west-2, STAGE=dev-$USER
tools/floci.sh deploy                # all apps -> stage dev-$USER, in dependency waves (~1.5 min cold)
tools/floci.sh deploy --stage dev-$USER --apps orders --hotswap   # fast inner loop for one app
tools/floci.sh test                  # integration tests tagged `floci`
pants --tag=e2e test apps/orders::   # e2e against what you deployed
tools/floci.sh reset                 # wipe state and start fresh
tools/floci.sh down
```
Extra args to `deploy` go straight to `tools/deploy.py` (see `--help`: `--apps`, `--affected-since`,
`--with-deps`, `--synth-only`, `--hotswap`). Extra args to `test` go to pants (e.g. `apps/catalog::`).

## "Prod" locally
`tools/floci.sh up --prod` starts a persistent Floci on :4567 (state in `.floci-data/`).
Deploy to it with `tools/floci.sh deploy --prod --stage prod --all`; point your shell at it with
`eval "$(tools/floci.sh env --prod)"`. Other commands take `--prod` too (`status`, `logs`, `down`).

## Using it from your own code / the AWS CLI
```bash
eval "$(tools/floci.sh env)"
aws s3 ls                            # AWS CLI v2 honours AWS_ENDPOINT_URL
aws dynamodb list-tables
```
boto3 >= 1.40 also honours `AWS_ENDPOINT_URL`, so app code needs no changes.

## Gotchas
- **Docker network:** Floci and the containers it spawns share `floci-net` (created by compose). Lambdas reach
  Floci as `http://floci:4566`; that's why `deploy` passes `--runtime-endpoint`.
- **Apple Silicon:** Lambdas are built x86_64 and run under emulation. Slower, but identical to CI.
- **Known Floci gaps** (docs/EXPERIMENTS.md #4): no AppSync `EvaluateMappingTemplate` (VTL test self-skips),
  no CDK custom-resource Lambdas (so no `auto_delete_objects`), functions run on the host architecture.
- **Port clash:** something already on 4566? Stop LocalStack or edit the port mapping in `docker-compose.yml`.
- **Stuck state:** `tools/floci.sh reset`. If containers linger: `docker ps -a --filter name=floci`, then `docker rm -f`.
- **Logs:** `tools/floci.sh logs -f`.
