"""Reject release-gate aliases at contract metadata grammar boundaries."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

_PARENTS = ("quality_assurance", "release", "acceptance")


def _normalized(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _within_edits(value: str, target: str, limit: int) -> bool:
    """Bound insertions, deletions, substitutions and adjacent transpositions."""

    if abs(len(value) - len(target)) > limit:
        return False
    previous = list(range(len(target) + 1))
    preceding: list[int] = []
    for i, left in enumerate(value, start=1):
        current = [i]
        for j, right in enumerate(target, start=1):
            distance = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (left != right))
            if i > 1 and j > 1 and left == target[j - 2] and value[i - 2] == right:
                distance = min(distance, preceding[j - 2] + 1)
            current.append(distance)
        preceding, previous = previous, current
    return previous[-1] <= limit


def _near_gate_key(key: str, value: Any) -> bool:
    normalized = _normalized(key)
    container = isinstance(value, (Mapping, list))
    if normalized in {"gate", "gates"}:
        return container
    if normalized in {"qualitygates", "golivegates"}:
        return True
    return any(
        _within_edits(normalized, canonical, 1)
        or (container and (_within_edits(normalized, canonical, 2) or canonical in normalized))
        for canonical in ("releasegates", "binaryreleasegates")
    )


def _near_parent_key(key: str) -> bool:
    normalized = _normalized(key)
    return normalized == "qa" or any(
        _within_edits(normalized, _normalized(parent), 1) for parent in _PARENTS
    )


def validate_gate_declaration_placement(
    contract: Mapping[str, Any], diagnostic: Callable[[str, str, str], None]
) -> None:
    """Inspect field names, never prose, application payloads or arbitrary nested data.

    Declarations belong to root ``binary_release_gates`` or
    ``quality_assurance.release_gates``. Inspect root, its three named metadata
    objects, and immediate requirement/criterion entry keys only. Known parent
    wrappers nested at those boundaries reject; their values are not traversed.
    Generic gate words, two-edit variants and prefixed/suffixed names require a
    container value; canonical names, one-edit variants and explicit synonyms
    do not. A scalar release_date, for example, is business metadata.
    This finite grammar is not a general unknown-field or natural-language check.
    """

    contexts: list[tuple[str, Mapping[str, Any], str | None]] = [
        ("", contract, "binary_release_gates")
    ]
    for name in _PARENTS:
        if name not in contract:
            continue
        value = contract[name]
        if not isinstance(value, Mapping):
            diagnostic(
                "RELEASE_GATE_COLLECTION_INVALID", name, "metadata container must be an object"
            )
            continue
        contexts.append(
            (name + ".", value, "release_gates" if name == "quality_assurance" else None)
        )
    for name in ("functional_requirements", "acceptance_criteria"):
        collection = contract.get(name)
        if isinstance(collection, Mapping):
            contexts.extend(
                (f"{name}.{identifier}.", item, None)
                for identifier, item in collection.items()
                if isinstance(item, Mapping)
            )
        elif isinstance(collection, list):
            contexts.extend(
                (f"{name}[{index}].", item, None)
                for index, item in enumerate(collection)
                if isinstance(item, Mapping)
            )
    for prefix, value, allowed in contexts:
        for key, item in value.items():
            if not isinstance(key, str):
                continue
            if key != allowed and _near_gate_key(key, item):
                diagnostic(
                    "RELEASE_GATE_DECLARATIONS_IGNORED",
                    prefix + key,
                    "release-gate field is misplaced or misspelled; use a supported container",
                )
            elif _near_parent_key(key) and (
                (not prefix and key not in _PARENTS)
                or (prefix and isinstance(item, (Mapping, list)))
            ):
                diagnostic(
                    "RELEASE_GATE_CONTAINER_MISPLACED",
                    prefix + key,
                    "metadata parent is misplaced or misspelled; use its exact root field",
                )
