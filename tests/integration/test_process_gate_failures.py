from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pmpe.barebones import BudgetCaps, RunState, run_to_release_ready
from pmpe.evidence.ledger import EvidenceLedger
from tests.integration.test_process_gate_runtime import (
    LocalSandbox,
    ReplayProvider,
    bound_contract,
    make_inputs,
)


@pytest.mark.parametrize("variant", ["crash", "unchanged", "missing_file", "extra_test"])
def test_negative_control_cannot_pass_by_crash_or_invalid_mutation(
    tmp_path: Path, variant: str
) -> None:
    from dataclasses import replace

    inputs, items = make_inputs(tmp_path)
    candidate = {"product.py": b"def health():\n    return {'status': 'ok'}\n"}
    mutant = {"product.py": b"raise RuntimeError('unrelated crash')\n"}
    if variant == "unchanged":
        mutant = candidate
    elif variant == "missing_file":
        mutant = {"other.py": b"# missing product"}
    elif variant == "extra_test":
        mutant["tests/extra.py"] = b"# unauthorized evaluator addition"
    inputs = replace(inputs, negative_controls={"broken": mutant})
    result = run_to_release_ready(
        contract=bound_contract(items),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="invalid-mutant",
        provider=ReplayProvider(),
        candidate_sandbox=LocalSandbox(),
        budget=BudgetCaps(max_attempts=1),
        process_gate_inputs=inputs,
    )
    assert result.state is RunState.HALTED
    events = list(EvidenceLedger.open_existing(tmp_path, result.run_id).verify())
    gates = next(
        event["payload"]["gates"]
        for event in events
        if event["event_type"] == "release_gates_evaluated"
    )
    assert gates[0]["status"] == "FAIL"


@pytest.mark.parametrize("variant", ["drop_after", "reorder", "wrong_inventory"])
def test_incomplete_integrity_observations_cannot_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: str
) -> None:
    from pmpe.process_collection import RecordingSandbox

    original = RecordingSandbox.boundary

    def changed(self: Any, stage: str, **kwargs: Any) -> None:
        original(self, stage, **kwargs)
        if stage == "release_before":
            if variant == "drop_after":
                del self.observations[-2]
            elif variant == "reorder":
                self.observations[-2:] = reversed(self.observations[-2:])
            else:
                self.observations[1]["expected_inventory_digest"] = "sha256:" + "0" * 64

    monkeypatch.setattr(RecordingSandbox, "boundary", changed)
    inputs, items = make_inputs(tmp_path)
    result = run_to_release_ready(
        contract=bound_contract(items),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="incomplete-integrity",
        provider=ReplayProvider(),
        candidate_sandbox=LocalSandbox(),
        budget=BudgetCaps(max_attempts=1),
        process_gate_inputs=inputs,
    )
    gates = next(
        event["payload"]["gates"]
        for event in EvidenceLedger.open_existing(tmp_path, result.run_id).verify()
        if event["event_type"] == "release_gates_evaluated"
    )
    assert gates[1]["status"] == "FAIL"
    assert result.state is RunState.HALTED


@pytest.mark.parametrize("variant", ["added", "modified", "deleted"])
def test_provenance_detects_manual_changes_after_verification(tmp_path: Path, variant: str) -> None:
    class RepairingProvider(ReplayProvider):
        def invoke(self, *, purpose: str, request: Any) -> dict[str, Any]:
            response = super().invoke(purpose=purpose, request=request)
            if purpose == "advisory_review":
                path = tmp_path / "candidate" / "product.py"
                if variant == "added":
                    (path.parent / "undisclosed.py").write_bytes(b"# manual")
                elif variant == "deleted":
                    path.unlink()
                else:
                    path.write_bytes(b"# modified outside coder response")
            return response

    inputs, items = make_inputs(tmp_path)
    result = run_to_release_ready(
        contract=bound_contract(items),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="manual-change",
        provider=RepairingProvider(),
        candidate_sandbox=LocalSandbox(),
        budget=BudgetCaps(max_attempts=1),
        process_gate_inputs=inputs,
    )
    gates = next(
        event["payload"]["gates"]
        for event in EvidenceLedger.open_existing(tmp_path, result.run_id).verify()
        if event["event_type"] == "release_gates_evaluated"
    )
    assert gates[2]["status"] == "FAIL"
    assert "OUT_OF_BAND_CHANGE" in gates[2]["evidence"]["reasons"]
    assert result.state is RunState.HALTED


