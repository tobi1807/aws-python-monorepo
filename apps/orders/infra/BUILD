# The CDK app is a PEX: the CDK CLI runs it (tools/deploy.py passes
# --app "python3 dist/apps.orders.infra/cdk_app.pex"). Pants owns its deps, so
# a change to libs/cdk_constructs marks this app as affected.
pex_binary(
    name="cdk_app",
    entry_point="orders_infra/app.py",
)
