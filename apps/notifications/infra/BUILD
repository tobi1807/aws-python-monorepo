# The CDK app is a PEX: the CDK CLI runs it (tools/deploy.py passes
# --app "python3 dist/apps.notifications.infra/cdk_app.pex").
pex_binary(
    name="cdk_app",
    entry_point="notifications_infra/app.py",
    execution_mode="venv",
)
