# The CDK app is a PEX: the CDK CLI runs it (tools/deploy.py passes
# --app "python3 dist/apps.platform.infra/cdk_app.pex"). venv mode unpacks the
# PEX so platform_infra/flags/features.json is a real file on disk at synth time.
pex_binary(
    name="cdk_app",
    entry_point="platform_infra/app.py",
    execution_mode="venv",
)
