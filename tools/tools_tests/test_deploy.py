from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Any

import pytest

import affected
import deploy

from .conftest import MakeRepo


class FakeRunner:
    """Replaces deploy.run_cmd: records commands, answers by matching the command text."""

    def __init__(self, responses: dict[str, tuple[int, str]] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.responses = responses or {}
        self._lock = threading.Lock()

    def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        with self._lock:
            self.calls.append(cmd)
        text = " ".join(cmd)
        for needle, (code, output) in self.responses.items():
            if needle in text:
                return subprocess.CompletedProcess(cmd, code, output, "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def matching(self, needle: str) -> list[str]:
        return [" ".join(c) for c in self.calls if needle in " ".join(c)]


@pytest.fixture
def repo(make_repo: MakeRepo) -> Path:
    return make_repo(platform=[], orders=["platform"], catalog=["platform"], invoicing=["orders"])


def plan_for(repo: Path, *argv: str) -> deploy.Plan:
    return deploy.make_plan(deploy.parse_args(["--root", str(repo), *argv]))


# ------------------------------------------------------------------ arguments


@pytest.mark.parametrize(
    "argv",
    [
        ["--stage", "Bad_Stage", "--apps", "a"],
        ["--stage", "x", "--apps", "a", "--all"],
        ["--stage", "x"],
        ["--stage", "prod", "--apps", "a", "--hotswap"],
        ["--stage", "x", "--apps", "a", "--target", "aws", "--endpoint", "http://x"],
        ["--stage", "x", "--apps", "a", "--parallel", "0"],
    ],
)
def test_invalid_arguments(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        deploy.parse_args(argv)


def test_runtime_endpoint_derivation() -> None:
    assert deploy.runtime_endpoint_for("http://localhost:4566") == "http://floci:4566"
    assert deploy.runtime_endpoint_for("http://127.0.0.1:4567") == "http://floci-prod:4566"
    assert deploy.runtime_endpoint_for("http://floci-prod.lan:4566") == "http://floci-prod.lan:4566"
    assert deploy.runtime_endpoint_for("http://localhost:1", "http://x:2") == "http://x:2"
    assert (
        deploy.runtime_endpoint_for("http://localhost:9000") == "http://host.docker.internal:9000"
    )


# ------------------------------------------------------------------ planning


def test_plan_apps_with_deps(repo: Path) -> None:
    plan = plan_for(repo, "--stage", "pr-1", "--apps", "invoicing", "--with-deps")
    assert plan.waves == (("platform",), ("orders",), ("invoicing",))
    assert plan.requested == ("invoicing",)
    assert plan.endpoint == "http://localhost:4566"


def test_plan_without_deps_is_just_the_apps(repo: Path) -> None:
    plan = plan_for(repo, "--stage", "prod", "--apps", "orders,catalog")
    assert plan.waves == (("catalog", "orders"),)


def test_plan_all(repo: Path) -> None:
    plan = plan_for(repo, "--stage", "dev-x", "--all")
    assert plan.waves == (("platform",), ("catalog", "orders"), ("invoicing",))


def test_plan_affected_since(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_affected(since: str, root: Path) -> list[str]:
        seen.append(since)
        return ["orders"]

    monkeypatch.setattr(affected, "affected_apps", fake_affected)
    plan = plan_for(repo, "--stage", "pr-9", "--affected-since", "origin/main", "--with-deps")
    assert seen == ["origin/main"]
    assert plan.waves == (("platform",), ("orders",))


def test_plan_nothing_affected(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(affected, "affected_apps", lambda since, root: [])
    plan = plan_for(repo, "--stage", "pr-9", "--affected-since", "x", "--with-deps")
    assert plan.apps == []


def test_plan_endpoint_from_flag_and_env(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://env:4566")
    assert plan_for(repo, "--stage", "x", "--apps", "platform").endpoint == "http://env:4566"
    plan = plan_for(
        repo, "--stage", "prod", "--apps", "platform", "--endpoint", "http://localhost:4567"
    )
    assert plan.endpoint == "http://localhost:4567"
    assert plan.runtime_endpoint == "http://floci-prod:4566"


def test_aws_target_has_no_endpoint(repo: Path) -> None:
    plan = plan_for(repo, "--stage", "x", "--apps", "platform", "--target", "aws")
    assert plan.endpoint is None
    assert deploy.bootstrap_cmd(plan) is None
    assert deploy.deploy_cmd(plan, "platform")[:3] == ["npx", "cdk", "deploy"]
    assert not any(a.startswith("runtime_endpoint_url") for a in deploy.synth_cmd(plan, "platform"))


# ------------------------------------------------------------------ commands


def test_commands(repo: Path) -> None:
    plan = plan_for(repo, "--stage", "pr-7", "--apps", "orders", "--hotswap")
    assert deploy.package_cmd(["platform", "orders"]) == [
        "pants",
        "--filter-target-type=-docker_image",
        "package",
        "apps/platform::",
        "apps/orders::",
    ]
    synth = deploy.synth_cmd(plan, "orders")
    assert synth[:5] == [
        "npx",
        "cdk",
        "synth",
        "--app",
        "python3 dist/apps.orders.infra/cdk_app.pex",
    ]
    assert "stage=pr-7" in synth
    assert "target=floci" in synth
    assert synth[-2:] == ["-o", "cdk.out/orders"]
    assert deploy.deploy_cmd(plan, "orders") == [
        "npx",
        "cdklocal",
        "deploy",
        "--app",
        "cdk.out/orders",
        "--require-approval",
        "never",
        "--hotswap",
    ]
    assert deploy.bootstrap_cmd(plan) == [
        "npx",
        "cdklocal",
        "bootstrap",
        "aws://000000000000/eu-west-2",
    ]
    assert deploy.gate_cmd(plan, "orders")[-7:] == [
        "should-deploy",
        "--app",
        "orders",
        "--stage",
        "pr-7",
        "--cdk-out",
        "cdk.out/orders",
    ]


def test_deploy_env_points_at_floci(repo: Path) -> None:
    plan = plan_for(repo, "--stage", "x", "--apps", "platform", "--endpoint", "http://h:4566")
    env = deploy.deploy_env(plan)
    assert env["AWS_ENDPOINT_URL"] == "http://h:4566"
    assert env["AWS_ACCESS_KEY_ID"] == env["AWS_SECRET_ACCESS_KEY"] == "test"
    assert env["AWS_DEFAULT_REGION"] == "eu-west-2"


def test_stage_docker_contexts(repo: Path) -> None:
    src = repo / "apps" / "orders" / "src" / "orders"
    src.mkdir(parents=True)
    (src / "Dockerfile").write_text("FROM scratch\n")
    built = repo / "dist" / "apps.orders.src.orders"
    built.mkdir(parents=True)
    (built / "worker.pex").write_text("pex")
    (built / "api.zip").write_text("zip")
    plan = plan_for(repo, "--stage", "x", "--apps", "orders,catalog")

    assert deploy.stage_docker_contexts(plan) == ["orders"]

    context = repo / "dist" / "docker" / "orders"
    staged = sorted(str(p.relative_to(context)) for p in context.rglob("*") if p.is_file())
    # Same layout as Pants' docker_image build context, so one Dockerfile serves both.
    assert staged == ["Dockerfile", "apps.orders.src.orders/worker.pex"]
    assert not (repo / "dist" / "docker" / "catalog").exists()


def test_kebab_case_app_uses_underscored_package(repo: Path) -> None:
    assert deploy.package_name("order-items") == "order_items"
    found = deploy.docker_context_files("order-items", repo)
    assert found is None


# ------------------------------------------------------------------ execution


def test_execute_runs_everything_in_order(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = FakeRunner()
    monkeypatch.setattr(deploy, "run_cmd", runner)
    plan = plan_for(repo, "--stage", "pr-1", "--apps", "orders", "--with-deps")

    results = deploy.execute(plan)

    assert [(r.app, r.wave, r.status) for r in results] == [
        ("platform", 1, "deployed"),
        ("orders", 2, "deployed"),
    ]
    assert len(runner.matching("pants --filter-target-type=-docker_image package")) == 1
    assert (
        runner.matching("pants --filter-target-type=-docker_image package")[0]
        == "pants --filter-target-type=-docker_image package apps/platform:: apps/orders::"
    )
    assert len(runner.matching("bootstrap")) == 1
    deploys = runner.matching("cdklocal deploy")
    assert [d.split()[4] for d in deploys] == ["cdk.out/platform", "cdk.out/orders"]
    assert len(runner.matching("artifact_hash.py record")) == 2


def test_unchanged_template_is_skipped(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = FakeRunner({"should-deploy --app platform": (10, "skip")})
    monkeypatch.setattr(deploy, "run_cmd", runner)
    plan = plan_for(repo, "--stage", "prod", "--apps", "platform,orders")

    results = {r.app: r.status for r in deploy.execute(plan)}

    assert results == {"platform": "skipped", "orders": "deployed"}
    assert [d for d in runner.matching("cdklocal deploy") if "platform" in d] == []
    assert [r for r in runner.matching("record") if "platform" in r] == []


def test_force_bypasses_the_gate(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = FakeRunner({"should-deploy": (10, "skip")})
    monkeypatch.setattr(deploy, "run_cmd", runner)
    plan = plan_for(repo, "--stage", "prod", "--apps", "platform", "--force")

    assert [r.status for r in deploy.execute(plan)] == ["deployed"]
    assert runner.matching("should-deploy") == []


def test_failure_stops_later_waves(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = FakeRunner({"cdklocal deploy --app cdk.out/platform": (1, "boom")})
    monkeypatch.setattr(deploy, "run_cmd", runner)
    plan = plan_for(repo, "--stage", "pr-1", "--apps", "invoicing", "--with-deps")

    results = deploy.execute(plan)

    assert [(r.app, r.status) for r in results] == [
        ("platform", "failed"),
        ("orders", "not-run"),
        ("invoicing", "not-run"),
    ]
    assert runner.matching("synth --app python3 dist/apps.orders") == []
    assert runner.matching("cdk.out/platform") != []
    assert runner.matching("record") == []


def test_synth_failure_is_failure(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deploy, "run_cmd", FakeRunner({"synth": (1, "bad stack")}))
    plan = plan_for(repo, "--stage", "x", "--apps", "platform")
    assert [r.status for r in deploy.execute(plan)] == ["failed"]


def test_build_failure_deploys_nothing(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = FakeRunner({"pants --filter-target-type=-docker_image package": (1, "")})
    monkeypatch.setattr(deploy, "run_cmd", runner)
    plan = plan_for(repo, "--stage", "x", "--apps", "orders", "--with-deps")

    assert [r.status for r in deploy.execute(plan)] == ["not-run", "not-run"]
    assert len(runner.calls) == 1


def test_failed_sibling_aborts_unstarted_apps(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = FakeRunner({"synth --app python3 dist/apps.catalog": (1, "x")})
    monkeypatch.setattr(deploy, "run_cmd", runner)
    plan = plan_for(repo, "--stage", "x", "--apps", "catalog,orders", "--parallel", "1")

    statuses = {r.app: r.status for r in deploy.execute(plan)}

    assert statuses == {"catalog": "failed", "orders": "not-run"}


def test_dry_run_runs_nothing(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(deploy, "run_cmd", lambda *a, **k: pytest.fail("subprocess in dry run"))
    code = deploy.main(
        ["--root", str(repo), "--stage", "dev-t", "--apps", "orders", "--with-deps", "--dry-run"]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "wave 1: platform (dependency)" in out
    assert "wave 2: orders" in out
    assert "pants --filter-target-type=-docker_image package apps/platform:: apps/orders::" in out
    assert "cdklocal bootstrap" in out
    assert out.index("cdk.out/platform") < out.index("cdk.out/orders")
    assert "planned" in out
    assert not (repo / "dist").exists()


def test_main_unknown_app(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = deploy.main(["--root", str(repo), "--stage", "x", "--apps", "nope", "--dry-run"])
    assert code == 2
    assert "unknown app" in capsys.readouterr().err


def test_main_nothing_to_deploy(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(affected, "affected_apps", lambda since, root: [])
    monkeypatch.setattr(deploy, "run_cmd", lambda *a, **k: pytest.fail("nothing to run"))
    code = deploy.main(["--root", str(repo), "--stage", "x", "--affected-since", "main"])
    assert code == 0
    assert "No apps to deploy" in capsys.readouterr().out


def test_main_exit_code_and_summary(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(deploy, "run_cmd", FakeRunner({"cdklocal deploy": (1, "nope")}))
    code = deploy.main(["--root", str(repo), "--stage", "x", "--apps", "platform"])
    out = capsys.readouterr().out
    assert code == 1
    assert "failed" in out


def test_summary_table_alignment() -> None:
    table = deploy.summary_table(
        [
            deploy.Result("platform", 1, "deployed", 12.34),
            deploy.Result("orders", 2, "skipped", 0.5),
        ]
    )
    lines = table.splitlines()
    assert lines[0].split() == ["app", "wave", "result", "seconds", "detail"]
    assert lines[2].split()[:4] == ["platform", "1", "deployed", "12.3"]
    assert lines[3].split()[:4] == ["orders", "2", "skipped", "0.5"]


def test_synth_only_never_bootstraps_or_deploys(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeRunner()
    monkeypatch.setattr(deploy, "run_cmd", runner)
    plan = plan_for(repo, "--stage", "pr-1", "--apps", "orders", "--with-deps", "--synth-only")

    assert [r.status for r in deploy.execute(plan)] == ["synthesized", "synthesized"]
    assert runner.matching("synth") != []
    assert runner.matching("bootstrap") == []
    assert runner.matching(" deploy ") == []
    assert runner.matching("record") == []
