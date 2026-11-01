from __future__ import annotations

import json
from pathlib import Path

import pytest

import deploy_plan

from .conftest import MakeRepo

MANIFESTS = {
    "platform": [],
    "orders": ["platform"],
    "catalog": ["platform"],
    "invoicing": ["orders", "catalog"],
    "standalone": [],
}


def test_load_manifests(make_repo: MakeRepo) -> None:
    root = make_repo(orders=["platform"], platform=[])
    assert deploy_plan.load_manifests(root) == {"orders": ["platform"], "platform": []}


def test_load_manifests_missing_key_means_no_deps(tmp_path: Path) -> None:
    (tmp_path / "apps" / "a").mkdir(parents=True)
    (tmp_path / "apps" / "a" / "deploy.toml").write_text("# nothing\n")
    assert deploy_plan.load_manifests(tmp_path) == {"a": []}


def test_load_manifests_rejects_bad_shape(tmp_path: Path) -> None:
    (tmp_path / "apps" / "a").mkdir(parents=True)
    (tmp_path / "apps" / "a" / "deploy.toml").write_text('depends_on = "platform"\n')
    with pytest.raises(deploy_plan.PlanError, match="must be a list"):
        deploy_plan.load_manifests(tmp_path)


def test_closure_is_transitive_and_includes_apps() -> None:
    assert deploy_plan.closure(MANIFESTS, ["invoicing"]) == {
        "invoicing",
        "orders",
        "catalog",
        "platform",
    }
    assert deploy_plan.closure(MANIFESTS, ["standalone"]) == {"standalone"}


def test_waves_with_deps_adds_closure() -> None:
    assert deploy_plan.waves(MANIFESTS, ["invoicing"], with_deps=True) == [
        ["platform"],
        ["catalog", "orders"],
        ["invoicing"],
    ]


def test_waves_without_deps_only_selected() -> None:
    assert deploy_plan.waves(MANIFESTS, ["orders", "catalog"], with_deps=False) == [
        ["catalog", "orders"]
    ]


def test_waves_without_deps_still_orders_selected_apps() -> None:
    assert deploy_plan.waves(MANIFESTS, ["invoicing", "orders"], with_deps=False) == [
        ["orders"],
        ["invoicing"],
    ]


def test_order_constrains_across_unselected_intermediate() -> None:
    # invoicing -> orders -> platform; orders isn't deployed but platform must still go first.
    assert deploy_plan.waves(MANIFESTS, ["invoicing", "platform"], with_deps=False) == [
        ["platform"],
        ["invoicing"],
    ]


def test_waves_dedupes_and_sorts() -> None:
    assert deploy_plan.waves(
        MANIFESTS, ["standalone", "platform", "standalone"], with_deps=False
    ) == [["platform", "standalone"]]


def test_unknown_app() -> None:
    with pytest.raises(deploy_plan.PlanError, match="unknown app 'nope'"):
        deploy_plan.waves(MANIFESTS, ["nope"], with_deps=False)


def test_unknown_dependency() -> None:
    manifests = {"orders": ["ghost"]}
    with pytest.raises(deploy_plan.PlanError, match="depends on unknown app 'ghost'"):
        deploy_plan.waves(manifests, ["orders"], with_deps=True)
    with pytest.raises(deploy_plan.PlanError, match="unknown app 'ghost'"):
        deploy_plan.waves(manifests, ["orders"], with_deps=False)


def test_cycle_names_the_cycle() -> None:
    manifests = {"a": ["b"], "b": ["c"], "c": ["a"], "d": []}
    with pytest.raises(deploy_plan.PlanError, match="dependency cycle") as info:
        deploy_plan.waves(manifests, ["a"], with_deps=False)
    message = str(info.value)
    assert all(name in message for name in ("a", "b", "c"))
    assert " -> " in message


