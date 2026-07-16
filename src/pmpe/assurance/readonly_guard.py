"""Runtime read-only proof: a content snapshot taken before a review and verified
after it. Tool configuration proves reviewers *cannot* write; this proves,
per run, that nothing *was* written — belt and braces recorded as evidence.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_SKIP_PARTS = {".git", "__pycache__", ".ruff_cache", ".pytest_cache", ".mypy_cache"}


def _file_map(root: Path) -> dict[str, str]:
    root = Path(root)
    entries: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in _SKIP_PARTS for part in rel.parts) or not path.is_file():
            continue
        entries[str(rel)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return entries


def tree_digest(root: Path) -> dict[str, str]:
    """Per-file content digests for every file under root (cache dirs excluded)."""
    return _file_map(root)


def verify_unmodified(root: Path, before: dict[str, str]) -> list[str]:
    """Return violations ([] = tree untouched): changed, added, and removed files."""
    after = _file_map(root)
    violations: list[str] = []
    for rel in sorted(set(before) & set(after)):
        if before[rel] != after[rel]:
            violations.append(f"changed: {rel}")
    for rel in sorted(set(after) - set(before)):
        violations.append(f"added: {rel}")
    for rel in sorted(set(before) - set(after)):
        violations.append(f"removed: {rel}")
    return violations
