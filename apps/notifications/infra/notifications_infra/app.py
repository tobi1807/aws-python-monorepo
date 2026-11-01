from cdk_constructs.app import create_app, default_env, stack_name
from notifications_infra.stack import NotificationsStack

app, ctx = create_app("notifications")
NotificationsStack(app, stack_name(ctx), ctx=ctx, env=default_env())
app.synth()
