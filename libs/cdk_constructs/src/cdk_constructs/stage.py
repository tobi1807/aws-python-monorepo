"""Stage/target context shared by every CDK app.

Context keys (pass with ``-c key=value``; ``tools/deploy.py`` sets them):
  stage                 required. "prod", "dev-<name>", "pr-<number>", ...
  target                "floci" (default) or "aws".
  runtime_endpoint_url  endpoint Lambda/ECS code uses to reach Floci from inside
                        its container. Ignored when target=aws.
"""

from __future__ import annotations

from dataclasses import dataclass

import aws_cdk as cdk
from constructs import Construct

DEFAULT_FLOCI_RUNTIME_ENDPOINT = "http://floci:4566"  # by name on floci-net


@dataclass(frozen=True)
class StageContext:
    app: str
    stage: str
    target: str
    runtime_endpoint_url: str | None

    @property
    def is_prod(self) -> bool:
        return self.stage == "prod"

    @property
    def is_ephemeral(self) -> bool:
        return self.stage.startswith(("pr-", "dev-"))

    @property
    def on_floci(self) -> bool:
        return self.target == "floci"

    @property
    def removal_policy(self) -> cdk.RemovalPolicy:
        return cdk.RemovalPolicy.RETAIN if self.is_prod else cdk.RemovalPolicy.DESTROY

    @property
    def use_canary(self) -> bool:
        """CodeDeploy traffic shifting: real AWS prod only (Floci has no CodeDeploy)."""
        return self.is_prod and not self.on_floci

    def name(self, resource: str) -> str:
        """Physical name for a resource: ``{stage}-{app}-{resource}``."""
        return f"{self.stage}-{self.app}-{resource}"

    def runtime_env(self) -> dict[str, str]:
        """Environment every Lambda function and container gets."""
        env = {"STAGE": self.stage, "POWERTOOLS_SERVICE_NAME": self.app}
        if self.on_floci and self.runtime_endpoint_url:
            env["AWS_ENDPOINT_URL"] = self.runtime_endpoint_url
        return env

    @classmethod
    def of(cls, scope: Construct, app: str) -> StageContext:
        node = scope.node
        stage = node.try_get_context("stage")
        if not stage:
            raise ValueError("Missing CDK context 'stage' (pass -c stage=<name>)")
        target = node.try_get_context("target") or "floci"
        if target not in ("floci", "aws"):
            raise ValueError(f"Unknown target {target!r}")
        endpoint = node.try_get_context("runtime_endpoint_url") or (
            DEFAULT_FLOCI_RUNTIME_ENDPOINT if target == "floci" else None
        )
        return cls(app=app, stage=stage, target=target, runtime_endpoint_url=endpoint)
