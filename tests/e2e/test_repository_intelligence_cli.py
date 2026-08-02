"""Issue #64 public CLI contract."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from pmpe.cli import main, repository_cmd
from pmpe.repository import scan_repository
from pmpe.repository.models import RepositorySnapshot, ScanConfig

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
    output_parent = tmp_path / "evidence"
    output_parent.mkdir()
    out = output_parent / "snapshot.json"
    observation = output_parent / "governance.json"
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


def test_repository_scan_cli_reports_malformed_observation_id_without_traceback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path)
    output_parent = tmp_path / "evidence"
    output_parent.mkdir()

    code = main(
        [
            "repository",
            "scan",
            "--repo",
            str(repo),
            "--repository",
            "example/cli-fixture",
            "--snapshot-out",
            str(output_parent / "snapshot.json"),
            "--governance-out",
            str(output_parent / "governance.json"),
            "--observation-id",
            "not-an-observation-id",
        ]
    )

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err.startswith("repository intelligence blocked: ")
    assert "recorded observation ID must be a safe opaque identifier" in captured.err
    assert "Traceback" not in captured.err


def test_repository_scan_cli_governance_binds_to_requested_commit(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _git(repo, "switch", "-q", "-c", "feature")
    (repo / "feature.txt").write_text("feature\n")
    _git(repo, "add", "feature.txt")
    _git(repo, "commit", "-q", "-m", "feature")
    feature_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "switch", "-q", "main")
    output_parent = tmp_path / "evidence"
    output_parent.mkdir()
    snapshot_path = output_parent / "snapshot.json"
    governance_path = output_parent / "governance.json"

    code = main(
        [
            "repository",
            "scan",
            "--repo",
            str(repo),
            "--repository",
            "example/cli-fixture",
            "--commit",
            feature_sha,
            "--default-branch",
            "main",
            "--snapshot-out",
            str(snapshot_path),
            "--governance-out",
            str(governance_path),
            "--observed-at",
            "2026-08-01T00:00:00Z",
            "--observation-id",
            "OBS-CLI-FEATURE",
        ]
    )

    assert code == 3
    assert json.loads(snapshot_path.read_text())["commit_sha"] == feature_sha
    assert json.loads(governance_path.read_text())["repository_snapshot_commit"] == feature_sha


def test_repository_scan_cli_refuses_to_create_unpinned_output_parents(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    missing_parent = tmp_path / "untrusted-parent"
    code = main(
        [
            "repository",
            "scan",
            "--repo",
            str(repo),
            "--repository",
            "example/cli-fixture",
            "--snapshot-out",
            str(missing_parent / "snapshot.json"),
        ]
    )
    assert code != 0
    assert not missing_parent.exists()
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == ""


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


def test_repository_scan_cli_refuses_output_directory_symlink_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    output_parent = tmp_path / "evidence"
    output_parent.mkdir()
    moved_parent = tmp_path / "moved-evidence"
    output = output_parent / "snapshot.json"

    def scan_then_swap(
        repository_root: Path | str,
        *,
        commit: str = "HEAD",
        config: ScanConfig,
    ) -> RepositorySnapshot:
        snapshot = scan_repository(repository_root, commit=commit, config=config)
        output_parent.rename(moved_parent)
        output_parent.symlink_to(repo, target_is_directory=True)
        return snapshot

    monkeypatch.setattr(repository_cmd, "scan_repository", scan_then_swap)
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
    assert not (repo / "snapshot.json").exists()
    assert not (moved_parent / "snapshot.json").exists()
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == ""


def test_repository_scan_cli_refuses_output_directory_adopted_as_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    output_parent = tmp_path / "evidence"
    output_parent.mkdir()
    output = output_parent / "snapshot.json"

    def scan_then_adopt(
        repository_root: Path | str,
        *,
        commit: str = "HEAD",
        config: ScanConfig,
    ) -> RepositorySnapshot:
        snapshot = scan_repository(repository_root, commit=commit, config=config)
        reservations = tuple(output_parent.glob(".pmpe-intelligence-reservation.*"))
        assert reservations
        for reservation in reservations:
            reservation.unlink()
        subprocess.run(
            ["git", "worktree", "add", "-q", "-b", "adopt-output", str(output_parent)],
            cwd=repo,
            check=True,
        )
        return snapshot

    monkeypatch.setattr(repository_cmd, "scan_repository", scan_then_adopt)
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
