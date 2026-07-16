"""``pmpe eng`` — the CLI surface over the engineering run engine.

Exit codes under test: 0 success, 2 rejected submission (malformed artifact),
3 blocked on a human gate (undecided findings, unapproved production deploy).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pmpe.cli import main
from pmpe.engineering.engine import EngineeringRun
from pmpe.gitops.local import LocalGitAdapter
from tests.integration.test_run_engine import _arch, drive_to_deploy

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "tests" / "fixtures" / "v2" / "contract_approved.json"
AGENTS_DIR = ROOT / ".claude" / "agents"


def _write(path: Path, payload: dict[str, Any]) -> str:
    path.write_text(json.dumps(payload))
    return str(path)


def _status(run_dir: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    capsys.readouterr()  # drop output accumulated from earlier commands
    assert main(["eng", "status", "--run-dir", str(run_dir)]) == 0
    loaded: dict[str, Any] = json.loads(capsys.readouterr().out)
    return loaded


def test_start_assess_submit_status_resume(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = tmp_path / "run"
    assert (
        main(
            [
                "eng",
                "start",
                "--contract",
                str(CONTRACT),
                "--run-dir",
                str(run_dir),
                "--agents-dir",
                str(AGENTS_DIR),
            ]
        )
        == 0
    )
    status = _status(run_dir, capsys)
    assert status["stage"] == "assessment"

    artifact = _write(tmp_path / "assessment.json", {"summary": "greenfield"})
    assert main(["eng", "assess", "--run-dir", str(run_dir), "--artifact", artifact]) == 0

    arch = _write(tmp_path / "arch.json", _arch(status["contract"]["digest"]))
    assert (
        main(
            [
                "eng",
                "submit",
                "--run-dir",
                str(run_dir),
                "--agent",
                "v2-system-architect",
                "--artifact",
                arch,
            ]
        )
        == 0
    )
    assert _status(run_dir, capsys)["stage"] == "plan"

    assert main(["eng", "resume", "--run-dir", str(run_dir)]) == 0
    assert "plan" in capsys.readouterr().out


def test_rejected_submission_exits_2(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    main(
        [
            "eng",
            "start",
            "--contract",
            str(CONTRACT),
            "--run-dir",
            str(run_dir),
            "--agents-dir",
            str(AGENTS_DIR),
        ]
    )
    main(
        [
            "eng",
            "assess",
            "--run-dir",
            str(run_dir),
            "--artifact",
            _write(tmp_path / "a.json", {"summary": "greenfield"}),
        ]
    )
    bad = _write(tmp_path / "bad-arch.json", _arch("sha256:wrong"))
    rc = main(
        [
            "eng",
            "submit",
            "--run-dir",
            str(run_dir),
            "--agent",
            "v2-system-architect",
            "--artifact",
            bad,
        ]
    )
    assert rc == 2


def test_production_gate_via_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    git = LocalGitAdapter(workspace)
    git.init()
    (workspace / "api.py").write_text("STATUS = 'ok'\n")
    git.commit_all("chore: base workspace")

    run = EngineeringRun.start(CONTRACT, tmp_path / "run", agents_dir=AGENTS_DIR)
    drive_to_deploy(run, workspace)
    run_dir = str(run.run_dir)

    rc = main(["eng", "deploy", "--run-dir", run_dir, "--environment", "production"])
    captured = capsys.readouterr()
    assert rc == 3
    assert "approval" in (captured.err + captured.out)

    assert (
        main(
            [
                "eng",
                "approve-production",
                "--run-dir",
                run_dir,
                "--owner",
                "abhillash",
                "--reason",
                "pilot cohort launch",
            ]
        )
        == 0
    )
    assert main(["eng", "deploy", "--run-dir", run_dir, "--environment", "production"]) == 0
    assert "FIXTURE MODE" in capsys.readouterr().out

    assert (
        main(
            [
                "eng",
                "report",
                "--run-dir",
                run_dir,
                "--verdict",
                "READY_FOR_PRODUCTION_APPROVAL",
            ]
        )
        == 0
    )
    assert _status(Path(run_dir), capsys)["stage"] == "complete"
