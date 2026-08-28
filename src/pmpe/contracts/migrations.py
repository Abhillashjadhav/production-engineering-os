"""Pure, ordered, versioned canonical-contract migrations."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class MigrationError(ValueError):
    """The requested migration path is unsafe, missing, or ambiguous."""


def _version_tuple(version: str) -> tuple[int, int, int]:
    try:
        parts = tuple(int(part) for part in version.split("."))
    except ValueError as exc:
        raise MigrationError(f"invalid semantic version: {version}") from exc
    if len(parts) != 3 or any(part < 0 for part in parts):
        raise MigrationError(f"invalid semantic version: {version}")
    return parts


@dataclass(frozen=True)
class MigrationStep:
    source_version: str
    target_version: str
    rule_version: str
    transform: Callable[[dict[str, Any]], dict[str, Any]]

    def __post_init__(self) -> None:
        if _version_tuple(self.target_version) <= _version_tuple(self.source_version):
            raise MigrationError("migration steps must move forward; downgrade is forbidden")


class MigrationRegistry:
    """A linear registry: one outgoing step per version, registered in order."""

    def __init__(self) -> None:
        self._steps: list[MigrationStep] = []

    def register(self, step: MigrationStep) -> None:
        if any(existing.source_version == step.source_version for existing in self._steps):
            raise MigrationError(f"ambiguous migration path from {step.source_version}")
        if self._steps and step.source_version != self._steps[-1].target_version:
            raise MigrationError(
                "migration registration order must form one contiguous forward path"
            )
        self._steps.append(step)

    def migrate(
        self,
        value: dict[str, Any],
        source_version: str,
        target_version: str,
    ) -> tuple[dict[str, Any], tuple[str, ...]]:
        if _version_tuple(target_version) < _version_tuple(source_version):
            raise MigrationError("downgrade migrations are forbidden")
        if source_version == target_version:
            return copy.deepcopy(value), ()
        current = source_version
        output = copy.deepcopy(value)
        rules: list[str] = []
        by_source = {step.source_version: step for step in self._steps}
        visited: set[str] = set()
        while current != target_version:
            if current in visited:
                raise MigrationError("migration cycle detected")
            visited.add(current)
            step = by_source.get(current)
            if step is None:
                raise MigrationError(f"no migration path from {source_version} to {target_version}")
            if _version_tuple(step.target_version) > _version_tuple(target_version):
                raise MigrationError(
                    f"migration path from {source_version} overshoots {target_version}"
                )
            try:
                output = step.transform(copy.deepcopy(output))
            except Exception as exc:
                raise MigrationError(f"migration rule {step.rule_version} failed") from exc
            if not isinstance(output, dict):
                raise MigrationError(f"migration rule {step.rule_version} returned non-object")
            rules.append(step.rule_version)
            current = step.target_version
        return output, tuple(rules)
