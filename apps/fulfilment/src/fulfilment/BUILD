python_sources()

# One zip per Lambda handler. Dependency inference means the zip contains only
# modules this handler actually imports (plus their third-party deps).
python_aws_lambda_function(
    name="intake",
    handler="intake.py:handler",
    runtime="python3.13",
    architecture="arm64",
)

python_aws_lambda_function(
    name="charge",
    handler="charge.py:handler",
    runtime="python3.13",
    architecture="arm64",
)

python_aws_lambda_function(
    name="publish_result",
    handler="publish_result.py:handler",
    runtime="python3.13",
    architecture="arm64",
)
