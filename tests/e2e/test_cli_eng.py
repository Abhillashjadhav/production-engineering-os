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


def test_non_runnable_contract_exits_3(tmp_path: Path) -> None:
    draft = json.loads(CONTRACT.read_text())
    draft["contract_status"] = "DRAFT"
    path = _write(tmp_path / "draft-contract.json", draft)
    rc = main(
        [
            "eng",
            "start",
            "--contract",
            path,
            "--run-dir",
            str(tmp_path / "run"),
            "--agents-dir",
            str(AGENTS_DIR),
        ]
    )
    assert rc == 3  # blocked on a human gate: the contract is not approved


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
    (workspace / "deploy").mkdir(parents=True)
    git = LocalGitAdapter(workspace)
    git.init()
    (workspace / "api.py").write_text("STATUS = 'ok'\n")
    (workspace / "deploy" / "run.sh").write_text("#!/bin/sh\necho serving\n")
    (workspace / "deploy" / "ROLLBACK.md").write_text("# Rollback\n\nRevert and rerun run.sh.\n")
    git.commit_all("chore: base workspace")

    run = EngineeringRun.start(CONTRACT, tmp_path / "run", agents_dir=AGENTS_DIR)
    drive_to_deploy(run, workspace)
    run_dir = str(run.run_dir)
    ws = str(workspace)

    # unattested readiness blocks production before authorization is considered
    rc = main(["eng", "deploy", "--run-dir", run_dir, "--environment", "production", "--repo", ws])
    captured = capsys.readouterr()
    assert rc == 3
    assert "readiness" in (captured.err + captured.out)

    attested = [
        "--repo",
        ws,
        "--health-verified",
        "--journey-verified",
    ]
    rc = main(["eng", "deploy", "--run-dir", run_dir, "--environment", "production", *attested])
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
    assert (
        main(["eng", "deploy", "--run-dir", run_dir, "--environment", "production", *attested]) == 0
    )
    assert "FIXTURE MODE" in capsys.readouterr().out

    # a release verdict without gate evaluations is refused (exit 1, PD-01)
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
        == 1
    )
    capsys.readouterr()
    assert (
        main(
            [
                "eng",
                "report",
                "--run-dir",
                run_dir,
                "--verdict",
                "READY_FOR_PRODUCTION_APPROVAL",
                "--gate",
                "GATE-001=pass",
                "--gate",
                "GATE-002=pass",
            ]
        )
        == 0
    )
    assert _status(Path(run_dir), capsys)["stage"] == "complete"
