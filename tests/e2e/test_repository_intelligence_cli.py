"""Issue #64 public CLI contract."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from pmpe.cli import main

pytestmark = pytest.mark.e2e


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
    (repo / "pyproject.toml").write_text("[project]\nname='cli-fixture'\nversion='1'\n")
    (repo / "README.md").write_text("# CLI fixture\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture")
    return repo


def test_repository_scan_cli_writes_artifacts_outside_scanned_repo(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path)
    out = tmp_path / "evidence" / "snapshot.json"
    observation = tmp_path / "evidence" / "governance.json"
    before = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    code = main(
        [
            "repository",
            "scan",
            "--repo",
            str(repo),
            "--repository",
            "example/cli-fixture",
            "--commit",
            "HEAD",
            "--default-branch",
            "main",
            "--snapshot-out",
            str(out),
            "--governance-out",
            str(observation),
            "--observed-at",
            "2026-08-01T00:00:00Z",
            "--observation-id",
            "OBS-CLI-001",
        ]
    )
    after = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    assert code == 3
    assert before == after == ""
    assert json.loads(out.read_text())["artifact_kind"] == "REPOSITORY_SNAPSHOT"
    assert json.loads(observation.read_text())["artifact_kind"] == "GOVERNANCE_OBSERVATION"
    output = json.loads(capsys.readouterr().out)
    assert output["snapshot_digest"].startswith("sha256:")
    assert output["governance_observation_id"] == "OBS-CLI-001"


def test_repository_scan_cli_refuses_to_write_inside_scanned_repository(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    code = main(
        [
            "repository",
            "scan",
            "--repo",
            str(repo),
            "--repository",
            "example/cli-fixture",
            "--snapshot-out",
            str(repo / "snapshot.json"),
        ]
    )
    assert code != 0
    assert not (repo / "snapshot.json").exists()


def test_repository_scan_cli_uses_actual_git_root_for_output_containment(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    nested = repo / "packages" / "component"
    nested.mkdir(parents=True)
    output = repo / "root-level-snapshot.json"
    code = main(
        [
            "repository",
            "scan",
            "--repo",
            str(nested),
            "--repository",
            "example/cli-fixture",
            "--snapshot-out",
            str(output),
        ]
    )
    assert code != 0
    assert not output.exists()


def test_repository_scan_cli_requires_distinct_artifact_outputs(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    output = tmp_path / "evidence" / "artifact.json"
    code = main(
        [
            "repository",
            "scan",
            "--repo",
            str(repo),
            "--repository",
            "example/cli-fixture",
            "--snapshot-out",
            str(output),
            "--governance-out",
            str(output),
        ]
    )
    assert code != 0
    assert not output.exists()


def test_repository_scan_cli_refuses_sibling_worktree_output(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    sibling = tmp_path / "sibling-worktree"
    _git(repo, "worktree", "add", "-q", "-b", "sibling", str(sibling))
    output = sibling / "snapshot.json"
    code = main(
        [
            "repository",
            "scan",
            "--repo",
            str(repo),
            "--repository",
            "example/cli-fixture",
            "--snapshot-out",
            str(output),
        ]
    )
    assert code != 0
    assert not output.exists()


def test_repository_scan_cli_refuses_external_git_metadata_output(tmp_path: Path) -> None:
    repo = tmp_path / "separate-repository"
    metadata = tmp_path / "separate-metadata.git"
    repo.mkdir()
    subprocess.run(
        [
            "git",
            "init",
            "-q",
            "--initial-branch=main",
            f"--separate-git-dir={metadata}",
        ],
        cwd=repo,
        check=True,
    )
    _git(repo, "config", "user.email", "fixture@localhost")
    _git(repo, "config", "user.name", "Fixture")
    (repo / "README.md").write_text("# Separate Git directory\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture")
    index = metadata / "index"
    before_index = index.read_bytes()
    code = main(
        [
            "repository",
            "scan",
            "--repo",
            str(repo),
            "--repository",
            "example/separate-fixture",
            "--snapshot-out",
            str(index),
        ]
    )
    assert code != 0
    assert index.read_bytes() == before_index
