"""Cross-app wiring through SSM Parameter Store.

``export_param`` publishes a value other apps may need.

Prefer runtime lookups (``runtime.config.get_config``) for anything app code
needs. Use ``import_param`` only when CloudFormation itself needs the value
(an IAM policy resource, a Step Functions task target): that creates a
*deploy-time* dependency, so the providing app must be listed in this app's
``deploy.toml`` ``depends_on``. ``tools/deploy_plan.py --check`` enforces it.
"""

from __future__ import annotations

from aws_cdk import aws_ssm as ssm
from constructs import Construct

from cdk_constructs.stage import StageContext


def param_path(stage: str, app: str, key: str) -> str:
    return f"/{stage}/{app}/{key}"


def export_param(scope: Construct, ctx: StageContext, key: str, value: str) -> ssm.StringParameter:
    return ssm.StringParameter(
        scope,
        f"Export-{key}",
        parameter_name=param_path(ctx.stage, ctx.app, key),
        string_value=value,
    )


def import_param(scope: Construct, ctx: StageContext, from_app: str, key: str) -> str:
    """Deploy-time import. ``from_app`` must be in this app's deploy.toml depends_on."""
    return ssm.StringParameter.value_for_string_parameter(
        scope, param_path(ctx.stage, from_app, key)
    )
