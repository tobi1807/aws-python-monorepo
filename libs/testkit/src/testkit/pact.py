"""Pact without a broker: pact files are committed to ``pacts/`` in the monorepo.

Why: in a monorepo consumer and provider change in the same commit, so the
"broker" is just the repo. Each pact file is a Pants ``file`` target that both
sides depend on, so when a consumer changes its expectations the pact file
changes and the *provider's* verification test becomes affected too —
affected-only CI then re-verifies exactly the right providers.

Consumer tests call ``check_consumer_pact``:
- normally: the generated pact must equal the committed one (drift = failure)
- with ``PACT_UPDATE=1`` (``tools/update-pacts.sh``): rewrite the committed file
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pact import Pact

os.environ.setdefault("PACT_DO_NOT_TRACK", "true")

PACTS_DIR = Path("pacts")


def pact_filename(consumer: str, provider: str) -> str:
    return f"{consumer}-{provider}.json"


def _normalise(doc: dict[str, Any]) -> dict[str, Any]:
    """Drop fields that vary between runs/versions so comparisons are stable."""
    doc = dict(doc)
    doc.pop("metadata", None)
    interactions = []
    for interaction in doc.get("interactions", []):
        interaction = dict(interaction)
        interaction.pop("key", None)
        interaction.pop("pending", None)
        interactions.append(interaction)
    doc["interactions"] = sorted(interactions, key=lambda i: i.get("description", ""))
    return doc


def check_consumer_pact(pact: Pact, tmp_path: Path) -> None:
    pact.write_file(tmp_path, overwrite=True)
    name = pact_filename(pact.consumer, pact.provider)
    generated = json.loads((tmp_path / name).read_text())

    if os.environ.get("PACT_UPDATE") == "1":
        repo_root = Path(os.environ["REPO_ROOT"])
        target = repo_root / PACTS_DIR / name
        target.write_text(json.dumps(generated, indent=2, sort_keys=True) + "\n")
        return

    committed_path = PACTS_DIR / name
    assert committed_path.exists(), (
        f"{committed_path} is missing. Generate it with: tools/update-pacts.sh"
    )
    committed = json.loads(committed_path.read_text())
    assert _normalise(generated) == _normalise(committed), (
        f"Consumer expectations changed but {committed_path} wasn't updated. "
        "Run tools/update-pacts.sh and commit the result."
    )


def committed_pact(consumer: str, provider: str) -> Path:
    return PACTS_DIR / pact_filename(consumer, provider)
