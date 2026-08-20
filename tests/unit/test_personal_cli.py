"""CLI proof for the one-command Personal Execution OS demo."""

from __future__ import annotations

import json
from pathlib import Path

from pmpe.cli import main
from pmpe.contracts.authoring import approve_contract_draft, build_contract_draft

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "v2" / "contract_approved.json"


def _answers():  # type: ignore[no-untyped-def]
    contract = json.loads(FIXTURE.read_text())
    for field in (
        "approved_at",
        "approved_by",
        "contract_status",
        "source_digest",
        "unresolved_questions",
    ):
        contract.pop(field)
    return contract


def test_personal_quickstart_runs_all_workflows(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    output = tmp_path / "personal-demo"
    assert main(["personal-demo", "quickstart", "--output", str(output)]) == 0
    stdout = capsys.readouterr().out
    assert "21 workflow packs completed in parallel" in stdout
    assert "unauthorized external actions: 0" in stdout
    report = json.loads((output / "personal-execution-report.json").read_text())
    assert report["evidence_complete"] is True
    assert (output / "mobile-review.json").exists()
    assert (output / "evidence-ledger.json").exists()


def test_personal_workflows_validate_real_input(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    output = tmp_path / "starter"
    assert main(["personal-workflows", "generate", "--output", str(output)]) == 0
    request = output / "synthetic-workflow-request.json"
    assert main(["personal-workflows", "validate", "--input", str(request)]) == 0
    assert "(21 packs)" in capsys.readouterr().out


def test_personal_workflows_validate_reports_malformed_input_without_traceback(
    tmp_path, capsys
) -> None:  # type: ignore[no-untyped-def]
    request = tmp_path / "malformed.json"
    request.write_text("{not-json")
    assert main(["personal-workflows", "validate", "--input", str(request)]) == 2
    captured = capsys.readouterr()
    assert "unreadable or malformed" in captured.err
    assert "Traceback" not in captured.err


def test_pack_specific_starter_is_cli_runnable(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    output = tmp_path / "starter"
    assert (
        main(
            [
                "personal-workflows",
                "starter",
                "--pack",
                "issue-to-draft-pr",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    request = output / "synthetic-workflow-request.json"
    run_output = tmp_path / "run"
    assert (
        main(
            [
                "personal-workflows",
                "run",
                "--context",
                str(request),
                "--output",
                str(run_output),
            ]
        )
        == 0
    )
    assert "1 workflow packs completed" in capsys.readouterr().out


def test_contract_draft_cli_reports_missing_product_truth(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps({"product_name": "Incomplete"}))
    output = tmp_path / "authoring"
    assert main(["contract", "draft", "--answers", str(answers), "--output", str(output)]) == 3
    assert "product input required" in capsys.readouterr().out
    questions = json.loads((output / "blocking-questions.json").read_text())
    assert questions["questions"]


def test_guided_cli_rejects_malformed_host_without_traceback(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["guided", "serve", "--host", "not-a-host"]) == 2
    stderr = capsys.readouterr().err
    assert "input rejected" in stderr
    assert "Traceback" not in stderr


def test_contract_handoff_requires_verified_approval_receipt(tmp_path) -> None:  # type: ignore[no-untyped-def]
    draft = build_contract_draft(_answers())
    assert draft.draft is not None and draft.draft_digest is not None
    approved = approve_contract_draft(
        draft.draft,
        expected_draft_digest=draft.draft_digest,
        approver="product-owner",
        approved_at="2026-08-19T12:00:00Z",
    )
    contract_path = tmp_path / "approved.json"
    receipt_path = tmp_path / "receipt.json"
    contract_path.write_text(json.dumps(approved.contract))
    receipt_path.write_text(json.dumps(approved.receipt))
    run_dir = tmp_path / "run"

    assert (
        main(
            [
                "contract",
                "handoff",
                "--contract",
                str(contract_path),
                "--receipt",
                str(receipt_path),
                "--expected-approver",
                "product-owner",
                "--run-dir",
                str(run_dir),
            ]
        )
        == 0
    )
    assert (run_dir / "approval-receipt.json").exists()
    lock = json.loads((run_dir / "approval-receipt.lock.json").read_text())
    assert lock["approval_receipt_digest"] == approved.receipt["receipt_digest"]
