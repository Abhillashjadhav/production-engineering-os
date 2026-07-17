"""Runtime read-only proof: a content snapshot taken before a review and verified
after it. Tool configuration proves reviewers *cannot* write; this proves,
per run, that nothing *was* written — belt and braces recorded as evidence.

The proof is drawn at the **git-tracked boundary**. The reviewable candidate is
the tracked working tree, so untracked runtime files — Claude Code's own
``.claude/scheduled_tasks.lock``, dependency caches (``node_modules``,
``.venv``), build output (``.next``) — are not reviewer-writable content and
never count as a write, symmetrically on both the snapshot and the verify side.
``_UNTRACKED_ALLOWLIST`` is the explicit, auditable seam for carrying a
deliberate untracked product file back into scope.

``tree_digest`` / ``_file_map`` (the whole-tree content map behind the
candidate *freeze* digest, in ``pmpe.engineering.candidate``) is a **different
concern** and is deliberately left walking the full tree — narrowing it would
move already-frozen candidate digests. Use ``readonly_snapshot`` /
``verify_unmodified`` for the reviewer proof, never ``tree_digest``.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

_SKIP_PARTS = {".git", "__pycache__", ".ruff_cache", ".pytest_cache", ".mypy_cache"}

# Untracked paths that are nonetheless reviewable product content and must stay
# inside the read-only proof. Empty by default — the boundary is "what git
# tracks"; this frozenset is the explicit exception seam.
_UNTRACKED_ALLOWLIST: frozenset[str] = frozenset()


def _file_map(root: Path) -> dict[str, str]:
    """Every file under root except cache dirs — the candidate *freeze* map.

    Deliberately broad and git-agnostic. Do not narrow it without re-freezing
    every candidate whose digest it produced (``pmpe.engineering.candidate``).
    """
    root = Path(root)
    entries: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in _SKIP_PARTS for part in rel.parts) or not path.is_file():
            continue
        entries[str(rel)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return entries


def tree_digest(root: Path) -> dict[str, str]:
    """Per-file content digests for every file under root (cache dirs excluded).

    This is the candidate-freeze content map. For the reviewer read-only proof
    use ``readonly_snapshot`` / ``verify_unmodified`` instead.
    """
    return _file_map(root)


def _tracked_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--cached"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [rel for rel in result.stdout.split("\0") if rel]


def _tracked_file_map(root: Path) -> dict[str, str]:
    """Content digests over git-tracked files plus the untracked allowlist.

    Untracked runtime files (harness locks, dependency/build caches) are outside
    the boundary — they are not reviewer-writable candidate content. A tracked
    file that has been deleted is intentionally absent here so ``verify_unmodified``
    reports it as ``removed``.
    """
    root = Path(root)
    rels = set(_tracked_files(root)) | set(_UNTRACKED_ALLOWLIST)
    entries: dict[str, str] = {}
    for rel in sorted(rels):
        path = root / rel
        if not path.is_file():
            continue
        entries[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return entries


def readonly_snapshot(root: Path) -> dict[str, str]:
    """The pre-review content snapshot for the read-only proof (tracked boundary)."""
    return _tracked_file_map(root)


def verify_unmodified(root: Path, before: dict[str, str]) -> list[str]:
    """Return violations ([] = tree untouched): changed, added, and removed files.

    Compared at the same git-tracked boundary as ``readonly_snapshot`` so a
    transient untracked runtime file (e.g. ``.claude/scheduled_tasks.lock`` that
    the harness deletes mid-review) cannot register as a reviewer write on either
    side.
    """
    after = _tracked_file_map(root)
    violations: list[str] = []
    for rel in sorted(set(before) & set(after)):
        if before[rel] != after[rel]:
            violations.append(f"changed: {rel}")
    for rel in sorted(set(after) - set(before)):
        violations.append(f"added: {rel}")
    for rel in sorted(set(before) - set(after)):
        violations.append(f"removed: {rel}")
    return violations
