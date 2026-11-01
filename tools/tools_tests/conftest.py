"""Shared fixtures: a throwaway repo layout with fake apps."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

MakeRepo = Callable[..., Path]


@pytest.fixture
def make_repo(tmp_path: Path) -> MakeRepo:
    """``make_repo(orders=["platform"], platform=[])`` writes apps/<app>/deploy.toml files."""

    def _make(**apps: list[str]) -> Path:
        for app, deps in apps.items():
            app_dir = tmp_path / "apps" / app
            (app_dir / "infra" / f"{app}_infra").mkdir(parents=True, exist_ok=True)
            deps_toml = ", ".join(f'"{d}"' for d in deps)
            (app_dir / "deploy.toml").write_text(f"depends_on = [{deps_toml}]\n")
        return tmp_path

    return _make
