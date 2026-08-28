"""Write-capable specialists work in isolated git worktrees: their edits cannot
touch the main tree until integration merges them."""

from __future__ import annotations

from pathlib import Path

import pytest

from pmpe.engineering.worktree import specialist_worktree
from pmpe.gitops.local import LocalGitAdapter


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git = LocalGitAdapter(root)
    git.init()
    (root / "shared.py").write_text("VALUE = 1\n")
    git.commit_all("chore: base")
    return root


def test_worktree_writes_do_not_touch_main_tree(repo: Path, tmp_path: Path) -> None:
    with specialist_worktree(repo, task_id="T-001", worktrees_root=tmp_path / "wt") as wt:
        assert wt.path.exists() and wt.path != repo
        (wt.path / "shared.py").write_text("VALUE = 2\n")
        (wt.path / "new_module.py").write_text("NEW = True\n")
        wt.commit("feat: T-001 change value")

    # main tree untouched by the specialist's work
    assert (repo / "shared.py").read_text() == "VALUE = 1\n"
    assert not (repo / "new_module.py").exists()

    # ...but the branch exists in the repo for integration to merge
    git = LocalGitAdapter(repo)
    git.checkout("specialist/T-001")
    assert (repo / "new_module.py").exists()


def test_worktree_is_cleaned_up_after_use(repo: Path, tmp_path: Path) -> None:
    with specialist_worktree(repo, task_id="T-002", worktrees_root=tmp_path / "wt") as wt:
        kept = wt.path
        (wt.path / "x.py").write_text("x = 1\n")
        wt.commit("feat: T-002 x")
    assert not kept.exists()


def test_uncommitted_worktree_changes_are_not_silently_lost(repo: Path, tmp_path: Path) -> None:
    """Leaving uncommitted work behind is an error, not a silent discard."""
    with (
        pytest.raises(RuntimeError, match="uncommitted"),
        specialist_worktree(repo, task_id="T-003", worktrees_root=tmp_path / "wt") as wt,
    ):
        (wt.path / "orphan.py").write_text("lost = True\n")
