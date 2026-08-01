"""Integrated exact-commit snapshot plus mutable-governance evidence."""

from __future__ import annotations

import importlib
import json
import subprocess
from pathlib import Path
from types import ModuleType

import pytest


def _api() -> ModuleType:
    try:
        return importlib.import_module("pmpe.repository")
    except ModuleNotFoundError:
        pytest.fail("issue #64 repository-intelligence API is not implemented", pytrace=False)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repository"
    repo.mkdir()
    _git(repo, "init", "-q", "--initial-branch=main")
    _git(repo, "config", "user.email", "fixture@localhost")
    _git(repo, "config", "user.name", "Fixture")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def main() -> None:\n    pass\n")
    (repo / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='1'\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_app.py").write_text("def test_app():\n    assert True\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture")
    return repo


def test_public_api_emits_separate_canonical_artifacts_without_mutating_repo(
    tmp_path: Path,
) -> None:
    api = _api()
    repo = _repo(tmp_path)
    before = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    config = api.ScanConfig(repository="example/integration", default_branch="main")
    snapshot = api.scan_repository(repo, commit="HEAD", config=config)
    observation = api.observe_governance(
        repo,
        repository="example/integration",
        ref="main",
        snapshot=snapshot,
        clock=api.RecordedUtcClock("2026-08-01T12:00:00Z"),
        id_provider=api.RecordedObservationIds("OBS-INTEGRATION-001"),
    )
    after = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")

    assert before == after == ""
    assert snapshot.commit_sha == _git(repo, "rev-parse", "HEAD")
    assert snapshot.artifact_kind == "REPOSITORY_SNAPSHOT"
    assert observation.artifact_kind == "GOVERNANCE_OBSERVATION"
    assert snapshot.snapshot_digest != observation.observation_output_digest
    assert json.loads(snapshot.canonical_bytes())["snapshot_digest"] == snapshot.snapshot_digest
    assert (
        json.loads(observation.canonical_bytes())["observation_output_digest"]
        == observation.observation_output_digest
    )


def test_dirty_state_is_only_in_governance_artifact(tmp_path: Path) -> None:
    api = _api()
    repo = _repo(tmp_path)
    (repo / "src" / "app.py").write_text("dirty\n")
    snapshot = api.scan_repository(
        repo,
        commit="HEAD",
        config=api.ScanConfig(repository="example/integration", default_branch="main"),
    )
    observation = api.observe_governance(
        repo,
        repository="example/integration",
        ref="main",
        snapshot=snapshot,
        clock=api.RecordedUtcClock("2026-08-01T12:00:00Z"),
        id_provider=api.RecordedObservationIds("OBS-INTEGRATION-001"),
    )
    assert "dirty" not in snapshot.canonical_bytes().decode()
    assert observation.local_state.worktree_dirty is True
    assert (repo / "src" / "app.py").read_text() == "dirty\n"
