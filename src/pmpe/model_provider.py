"""The only external adapter used by the bare-bones Engineering OS core."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

GENERIC_PROVIDER_ISOLATION = "UNVERIFIED_GENERIC_COMMAND"
OFFLINE_PROVIDER_ISOLATION = "UNVERIFIED_OFFLINE_MODE"


class ModelProvider(Protocol):
    """Return structured output for one digest-bound model request."""

    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]: ...
