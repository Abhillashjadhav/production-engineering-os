"""TEST ONLY packet fixtures; no user approval is created by these controls."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from pmpe.barebones import (
    BudgetCaps,
    ContractInvalidError,
    compile_barebones_plan,
    default_template,
    run_to_release_ready,
)
from pmpe.contracts.canonical import canonical_digest
from pmpe.evidence.ledger import EvidenceLedger
from tests.integration.test_process_gate_runtime import (
    LocalSandbox,
    ReplayProvider,
    bound_contract,
    make_inputs,
)


def approved_fixture(
    tmp_path: Path, *, include_fresh_gate: bool = True
) -> tuple[Any, dict[str, Any], bytes]:
    from pmpe.process_gates import raw_digest

    inputs, items = make_inputs(tmp_path)
    draft = bound_contract(items)
    if not include_fresh_gate:
        del draft["binary_release_gates"][2]
    draft.update(contract_status="DRAFT", approved_by="", approved_at="")
    approved = {
        **draft,
        "contract_status": "APPROVED",
        "approved_by": "TEST-ONLY-fixture",
        "approved_at": "2026-09-24T00:00:00Z",
    }
    receipt = {
        "schema_version": "1.0.0",
        "decision": "APPROVED",
        "approved_at": approved["approved_at"],
        "approved_by": approved["approved_by"],
        "approved_contract_digest": canonical_digest(approved),
        "contract_id": approved["contract_id"],
        "contract_version": approved["contract_version"],
        "draft_digest": canonical_digest(draft),
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    receipt_bytes = json.dumps(receipt).encode()
    plan = compile_barebones_plan(
        contract=approved, repository_root=tmp_path, template=default_template()
    )
    packet = {
        "contract": json.dumps(approved).encode(),
        "receipt": receipt_bytes,
        "draft": json.dumps(draft).encode(),
        "plan": json.dumps(plan.as_dict()).encode(),
        "source_manifest": inputs.source_manifest,
    }
    paths = {}
    for key, value in packet.items():
        path = tmp_path / (key + ".json")
        path.write_bytes(value)
        paths[key] = path
    freeze = json.dumps(
        {
            "schema_version": "1",
            "artifacts": {key: raw_digest(value) for key, value in packet.items()},
        },
        sort_keys=True,
    ).encode()
    inputs = replace(
        inputs,
        approval_freeze=freeze,
        approval_freeze_expected_digest=raw_digest(freeze),
        approval_paths=paths,
    )
    return inputs, approved, receipt_bytes


def test_source_only_checks_are_not_full_approval_integrity(tmp_path: Path) -> None:
    inputs, items = make_inputs(tmp_path)
    result = run_to_release_ready(
        contract=bound_contract(items),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="unapproved-source-checks",
        provider=ReplayProvider(),
        candidate_sandbox=LocalSandbox(),
        budget=BudgetCaps(max_attempts=1),
        process_gate_inputs=inputs,
    )
    gate = next(
        event["payload"]["gates"][1]
        for event in EvidenceLedger.open_existing(tmp_path, result.run_id).verify()
        if event["event_type"] == "release_gates_evaluated"
    )
    assert gate["status"] == "NOT_EVALUATED"
    assert gate["evidence"]["source_checks_status"] == "PASS"
    assert "APPROVAL_PACKET_NOT_BOUND" in gate["evidence"]["reasons"]


def test_complete_test_only_approval_packet_allows_integrity_pass(tmp_path: Path) -> None:
    inputs, approved, receipt_bytes = approved_fixture(tmp_path)
    result = run_to_release_ready(
        contract=approved,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="test-only-approved-packet",
        provider=ReplayProvider(),
        candidate_sandbox=LocalSandbox(),
        budget=BudgetCaps(max_attempts=1),
        process_gate_inputs=inputs,
        approval_receipt=json.loads(receipt_bytes),
        approval_authority="TEST-ONLY-fixture",
        approval_receipt_bytes=receipt_bytes,
    )
    gate = next(
        event["payload"]["gates"][1]
        for event in EvidenceLedger.open_existing(tmp_path, result.run_id).verify()
        if event["event_type"] == "release_gates_evaluated"
    )
    assert gate["status"] == "PASS"
    assert gate["evidence"]["approval_freeze_digest"] == inputs.approval_freeze_expected_digest


@pytest.mark.parametrize("field", ["contract", "receipt", "draft", "plan", "source_manifest"])
def test_changed_outer_packet_refuses_before_provider(tmp_path: Path, field: str) -> None:
    inputs, approved, receipt_bytes = approved_fixture(tmp_path)
    path = inputs.approval_paths[field]
    path.write_bytes(path.read_bytes() + b"\n")
    provider = ReplayProvider()
    with pytest.raises(ContractInvalidError, match="approval packet"):
        run_to_release_ready(
            contract=approved,
            repository_root=tmp_path,
            workspace=tmp_path / "candidate",
            run_id="changed-outer-packet",
            provider=provider,
            candidate_sandbox=LocalSandbox(),
            process_gate_inputs=inputs,
            approval_receipt=json.loads(receipt_bytes),
            approval_authority="TEST-ONLY-fixture",
            approval_receipt_bytes=receipt_bytes,
        )
    assert provider.calls == 0


def test_observed_integrity_mismatch_is_terminal_even_after_bytes_are_restored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pmpe.process_collection import RecordingSandbox
    from pmpe.process_gates import build_source_manifest, raw_digest

    inputs, items = make_inputs(tmp_path)
    guarded = tmp_path / "guarded-source.txt"
    guarded.write_bytes(b"original")
    sources = {**inputs.source_paths, "guarded": guarded}
    manifest = build_source_manifest(
        default_template(), sources, inputs.execution_profile, sandbox=LocalSandbox()
    )
    inputs = replace(inputs, source_manifest=manifest, source_paths=sources)
    items[1]["source_manifest_digest"] = raw_digest(manifest)
    boundary = RecordingSandbox.boundary
    changed_once = False

    def change_then_restore(self: Any, stage: str, **kwargs: Any) -> None:
        nonlocal changed_once
        if stage == "after" and self.phase == "candidate" and not changed_once:
            changed_once = True
            guarded.write_bytes(b"tampered")
            try:
                boundary(self, stage, **kwargs)
            finally:
                guarded.write_bytes(b"original")
        else:
            boundary(self, stage, **kwargs)

    monkeypatch.setattr(RecordingSandbox, "boundary", change_then_restore)
    provider = ReplayProvider()
    result = run_to_release_ready(
        contract=bound_contract(items),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="sticky-integrity",
        provider=provider,
        candidate_sandbox=LocalSandbox(),
        budget=BudgetCaps(max_attempts=2),
        process_gate_inputs=inputs,
    )
    assert provider.calls == 1
    assert result.cause == "PROCESS_INTEGRITY_MISMATCH"
    events = list(EvidenceLedger.open_existing(tmp_path, result.run_id).verify())
    assert events[-1]["state"] == "HALTED"
    assert not any(event["event_type"] == "release_ready" for event in events)
