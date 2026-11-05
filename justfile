# Task menu. Every recipe is one line that calls an existing script: no logic lives here.
#   just --list        (install: brew install just | cargo install just | https://just.systems)

set shell := ["bash", "-euo", "pipefail", "-c"]

base := env_var_or_default("BASE_REF", "origin/main")
stage := "dev-" + env_var_or_default("USER", "me")

default:
    @just --list

# --- Floci (local AWS) ---
up:
    tools/floci.sh up
down:
    tools/floci.sh down
reset:
    tools/floci.sh reset
logs:
    tools/floci.sh logs -f
doctor:
    tools/floci.sh doctor

# Deploy to local Floci. `just deploy` = all apps; `just deploy orders` = one app (hotswap)
deploy *apps:
    if [ -z "{{apps}}" ]; then tools/floci.sh deploy --stage {{stage}} --all; else tools/floci.sh deploy --stage {{stage}} --apps {{replace(apps, " ", ",")}} --hotswap; fi

# --- Checks ---
fmt:
    pants fmt ::
lint:
    pants lint check ::
# Unit/infra/contract tests; pass targets to narrow: `just test apps/orders::`
test *targets="::":
    pants --tag=-floci --tag=-e2e test {{targets}}
# Only what changed vs. main (same as CI's `checks`)
affected:
    tools/ci-pants.sh {{base}} --tag=-floci --tag=-e2e lint check test
# Floci integration tests (needs `just up`)
integration *targets="::":
    tools/floci.sh test {{targets}}
# Whole PR-stage flow locally: fresh Floci, deploy affected + deps, e2e, tear down
e2e: reset
    python3 tools/deploy.py --stage {{stage}} --affected-since {{base}} --with-deps --endpoint http://localhost:4566 --runtime-endpoint http://floci:4566
    AWS_ENDPOINT_URL=http://localhost:4566 FLOCI_ENDPOINT=http://localhost:4566 pants --tag=e2e test ::
# Which apps does this change touch?
plan:
    python3 tools/affected.py --since {{base}}
# Refresh Pact files after changing a contract
pacts:
    tools/update-pacts.sh