def test_test_provider_cannot_attest_fresh_model(tmp_path: Path) -> None:
    from dataclasses import replace

    from pmpe.barebones import ContractInvalidError

    inputs, items = make_inputs(tmp_path)
    inputs = replace(
        inputs,
        generation_mode="fresh",
        provider_attestation={"kind": "live_model", "statement": "False test assertion"},
    )
    provider = ReplayProvider()
    with pytest.raises(ContractInvalidError, match="test providers cannot qualify"):
        run_to_release_ready(
            contract=bound_contract(items),
            repository_root=tmp_path,
            workspace=tmp_path / "candidate",
            run_id="false-fresh",
            provider=provider,
            candidate_sandbox=LocalSandbox(),
            process_gate_inputs=inputs,
        )
    assert provider.calls == 0


def test_omitted_engine_source_cannot_pass_manifest_admission(tmp_path: Path) -> None:
    from dataclasses import replace

    from pmpe.barebones import ContractInvalidError
    from pmpe.process_gates import raw_digest

    inputs, items = make_inputs(tmp_path)
    manifest = json.loads(inputs.source_manifest)
    manifest["artifacts"].pop(
        next(key for key in manifest["artifacts"] if key.startswith("engine/"))
    )
    payload = json.dumps(manifest).encode()
    inputs = replace(inputs, source_manifest=payload)
    items[1]["source_manifest_digest"] = raw_digest(payload)
    provider = ReplayProvider()
    with pytest.raises(ContractInvalidError, match="omits or adds"):
        run_to_release_ready(
            contract=bound_contract(items),
            repository_root=tmp_path,
            workspace=tmp_path / "candidate",
            run_id="omitted-source",
            provider=provider,
            candidate_sandbox=LocalSandbox(),
            process_gate_inputs=inputs,
        )
    assert provider.calls == 0


@pytest.mark.parametrize("invalid", [False, 0, "", [], {}])
def test_falsy_arbitrary_criterion_results_never_mean_pass(invalid: Any) -> None:
    from pmpe.contracts.release_gates import CompiledReleaseGate
    from pmpe.release_gates import release_gate_results

    gate = CompiledReleaseGate("G1", ("AC-001",))
    assert release_gate_results([gate], {"AC-001": invalid})[0]["status"] == "NOT_EVALUATED"
    assert release_gate_results([gate], {"AC-001": ()})[0]["status"] == "PASS"


def test_unknown_plausible_sandbox_report_is_not_admitted(tmp_path: Path) -> None:
    from pmpe.barebones import ContractInvalidError

    class UnknownReporter(LocalSandbox):
        pass

    inputs, items = make_inputs(tmp_path)
    provider = ReplayProvider()
    with pytest.raises(ContractInvalidError, match="sandbox identity is not declared"):
        run_to_release_ready(
            contract=bound_contract(items),
            repository_root=tmp_path,
            workspace=tmp_path / "candidate",
            run_id="unknown-sandbox",
            provider=provider,
            candidate_sandbox=UnknownReporter(),
            process_gate_inputs=inputs,
        )
    assert provider.calls == 0
    assert not (tmp_path / "candidate").exists()


