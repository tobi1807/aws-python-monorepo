python_sources()

# One zip per Lambda handler. Dependency inference means the zip contains only
# modules this handler actually imports (plus their third-party deps).
python_aws_lambda_function(
    name="api",
    handler="api.py:handler",
    runtime="python3.13",
    architecture="x86_64",
)
