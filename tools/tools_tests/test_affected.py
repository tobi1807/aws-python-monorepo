from __future__ import annotations

import json
from pathlib import Path

import pytest

import affected

from .conftest import MakeRepo


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("apps/orders/src/orders/api.py", ["orders"]),
        ("apps/orders/src/orders:api", ["orders"]),
        ("//apps/catalog/infra:cdk_app", ["catalog"]),
        ("apps/orders/tests/orders_tests/unit:tests#test_api.py", ["orders"]),
        ("apps/order-items/src/order_items/h.py:../src", ["order-items"]),
        ("apps/orders", ["orders"]),
        ("libs/runtime/src/runtime/aws.py", []),
        ("pacts:orders-catalog", []),
        ("tools/affected.py", []),
        ("applications/orders/x.py", []),
        ("apps/", []),
        ("", []),
    ],
)
def test_single_address(address: str, expected: list[str]) -> None:
    assert affected.apps_from_addresses([address]) == expected


def test_addresses_are_sorted_and_unique() -> None:
    addresses = [
        "apps/orders/src/orders/api.py",
        "apps/catalog/src/catalog:fx",
        "libs/contracts/src/contracts/orders.py",
        "//apps/orders/infra:cdk_app",
        "apps/orders/src/orders:api",
    ]
    assert affected.apps_from_addresses(addresses) == ["catalog", "orders"]


def test_addresses_accept_any_iterable() -> None:
    assert affected.apps_from_addresses(iter(["apps/a/x.py"])) == ["a"]


@pytest.mark.parametrize(
    "path",
    [
        "pants.toml",
        "pants.ci.toml",
        "package.json",
        "package-lock.json",
        "ruff.toml",
        "pyproject.toml",
        ".github/workflows/pr.yml",
        ".github/workflows/main.yml",
        "3rdparty/python/default.lock",
        "./pants.toml",
    ],
)
def test_global_config_detected(path: str) -> None:
    assert affected.touches_global_config(["apps/orders/src/orders/api.py", path])


@pytest.mark.parametrize(
    "path",
    [
        "apps/orders/pyproject.toml",
        "apps/orders/package.json",
        "docs/pants.toml",
        ".github/CODEOWNERS",
        ".github/actions/setup/action.yml",
        "README.md",
        "tools/deploy.py",
    ],
)
def test_non_global_files_ignored(path: str) -> None:
    assert not affected.touches_global_config([path])


def test_touches_global_config_empty() -> None:
    assert not affected.touches_global_config([])


def test_deploy_toml_change_marks_app_affected() -> None:
    files = ["apps/orders/deploy.toml", "apps/orders/README.md", "apps/x/src/x/deploy.toml"]
    assert affected.apps_from_changed_files(files) == ["orders"]


def test_all_apps_requires_deploy_toml(make_repo: MakeRepo) -> None:
    root = make_repo(orders=["platform"], platform=[])
    (root / "apps" / "draft" / "src").mkdir(parents=True)
    assert affected.all_apps(root) == ["orders", "platform"]


def test_affected_apps_global_config_means_everything(
    make_repo: MakeRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(orders=[], platform=[])
    monkeypatch.setattr(affected, "git_changed_files", lambda since, root: ["pants.toml"])
    monkeypatch.setattr(
        affected, "pants_changed_addresses", lambda *a: pytest.fail("pants must not run")
    )
    assert affected.affected_apps("origin/main", root) == ["orders", "platform"]


def test_affected_apps_combines_pants_and_deploy_toml(
    make_repo: MakeRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_repo(orders=[], platform=[], catalog=[])
    monkeypatch.setattr(
        affected, "git_changed_files", lambda since, root: ["apps/catalog/deploy.toml"]
    )
    monkeypatch.setattr(
        affected,
        "pants_changed_addresses",
        lambda since, root: ["apps/orders/src/orders/api.py", "apps/deleted/src/x.py"],
    )
    assert affected.affected_apps("origin/main", root) == ["catalog", "orders"]


def test_cli_json_and_lines(
    make_repo: MakeRepo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(orders=[], platform=[])
    monkeypatch.setattr(affected, "git_changed_files", lambda since, root: [])
    monkeypatch.setattr(
        affected, "pants_changed_addresses", lambda since, root: ["apps/orders/infra:cdk_app"]
    )

    assert affected.main(["--since", "HEAD", "--root", str(root)]) == 0
    assert json.loads(capsys.readouterr().out) == {"apps": ["orders"], "count": 1}

    assert affected.main(["--since", "HEAD", "--format", "lines", "--root", str(root)]) == 0
    assert capsys.readouterr().out == "orders\n"


def test_cli_nothing_affected(
    make_repo: MakeRepo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root: Path = make_repo(orders=[])
    monkeypatch.setattr(affected, "git_changed_files", lambda since, root: [])
    monkeypatch.setattr(affected, "pants_changed_addresses", lambda since, root: [])
    affected.main(["--since", "HEAD", "--root", str(root)])
    assert json.loads(capsys.readouterr().out) == {"apps": [], "count": 0}


def test_cli_check_global(
    make_repo: MakeRepo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(orders=[])
    monkeypatch.setattr(affected, "git_changed_files", lambda since, root: ["pants.toml"])
    affected.main(["--since", "HEAD", "--check-global", "--root", str(root)])
    assert capsys.readouterr().out.strip() == "true"
    monkeypatch.setattr(affected, "git_changed_files", lambda since, root: ["README.md"])
    affected.main(["--since", "HEAD", "--check-global", "--root", str(root)])
    assert capsys.readouterr().out.strip() == "false"
