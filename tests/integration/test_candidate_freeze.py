"""The frozen candidate: manifest binds commit + tree digest + contract digest;
any post-freeze change is detected; refreezing creates a new candidate id."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pmpe.engineering.candidate import (
    CandidateViolation,
    freeze_candidate,
    verify_frozen,
)
from pmpe.gitops.local import LocalGitAdapter

CONTRACT_DIGEST = "sha256:feed"


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git = LocalGitAdapter(root)
    git.init()
    (root / "app.py").write_text("VALUE = 1\n")
    git.commit_all("feat: base")
    return root


def test_freeze_writes_manifest_binding_all_digests(repo: Path, tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    candidate = freeze_candidate(repo, run_dir, contract_digest=CONTRACT_DIGEST)
    assert candidate.candidate_id == "CAND-001"
    manifest = json.loads((run_dir / "candidate-manifest.json").read_text())
    assert manifest["candidate_id"] == "CAND-001"
    assert manifest["contract_digest"] == CONTRACT_DIGEST
    assert manifest["commit"]
    assert manifest["tree_digest"].startswith("sha256:")
    assert manifest["frozen_at"]


def test_verify_frozen_passes_on_untouched_tree(repo: Path, tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    freeze_candidate(repo, run_dir, contract_digest=CONTRACT_DIGEST)
    verify_frozen(repo, run_dir)


def test_any_post_freeze_change_fails_closed(repo: Path, tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    freeze_candidate(repo, run_dir, contract_digest=CONTRACT_DIGEST)
    (repo / "app.py").write_text("VALUE = 2\n")
    with pytest.raises(CandidateViolation):
        verify_frozen(repo, run_dir)


def test_freeze_rejects_uncommitted_changes(repo: Path, tmp_path: Path) -> None:
    """A dirty worktree must never freeze: the manifest would record a commit
    that does not contain the digested content, so reviews and deployments
    would certify content absent from the recorded commit."""
    (repo / "app.py").write_text("VALUE = 99  # uncommitted\n")
    with pytest.raises(CandidateViolation, match="dirty worktree"):
        freeze_candidate(repo, tmp_path / "run", contract_digest=CONTRACT_DIGEST)
    assert not (tmp_path / "run" / "candidate-manifest.json").exists()


def test_freeze_rejects_untracked_files(repo: Path, tmp_path: Path) -> None:
    (repo / "sneaky.py").write_text("x = 1\n")
    with pytest.raises(CandidateViolation, match="dirty worktree"):
        freeze_candidate(repo, tmp_path / "run", contract_digest=CONTRACT_DIGEST)


def test_refreeze_after_fixes_creates_new_candidate(repo: Path, tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    first = freeze_candidate(repo, run_dir, contract_digest=CONTRACT_DIGEST)
    git = LocalGitAdapter(repo)
    (repo / "app.py").write_text("VALUE = 2\n")
    git.commit_all("fix: RF-001 value")
    second = freeze_candidate(repo, run_dir, contract_digest=CONTRACT_DIGEST)
    assert second.candidate_id == "CAND-002"
    assert second.tree_digest != first.tree_digest
    history = sorted((run_dir / "candidates").glob("CAND-*.json"))
    assert len(history) == 2  # both manifests preserved
    latest = json.loads((run_dir / "candidate-manifest.json").read_text())
    assert latest["candidate_id"] == "CAND-002"
