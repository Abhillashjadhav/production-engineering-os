from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from pmpe import barebones as barebones_runtime
from pmpe.barebones import BudgetCaps, RunState, run_to_release_ready
from pmpe.cli import barebones_cmd, build_parser, main
from pmpe.cli.barebones_cmd import CommandModelProvider
from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes
from pmpe.domain.errors import ContractViolation
from pmpe.evidence.ledger import EvidenceIntegrityError, EvidenceLedger
from pmpe.provider_isolation import OfflineConfinedProvider

_REPOSITORY = Path(__file__).parents[2]


@pytest.mark.parametrize(
    ("exception", "expected_cause"),
    [
        (barebones_runtime.ContractInvalidError, "CONTRACT_INVALID"),
        (RuntimeError, "EXECUTION_FAILED"),
    ],
)
def test_sandbox_exception_records_terminal_failure_consistently(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    exception: type[Exception],
    expected_cause: str,
) -> None:
    """A TEST-ONLY sandbox refuses before any provider call or candidate execution."""

    class RefusingSandbox:
        def run(self, *_args: Any, **_kwargs: Any) -> None:
            raise exception("TEST-ONLY sandbox unavailable")

    monkeypatch.setattr(barebones_runtime, "BubblewrapCandidateSandbox", RefusingSandbox)
    marker = tmp_path / "provider-called"
    provider_script = tmp_path / "provider.py"
    provider_script.write_text(
        f"from pathlib import Path; Path({str(marker)!r}).write_text('called')"
    )
    run_id = "sandbox-refusal"
    assert (
        main(
            [
                "barebones",
                "run",
                str(_REPOSITORY / "examples/barebones/e1-contract.json"),
                "--workspace",
                str(tmp_path / "candidate"),
                "--run-id",
                run_id,
                "--repository-root",
                str(tmp_path),
                "--approval-receipt",
                str(_REPOSITORY / "examples/barebones/e1-approval-receipt.json"),
                "--expected-approver",
                "fixture-human",
                "--provider-command",
                f"{sys.executable} {provider_script}",
            ]
        )
        == 3
    )
    immediate = json.loads(capsys.readouterr().out)
    assert immediate["state"] == "HALTED"
    assert immediate["cause"] == expected_cause
    assert not marker.exists()

    events = tuple(EvidenceLedger.open_existing(tmp_path, run_id).verify())
    assert events[-1]["event_type"] == "halted"
    assert events[-1]["state"] == "HALTED"
    assert events[-1]["payload"]["cause"] == immediate["cause"]
    assert all(event["event_type"] != "release_ready" for event in events)

    assert main(["barebones", "status", run_id, "--repository-root", str(tmp_path)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert (status["state"], status["cause"]) == ("HALTED", immediate["cause"])
    assert main(["barebones", "inspect", run_id, "--repository-root", str(tmp_path)]) == 3
    inspect = json.loads(capsys.readouterr().out)
    assert inspect["state"] == "HALTED"
    assert inspect["release_eligible"] is False


def test_terminal_persistence_failure_is_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed terminal append cannot be mistaken for a finalized run."""

    class RefusingSandbox:
        def run(self, *_args: Any, **_kwargs: Any) -> None:
            raise barebones_runtime.ContractInvalidError("TEST-ONLY sandbox unavailable")

    append = EvidenceLedger.append

    def refuse_halt(self: EvidenceLedger, **kwargs: Any) -> Any:
        if kwargs.get("event_type") == "halted":
            raise EvidenceIntegrityError("TEST-ONLY terminal persistence refused")
        return append(self, **kwargs)

    monkeypatch.setattr(EvidenceLedger, "append", refuse_halt)
    contract = json.loads((_REPOSITORY / "examples/barebones/e1-contract.json").read_text())
    with pytest.raises(
        EvidenceIntegrityError, match="terminal evidence append could not be confirmed"
    ):
        run_to_release_ready(
            contract=contract,
            repository_root=tmp_path,
            workspace=tmp_path / "candidate",
            run_id="failed-persistence",
            provider=CommandModelProvider("TEST-ONLY-never-run", 1),
            candidate_sandbox=RefusingSandbox(),
        )


def test_empty_meaningful_red_records_terminal_failure_without_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed baseline assertion after validation cannot remain IN_PROGRESS."""

    class NoRunSandbox:
        def run(self, *_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("TEST-ONLY sandbox must not execute")

    monkeypatch.setattr(barebones_runtime, "_verify_snapshot", lambda *_args, **_kwargs: ())
    contract = json.loads((_REPOSITORY / "examples/barebones/e1-contract.json").read_text())
    with pytest.raises(barebones_runtime.ContractInvalidError, match="baseline did not observe"):
        run_to_release_ready(
            contract=contract,
            repository_root=tmp_path,
            workspace=tmp_path / "candidate",
            run_id="empty-meaningful-red",
            provider=CommandModelProvider("TEST-ONLY-never-run", 1),
            candidate_sandbox=NoRunSandbox(),
        )
    events = tuple(EvidenceLedger.open_existing(tmp_path, "empty-meaningful-red").verify())
    assert events[-1]["event_type"] == "halted"
    assert events[-1]["state"] == "HALTED"
    assert events[-1]["payload"]["cause"] == "CONTRACT_INVALID"


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

    assert args.fn(args) == 3
    output = json.loads(capsys.readouterr().out)
    assert output["state"] == "HALTED"
    assert output["cause"] == "PROVIDER_WRITE_ISOLATION_UNVERIFIED"
    assert output["assurance_scope"] == "CANDIDATE_RESPONSE_ONLY"
    assert output["release_eligible"] is False
    assert output["release_blocker"] == "PROVIDER_WRITE_ISOLATION_UNVERIFIED"
    assert output["model_calls"] == 1
    events = [json.loads(line) for line in Path(output["evidence"]).read_text().splitlines()]
    approval = events[0]["payload"]["approval"]
    assert approval["status"] == "VERIFIED"
    assert approval["authority"] == "fixture-human"
    receipt = json.loads((_REPOSITORY / "examples/barebones/e1-approval-receipt.json").read_text())
    receipt_path = _REPOSITORY / "examples/barebones/e1-approval-receipt.json"
    submitted_digest = "sha256:" + hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    assert approval["receipt_digest"] == receipt["receipt_digest"]
    assert approval["receipt_blob_digest"] == submitted_digest

    for command in ("status", "evidence", "inspect"):
        assert main(
            [
                "barebones",
                command,
                "cli-e1",
                "--repository-root",
                str(tmp_path),
            ]
        ) == (3 if command == "inspect" else 0)
        publication = json.loads(capsys.readouterr().out)
        assert publication["approval"] == {
            "status": "VERIFIED",
            "authority": "fixture-human",
            "receipt_digest": receipt["receipt_digest"],
        }
        if command == "inspect":
            assert publication["candidate_response_verified"] is True
            assert publication["release_eligible"] is False
            assert publication["release_blocker"] == "PROVIDER_WRITE_ISOLATION_UNVERIFIED"


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


def test_invalid_run_id_is_rejected_before_contract_or_provider(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = build_parser().parse_args(
        [
            "barebones",
            "run",
            str(_REPOSITORY / "examples/barebones/e1-contract.json"),
            "--workspace",
            str(tmp_path / "candidate"),
            "--run-id",
            "../bad",
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
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "cause": "EVIDENCE_INVALID",
        "detail": "run_id must be a bounded filesystem-safe identifier",
        "state": "HALTED",
    }
    assert not (tmp_path / ".pmpe").exists()


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


@pytest.mark.parametrize("invalid_cost", [float("inf"), 10**400, (1 << 53) + 1])
def test_invalid_provider_cost_is_classified_before_evidence(
    tmp_path: Path, invalid_cost: int | float
) -> None:
    class InvalidCostProvider:
        def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
            return {
                "request_digest": request["request_digest"],
                "files": {},
                "usage": {"estimated_cost_usd": invalid_cost},
            }

    contract = json.loads((_REPOSITORY / "examples/barebones/e1-contract.json").read_text())
    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="invalid-provider-cost",
        provider=InvalidCostProvider(),
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


def test_accumulated_provider_tokens_outside_json_range_are_rejected() -> None:
    class HugeTokenProvider:
        def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
            return {
                "request_digest": request["request_digest"],
                "files": {},
                "usage": {"input_tokens": (1 << 53) - 1},
            }

    counters: dict[str, Any] = {
        "calls": 0,
        "bytes": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "estimated_cost_usd": 0.0,
        "provider_model_id": "",
    }
    provider = HugeTokenProvider()
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

    assert counters["tokens_in"] == (1 << 53) - 1


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


@pytest.mark.parametrize(
    "failure",
    [
        "missing-provider",
        "request-io",
        "path-validation-io",
        "candidate-path-collision",
        "snapshot-io",
    ],
)
def test_post_admission_io_failure_has_persisted_terminal_status(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    workspace = tmp_path / "candidate"
    provider_command = str(tmp_path / "missing-provider")
    if failure not in {"missing-provider", "request-io"}:
        provider = tmp_path / "provider.py"
        relative = (
            "product.py/child.py"
            if failure == "candidate-path-collision"
            else "normal_added.py"
            if failure == "path-validation-io"
            else "product.py"
        )
        files = {relative: 'def health():\n    return {"status": "ok"}\n'}
        provider.write_text(
            "import json, sys\n"
            "request = json.load(sys.stdin)['request']\n"
            f"files = {files!r}\n"
            "print(json.dumps({'request_digest': request['request_digest'], 'files': files}))\n"
        )
        provider_command = f"{sys.executable} {provider}"
    if failure == "request-io":

        def interrupted_request(**_kwargs: Any) -> dict[str, Any]:
            raise OSError("TEST-ONLY request I/O interruption")

        monkeypatch.setattr(barebones_runtime, "_model_request", interrupted_request)
    if failure == "path-validation-io":
        original_safe_path = barebones_runtime._safe_path

        def interrupted_path(root: Path, relative: str) -> Path:
            if relative == "normal_added.py":
                raise OSError("TEST-ONLY path inspection I/O interruption")
            return original_safe_path(root, relative)

        monkeypatch.setattr(barebones_runtime, "_safe_path", interrupted_path)
    if failure == "snapshot-io":
        original_snapshot = barebones_runtime._workspace_snapshot
        workspace_snapshots = 0

        def interrupted_snapshot(path: Path) -> dict[str, bytes]:
            nonlocal workspace_snapshots
            if path == workspace:
                workspace_snapshots += 1
                if workspace_snapshots == 2:
                    raise OSError("TEST-ONLY snapshot I/O interruption")
            return original_snapshot(path)

        monkeypatch.setattr(barebones_runtime, "_workspace_snapshot", interrupted_snapshot)

    run_id = f"normal-io-{failure}"
    assert (
        main(
            [
                "barebones",
                "run",
                str(_REPOSITORY / "examples/barebones/e1-contract.json"),
                "--workspace",
                str(workspace),
                "--run-id",
                run_id,
                "--repository-root",
                str(tmp_path),
                "--approval-receipt",
                str(_REPOSITORY / "examples/barebones/e1-approval-receipt.json"),
                "--expected-approver",
                "fixture-human",
                "--provider-command",
                provider_command,
            ]
        )
        == 3
    )
    immediate = json.loads(capsys.readouterr().out)
    assert (immediate["state"], immediate["cause"]) == ("HALTED", "EXECUTION_FAILED")
    events = tuple(EvidenceLedger.open_existing(tmp_path, run_id).verify())
    assert (events[-1]["event_type"], events[-1]["state"]) == ("halted", "HALTED")
    assert events[-1]["payload"]["cause"] == immediate["cause"]
    assert main(["barebones", "status", run_id, "--repository-root", str(tmp_path)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert (status["state"], status["cause"]) == ("HALTED", immediate["cause"])
    assert main(["barebones", "inspect", run_id, "--repository-root", str(tmp_path)]) == 3
    inspection = json.loads(capsys.readouterr().out)
    assert inspection["state"] == "HALTED"
    assert inspection["release_eligible"] is False


def test_unbalanced_provider_command_is_structured_contract_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_id = "malformed-provider-command"
    assert (
        main(
            [
                "barebones",
                "run",
                str(_REPOSITORY / "examples/barebones/e1-contract.json"),
                "--workspace",
                str(tmp_path / "candidate"),
                "--run-id",
                run_id,
                "--repository-root",
                str(tmp_path),
                "--approval-receipt",
                str(_REPOSITORY / "examples/barebones/e1-approval-receipt.json"),
                "--expected-approver",
                "fixture-human",
                "--provider-command",
                "'unbalanced",
            ]
        )
        == 3
    )
    output = json.loads(capsys.readouterr().out)
    assert (output["state"], output["cause"]) == ("HALTED", "CONTRACT_INVALID")
    assert output["detail"] == "provider command is malformed"
    assert not (tmp_path / "candidate").exists()
    assert not (tmp_path / ".pmpe" / "runs" / run_id).exists()


def test_transient_baseline_blob_io_failure_persists_halt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    put_blob = EvidenceLedger.put_blob
    calls = 0

    def fail_once_at_baseline(self: EvidenceLedger, payload: bytes) -> str:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("TEST-ONLY baseline blob write failed")
        return put_blob(self, payload)

    monkeypatch.setattr(EvidenceLedger, "put_blob", fail_once_at_baseline)
    run_id = "transient-baseline-blob-io"
    assert (
        main(
            [
                "barebones",
                "run",
                str(_REPOSITORY / "examples/barebones/e1-contract.json"),
                "--workspace",
                str(tmp_path / "candidate"),
                "--run-id",
                run_id,
                "--repository-root",
                str(tmp_path),
                "--approval-receipt",
                str(_REPOSITORY / "examples/barebones/e1-approval-receipt.json"),
                "--expected-approver",
                "fixture-human",
                "--provider-command",
                str(tmp_path / "never-started-provider"),
            ]
        )
        == 3
    )
    immediate = json.loads(capsys.readouterr().out)
    assert (immediate["state"], immediate["cause"]) == ("HALTED", "EXECUTION_FAILED")
    assert calls == 4
    events = tuple(EvidenceLedger.open_existing(tmp_path, run_id).verify())
    assert (events[-1]["event_type"], events[-1]["state"]) == ("halted", "HALTED")
    assert events[-1]["payload"]["cause"] == "EXECUTION_FAILED"
    assert main(["barebones", "status", run_id, "--repository-root", str(tmp_path)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert (status["state"], status["cause"]) == ("HALTED", "EXECUTION_FAILED")


def test_terminal_append_io_failure_does_not_claim_a_finalized_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    append = EvidenceLedger.append

    def refuse_terminal(self: EvidenceLedger, **kwargs: Any) -> Any:
        if kwargs.get("event_type") == "halted":
            raise OSError("TEST-ONLY terminal append failed")
        return append(self, **kwargs)

    monkeypatch.setattr(EvidenceLedger, "append", refuse_terminal)
    run_id = "terminal-append-io"
    assert (
        main(
            [
                "barebones",
                "run",
                str(_REPOSITORY / "examples/barebones/e1-contract.json"),
                "--workspace",
                str(tmp_path / "candidate"),
                "--run-id",
                run_id,
                "--repository-root",
                str(tmp_path),
                "--approval-receipt",
                str(_REPOSITORY / "examples/barebones/e1-approval-receipt.json"),
                "--expected-approver",
                "fixture-human",
                "--provider-command",
                str(tmp_path / "missing-provider"),
            ]
        )
        == 3
    )
    immediate = json.loads(capsys.readouterr().out)
    assert (immediate["state"], immediate["cause"]) == (
        "UNKNOWN",
        "EVIDENCE_PERSISTENCE_UNCONFIRMED",
    )
    assert immediate["release_eligible"] is False
    events = tuple(EvidenceLedger.open_existing(tmp_path, run_id).verify())
    assert events[-1]["state"] == "BUILDING"
    assert main(["barebones", "status", run_id, "--repository-root", str(tmp_path)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert (status["state"], status["cause"]) == ("BUILDING", "IN_PROGRESS")


def test_offline_provider_mode_is_labeled_without_release_authority(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    class FixtureOfflineResponse:
        def run_with_input(self, *_args: Any, input_data: bytes, **_kwargs: Any) -> Any:
            request = json.loads(input_data)["request"]
            response = {
                "request_digest": request["request_digest"],
                "files": {"product.py": 'def health():\n    return {"status": "ok"}\n'},
            }
            return subprocess.CompletedProcess([], 0, json.dumps(response), "")

    bundle = tmp_path / "offline-bundle"
    bundle.mkdir()
    (bundle / "adapter.py").write_text("# TEST-ONLY fixture entry\n")
    monkeypatch.setattr(
        "pmpe.provider_isolation._protected_system_python", lambda: "/usr/bin/python3"
    )
    provider = OfflineConfinedProvider(
        bundle=bundle,
        entry="adapter.py",
        protected_roots=(),
        timeout_seconds=5,
        sandbox=FixtureOfflineResponse(),  # type: ignore[arg-type] - test-only adapter response
    )
    contract = json.loads((_REPOSITORY / "examples/barebones/e1-contract.json").read_text())
    run_id = "offline-mode-label"
    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id=run_id,
        provider=provider,
    )
    assert result.state is RunState.HALTED
    assert result.cause == "PROVIDER_WRITE_ISOLATION_UNVERIFIED"
    assert result.telemetry["provider_write_isolation"] == "UNVERIFIED_OFFLINE_MODE"
    events = tuple(EvidenceLedger.open_existing(tmp_path, run_id).verify())
    candidate = next(
        event for event in events if event["event_type"] == "candidate_response_verified"
    )
    assert candidate["payload"]["provider_write_isolation"] == "UNVERIFIED_OFFLINE_MODE"
    assert events[-1]["payload"]["provider_write_isolation"] == "UNVERIFIED_OFFLINE_MODE"
    assert not any(event["event_type"] == "release_ready" for event in events)
    assert main(["barebones", "status", run_id, "--repository-root", str(tmp_path)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["telemetry"]["provider_write_isolation"] == "UNVERIFIED_OFFLINE_MODE"
    assert status["release_eligible"] is False
    assert main(["barebones", "inspect", run_id, "--repository-root", str(tmp_path)]) == 3
    inspection = json.loads(capsys.readouterr().out)
    assert inspection["provider_write_isolation"] == "UNVERIFIED_OFFLINE_MODE"
    assert inspection["release_eligible"] is False


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


def test_provider_group_is_fenced_before_the_exited_leader_is_reaped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []

    class ExitedProvider:
        pid = 4321

        def wait(self, timeout: float | None = None) -> int:
            events.append(("wait", timeout))
            return 7

    def observed_waitid(*args: object) -> object:
        events.append(("waitid", args))
        return object()

    def observed_killpg(pid: int, action: object) -> None:
        events.append(("killpg", pid, action))

    monkeypatch.setattr(barebones_cmd.os, "waitid", observed_waitid)
    monkeypatch.setattr(barebones_cmd.os, "killpg", observed_killpg)
    process = ExitedProvider()

    assert barebones_cmd._wait_for_provider_exit_without_reaping(process, 1.0)  # type: ignore[arg-type]
    assert barebones_cmd._fence_provider_group(process) == 7  # type: ignore[arg-type]
    assert [event[0] for event in events] == ["waitid", "killpg", "wait"]  # type: ignore[index]


def test_command_provider_propagates_outer_timeout_to_the_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def completed(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        observed["args"] = args
        observed["environment"] = kwargs.get("environment")
        return subprocess.CompletedProcess(
            ("provider",),
            0,
            b'{"request_digest":"bound","summary":"ok"}',
            b"",
        )

    monkeypatch.setattr(barebones_cmd, "_run_provider_command", completed)

    response = CommandModelProvider("provider", 960).invoke(
        purpose="advisory_review", request={"request_digest": "bound"}
    )

    assert response["summary"] == "ok"
    environment = observed["environment"]
    assert isinstance(environment, dict)
    assert environment["PMPE_PROVIDER_TIMEOUT_SECONDS"] == "960"


def test_default_provider_timeout_allows_the_codex_xhigh_budget() -> None:
    args = build_parser().parse_args(
        [
            "barebones",
            "run",
            "contract.json",
            "--workspace",
            "candidate",
            "--run-id",
            "run",
            "--approval-receipt",
            "receipt.json",
            "--expected-approver",
            "owner",
            "--provider-command",
            "provider",
        ]
    )

    assert args.provider_timeout == 960


class _ComparableProvider:
    def __init__(
        self,
        *,
        variant: str,
        prompt_version: str = "prompt-v1",
        cli_version: str = "codex-cli_1.0.0",
    ) -> None:
        self.variant = variant
        self.prompt_version = prompt_version
        self.cli_version = cli_version

    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        metadata = {
            "provider": "real-provider-fixture",
            "model": "gpt-example",
            "prompt_version": self.prompt_version,
            "cli_version": self.cli_version,
        }
        if purpose == "code":
            return {
                "request_digest": request["request_digest"],
                "provider_metadata": metadata,
                "files": {
                    "product.py": (
                        f'"""{self.variant}."""\n\n'
                        "def health() -> dict[str, str]:\n"
                        '    return {"status": "ok"}\n'
                    )
                },
            }
        return {
            "request_digest": request["request_digest"],
            "provider_metadata": metadata,
            "summary": "Deterministic checks passed.",
        }


def _approved_comparable_run(
    root: Path,
    *,
    run_id: str,
    variant: str,
    prompt_version: str = "prompt-v1",
    historical_release: bool = True,
) -> None:
    contract_path = _REPOSITORY / "examples/barebones/e1-contract.json"
    receipt_path = _REPOSITORY / "examples/barebones/e1-approval-receipt.json"
    contract = json.loads(contract_path.read_text())
    receipt_source = receipt_path.read_bytes()
    result = run_to_release_ready(
        contract=contract,
        repository_root=root,
        workspace=root / "candidate",
        run_id=run_id,
        provider=_ComparableProvider(
            variant=variant,
            prompt_version=prompt_version,
        ),
        approval_receipt=json.loads(receipt_source),
        approval_authority="fixture-human",
        approval_receipt_bytes=receipt_source,
    )
    assert result.state is RunState.HALTED
    assert result.cause == "PROVIDER_WRITE_ISOLATION_UNVERIFIED"
    if historical_release:
        # Reconstruct a legacy release record only as a reader fixture. The
        # current generic-provider runtime never emits this terminal state.
        events_path = root / ".pmpe" / "runs" / run_id / "events.jsonl"
        events = [json.loads(line) for line in events_path.read_text().splitlines()]
        candidate = next(
            event for event in events if event["event_type"] == "candidate_response_verified"
        )
        terminal = events[-1]
        terminal["event_type"] = "release_ready"
        terminal["state"] = "RELEASE_READY"
        terminal["blob_digests"] = candidate["blob_digests"]
        terminal["payload"] = {
            "candidate_digest": candidate["payload"]["candidate_digest"],
            "telemetry": {"model_calls": 1},
        }
        _write_events_with_valid_hash_chain(events_path, events)


def _write_events_with_valid_hash_chain(events_path: Path, events: list[dict[str, Any]]) -> None:
    previous_digest = "sha256:" + "0" * 64
    for event in events:
        event["previous_digest"] = previous_digest
        body = {key: value for key, value in event.items() if key != "event_digest"}
        event["event_digest"] = canonical_digest(body)
        previous_digest = event["event_digest"]
    events_path.write_bytes(b"".join(canonical_json_bytes(event) + b"\n" for event in events))


def _rewrite_subject_with_valid_hash_chain(root: Path, *, run_id: str, event_type: str) -> None:
    events_path = root / ".pmpe" / "runs" / run_id / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    changed = False
    for event in events:
        if event["event_type"] == event_type:
            event["subject_digest"] = "sha256:" + "f" * 64
            changed = True
    assert changed
    _write_events_with_valid_hash_chain(events_path, events)


def _rewrite_plan_with_valid_hash_chain(root: Path, *, run_id: str) -> None:
    events_path = root / ".pmpe" / "runs" / run_id / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    validation = next(event for event in events if event["event_type"] == "contract_validated")
    payload = validation["payload"]
    contract_digest = payload["contract_digest"]
    receipt_blob_digest = payload["approval"]["receipt_blob_digest"]
    plan_blob_digest = next(
        digest
        for digest in validation["blob_digests"]
        if digest not in {contract_digest, receipt_blob_digest}
    )
    blobs = root / ".pmpe" / "blobs"
    plan = json.loads((blobs / plan_blob_digest.removeprefix("sha256:")).read_text())
    plan["requirements"] = [*plan["requirements"], "FORGED-REQUIREMENT"]
    projection = {
        field: plan[field]
        for field in (
            "contract_digest",
            "requirements",
            "tasks",
            "criteria",
            "trusted_test_digests",
        )
    }
    plan["plan_digest"] = canonical_digest(projection)
    plan_source = json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    replacement_digest = "sha256:" + hashlib.sha256(plan_source).hexdigest()
    (blobs / replacement_digest.removeprefix("sha256:")).write_bytes(plan_source)
    validation["blob_digests"] = sorted(
        replacement_digest if digest == plan_blob_digest else digest
        for digest in validation["blob_digests"]
    )
    payload["plan_digest"] = plan["plan_digest"]
    _write_events_with_valid_hash_chain(events_path, events)


def _put_json_blob(root: Path, value: Any) -> str:
    source = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    digest = "sha256:" + hashlib.sha256(source).hexdigest()
    (root / ".pmpe" / "blobs" / digest.removeprefix("sha256:")).write_bytes(source)
    return digest


def _rewrite_coder_evidence(
    root: Path,
    *,
    run_id: str,
    mutate: Callable[[dict[str, Any], dict[str, Any]], None],
) -> None:
    events_path = root / ".pmpe" / "runs" / run_id / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    coder = next(event for event in reversed(events) if event["event_type"] == "coder_completed")
    payload = coder["payload"]
    blobs = root / ".pmpe" / "blobs"
    request = json.loads(
        (blobs / payload["request_blob_digest"].removeprefix("sha256:")).read_text()
    )
    response = json.loads(
        (blobs / payload["response_blob_digest"].removeprefix("sha256:")).read_text()
    )
    mutate(request, response)
    request_blob_digest = _put_json_blob(root, request)
    response_blob_digest = _put_json_blob(root, response)
    payload["request_blob_digest"] = request_blob_digest
    payload["response_blob_digest"] = response_blob_digest
    payload["provider_behavior"]["request_digest"] = response["request_digest"]
    payload["provider_behavior"]["output_digest"] = canonical_digest(response["files"])
    coder["blob_digests"] = sorted({request_blob_digest, response_blob_digest})
    _write_events_with_valid_hash_chain(events_path, events)


def test_compare_refuses_candidate_only_runs_without_sealed_release(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline_root = tmp_path / "baseline"
    current_root = tmp_path / "current"
    _approved_comparable_run(
        baseline_root, run_id="baseline", variant="first candidate", historical_release=False
    )
    _approved_comparable_run(
        current_root, run_id="current", variant="second candidate", historical_release=False
    )
    assert (
        main(
            [
                "barebones",
                "compare",
                "baseline",
                "current",
                "--baseline-root",
                str(baseline_root),
                "--current-root",
                str(current_root),
                "--expected-approver",
                "fixture-human",
                "--compiler-root",
                str(_REPOSITORY),
            ]
        )
        == 3
    )
    comparison = json.loads(capsys.readouterr().out)
    assert comparison["state"] == "HALTED"
    assert comparison["cause"] == "EVIDENCE_INVALID"


def test_compare_uses_verified_ledgers_and_keeps_candidate_variation_visible(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline_root = tmp_path / "baseline"
    current_root = tmp_path / "current"
    _approved_comparable_run(
        baseline_root,
        run_id="baseline",
        variant="first candidate",
    )
    _approved_comparable_run(
        current_root,
        run_id="current",
        variant="second candidate",
        prompt_version="prompt-v2",
    )

    result = main(
        [
            "barebones",
            "compare",
            "baseline",
            "current",
            "--baseline-root",
            str(baseline_root),
            "--current-root",
            str(current_root),
            "--expected-approver",
            "fixture-human",
            "--compiler-root",
            str(_REPOSITORY),
        ]
    )

    assert result == 0
    comparison = json.loads(capsys.readouterr().out)
    assert comparison["status"] == "COMPARABLE"
    assert comparison["plan_repeatable"] is True
    assert comparison["candidate_variation"]["detected"] is True
    assert comparison["behavior_drift"]["detected"] is True
    assert comparison["behavior_drift"]["cause"] == "PROVIDER_CONFIGURATION_CHANGED"
    assert comparison["behavior_drift"]["attribution"] == ["prompt_version"]
    assert comparison["baseline"]["provider_behavior"]["cli_version"] == "codex-cli_1.0.0"


@pytest.mark.parametrize(
    "replacement_files",
    (
        {},
        {
            "product.py": (
                '"""Unsealed response."""\n\n'
                "def health() -> dict[str, str]:\n"
                '    return {"status": "ok"}\n'
            )
        },
    ),
    ids=("empty-response", "different-response"),
)
def test_compare_rejects_coder_response_not_bound_to_sealed_candidate(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    replacement_files: dict[str, str],
) -> None:
    baseline_root = tmp_path / "baseline"
    current_root = tmp_path / "current"
    _approved_comparable_run(baseline_root, run_id="baseline", variant="first candidate")
    _approved_comparable_run(current_root, run_id="current", variant="second candidate")

    def replace_response(_request: dict[str, Any], response: dict[str, Any]) -> None:
        response["files"] = replacement_files

    _rewrite_coder_evidence(
        current_root,
        run_id="current",
        mutate=replace_response,
    )

    exit_code = main(
        [
            "barebones",
            "compare",
            "baseline",
            "current",
            "--baseline-root",
            str(baseline_root),
            "--current-root",
            str(current_root),
            "--expected-approver",
            "fixture-human",
            "--compiler-root",
            str(_REPOSITORY),
        ]
    )

    assert exit_code == 3
    comparison = json.loads(capsys.readouterr().out)
    assert comparison["detail"] == "Coder response files do not match the sealed candidate"


def test_compare_recomputes_the_recorded_coder_request_digest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline_root = tmp_path / "baseline"
    current_root = tmp_path / "current"
    _approved_comparable_run(baseline_root, run_id="baseline", variant="first candidate")
    _approved_comparable_run(current_root, run_id="current", variant="second candidate")

    def forge_digest(request: dict[str, Any], response: dict[str, Any]) -> None:
        forged = "sha256:" + "f" * 64
        request["request_digest"] = forged
        response["request_digest"] = forged

    _rewrite_coder_evidence(current_root, run_id="current", mutate=forge_digest)

    exit_code = main(
        [
            "barebones",
            "compare",
            "baseline",
            "current",
            "--baseline-root",
            str(baseline_root),
            "--current-root",
            str(current_root),
            "--expected-approver",
            "fixture-human",
            "--compiler-root",
            str(_REPOSITORY),
        ]
    )

    assert exit_code == 3
    comparison = json.loads(capsys.readouterr().out)
    assert comparison["detail"] == "Coder request digest is inconsistent"


def test_compare_binds_recorded_coder_request_to_the_approved_contract_and_plan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline_root = tmp_path / "baseline"
    current_root = tmp_path / "current"
    _approved_comparable_run(baseline_root, run_id="baseline", variant="first candidate")
    _approved_comparable_run(current_root, run_id="current", variant="second candidate")

    def forge_contract(request: dict[str, Any], response: dict[str, Any]) -> None:
        request["contract"]["contract_id"] = "FORGED-CONTRACT"
        body = {key: value for key, value in request.items() if key != "request_digest"}
        request_digest = canonical_digest(body)
        request["request_digest"] = request_digest
        response["request_digest"] = request_digest

    _rewrite_coder_evidence(current_root, run_id="current", mutate=forge_contract)

    exit_code = main(
        [
            "barebones",
            "compare",
            "baseline",
            "current",
            "--baseline-root",
            str(baseline_root),
            "--current-root",
            str(current_root),
            "--expected-approver",
            "fixture-human",
            "--compiler-root",
            str(_REPOSITORY),
        ]
    )

    assert exit_code == 3
    comparison = json.loads(capsys.readouterr().out)
    assert comparison["detail"] == ("Coder request is not bound to the approved contract and plan")


def test_compare_fails_closed_for_different_provider_requests(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline_root = tmp_path / "baseline"
    current_root = tmp_path / "current"
    _approved_comparable_run(
        baseline_root,
        run_id="baseline",
        variant="first candidate",
    )
    contract = json.loads((_REPOSITORY / "examples/barebones/e1-contract.json").read_text())
    contract["contract_status"] = "DRAFT"
    contract["approved_by"] = ""
    contract["approved_at"] = ""
    contract["functional_requirements"]["FR-001"]["statement"] = "A different request"
    draft_digest = canonical_digest(contract)
    approved_contract = json.loads(json.dumps(contract))
    approved_contract["contract_status"] = "APPROVED"
    approved_contract["approved_by"] = "fixture-human"
    approved_contract["approved_at"] = "2026-08-26T15:00:00Z"
    receipt = {
        "approved_at": approved_contract["approved_at"],
        "approved_by": approved_contract["approved_by"],
        "approved_contract_digest": canonical_digest(approved_contract),
        "contract_id": approved_contract["contract_id"],
        "contract_version": approved_contract["contract_version"],
        "decision": "APPROVED",
        "draft_digest": draft_digest,
        "schema_version": "1.0.0",
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    receipt_source = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    result = run_to_release_ready(
        contract=approved_contract,
        repository_root=current_root,
        workspace=current_root / "candidate",
        run_id="current",
        provider=_ComparableProvider(variant="second candidate"),
        approval_receipt=receipt,
        approval_authority="fixture-human",
        approval_receipt_bytes=receipt_source,
    )
    assert result.state is RunState.HALTED
    assert result.cause == "PROVIDER_WRITE_ISOLATION_UNVERIFIED"
    events_path = current_root / ".pmpe" / "runs" / "current" / "events.jsonl"
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    candidate = next(
        event for event in events if event["event_type"] == "candidate_response_verified"
    )
    events[-1]["event_type"] = "release_ready"
    events[-1]["state"] = "RELEASE_READY"
    events[-1]["blob_digests"] = candidate["blob_digests"]
    events[-1]["payload"] = {"candidate_digest": candidate["payload"]["candidate_digest"]}
    _write_events_with_valid_hash_chain(events_path, events)

    exit_code = main(
        [
            "barebones",
            "compare",
            "baseline",
            "current",
            "--baseline-root",
            str(baseline_root),
            "--current-root",
            str(current_root),
            "--expected-approver",
            "fixture-human",
            "--compiler-root",
            str(_REPOSITORY),
        ]
    )

    assert exit_code == 3
    comparison = json.loads(capsys.readouterr().out)
    assert comparison["status"] == "NOT_COMPARABLE"
    assert comparison["cause"] == "CONTRACT_CHANGED"


def test_compare_reverifies_approval_binding(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_root = tmp_path / "baseline"
    current_root = tmp_path / "current"
    _approved_comparable_run(
        baseline_root,
        run_id="baseline",
        variant="first candidate",
    )
    _approved_comparable_run(
        current_root,
        run_id="current",
        variant="second candidate",
    )

    def reject_approval(*args: object, **kwargs: object) -> str:
        raise ContractViolation("injected approval mismatch")

    monkeypatch.setattr(barebones_cmd, "verify_contract_approval", reject_approval)

    exit_code = main(
        [
            "barebones",
            "compare",
            "baseline",
            "current",
            "--baseline-root",
            str(baseline_root),
            "--current-root",
            str(current_root),
            "--expected-approver",
            "fixture-human",
            "--compiler-root",
            str(_REPOSITORY),
        ]
    )

    assert exit_code == 3
    comparison = json.loads(capsys.readouterr().out)
    assert comparison["state"] == "HALTED"
    assert comparison["cause"] == "EVIDENCE_INVALID"
    assert comparison["detail"] == "approval evidence is not bound to the contract"


@pytest.mark.parametrize(
    ("event_type", "expected_detail"),
    (
        ("coder_completed", "Coder behavior is not bound to the approved contract"),
        ("release_ready", "release candidate is not bound to the approved contract"),
    ),
)
def test_compare_rejects_cross_subject_coder_and_release_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    event_type: str,
    expected_detail: str,
) -> None:
    baseline_root = tmp_path / "baseline"
    current_root = tmp_path / "current"
    _approved_comparable_run(
        baseline_root,
        run_id="baseline",
        variant="first candidate",
    )
    _approved_comparable_run(
        current_root,
        run_id="current",
        variant="second candidate",
    )
    _rewrite_subject_with_valid_hash_chain(
        current_root,
        run_id="current",
        event_type=event_type,
    )

    exit_code = main(
        [
            "barebones",
            "compare",
            "baseline",
            "current",
            "--baseline-root",
            str(baseline_root),
            "--current-root",
            str(current_root),
            "--expected-approver",
            "fixture-human",
            "--compiler-root",
            str(_REPOSITORY),
        ]
    )

    assert exit_code == 3
    comparison = json.loads(capsys.readouterr().out)
    assert comparison["state"] == "HALTED"
    assert comparison["cause"] == "EVIDENCE_INVALID"
    assert comparison["detail"] == expected_detail


def test_compare_requires_a_caller_trusted_approval_authority(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline_root = tmp_path / "baseline"
    current_root = tmp_path / "current"
    _approved_comparable_run(
        baseline_root,
        run_id="baseline",
        variant="first candidate",
    )
    _approved_comparable_run(
        current_root,
        run_id="current",
        variant="second candidate",
    )

    exit_code = main(
        [
            "barebones",
            "compare",
            "baseline",
            "current",
            "--baseline-root",
            str(baseline_root),
            "--current-root",
            str(current_root),
            "--expected-approver",
            "untrusted-ledger-authority",
            "--compiler-root",
            str(_REPOSITORY),
        ]
    )

    assert exit_code == 3
    comparison = json.loads(capsys.readouterr().out)
    assert comparison["state"] == "HALTED"
    assert comparison["cause"] == "EVIDENCE_INVALID"
    assert comparison["detail"] == "approval authority does not match --expected-approver"


def test_compare_recompiles_the_contract_instead_of_trusting_a_fabricated_plan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline_root = tmp_path / "baseline"
    current_root = tmp_path / "current"
    _approved_comparable_run(
        baseline_root,
        run_id="baseline",
        variant="first candidate",
    )
    _approved_comparable_run(
        current_root,
        run_id="current",
        variant="second candidate",
    )
    _rewrite_plan_with_valid_hash_chain(current_root, run_id="current")

    exit_code = main(
        [
            "barebones",
            "compare",
            "baseline",
            "current",
            "--baseline-root",
            str(baseline_root),
            "--current-root",
            str(current_root),
            "--expected-approver",
            "fixture-human",
            "--compiler-root",
            str(_REPOSITORY),
        ]
    )

    assert exit_code == 3
    comparison = json.loads(capsys.readouterr().out)
    assert comparison["state"] == "HALTED"
    assert comparison["cause"] == "EVIDENCE_INVALID"
    assert comparison["detail"] == "recorded plan does not match deterministic compilation"
