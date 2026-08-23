from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from pmpe import barebones as barebones_runtime
from pmpe.barebones import BudgetCaps, RunState, run_to_release_ready
from pmpe.cli import barebones_cmd, build_parser
from pmpe.cli.barebones_cmd import CommandModelProvider

_REPOSITORY = Path(__file__).parents[2]


def test_barebones_cli_runs_a_contract_without_cloud_services(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = Path(__file__).parents[2]
    args = build_parser().parse_args(
        [
            "barebones",
            str(repository / "examples/barebones/e1-contract.json"),
            "--workspace",
            str(tmp_path / "candidate"),
            "--run-id",
            "cli-e1",
            "--repository-root",
            str(tmp_path),
            "--approval-receipt",
            str(_REPOSITORY / "examples/barebones/e1-approval-receipt.json"),
            "--expected-approver",
            "fixture-human",
            "--provider-command",
            f"{sys.executable} {repository / 'examples/barebones/e1-provider.py'}",
        ]
    )

    assert args.fn(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["state"] == "RELEASE_READY"
    assert output["model_calls"] == 2
    events = [json.loads(line) for line in Path(output["evidence"]).read_text().splitlines()]
    approval = events[0]["payload"]["approval"]
    assert approval["status"] == "VERIFIED"
    assert approval["authority"] == "fixture-human"
    receipt = json.loads((_REPOSITORY / "examples/barebones/e1-approval-receipt.json").read_text())
    receipt_path = _REPOSITORY / "examples/barebones/e1-approval-receipt.json"
    submitted_digest = "sha256:" + hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    assert approval["receipt_digest"] == receipt["receipt_digest"]
    assert approval["receipt_blob_digest"] == submitted_digest


def test_unapproved_contract_is_rejected_before_provider(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    contract = tmp_path / "unapproved.json"
    contract.write_text(
        json.dumps(
            {
                "contract_id": "PMOS-UNAPPROVED",
                "contract_status": "DRAFT",
                "approved_by": "fixture-human",
            }
        )
    )
    args = build_parser().parse_args(
        [
            "barebones",
            str(contract),
            "--workspace",
            str(tmp_path / "candidate"),
            "--run-id",
            "unapproved",
            "--repository-root",
            str(tmp_path),
            "--approval-receipt",
            str(_REPOSITORY / "examples/barebones/e1-approval-receipt.json"),
            "--expected-approver",
            "fixture-human",
            "--provider-command",
            "must-not-run",
        ]
    )

    assert args.fn(args) == 3
    output = json.loads(capsys.readouterr().out)
    assert output["detail"] == "contract_status must be APPROVED"


def test_missing_approval_receipt_is_structured_contract_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = build_parser().parse_args(
        [
            "barebones",
            str(_REPOSITORY / "examples/barebones/e1-contract.json"),
            "--workspace",
            str(tmp_path / "candidate"),
            "--run-id",
            "missing-receipt",
            "--repository-root",
            str(tmp_path),
            "--approval-receipt",
            str(tmp_path / "missing.json"),
            "--expected-approver",
            "fixture-human",
            "--provider-command",
            "must-not-run",
        ]
    )

    assert args.fn(args) == 3
    output = json.loads(capsys.readouterr().out)
    assert output["detail"] == "cannot read approval receipt"


def test_contract_changed_after_approval_is_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = Path(__file__).parents[2]
    contract = json.loads((repository / "examples/barebones/e1-contract.json").read_text())
    contract["functional_requirements"]["FR-001"]["statement"] = "Unapproved change"
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(contract))
    args = build_parser().parse_args(
        [
            "barebones",
            str(changed),
            "--workspace",
            str(tmp_path / "candidate"),
            "--run-id",
            "changed-after-approval",
            "--repository-root",
            str(tmp_path),
            "--approval-receipt",
            str(_REPOSITORY / "examples/barebones/e1-approval-receipt.json"),
            "--expected-approver",
            "fixture-human",
            "--provider-command",
            "must-not-run",
        ]
    )

    assert args.fn(args) == 3
    output = json.loads(capsys.readouterr().out)
    assert output["detail"] == "approval receipt is not bound to the approved contract"


def test_approver_mismatch_is_rejected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repository = Path(__file__).parents[2]
    args = build_parser().parse_args(
        [
            "barebones",
            str(repository / "examples/barebones/e1-contract.json"),
            "--workspace",
            str(tmp_path / "candidate"),
            "--run-id",
            "wrong-approver",
            "--repository-root",
            str(tmp_path),
            "--approval-receipt",
            str(_REPOSITORY / "examples/barebones/e1-approval-receipt.json"),
            "--expected-approver",
            "different-human",
            "--provider-command",
            "must-not-run",
        ]
    )

    assert args.fn(args) == 3
    output = json.loads(capsys.readouterr().out)
    assert output["detail"] == "approved_by does not match --expected-approver"


def test_model_response_credentials_are_rejected_before_evidence() -> None:
    class CredentialProvider:
        def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
            return {
                "request_digest": request["request_digest"],
                "summary": "sk-" + "a" * 24,
            }

    counters: dict[str, Any] = {
        "calls": 0,
        "bytes": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "estimated_cost_usd": 0.0,
        "provider_model_id": "",
    }
    with pytest.raises(RuntimeError, match="MODEL_RESPONSE_CONTAINS_CREDENTIAL"):
        barebones_runtime._invoke_bound(
            CredentialProvider(),
            purpose="advisory_review",
            request={"request_digest": "bound"},
            budget=BudgetCaps(),
            counters=counters,
        )


def test_non_finite_provider_cost_is_classified_before_evidence(tmp_path: Path) -> None:
    class NonFiniteCostProvider:
        def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
            return {
                "request_digest": request["request_digest"],
                "files": {},
                "usage": {"estimated_cost_usd": float("inf")},
            }

    contract = json.loads((_REPOSITORY / "examples/barebones/e1-contract.json").read_text())
    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="non-finite-provider-cost",
        provider=NonFiniteCostProvider(),
    )

    assert result.state is RunState.HALTED
    assert result.cause == "MODEL_PROVIDER_USAGE_INVALID"
    assert result.model_calls == 1
    assert result.telemetry["estimated_cost_usd"] == 0.0
    event = json.loads(result.evidence_path.read_text().splitlines()[-1])
    assert event["payload"]["cause"] == "MODEL_PROVIDER_USAGE_INVALID"
    assert event["payload"]["telemetry"]["estimated_cost_usd"] == 0.0


def test_accumulated_provider_cost_overflow_is_rejected_before_assignment() -> None:
    class HugeFiniteCostProvider:
        def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
            return {
                "request_digest": request["request_digest"],
                "files": {},
                "usage": {"estimated_cost_usd": 1e308},
            }

    counters: dict[str, Any] = {
        "calls": 0,
        "bytes": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "estimated_cost_usd": 0.0,
        "provider_model_id": "",
    }
    provider = HugeFiniteCostProvider()
    request = {"request_digest": "bound"}
    barebones_runtime._invoke_bound(
        provider,
        purpose="code",
        request=request,
        budget=BudgetCaps(),
        counters=counters,
    )

    with pytest.raises(RuntimeError, match="MODEL_PROVIDER_USAGE_INVALID"):
        barebones_runtime._invoke_bound(
            provider,
            purpose="advisory_review",
            request=request,
            budget=BudgetCaps(),
            counters=counters,
        )

    assert counters["estimated_cost_usd"] == 1e308


def test_provider_error_credentials_are_classified_without_persisting_secret() -> None:
    secret = "sk-" + "a" * 24

    assert (
        barebones_runtime._classify_provider_error(RuntimeError(secret)) == "MODEL_PROVIDER_FAILED"
    )
    assert secret not in barebones_runtime._classify_provider_error(RuntimeError(secret))


def test_provider_timeout_is_a_classified_halt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timeout(*args: object, **kwargs: object) -> object:
        raise RuntimeError("MODEL_PROVIDER_TIMEOUT")

    monkeypatch.setattr(barebones_cmd, "_run_provider_command", timeout)
    repository = Path(__file__).parents[2]
    contract = json.loads((repository / "examples/barebones/e1-contract.json").read_text())
    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="provider-timeout",
        provider=CommandModelProvider("provider", 1),
    )

    assert result.state is RunState.HALTED
    assert result.cause == "MODEL_PROVIDER_TIMEOUT"
    assert result.model_calls == 1
    event = json.loads(result.evidence_path.read_text().splitlines()[-1])
    assert event["event_type"] == "halted"
    assert event["payload"]["cause"] == "MODEL_PROVIDER_TIMEOUT"
    assert event["payload"]["telemetry"] == result.telemetry


