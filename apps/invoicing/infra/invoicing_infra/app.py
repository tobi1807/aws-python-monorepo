from cdk_constructs.app import create_app, default_env, stack_name
from invoicing_infra.stack import InvoicingStack

app, ctx = create_app("invoicing")
InvoicingStack(app, stack_name(ctx), ctx=ctx, env=default_env())
app.synth()
