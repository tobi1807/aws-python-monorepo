# The CDK app is a PEX: the CDK CLI runs it (tools/deploy.py passes
# --app "python3 dist/apps.catalog.infra/cdk_app.pex"). Pants owns its deps, so
# a change to libs/cdk_constructs marks this app as affected.
# venv execution mode unpacks the PEX into a real virtualenv, so the schema and
# VTL files (declared as resources in catalog_infra/BUILD) are plain files that
# `Path(__file__).parent` can find.
pex_binary(
    name="cdk_app",
    entry_point="catalog_infra/app.py",
    execution_mode="venv",
)
