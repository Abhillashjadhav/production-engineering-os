"""Reject release-gate aliases at contract metadata grammar boundaries."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any


def _near_gate_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    if normalized in {"gate", "gates"}:
        return True
    for canonical in ("releasegates", "binaryreleasegates"):
        if canonical in normalized:
            return True
        if len(normalized) == len(canonical):
            if sum(left != right for left, right in zip(normalized, canonical, strict=True)) <= 1:
                return True
            if any(
                normalized == canonical[:i] + canonical[i + 1] + canonical[i] + canonical[i + 2 :]
                for i in range(len(canonical) - 1)
            ):
                return True
        longer, shorter = sorted((normalized, canonical), key=len, reverse=True)
        if len(longer) == len(shorter) + 1 and any(
            longer[:i] + longer[i + 1 :] == shorter for i in range(len(longer))
        ):
            return True
    return False


def validate_gate_declaration_placement(
    contract: Mapping[str, Any], diagnostic: Callable[[str, str, str], None]
) -> None:
    """Inspect field names, never prose, application payloads or arbitrary nested data.

    Gate declarations belong to root ``binary_release_gates`` or
    ``quality_assurance.release_gates``. Root, quality_assurance and release are
    the relevant metadata objects in the accepted contract grammar.
    """

    contexts: list[tuple[str, Mapping[str, Any], str | None]] = [
        ("", contract, "binary_release_gates")
    ]
    for name in ("quality_assurance", "release"):
        value = contract.get(name)
        if isinstance(value, Mapping):
            contexts.append(
                (name + ".", value, "release_gates" if name == "quality_assurance" else None)
            )
    for prefix, value, allowed in contexts:
        for key in value:
            if isinstance(key, str) and key != allowed and _near_gate_key(key):
                diagnostic(
                    "RELEASE_GATE_DECLARATIONS_IGNORED",
                    prefix + key,
                    "release-gate field is misplaced or misspelled; use a supported container",
                )