def test_malformed_contract_is_reported_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    contract = tmp_path / "malformed.json"
    contract.write_text("{not-json")
    args = build_parser().parse_args(
        [
            "barebones",
            str(contract),
            "--workspace",
            str(tmp_path / "candidate"),
            "--run-id",
            "malformed-contract",
            "--repository-root",
            str(tmp_path),
            "--approval-receipt",
            str(_REPOSITORY / "examples/barebones/e1-approval-receipt.json"),
            "--expected-approver",
            "fixture-human",
            "--provider-command",
            "provider",
        ]
    )

    assert args.fn(args) == 3
    output = json.loads(capsys.readouterr().out)
    assert output["state"] == "HALTED"
    assert output["cause"] == "CONTRACT_INVALID"
    assert output["diagnostics"][0]["code"] == "MALFORMED_SOURCE"


def test_non_empty_workspace_is_rejected_before_evidence_is_created(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = Path(__file__).parents[2]
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    (workspace / "previous.txt").write_text("occupied")
    args = build_parser().parse_args(
        [
            "barebones",
            str(repository / "examples/barebones/e1-contract.json"),
            "--workspace",
            str(workspace),
            "--run-id",
            "occupied-workspace",
            "--repository-root",
            str(tmp_path),
            "--approval-receipt",
            str(_REPOSITORY / "examples/barebones/e1-approval-receipt.json"),
            "--expected-approver",
            "fixture-human",
            "--provider-command",
            "provider",
        ]
    )

    assert args.fn(args) == 3
    output = json.loads(capsys.readouterr().out)
    assert output["state"] == "HALTED"
    assert output["cause"] == "CONTRACT_INVALID"
    assert output["detail"] == "candidate workspace must be empty"
    assert not (tmp_path / ".pmpe" / "runs" / "occupied-workspace").exists()


def test_workspace_cannot_overlap_evidence_storage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repository = Path(__file__).parents[2]
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    args = build_parser().parse_args(
        [
            "barebones",
            str(repository / "examples/barebones/e1-contract.json"),
            "--workspace",
            str(workspace),
            "--run-id",
            "overlapping-roots",
            "--repository-root",
            str(workspace),
            "--approval-receipt",
            str(_REPOSITORY / "examples/barebones/e1-approval-receipt.json"),
            "--expected-approver",
            "fixture-human",
            "--provider-command",
            "provider",
        ]
    )

    assert args.fn(args) == 3
    output = json.loads(capsys.readouterr().out)
    assert output["state"] == "HALTED"
    assert output["cause"] == "CONTRACT_INVALID"
    assert output["detail"] == "candidate workspace must not overlap evidence storage"
    assert not (workspace / ".pmpe").exists()


def test_command_provider_rejects_non_json_numeric_constants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Completed:
        returncode = 0
        stdout = b'{"request_digest":"bound","score":NaN}'
        stderr = b""

    monkeypatch.setattr(barebones_cmd, "_run_provider_command", lambda *args, **kwargs: Completed())

    with pytest.raises(RuntimeError, match="malformed JSON"):
        CommandModelProvider("provider", 1).invoke(
            purpose="advisory_review", request={"request_digest": "bound"}
        )


def test_command_provider_rejects_malformed_utf8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = barebones_cmd.subprocess.CompletedProcess(
        ("provider",),
        0,
        b'{"request_digest":"bound","file":"\xff"}',
        b"",
    )
    monkeypatch.setattr(barebones_cmd, "_run_provider_command", lambda *args, **kwargs: completed)

    with pytest.raises(RuntimeError, match="malformed JSON"):
        CommandModelProvider("provider", 1).invoke(
            purpose="code", request={"request_digest": "bound"}
        )


def test_command_provider_output_is_bounded_before_capture() -> None:
    with pytest.raises(RuntimeError, match="MODEL_PROVIDER_OUTPUT_LIMIT"):
        barebones_cmd._run_provider_command(
            (sys.executable, "-c", "import sys; sys.stdout.write('x' * 1000)"),
            b"{}",
            2,
            output_limit_bytes=32,
        )
