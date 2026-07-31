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
    assert code == 0
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
