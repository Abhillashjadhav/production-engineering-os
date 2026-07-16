"""Workspace file writer with path-safety guarantees."""

from __future__ import annotations

from pathlib import Path

from pmpe.domain.errors import StepFailure
from pmpe.domain.models import GeneratedFile


def write_files(workspace: Path, files: list[GeneratedFile]) -> list[Path]:
    """Write generated files under the workspace root — never outside it."""
    written: list[Path] = []
    root = workspace.resolve()
    for gf in files:
        rel = Path(gf.path)
        if rel.is_absolute() or ".." in rel.parts:
            raise StepFailure("implement", f"unsafe generated path: {gf.path}")
        target = (root / rel).resolve()
        if not target.is_relative_to(root):
            raise StepFailure("implement", f"generated path escapes workspace: {gf.path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(gf.content)
        written.append(target)
    return written
