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
from pmpe.contracts.authoring import approve_contract_draft
from pmpe.contracts.canonical import canonical_digest
from pmpe.engineering.engine import EngineeringRun
from pmpe.engineering.ledger import EvidenceLedger
from pmpe.gitops.local import LocalGitAdapter
from pmpe.privacy.retention import retention_policy_digest, terminal_retention_digest
from tests.integration.test_run_engine import drive_to_deploy

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "tests" / "fixtures" / "v2" / "contract_approved.json"
AGENTS_DIR = ROOT / ".claude" / "agents"


def _receipt(tmp_path: Path) -> Path:
    approved = json.loads(CONTRACT.read_text())
    draft = dict(approved)
    draft.update(contract_status="DRAFT", approved_by="", approved_at="")
    result = approve_contract_draft(
        draft,
        expected_draft_digest=canonical_digest(draft),
        approver=str(approved["approved_by"]),
        approved_at=str(approved["approved_at"]),
    )
    assert result.contract == approved
    path = tmp_path / "approval-receipt.json"
    path.write_text(json.dumps(result.receipt))
    return path


def _approval_args(tmp_path: Path) -> list[str]:
    return [
        "--receipt",
        str(_receipt(tmp_path)),
        "--expected-approver",
        "abhillash (PM Agent OS)",
    ]


def _write(path: Path, payload: dict[str, Any]) -> str:
    path.write_text(json.dumps(payload))
    return str(path)


def _status(run_dir: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    capsys.readouterr()  # drop output accumulated from earlier commands
    assert main(["eng", "status", "--run-dir", str(run_dir)]) == 0
    loaded: dict[str, Any] = json.loads(capsys.readouterr().out)
    return loaded


def test_status_and_resume_remain_available_for_historical_v2_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = tmp_path / "run"
    EngineeringRun.start(
        CONTRACT,
        run_dir,
        agents_dir=AGENTS_DIR,
        approval_receipt_path=_receipt(tmp_path),
        expected_approver="abhillash (PM Agent OS)",
    )
    status = _status(run_dir, capsys)
    assert status["stage"] == "assessment"

    assert main(["eng", "resume", "--run-dir", str(run_dir)]) == 0
    assert "assessment" in capsys.readouterr().out


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
            *_approval_args(tmp_path),
        ]
    )
    assert rc == 3  # blocked on a human gate: the contract is not approved


@pytest.mark.parametrize("command", ["start", "assess", "submit", "freeze", "deploy"])
def test_mutating_eng_commands_are_retired_to_phase_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    argv = ["eng", command]
    if command == "start":
        argv += [
            "--contract",
            str(CONTRACT),
            "--run-dir",
            str(tmp_path / "run"),
            *_approval_args(tmp_path),
        ]
    else:
        argv += ["--run-dir", str(tmp_path / "run")]
        if command == "assess":
            argv += ["--artifact", str(tmp_path / "artifact.json")]
        elif command == "submit":
            argv += [
                "--agent",
                "v2-system-architect",
                "--artifact",
                str(tmp_path / "artifact.json"),
            ]
        elif command == "freeze":
            argv += ["--repo", str(tmp_path)]
        elif command == "deploy":
            argv += ["--environment", "staging", "--repo", str(tmp_path)]

    assert main(argv) == 3
    assert "LifecycleControlPlane" in capsys.readouterr().out
    assert not (tmp_path / "run" / "run-state.json").exists()


def test_production_mutation_is_retired_via_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "deploy").mkdir(parents=True)
    git = LocalGitAdapter(workspace)
    git.init()
    (workspace / "api.py").write_text("STATUS = 'ok'\n")
    (workspace / "deploy" / "run.sh").write_text("#!/bin/sh\necho serving\n")
    (workspace / "deploy" / "ROLLBACK.md").write_text("# Rollback\n\nRevert and rerun run.sh.\n")
    git.commit_all("chore: base workspace")

    run = EngineeringRun.start(CONTRACT, tmp_path / "run", agents_dir=AGENTS_DIR, fixture_mode=True)
    drive_to_deploy(run, workspace)
    run_dir = str(run.run_dir)
    ws = str(workspace)

    rc = main(["eng", "deploy", "--run-dir", run_dir, "--environment", "production", "--repo", ws])
    captured = capsys.readouterr()
    assert rc == 3
    assert "retired" in (captured.err + captured.out)


def test_retention_purge_runs_without_creating_a_new_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from datetime import UTC, datetime, timedelta

    expired = tmp_path / "expired"
    expired.mkdir()
    state = expired / "run-state.json"
    run_id = "eng-expired"
    retention_days = 30
    state.write_text(
        json.dumps(
            {
                "retention_days": retention_days,
                "run_id": run_id,
                "stage": "complete",
            }
        )
    )
    ledger = EvidenceLedger(expired, run_id=run_id)
    ledger.record(
        stage="contract_lock",
        agent="core",
        action="lock",
        output_digests={"retention_policy": retention_policy_digest(retention_days)},
    )
    ledger.record(
        stage="release_report",
        agent="core",
        action="report",
        output_digests={
            "terminal_retention": terminal_retention_digest(
                retention_days,
                stage="complete",
            )
        },
    )
    events_path = expired / "ledger.jsonl"
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    terminal = events[-1]
    terminal["ts"] = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    identity = {key: value for key, value in terminal.items() if key not in {"event_id", "ts"}}
    terminal["event_id"] = canonical_digest(
        identity if terminal["idempotency_key"] else {**identity, "ts": terminal["ts"]}
    )
    events_path.write_text("".join(json.dumps(event) + "\n" for event in events))

    assert main(["retention", "purge", "--runs-root", str(tmp_path)]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["deleted"] == ["expired"]
    assert not expired.exists()
