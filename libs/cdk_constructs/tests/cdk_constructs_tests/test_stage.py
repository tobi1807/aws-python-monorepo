from __future__ import annotations

import aws_cdk as cdk
import pytest

from cdk_constructs.assets import lambda_zip_path
from cdk_constructs.stage import DEFAULT_FLOCI_RUNTIME_ENDPOINT, StageContext


def ctx(**context: str) -> StageContext:
    return StageContext.of(cdk.App(context=context), "orders")


def test_stage_is_required() -> None:
    with pytest.raises(ValueError, match="stage"):
        ctx()


def test_floci_defaults() -> None:
    c = ctx(stage="pr-3")
    assert c.on_floci and c.is_ephemeral and not c.is_prod
    assert c.runtime_env()["AWS_ENDPOINT_URL"] == DEFAULT_FLOCI_RUNTIME_ENDPOINT
    assert c.removal_policy == cdk.RemovalPolicy.DESTROY


def test_aws_target_has_no_endpoint_override() -> None:
    c = ctx(stage="prod", target="aws")
    assert "AWS_ENDPOINT_URL" not in c.runtime_env()
    assert c.removal_policy == cdk.RemovalPolicy.RETAIN
    assert c.use_canary


def test_canary_never_on_floci() -> None:
    assert not ctx(stage="prod").use_canary


def test_naming() -> None:
    assert ctx(stage="dev-tobi").name("table") == "dev-tobi-orders-table"


def test_unknown_target_rejected() -> None:
    with pytest.raises(ValueError):
        ctx(stage="prod", target="gcp")


def test_lambda_zip_path_matches_pants_dist_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPO_ROOT", "/repo")
    assert str(lambda_zip_path("apps/orders/src/orders", "api")) == (
        "/repo/dist/apps.orders.src.orders/api.zip"
    )
