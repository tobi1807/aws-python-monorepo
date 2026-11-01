# Experiments

Each experiment has a question, how to run it, and what to record. Results go
in the table at the bottom so decisions are backed by numbers from *this* repo.

## 1. Affected-only CI accuracy
**Question:** does a change rebuild/deploy exactly the apps it should?
- Edit `libs/contracts/src/contracts/fulfilment.py` → expect `fulfilment`, `notifications` (and nothing that only imports `contracts.orders`).
- Edit `libs/contracts/src/contracts/orders.py` → expect `orders`, `fulfilment`, `invoicing`.
- Edit `libs/runtime/src/runtime/flags.py` → expect only apps importing `runtime.flags`.
- Edit a pact file → expect both the consumer and provider.
```
python3 tools/affected.py --since HEAD~1 --format lines
```
**Record:** expected vs actual apps per change. Any surprise is either a real
dependency or a barrel import to remove.

## 2. Fan-out vs artifact-hash gate
**Question:** how many "affected" apps actually produce a different deployable?
- Change a docstring in `libs/runtime/src/runtime/config.py`, then
  `python3 tools/deploy.py --stage dev-$USER --affected-since HEAD~1` twice.
**Record:** affected count vs deployed count, and whether Pants zips are
byte-reproducible across two `pants package` runs (`sha256sum dist/**/*.zip`).
If they aren't, the template hash still changes — note it as a follow-up.

## 3. Remote cache: none vs GitHub Actions vs S3-backed bazel-remote
**Question:** what does each cache buy in CI wall-clock time?
- Local S3-backed run: `docker compose --profile cache up -d` then
  `PANTS_CONFIG_FILES=pants.cache.toml pants test ::` twice (second run should be ~all cache hits).
- Clear local cache between runs to simulate a fresh CI runner:
  `rm -rf ~/.cache/pants/lmdb_store`.
- In CI, compare the `checks` job duration with `remote_cache_read=false` vs the GHA cache.
**Record:** cold, warm-local, warm-remote durations; cache hit rate from Pants
stats (`[stats] log = true`).

## 4. Floci fidelity per service
**Question:** which AWS behaviours can we trust Floci for?
- `docker compose up -d floci`, then `FLOCI_ENDPOINT=http://localhost:4566 pants --tag=floci test ::`.
- Then a full deploy: `python3 tools/deploy.py --stage dev-$USER --all`.
**Record per service** (AppSync+VTL evaluation, Step Functions ECS `.sync`,
EventBridge → SQS, AppConfig data API, API Gateway HTTP API, Lambda in Docker,
ECS Fargate tasks, SSM, Secrets Manager): works / partial / missing. This
tells you which test layer must cover what once real AWS exists.

## 5. PR-stage time budget
**Question:** can a PR stage be ready in under 10 minutes?
- Time `tools/deploy.py --stage pr-test --affected-since origin/main --with-deps`
  against a fresh Floci for: one leaf app (`notifications`), a mid app
  (`fulfilment`, which pulls in `invoicing` + `platform`), and `--all`.
- Repeat with `--hotswap` on an already-deployed stage after a code-only change.
**Record:** seconds per app/wave; where time goes (package, synth, deploy).

## 6. Lambda artifact size
**Question:** how big are zips, and is excluding boto3 worth it?
- `pants package apps/*/src::` then `ls -la dist/*/*.zip`.
- The Lambda runtime already ships boto3/botocore; try excluding them and
  compare size and cold start on Floci.
**Record:** size per function, cold start with and without boto3 bundled.

## 7. Pact without a broker
**Question:** does committing pacts in the monorepo give the same safety as a broker?
- Break a contract: change `fulfilment`'s consumer expectations (e.g. require a
  new field) and run `tools/update-pacts.sh` → `orders` provider verification
  should fail in the same PR.
- Make an additive change to `OrderPlaced` → nothing fails.
**Record:** whether every breaking change was caught before merge.

## 8. Synth time per app
**Question:** does one-CDK-app-per-service keep synth fast as the repo grows?
- `time npx cdk synth --app "python3 dist/apps.<app>.infra/cdk_app.pex" -c stage=dev -o cdk.out/<app> --quiet` per app.
**Record:** seconds per app. Target: under 20s each (jsii start-up dominates).

## Results

| # | Date | Result | Decision |
|---|------|--------|----------|
| 1 | | | |
| 2 | | | |
| 3 | | | |
| 4 | | | |
| 5 | | | |
| 6 | | | |
| 7 | | | |
| 8 | | | |
