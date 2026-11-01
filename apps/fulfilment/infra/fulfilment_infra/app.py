from cdk_constructs.app import create_app, default_env, stack_name
from fulfilment_infra.stack import FulfilmentStack

app, ctx = create_app("fulfilment")
FulfilmentStack(app, stack_name(ctx), ctx=ctx, env=default_env())
app.synth()
