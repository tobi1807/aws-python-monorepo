"""Feature flags backed by AppConfig (owned by the platform app).

Flags separate *deploy* from *release*: unfinished work ships dark and is
switched on without a deploy. Uses the Powertools Feature Flags schema.

Environment (set by ``ServiceFunction`` / the ECS task definition):
  FLAGS_APPLICATION, FLAGS_ENVIRONMENT, FLAGS_PROFILE
"""

from __future__ import annotations

import os
from functools import cache
from typing import Any

from aws_lambda_powertools.utilities.feature_flags import AppConfigStore, FeatureFlags


@cache
def _flags() -> FeatureFlags:
    store = AppConfigStore(
        application=os.environ["FLAGS_APPLICATION"],
        environment=os.environ["FLAGS_ENVIRONMENT"],
        name=os.environ.get("FLAGS_PROFILE", "features"),
        max_age=60,
    )
    return FeatureFlags(store=store)


def is_enabled(name: str, *, context: dict[str, Any] | None = None, default: bool = False) -> bool:
    if "FLAGS_APPLICATION" not in os.environ:
        return default
    return bool(_flags().evaluate(name=name, context=context or {}, default=default))


def reset() -> None:
    _flags.cache_clear()
