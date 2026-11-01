from cdk_constructs.app import create_app, default_env, stack_name
from orders_infra.stack import OrdersStack

app, ctx = create_app("orders")
OrdersStack(app, stack_name(ctx), ctx=ctx, env=default_env())
app.synth()
