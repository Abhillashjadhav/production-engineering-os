"""Isolated git worktrees for write-capable specialist agents.

A specialist's edits land on its own branch via its own worktree; the main tree
is untouched until the Integration Engineer merges accepted branches. Leaving
uncommitted work behind is an error — silent discards would hide half-done
tasks.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from pmpe.domain.errors import GitError
from pmpe.gitops.local import LocalGitAdapter


@dataclass
class SpecialistWorktree:
    path: Path
    branch: str
    _git: LocalGitAdapter

    def commit(self, message: str) -> str:
        return self._git.commit_all(message)

    def has_uncommitted_changes(self) -> bool:
        return bool(self._git._run("status", "--porcelain"))  # noqa: SLF001


@contextmanager
def specialist_worktree(
    repo: Path,
    *,
    task_id: str,
    worktrees_root: Path,
    branch_name: str | None = None,
    worktree_name: str | None = None,
) -> Iterator[SpecialistWorktree]:
    repo_git = LocalGitAdapter(repo)
    branch = branch_name or f"specialist/{task_id}"
    worktrees_root = Path(worktrees_root)
    worktrees_root.mkdir(parents=True, exist_ok=True)
    wt_path = worktrees_root / (worktree_name or task_id)
    repo_git._run("worktree", "add", "-b", branch, str(wt_path))  # noqa: SLF001
    worktree = SpecialistWorktree(path=wt_path, branch=branch, _git=LocalGitAdapter(wt_path))
    try:
        yield worktree
        if wt_path.exists() and worktree.has_uncommitted_changes():
            raise RuntimeError(
                f"specialist worktree for {task_id} has uncommitted changes — commit or "
                "escalate before leaving the task"
            )
    finally:
        try:
            repo_git._run("worktree", "remove", "--force", str(wt_path))  # noqa: SLF001
        except GitError:
            # A lifecycle cancellation may already have force-removed this exact
            # dedicated worktree after preserving its status evidence.
            if wt_path.exists():
                raise
        shutil.rmtree(wt_path, ignore_errors=True)