def test_fresh_label_on_test_provider_remains_not_evaluated(tmp_path: Path) -> None:
    from dataclasses import replace

    inputs, items = make_inputs(tmp_path)
    inputs = replace(inputs, generation_mode="fresh")
    result = run_to_release_ready(
        contract=bound_contract(items),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="fresh-test-label",
        provider=ReplayProvider(),
        candidate_sandbox=LocalSandbox(),
        budget=BudgetCaps(max_attempts=1),
        process_gate_inputs=inputs,
    )
    gates = next(
        event["payload"]["gates"]
        for event in EvidenceLedger.open_existing(tmp_path, result.run_id).verify()
        if event["event_type"] == "release_gates_evaluated"
    )
    assert gates[2]["status"] == "NOT_EVALUATED"
    assert result.state is RunState.HALTED


def test_mechanical_process_subset_reaches_release_ready(tmp_path: Path) -> None:
    from tests.integration.test_process_gate_approval import approved_fixture

    inputs, candidate, receipt_bytes = approved_fixture(tmp_path, include_fresh_gate=False)
    result = run_to_release_ready(
        contract=candidate,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="mechanical-positive",
        provider=ReplayProvider(),
        candidate_sandbox=LocalSandbox(),
        budget=BudgetCaps(max_attempts=1),
        process_gate_inputs=inputs,
        approval_receipt=json.loads(receipt_bytes),
        approval_authority="TEST-ONLY-fixture",
        approval_receipt_bytes=receipt_bytes,
    )
    assert result.state is RunState.RELEASE_READY
    events = list(EvidenceLedger.open_existing(tmp_path, result.run_id).verify())
    gates = next(
        event["payload"]["gates"]
        for event in events
        if event["event_type"] == "release_gates_evaluated"
    )
    assert [gate["status"] for gate in gates] == ["PASS"] * 3
    assert events[-1]["event_type"] == "release_ready"
    from pmpe.evidence.release_gates import validate_release_gate_evidence

    validate_release_gate_evidence(EvidenceLedger.open_existing(tmp_path, result.run_id), events)


def test_repair_attempt_preserves_prior_applied_response_provenance(tmp_path: Path) -> None:
    from dataclasses import replace

    class RepairProvider(ReplayProvider):
        def invoke(self, *, purpose: str, request: Any) -> dict[str, Any]:
            response = super().invoke(purpose=purpose, request=request)
            if self.calls == 1:
                response["files"] = {
                    "product.py": "def health():\n    return {'status': 'broken'}\n",
                    "helper.py": "# retained first response\n",
                }
            return response

    inputs, items = make_inputs(tmp_path)
    inputs = replace(
        inputs,
        source_paths={**inputs.source_paths, "repair_provider": Path(__file__).resolve()},
        negative_controls={
            "broken": {
                "product.py": b"def health():\n    return {'status': 'broken'}\n",
                "helper.py": b"# retained first response\n",
            }
        },
    )
    from pmpe.barebones import default_template
    from pmpe.process_gates import build_source_manifest, raw_digest

    manifest = build_source_manifest(
        default_template(), inputs.source_paths, inputs.execution_profile, sandbox=LocalSandbox()
    )
    inputs = replace(inputs, source_manifest=manifest)
    items[1]["source_manifest_digest"] = raw_digest(manifest)
    result = run_to_release_ready(
        contract=bound_contract(items),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="repair-provenance",
        provider=RepairProvider(),
        candidate_sandbox=LocalSandbox(),
        budget=BudgetCaps(max_attempts=2),
        process_gate_inputs=inputs,
    )
    events = list(EvidenceLedger.open_existing(tmp_path, result.run_id).verify())
    gates = [
        event["payload"]["gates"]
        for event in events
        if event["event_type"] == "release_gates_evaluated"
    ][-1]
    assert [gate["status"] for gate in gates] == ["PASS", "NOT_EVALUATED", "NOT_EVALUATED", "PASS"]
    assert len(gates[2]["evidence"]["coder_events"]) == 2
    assert result.state is RunState.HALTED
