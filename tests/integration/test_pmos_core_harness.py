"""Ordinary contract-mapping checks for the frozen PMOS task-tracker reference."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import runpy
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from pmpe import barebones as barebones_runtime
from pmpe.barebones import (
    BubblewrapCandidateSandbox,
    BudgetCaps,
    ContractInvalidError,
    RunState,
    _run_fixed_task_tracker,
    run_to_release_ready,
)
from pmpe.cli import main
from pmpe.contracts.authoring import approve_contract_draft, verify_contract_approval
from pmpe.contracts.canonical import canonical_digest
from pmpe.core_harness import CoreHarnessInvalidError, compile_required_harness
from pmpe.evidence.ledger import EvidenceLedger
from pmpe.task_tracker_harness import fixed_template, registry_identity
from tests.conftest import _LocalCandidateTestSandbox

ROOT = Path(__file__).resolve().parents[2]
PACKET = ROOT / "examples/pmos-task-tracker"
SOURCE = PACKET / "source"
MAPPED = PACKET / "mapped"


def _json(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text())
    return loaded


def test_source_bytes_and_mapped_draft_reproduce_exactly(tmp_path: Path) -> None:
    renderer = runpy.run_path(str(PACKET / "render_core_mapping.py"))
    for name, expected in renderer["SOURCE_RAW_SHA256"].items():
        assert hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == expected
    renderer["render"](tmp_path)
    for name in (
        "publisher-input.mapped.json",
        "contract.draft.json",
        "core-harness-mapping.json",
        "mapping-summary.json",
    ):
        assert (tmp_path / name).read_bytes() == (MAPPED / name).read_bytes()


def test_frozen_source_and_mapped_draft_preserve_all_pmos_cases_and_conditions() -> None:
    source = _json(SOURCE / "contract.approved.json")
    receipt = _json(SOURCE / "approval-receipt.json")
    mapping = _json(MAPPED / "core-harness-mapping.json")
    draft = _json(MAPPED / "contract.draft.json")
    summary = _json(MAPPED / "mapping-summary.json")
    assert hashlib.sha256((SOURCE / "contract.approved.json").read_bytes()).hexdigest() == (
        "41f93f23ca57cef11201fe685b18d66be882c122e5a3c7192e37e9018de0f0e2"
    )
    assert (
        verify_contract_approval(source, receipt, expected_approver="Abhillash Jadhav")
        == mapping["source_receipt_digest"]
    )
    assert mapping["source_contract_digest"] == canonical_digest(source)
    assert draft["contract_status"] == "DRAFT"
    assert draft["approved_by"] == draft["approved_at"] == ""
    assert summary["exact_draft_digest_approved"] is False
    assert summary["release_eligible"] is False
    assert summary["mapped_draft_digest"] == canonical_digest(draft)
    assert draft["required_harness_digest"] == canonical_digest(mapping)
    assert mapping["registry"] == registry_identity()
    assert draft["acceptance_criteria"] == source["acceptance_criteria"]
    assert len(draft["acceptance_criteria"]) == 14
    assert draft["acceptance_criteria"][12]["measure"] == (
        "task_tracker.missing_acknowledged_records"
    )
    assert draft["acceptance_criteria"][12]["sample"] == {"minimum": 10}
    assert [item["description"] for item in mapping["required_conditions"]] == [
        item["description"] for item in source["binary_release_gates"]
    ]
    assert all(item["required"] is True for item in mapping["required_conditions"])
    plan = compile_required_harness(draft, mapping)
    assert plan is not None
    assert len(plan.conditions) == 5
    assert plan.unproven_conditions() == tuple(f"GATE-{index:03}" for index in range(1, 6))


def test_missing_or_inconsistent_core_harness_mapping_refuses_admission() -> None:
    draft = _json(MAPPED / "contract.draft.json")
    mapping = _json(MAPPED / "core-harness-mapping.json")
    with pytest.raises(CoreHarnessInvalidError, match="missing"):
        compile_required_harness(draft, None)
    changed = copy.deepcopy(mapping)
    changed["required_conditions"][4]["description"] = "unreviewed change"
    with pytest.raises(CoreHarnessInvalidError, match="differs from contract digest"):
        compile_required_harness(draft, changed)
    for mutation in ("drop_condition", "drop_criterion", "self_claimed_pass"):
        changed = copy.deepcopy(mapping)
        if mutation == "drop_condition":
            changed["required_conditions"].pop()
        elif mutation == "drop_criterion":
            changed["required_conditions"][0]["criterion_refs"].pop()
        else:
            changed["required_conditions"][0]["status"] = "PASS"
        synthetic_contract = copy.deepcopy(draft)
        synthetic_contract["required_harness_digest"] = canonical_digest(changed)
        with pytest.raises(CoreHarnessInvalidError):
            compile_required_harness(synthetic_contract, changed)


def test_public_compile_requires_fixed_registry_and_mapping(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    contract = MAPPED / "contract.draft.json"
    mapping = MAPPED / "core-harness-mapping.json"
    base = ["barebones", "compile", str(contract), "--repository-root", str(tmp_path)]
    assert main(base) == 3
    assert json.loads(capsys.readouterr().out)["cause"] == "CONTRACT_INVALID"
    assert main([*base, "--core-harness-mapping", str(mapping)]) == 3
    assert json.loads(capsys.readouterr().out)["cause"] == "CONTRACT_INVALID"
    assert (
        main([*base, "--template", "pmos-task-tracker-v1", "--core-harness-mapping", str(mapping)])
        == 0
    )
    compiled = json.loads(capsys.readouterr().out)
    assert compiled["status"] == "COMPILES"
    assert compiled["contract_status"] == "DRAFT"
    assert compiled["coverage"] == {"structured": 13, "human_test": 0, "total": 14}
    assert compiled["unsupported_criteria"] == []
    assert compiled["execution_eligibility"] == "CORE_HARNESS_PROOF_PENDING"
    assert compiled["core_harness"]["proof_status"] == "NOT_ESTABLISHED"
    assert compiled["core_harness"]["required_condition_ids"] == [
        f"GATE-{index:03}" for index in range(1, 6)
    ]


class RetainedProductFixtureProvider:
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        assert purpose == "code"
        return {
            "request_digest": request["request_digest"],
            "files": {
                "product.py": (ROOT / "tests/fixtures/pmos_task_tracker_product.py").read_text()
            },
        }


class RepairingProductFixtureProvider:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        assert purpose == "code"
        self.calls += 1
        correct = (ROOT / "tests/fixtures/pmos_task_tracker_product.py").read_text()
        broken_line = 'tasks = [task for task in tasks if task["status"] == args.status]'
        assert broken_line in correct
        source = correct.replace(broken_line, "tasks = []") if self.calls == 1 else correct
        return {"request_digest": request["request_digest"], "files": {"product.py": source}}


def test_mapped_test_issuance_runs_all_14_approved_cases_and_still_halts_release(
    tmp_path: Path,
) -> None:
    draft = _json(MAPPED / "contract.draft.json")
    mapping = _json(MAPPED / "core-harness-mapping.json")
    issued = approve_contract_draft(
        draft,
        expected_draft_digest=canonical_digest(draft),
        approver="test-only-core-harness-issuer",
        approved_at="2026-10-01T00:00:00Z",
    )
    receipt_source = json.dumps(issued.receipt, sort_keys=True).encode()
    result = run_to_release_ready(
        contract=issued.contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="test-only-mapped-task-tracker",
        provider=RetainedProductFixtureProvider(),
        template=fixed_template(),
        budget=BudgetCaps(max_attempts=1),
        candidate_sandbox=_LocalCandidateTestSandbox(),
        approval_receipt=issued.receipt,
        approval_authority="test-only-core-harness-issuer",
        approval_receipt_bytes=receipt_source,
        core_harness_mapping=mapping,
    )
    assert result.state is RunState.HALTED
    assert result.cause == "PROVIDER_WRITE_ISOLATION_UNVERIFIED"
    assert result.model_calls == 1
    assert result.telemetry["core_harness"]["proof_status"] == "NOT_ESTABLISHED"
    ledger = EvidenceLedger.open_existing(tmp_path, result.run_id)
    events = tuple(ledger.verify())
    observed = [event for event in events if event["event_type"] == "supervisor_observations"]
    assert len(observed) == 2
    baseline, candidate = observed
    assert [item["criterion_id"] for item in baseline["payload"]["observations"]] == [
        f"AC-{index:03}" for index in range(1, 15)
    ]
    assert all(item["assertions_passed"] is False for item in baseline["payload"]["observations"])
    assert all(item["assertions_passed"] is True for item in candidate["payload"]["observations"])
    criterion_store_paths = []
    for entry in candidate["payload"]["observations"]:
        trace = json.loads(ledger.read_blob(entry["trace_digest"]))
        stores = {item["argv"][5] for item in trace}
        assert len(stores) == 1
        criterion_store_paths.append(next(iter(stores)))
    assert len(set(criterion_store_paths)) == 14
    expected_errors = {
        "AC-008": (2, "INVALID_TITLE"),
        "AC-009": (2, "INVALID_ID"),
        "AC-010": (2, "INVALID_STATUS"),
        "AC-011": (1, "STORE_INVALID"),
        "AC-012": (1, "STORE_IO"),
    }
    for entry in candidate["payload"]["observations"]:
        expected = expected_errors.get(entry["criterion_id"])
        if expected is None:
            continue
        trace = json.loads(ledger.read_blob(entry["trace_digest"]))
        assert any(
            item["result"]["exit_code"] == expected[0]
            and item["result"]["output"] == {"error": expected[1]}
            for item in trace
        )
    baseline_measure = baseline["payload"]["observations"][12]
    candidate_measure = candidate["payload"]["observations"][12]
    for event, entry, sample in (
        (baseline, baseline_measure, 0),
        (candidate, candidate_measure, 10),
    ):
        assert entry["criterion_id"] == "AC-013"
        assert entry["trace_digest"] in event["blob_digests"]
        response = json.loads(ledger.read_blob(entry["response_digest"]))
        trace = json.loads(ledger.read_blob(entry["trace_digest"]))
        assert (response["sample_size"], response["value"]) == (sample, 0)
        assert len(trace) == 11
        assert all(item["argv"][-2] == "create" for item in trace[:10])
        assert trace[-1]["argv"][-3:] == ["list", "--status", "all"]
    baseline_trace = json.loads(ledger.read_blob(baseline_measure["trace_digest"]))
    assert all(
        item["result"] == {"exit_code": 2, "output": {"error": "NOT_IMPLEMENTED"}}
        for item in baseline_trace
    )
    candidate_trace = json.loads(ledger.read_blob(candidate_measure["trace_digest"]))
    acknowledgements = [item["result"]["output"]["task"] for item in candidate_trace[:10]]
    assert [task["id"] for task in acknowledgements] == list(range(1, 11))
    assert candidate_trace[-1]["result"]["output"]["tasks"] == acknowledgements
    gates = next(event for event in events if event["event_type"] == "release_gates_evaluated")
    assert [gate["status"] for gate in gates["payload"]["gates"]] == ["PASS"]
    core = next(event for event in events if event["event_type"] == "core_conditions_evaluated")
    assert core["payload"]["mapping_digest"] == draft["required_harness_digest"]
    assert [item["status"] for item in core["payload"]["conditions"]] == [
        "PASS",
        "BLOCKED",
        "BLOCKED",
        "BLOCKED",
        "BLOCKED",
    ]
    assert core["payload"]["blocking_condition_ids"] == [
        f"GATE-{index:03}" for index in range(2, 6)
    ]
    assert core["payload"]["release_eligible"] is False
    assert result.telemetry["core_harness"]["blocking_condition_ids"] == [
        f"GATE-{index:03}" for index in range(2, 6)
    ]
    assert events[-1]["state"] == "HALTED"
    assert not any(event["event_type"] == "release_ready" for event in events)


def test_fixed_harness_accepts_an_ordinary_second_attempt_product_repair(tmp_path: Path) -> None:
    draft = _json(MAPPED / "contract.draft.json")
    mapping = _json(MAPPED / "core-harness-mapping.json")
    provider = RepairingProductFixtureProvider()
    result = run_to_release_ready(
        contract=draft,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="test-only-filter-repair",
        provider=provider,
        template=fixed_template(),
        budget=BudgetCaps(max_attempts=2),
        candidate_sandbox=_LocalCandidateTestSandbox(),
        core_harness_mapping=mapping,
    )
    assert provider.calls == 2
    assert (result.state, result.cause) == (
        RunState.HALTED,
        "PROVIDER_WRITE_ISOLATION_UNVERIFIED",
    )
    events = tuple(EvidenceLedger.open_existing(tmp_path, result.run_id).verify())
    assert sum(event["event_type"] == "verification_started" for event in events) == 2
    final = [event for event in events if event["event_type"] == "supervisor_observations"][-1]
    assert all(item["assertions_passed"] for item in final["payload"]["observations"])
    assert not any(event["event_type"] == "release_ready" for event in events)


@pytest.mark.skipif(
    os.environ.get("PMPE_TEST_REAL_SANDBOX") != "true",
    reason="requires the dedicated CI namespace runtime",
)
def test_fixed_task_tracker_product_uat_in_supported_candidate_sandbox(tmp_path: Path) -> None:
    draft = _json(MAPPED / "contract.draft.json")
    mapping = _json(MAPPED / "core-harness-mapping.json")
    result = run_to_release_ready(
        contract=draft,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="test-only-real-sandbox-task-tracker",
        provider=RetainedProductFixtureProvider(),
        template=fixed_template(),
        budget=BudgetCaps(max_attempts=1),
        candidate_sandbox=BubblewrapCandidateSandbox(),
        core_harness_mapping=mapping,
    )
    assert (result.state, result.cause) == (
        RunState.HALTED,
        "PROVIDER_WRITE_ISOLATION_UNVERIFIED",
    )
    events = tuple(EvidenceLedger.open_existing(tmp_path, result.run_id).verify())
    candidate = [event for event in events if event["event_type"] == "supervisor_observations"][-1]
    assert len(candidate["payload"]["observations"]) == 14
    assert all(item["assertions_passed"] for item in candidate["payload"]["observations"])
    assert not any(event["event_type"] == "release_ready" for event in events)


def test_fixed_observer_refuses_protocol_failure_instead_of_assertion_red(tmp_path: Path) -> None:
    (tmp_path / "product.py").write_text("# TEST-ONLY missing CLI JSON\n")
    with pytest.raises(ContractInvalidError, match="observer failed before an assertion"):
        _run_fixed_task_tracker(
            tmp_path,
            "observe",
            {"fixture": "empty", "steps": [["list"]]},
            _LocalCandidateTestSandbox(),
            deadline=None,
        )


def test_fixed_observer_bounds_each_child_process(tmp_path: Path) -> None:
    (tmp_path / "product.py").write_text("import time\ntime.sleep(5)\n")
    with pytest.raises(ContractInvalidError, match="child process timed out"):
        _run_fixed_task_tracker(
            tmp_path,
            "observe",
            {"fixture": "empty", "steps": [["list"]]},
            _LocalCandidateTestSandbox(),
            deadline=None,
        )


def test_expired_aggregate_deadline_refuses_before_child_process(tmp_path: Path) -> None:
    class NeverSandbox:
        def run(self, *_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("observer must not start after aggregate deadline")

    with pytest.raises(RuntimeError, match="TRUSTED_VERIFICATION_TIME_LIMIT"):
        _run_fixed_task_tracker(
            tmp_path,
            "observe",
            {"fixture": "empty", "steps": [["list"]]},
            NeverSandbox(),  # type: ignore[arg-type] - test-only no-run assertion
            deadline=time.monotonic() - 1,
        )


def test_public_cli_runs_test_only_task_tracker_packet_but_refuses_release(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = _json(MAPPED / "contract.draft.json")
    mapping = MAPPED / "core-harness-mapping.json"
    issued = approve_contract_draft(
        draft,
        expected_draft_digest=canonical_digest(draft),
        approver="test-only-cli-issuer",
        approved_at="2026-10-01T00:00:00Z",
    )
    contract_path = tmp_path / "contract.json"
    receipt_path = tmp_path / "receipt.json"
    contract_path.write_text(json.dumps(issued.contract))
    receipt_path.write_text(json.dumps(issued.receipt))
    provider_script = tmp_path / "fixture_provider.py"
    product_path = ROOT / "tests/fixtures/pmos_task_tracker_product.py"
    provider_script.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "request = json.load(sys.stdin)['request']\n"
        f"product = Path({str(product_path)!r}).read_text()\n"
        "print(json.dumps({'request_digest': request['request_digest'], "
        "'files': {'product.py': product}}))\n"
    )
    monkeypatch.setattr(barebones_runtime, "BubblewrapCandidateSandbox", _LocalCandidateTestSandbox)
    run_id = "test-only-task-tracker-cli"
    assert (
        main(
            [
                "barebones",
                "run",
                str(contract_path),
                "--workspace",
                str(tmp_path / "candidate"),
                "--run-id",
                run_id,
                "--repository-root",
                str(tmp_path),
                "--approval-receipt",
                str(receipt_path),
                "--expected-approver",
                "test-only-cli-issuer",
                "--provider-command",
                f"{sys.executable} {provider_script}",
                "--template",
                "pmos-task-tracker-v1",
                "--core-harness-mapping",
                str(mapping),
            ]
        )
        == 3
    )
    immediate = json.loads(capsys.readouterr().out)
    assert (immediate["state"], immediate["cause"]) == (
        "HALTED",
        "PROVIDER_WRITE_ISOLATION_UNVERIFIED",
    )
    assert immediate["annotation"]["candidate_response_verified"] is True
    assert immediate["release_eligible"] is False
    ledger = EvidenceLedger.open_existing(tmp_path, run_id)
    events = tuple(ledger.verify())
    observations = [event for event in events if event["event_type"] == "supervisor_observations"]
    assert len(observations) == 2
    assert len(observations[1]["payload"]["observations"]) == 14
    assert all(
        item["assertions_passed"] is True for item in observations[1]["payload"]["observations"]
    )
    assert not any(event["event_type"] == "release_ready" for event in events)
    assert main(["barebones", "inspect", run_id, "--repository-root", str(tmp_path)]) == 3
    inspection = json.loads(capsys.readouterr().out)
    assert inspection["candidate_response_verified"] is True
    assert inspection["release_eligible"] is False
