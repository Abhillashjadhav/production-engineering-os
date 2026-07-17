"""The reviewer read-only proof is drawn at the git-tracked boundary.

Transient untracked runtime files — Claude Code's own
``.claude/scheduled_tasks.lock``, dependency caches, build output — are not
reviewer-writable candidate content and never count as a write, on either
side of the snapshot/verify comparison. Any change to a tracked candidate
file is still caught.

Regression coverage for the harness-lock false positive: a snapshot taken
while the lock was present, then the harness deleting its own lock during the
review window, must NOT read as ``removed: .claude/scheduled_tasks.lock``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pmpe.assurance.readonly_guard import readonly_snapshot, verify_unmodified


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "t")
    (root / "app.py").write_text("VALUE = 1\n")
    (root / "src").mkdir()
    (root / "src" / "mod.py").write_text("X = 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    return root


def test_transient_harness_lock_deletion_is_not_a_reviewer_write(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    lock = repo / ".claude" / "scheduled_tasks.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("held")  # untracked harness runtime file, present at snapshot time
    before = readonly_snapshot(repo)
    assert ".claude/scheduled_tasks.lock" not in before  # outside the tracked boundary
    lock.unlink()  # the harness deletes its own lock during the review window
    assert verify_unmodified(repo, before) == []  # the exact prior false positive, now clean


def test_untracked_additions_are_outside_the_boundary(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    before = readonly_snapshot(repo)
    (repo / ".next").mkdir()
    (repo / ".next" / "BUILD_ID").write_text("abc")  # untracked build output
    (repo / ".claude").mkdir()
    (repo / ".claude" / "scheduled_tasks.lock").write_text("held")  # untracked harness file
    assert verify_unmodified(repo, before) == []


def test_a_real_tracked_file_modification_is_detected(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    before = readonly_snapshot(repo)
    (repo / "src" / "mod.py").write_text("X = 2\n")  # a reviewer edits tracked content
    assert verify_unmodified(repo, before) == ["changed: src/mod.py"]


def test_a_removed_tracked_file_is_detected(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "repo")
    before = readonly_snapshot(repo)
    (repo / "app.py").unlink()  # a reviewer deletes tracked content
    assert verify_unmodified(repo, before) == ["removed: app.py"]
