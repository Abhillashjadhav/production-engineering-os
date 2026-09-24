"""Offline mechanical controls; these tests never attest a live model session."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from pmpe.barebones import (
    BudgetCaps,
    RunState,
    compile_barebones_plan,
    default_template,
    run_to_release_ready,
)
from pmpe.contracts.acceptance import AcceptanceCompileError
from pmpe.contracts.canonical import canonical_digest
from pmpe.evidence.ledger import EvidenceLedger


class ReplayProvider:
    calls = 0

    def invoke(self, *, purpose: str, request: Any) -> dict[str, Any]:
        self.calls += 1
        return {
            "request_digest": request["request_digest"],
            "files": {"product.py": "def health():\n    return {'status': 'ok'}\n"},
        }


class LocalSandbox:
    def isolation_report(self) -> dict[str, Any]:
        return {
            "mode": "authorized_host_fallback",
            "missing_isolations": ["namespaces", "network"],
            "full_isolation_claimed": False,
        }

    def run(self, workspace: Path, argv: Any, *, timeout_seconds: float, environment: Any) -> Any:
        translated = [str(arg).replace("'/workspace'", repr(str(workspace))) for arg in argv]
        return subprocess.run(
            translated,
            cwd=workspace,
            env=environment,
            timeout=timeout_seconds,
            capture_output=True,
            text=True,
            check=False,
        )


def contract() -> dict[str, Any]:
    return json.loads(
        (Path(__file__).parents[2] / "examples/barebones/e1-contract.json").read_text()
    )


def bindings(manifest_digest: str, profile_digest: str) -> list[dict[str, Any]]:
    return [
        {
            "kind": "negative_controls",
            "baseline": {
                "event": "meaningful_red_confirmed",
                "required_failure_code": "ASSERTION_FAILED",
            },
            "required_failure_code": "ASSERTION_FAILED",
            "mutants": [{"id": "broken", "must_fail": ["AC-001"], "must_not_touch": ["tests/"]}],
        },
        {
            "kind": "digest_boundaries",
            "source_manifest_digest": manifest_digest,
            "per_check": ["before", "after"],
            "require_command_boundary": True,
            "require_release_boundary": True,
        },
        {
            "kind": "generation_provenance",
            "mode": "fresh",
            "roles": ["code"],
            "require": [
                "request_blob",
                "response_blob",
                "candidate_equals_applied_responses",
                "process_record_per_criterion",
                "criterion_result_per_criterion",
            ],
        },
        {
            "kind": "execution_disclosure",
            "execution_profile_sha256": profile_digest,
            "required": [
                "effective_uid",
                "is_root",
                "sandbox_class",
                "isolation_mode",
                "missing_isolations",
                "approval_receipt_authentication",
                "generation_mode",
                "real_sandbox_leg",
                "readiness_scope",
            ],
            "forbid": {"full_isolation_claimed": True, "readiness_scope": "general"},
        },
    ]


def bound_contract(items: list[dict[str, Any]]) -> dict[str, Any]:
    result = contract()
    result["binary_release_gates"] = [
        {
            "id": f"GATE-{index + 2:03}",
            "description": "TEST ONLY process obligation",
            "binding": item,
        }
        for index, item in enumerate(items)
    ]
    return result


def make_inputs(tmp_path: Path) -> tuple[Any, list[dict[str, Any]]]:
    from pmpe.process_gates import ProcessGateInputs, build_source_manifest, raw_digest

    profile = json.dumps(
        {
            "scope": "can attempt and evaluate; not a delivery guarantee",
            "authorized_fallback": {
                "unavailable_additional_protections": ["namespaces", "network"]
            },
        }
    ).encode()
    manifest_paths = {
        "adapter": Path(__file__).resolve(),
        "test_controls": Path(__file__).with_name("test_process_gate_failures.py").resolve(),
    }
    manifest = build_source_manifest(
        default_template(), manifest_paths, profile, sandbox=LocalSandbox()
    )
    inputs = ProcessGateInputs(
        generation_mode="replay",
        provider_attestation={
            "kind": "test",
            "statement": "Offline deterministic replay, no model called.",
        },
        source_manifest=manifest,
        source_paths=manifest_paths,
        execution_profile=profile,
        negative_controls={
            "broken": {"product.py": b"def health():\n    return {'status': 'broken'}\n"}
        },
        real_sandbox_leg={"status": "NOT_ATTEMPTED", "reason": "Offline test, no namespace claim."},
    )
    return inputs, bindings(raw_digest(manifest), raw_digest(profile))


def test_four_typed_bindings_compile_without_changing_criteria(tmp_path: Path) -> None:
    items = bindings("sha256:" + "a" * 64, "sha256:" + "b" * 64)
    plan = compile_barebones_plan(
        contract=bound_contract(items), repository_root=tmp_path, template=default_template()
    )
    assert len(plan.release_gates) == 4
    assert plan.as_dict()["release_gates"] == tuple(
        {"gate_id": f"GATE-{i + 2:03}", "binding": value} for i, value in enumerate(items)
    )


@pytest.mark.parametrize("mutation", ["unknown", "both", "bool_boundary", "unknown_criterion"])
def test_malformed_typed_bindings_refused(tmp_path: Path, mutation: str) -> None:
    items = bindings("sha256:" + "a" * 64, "sha256:" + "b" * 64)
    candidate = bound_contract(items)
    if mutation == "unknown":
        items[0]["surprise"] = True
    elif mutation == "both":
        candidate["binary_release_gates"][0]["acceptance_criterion_refs"] = ["AC-001"]
    elif mutation == "bool_boundary":
        items[1]["require_command_boundary"] = 1
    else:
        items[0]["mutants"][0]["must_fail"] = ["AC-UNKNOWN"]
    with pytest.raises(AcceptanceCompileError):
        compile_barebones_plan(
            contract=candidate, repository_root=tmp_path, template=default_template()
        )


def test_retained_replay_passes_mechanical_gates_but_never_fresh_gate(tmp_path: Path) -> None:
    inputs, items = make_inputs(tmp_path)
    result = run_to_release_ready(
        contract=bound_contract(items),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="offline-replay",
        provider=ReplayProvider(),
        candidate_sandbox=LocalSandbox(),
        budget=BudgetCaps(max_attempts=1),
        process_gate_inputs=inputs,
    )
    assert result.state is RunState.HALTED
    ledger = EvidenceLedger.open_existing(tmp_path, result.run_id)
    events = list(ledger.verify())
    event = next(event for event in events if event["event_type"] == "release_gates_evaluated")
    gates = event["payload"]["gates"]
    assert [gate["status"] for gate in gates] == ["PASS", "NOT_EVALUATED", "NOT_EVALUATED", "PASS"]
    assert all(gate["evidence"]["run_id"] == result.run_id for gate in gates)
    assert not any(event["event_type"] == "release_ready" for event in events)
    integrity = gates[1]["evidence"]
    assert integrity["observations"][-2]["stage"] == "command_after"
    assert integrity["observations"][-1]["stage"] == "release_before"
    records = gates[2]["evidence"]["process_records"]
    assert {(record["phase"], record["criterion_id"]) for record in records} == {
        ("baseline", "AC-001"),
        ("candidate", "AC-001"),
        ("mutant:broken", "AC-001"),
    }
    for record in records:
        assert ledger.read_blob(record["stdout_digest"]) is not None
        assert record["executed_argv"]


def test_declared_process_gate_missing_runtime_input_refuses_before_provider(
    tmp_path: Path,
) -> None:
    provider = ReplayProvider()
    from pmpe.barebones import ContractInvalidError

    with pytest.raises(ContractInvalidError, match="process gate"):
        run_to_release_ready(
            contract=bound_contract(bindings("sha256:" + "a" * 64, "sha256:" + "b" * 64)),
            repository_root=tmp_path,
            workspace=tmp_path / "candidate",
            run_id="missing-input",
            provider=provider,
        )
    assert provider.calls == 0
    assert not (tmp_path / "candidate").exists()


def test_no_gate_and_criterion_gate_serialization_are_unchanged(tmp_path: Path) -> None:
    original = contract()
    no_gate = compile_barebones_plan(
        contract=original, repository_root=tmp_path, template=default_template()
    )
    assert "release_gates" not in no_gate.as_dict()
    original["binary_release_gates"] = [
        {"id": "G1", "description": "health", "acceptance_criterion_refs": ["AC-001"]}
    ]
    plan = compile_barebones_plan(
        contract=original, repository_root=tmp_path, template=default_template()
    )
    assert plan.as_dict()["release_gates"] == (
        {"gate_id": "G1", "acceptance_criterion_refs": ("AC-001",)},
    )
    shell = {key: value for key, value in plan.as_dict().items() if key != "plan_digest"}
    assert canonical_digest(shell) == plan.plan_digest
    assert [asdict(item) for item in plan.criteria] == [asdict(item) for item in no_gate.criteria]