def test_self_dependency_is_a_cycle() -> None:
    with pytest.raises(deploy_plan.PlanError, match="a -> a"):
        deploy_plan.waves({"a": ["a"]}, ["a"], with_deps=False)


# ------------------------------------------------------------------ check()

IMPORT = 'x = import_param(self, ctx, "{app}", "{key}")\n'


def write_infra(root: Path, app: str, source: str) -> None:
    (root / "apps" / app / "infra" / f"{app}_infra" / "stack.py").write_text(source)


def test_check_ok(make_repo: MakeRepo) -> None:
    root = make_repo(orders=["platform"], platform=[])
    write_infra(root, "orders", IMPORT.format(app="platform", key="bus"))
    assert deploy_plan.check(root) == []


def test_check_reports_undeclared_import_param(make_repo: MakeRepo) -> None:
    root = make_repo(orders=["platform"], platform=[], catalog=[])
    write_infra(root, "orders", "# header\n" + IMPORT.format(app="catalog", key="table-name"))
    problems = deploy_plan.check(root)
    assert len(problems) == 1
    assert "stack.py:2" in problems[0]
    assert "'catalog'" in problems[0]
    assert "apps/orders/deploy.toml" in problems[0]


def test_check_handles_multiline_calls_and_single_quotes(make_repo: MakeRepo) -> None:
    root = make_repo(orders=[], catalog=[])
    write_infra(
        root,
        "orders",
        "y = import_param(\n    self,\n    ctx,\n    'catalog',\n    'k',\n)\n",
    )
    assert len(deploy_plan.check(root)) == 1


def test_check_ignores_comments_and_own_params(make_repo: MakeRepo) -> None:
    root = make_repo(orders=[], catalog=[])
    write_infra(
        root,
        "orders",
        "# import_param(self, ctx, 'catalog', 'k')\n" + IMPORT.format(app="orders", key="k"),
    )
    assert deploy_plan.check(root) == []


def test_check_reports_unknown_depends_on(make_repo: MakeRepo) -> None:
    root = make_repo(orders=["ghost"])
    problems = deploy_plan.check(root)
    assert problems == ["apps/orders/deploy.toml: depends_on 'ghost' is not an app"]


def test_check_reports_infra_without_manifest(make_repo: MakeRepo) -> None:
    root = make_repo(orders=[])
    (root / "apps" / "draft" / "infra").mkdir(parents=True)
    assert deploy_plan.check(root) == ["apps/draft: has infra/ but no deploy.toml"]


def test_check_reports_cycles(make_repo: MakeRepo) -> None:
    root = make_repo(a=["b"], b=["a"])
    problems = deploy_plan.check(root)
    assert any("dependency cycle" in p for p in problems)


# ------------------------------------------------------------------ CLI


def test_cli_prints_waves(make_repo: MakeRepo, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_repo(orders=["platform"], platform=[])
    assert deploy_plan.main(["--apps", "orders", "--with-deps", "--root", str(root)]) == 0
    assert capsys.readouterr().out.splitlines() == ["wave 1: platform", "wave 2: orders"]


def test_cli_json(make_repo: MakeRepo, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_repo(orders=["platform"], platform=[])
    deploy_plan.main(["--apps", "orders", "--with-deps", "--json", "--root", str(root)])
    assert json.loads(capsys.readouterr().out) == {"waves": [["platform"], ["orders"]]}


def test_cli_error_exit_code(make_repo: MakeRepo, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_repo(orders=[])
    assert deploy_plan.main(["--apps", "nope", "--root", str(root)]) == 2
    assert "unknown app" in capsys.readouterr().err


def test_cli_check_exit_codes(make_repo: MakeRepo, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_repo(orders=["platform"], platform=[], catalog=[])
    assert deploy_plan.main(["--check", "--root", str(root)]) == 0
    write_infra(root, "orders", IMPORT.format(app="catalog", key="k"))
    assert deploy_plan.main(["--check", "--root", str(root)]) == 1
    assert "catalog" in capsys.readouterr().err
