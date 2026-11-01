python_requirements(
    name="reqs",
    source="requirements.txt",
    module_mapping={
        "aws-lambda-powertools": ["aws_lambda_powertools"],
        "aws-cdk-lib": ["aws_cdk"],
        "pact-python": ["pact"],
    },
    overrides={
        # Powertools utilities (feature flags, parameters, batch) import boto3 at
        # runtime but don't declare it, because Lambda ships boto3. Make it explicit
        # so tests and packaged artifacts always get it.
        "aws-lambda-powertools": {"dependencies": [":reqs#boto3"]},
    },
)
