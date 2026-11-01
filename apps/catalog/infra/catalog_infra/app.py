from catalog_infra.stack import CatalogStack
from cdk_constructs.app import create_app, default_env, stack_name

app, ctx = create_app("catalog")
CatalogStack(app, stack_name(ctx), ctx=ctx, env=default_env())
app.synth()
