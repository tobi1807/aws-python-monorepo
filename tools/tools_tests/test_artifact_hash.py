from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import boto3
import pytest
from moto import mock_aws

import artifact_hash

TEMPLATE: dict[str, Any] = {
    "Resources": {
        "Fn": {"Type": "AWS::Lambda::Function", "Properties": {"Code": {"S3Key": "abc.zip"}}},
        "Table": {"Type": "AWS::DynamoDB::GlobalTable", "Properties": {"TableName": "t"}},
    }
}


def write_assembly(directory: Path, templates: dict[str, Any], indent: int | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, document in templates.items():
        (directory / f"{name}.template.json").write_text(json.dumps(document, indent=indent))
    (directory / "manifest.json").write_text(
        json.dumps({"noise": "ignored", "path": str(directory)})
    )
    return directory


@pytest.fixture
def ssm(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    with mock_aws():
        yield boto3.client("ssm")


# ------------------------------------------------------------------ template_hash


def test_hash_ignores_key_order_and_whitespace(tmp_path: Path) -> None:
    reordered = {"Resources": dict(reversed(list(TEMPLATE["Resources"].items())))}
    a = write_assembly(tmp_path / "a", {"dev-orders": TEMPLATE})
    b = write_assembly(tmp_path / "b", {"dev-orders": reordered}, indent=4)
    assert artifact_hash.template_hash(a) == artifact_hash.template_hash(b)


def test_hash_ignores_non_template_files(tmp_path: Path) -> None:
    a = write_assembly(tmp_path / "a", {"dev-orders": TEMPLATE})
    b = write_assembly(tmp_path / "b", {"dev-orders": TEMPLATE})
    (b / "manifest.json").write_text("different")
    (b / "asset.123").mkdir()
    (b / "asset.123" / "stray.template.json").write_text("{}")
    assert artifact_hash.template_hash(a) == artifact_hash.template_hash(b)


def test_hash_changes_with_content(tmp_path: Path) -> None:
    changed = json.loads(json.dumps(TEMPLATE))
    changed["Resources"]["Fn"]["Properties"]["Code"]["S3Key"] = "def.zip"
    a = write_assembly(tmp_path / "a", {"dev-orders": TEMPLATE})
    b = write_assembly(tmp_path / "b", {"dev-orders": changed})
    assert artifact_hash.template_hash(a) != artifact_hash.template_hash(b)


def test_hash_changes_with_stack_name_or_extra_stack(tmp_path: Path) -> None:
    base = artifact_hash.template_hash(write_assembly(tmp_path / "a", {"dev-orders": TEMPLATE}))
    renamed = write_assembly(tmp_path / "b", {"dev-orders2": TEMPLATE})
    extra = write_assembly(tmp_path / "c", {"dev-orders": TEMPLATE, "dev-extra": {}})
    assert artifact_hash.template_hash(renamed) != base
    assert artifact_hash.template_hash(extra) != base


def test_hash_without_templates_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(artifact_hash.NoTemplatesError):
        artifact_hash.template_hash(tmp_path)


def test_hash_is_hex_sha256(tmp_path: Path) -> None:
    value = artifact_hash.template_hash(write_assembly(tmp_path, {"s": TEMPLATE}))
    assert len(value) == 64
    int(value, 16)


# ------------------------------------------------------------------ SSM


def test_param_name() -> None:
    assert artifact_hash.param_name("prod", "orders") == "/deploy-hashes/prod/orders"


def test_fetch_missing_is_none(ssm: Any) -> None:
    assert artifact_hash.fetch_hash("prod", "orders") is None


def test_store_then_fetch_and_overwrite(ssm: Any) -> None:
    artifact_hash.store_hash("prod", "orders", "one")
    assert artifact_hash.fetch_hash("prod", "orders") == "one"
    artifact_hash.store_hash("prod", "orders", "two")
    assert artifact_hash.fetch_hash("prod", "orders") == "two"
    assert artifact_hash.fetch_hash("pr-1", "orders") is None


def test_should_deploy_lifecycle(ssm: Any, tmp_path: Path) -> None:
    out = write_assembly(tmp_path / "orders", {"prod-orders": TEMPLATE})
    assert artifact_hash.should_deploy("orders", "prod", out) is True
    artifact_hash.record("orders", "prod", out)
    assert artifact_hash.should_deploy("orders", "prod", out) is False
    # Other stage/app are independent.
    assert artifact_hash.should_deploy("orders", "pr-1", out) is True
    assert artifact_hash.should_deploy("catalog", "prod", out) is True

    changed = json.loads(json.dumps(TEMPLATE))
    changed["Resources"]["Fn"]["Properties"]["Code"]["S3Key"] = "new.zip"
    write_assembly(out, {"prod-orders": changed})
    assert artifact_hash.should_deploy("orders", "prod", out) is True


# ------------------------------------------------------------------ CLI


def test_cli_should_deploy_exit_codes(
    ssm: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = write_assembly(tmp_path / "orders", {"prod-orders": TEMPLATE})
    args = ["--app", "orders", "--stage", "prod", "--cdk-out", str(out)]

    assert artifact_hash.main(["should-deploy", *args]) == 0
    assert capsys.readouterr().out.strip() == "deploy"

    assert artifact_hash.main(["record", *args]) == 0
    capsys.readouterr()

    assert artifact_hash.main(["should-deploy", *args]) == artifact_hash.EXIT_SKIP == 10
    assert capsys.readouterr().out.strip() == "skip"


def test_cli_fails_open_when_ssm_unreachable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = write_assembly(tmp_path / "orders", {"prod-orders": TEMPLATE})

    def boom(*args: Any, **kwargs: Any) -> None:
        raise ConnectionError("no route to Floci")

    monkeypatch.setattr(artifact_hash, "fetch_hash", boom)
    code = artifact_hash.main(
        ["should-deploy", "--app", "orders", "--stage", "p", "--cdk-out", str(out)]
    )
    assert code == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "deploy"
    assert "no route" in captured.err


def test_cli_missing_assembly_is_an_error(tmp_path: Path) -> None:
    argv = ["should-deploy", "--app", "x", "--stage", "p", "--cdk-out", str(tmp_path / "none")]
    assert artifact_hash.main(argv) == 2
