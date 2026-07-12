"""SYS-08/SYS-10 support: the local git adapter drives a real git repository."""

from __future__ import annotations

from pathlib import Path

import pytest

from pmpe.gitops.local import LocalGitAdapter


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


def test_init_creates_repo_on_main(workspace: Path) -> None:
    git = LocalGitAdapter(workspace)
    git.init()
    assert (workspace / ".git").is_dir()
    assert git.current_branch() == "main"


def test_commit_and_log(workspace: Path) -> None:
    git = LocalGitAdapter(workspace)
    git.init()
    (workspace / "a.txt").write_text("hello\n")
    sha = git.commit_all("feat: add a")
    assert len(sha) >= 7
    subjects = [c.subject for c in git.log()]
    assert subjects[0] == "feat: add a"


def test_branch_commit_merge_flow(workspace: Path) -> None:
    git = LocalGitAdapter(workspace)
    git.init()
    (workspace / "base.txt").write_text("base\n")
    git.commit_all("chore: base")

    git.create_branch("build/run-1")
    (workspace / "feature.txt").write_text("feature\n")
    git.commit_all("feat: feature file")

    stat = git.diff_stat("main")
    assert "feature.txt" in stat

    git.merge_to_main("build/run-1")
    assert git.current_branch() == "main"
    assert (workspace / "feature.txt").exists()


def test_log_preserves_commit_order(workspace: Path) -> None:
    git = LocalGitAdapter(workspace)
    git.init()
    (workspace / "one.txt").write_text("1\n")
    git.commit_all("test: first")
    (workspace / "two.txt").write_text("2\n")
    git.commit_all("feat: second")
    subjects = [c.subject for c in git.log()]  # newest first
    assert subjects.index("feat: second") < subjects.index("test: first")


def test_commit_identity_is_isolated_from_user_config(workspace: Path) -> None:
    git = LocalGitAdapter(workspace)
    git.init()
    (workspace / "a.txt").write_text("x\n")
    git.commit_all("chore: x")
    author = git.last_author()
    assert "pmpe" in author.lower()
