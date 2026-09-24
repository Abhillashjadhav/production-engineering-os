"""R4 semantic regressions over unchanged retained task-tracker evaluator bytes."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from pmpe.barebones import BudgetCaps, ContractInvalidError, Template, run_to_release_ready
from pmpe.evidence.ledger import EvidenceLedger
from pmpe.contracts.canonical import canonical_digest
from pmpe.process_gate_inputs import ProcessGateInputs
from pmpe.process_sources import implementation_identity
from tests.integration.test_process_gate_runtime import LocalSandbox, ReplayProvider, bound_contract, make_inputs

RETAINED = Path(__file__).parents[2] / "reviews/r3-process-gates/task-store-v2-draft"


def retained_blob(digest: str) -> bytes:
    return (RETAINED / "retained-ledger/blobs" / digest.removeprefix("sha256:")).read_bytes()


def retained_snapshot(digest: str) -> dict[str, bytes]:
    return {path: retained_blob(value) for path, value in json.loads(retained_blob(digest)).items()}


class TaskReplayProvider:
    def __init__(self, product: bytes) -> None:
        self.product = product.decode()
        self.calls = 0

    def invoke(self, *, purpose: str, request: Any) -> dict[str, Any]:
        self.calls += 1
        return {"request_digest": request["request_digest"], "files": {"product.py": self.product}}


def task_fixture() -> tuple[dict[str, Any], Template, dict[str, dict[str, bytes]], bytes]:
    contract = json.loads((RETAINED / "contract.draft.json").read_bytes())
    manifest = json.loads((RETAINED / "source-manifest.json").read_bytes())
    template = Template(**json.loads(retained_blob(manifest["artifacts"]["bindings"])))
    gates = json.loads((RETAINED / "gate-evidence.json").read_bytes())["gates"]
    mutants = {control["mutant_id"]: retained_snapshot(control["mutant_digest"])
               for control in gates[1]["evidence"]["mutants"]}
    contract["binary_release_gates"] = [contract["binary_release_gates"][1]]
    return contract, template, mutants, (RETAINED / "candidate/product.py").read_bytes()


def gates_for(root: Path, run_id: str) -> list[dict[str, Any]]:
    return next(event["payload"]["gates"] for event in EvidenceLedger.open_existing(root, run_id).verify()
                if event["event_type"] == "release_gates_evaluated")


@pytest.mark.parametrize("variant", ["retained", "full_crash", "missing_prerequisite", "invalid_json", "targeted_crash", "same_mutant"])
def test_task_tracker_negative_controls_reject_observer_crashes(tmp_path: Path, variant: str) -> None:
    contract, template, mutants, product = task_fixture()
    if variant == "same_mutant":
        mutants["filtering"] = dict(mutants["persistence"])
    elif variant != "retained":
        for name, mutant in mutants.items():
            if variant == "targeted_crash":
                source = product.decode()
                if name == "persistence":
                    source = source.replace("def save_store(path, state):", "def save_store(path, state):\n    raise RuntimeError('targeted persistence crash')")
                else:
                    source = source.replace("args = parser.parse_args()", "args = parser.parse_args()\n    if args.command == 'list' and args.status in ('open', 'completed'):\n        raise RuntimeError('targeted filter crash')")
                mutant["product.py"] = source.encode()
            else:
                mutant["product.py"] = {"full_crash": b"raise RuntimeError('arbitrary crash')\n", "missing_prerequisite": b"import absent_r4_prerequisite\n", "invalid_json": b"print('not-json')\n"}[variant]
    inputs = ProcessGateInputs(negative_controls=mutants)
    result = run_to_release_ready(contract=contract, repository_root=tmp_path, workspace=tmp_path / "candidate", run_id=variant,
        provider=TaskReplayProvider(product), template=template, candidate_sandbox=LocalSandbox(), budget=BudgetCaps(max_attempts=1), process_gate_inputs=inputs)
    gate = gates_for(tmp_path, result.run_id)[0]
    assert gate["status"] == ("PASS" if variant == "retained" else "FAIL")


def test_spoofed_canonical_class_identity_is_refused() -> None:
    class Spoof(LocalSandbox):
        pass
    Spoof.__module__, Spoof.__qualname__ = LocalSandbox.__module__, LocalSandbox.__qualname__
    with pytest.raises(ValueError, match="canonical"):
        implementation_identity(Spoof())


class StatefulSandbox(LocalSandbox):
    def __init__(self) -> None:
        self.reports = 0

    def isolation_report(self) -> dict[str, Any]:
        self.reports += 1
        if self.reports == 1:
            return super().isolation_report()
        return {"mode": "bubblewrap", "missing_isolations": [], "full_isolation_claimed": False}


def test_isolation_report_is_frozen_at_admission(tmp_path: Path) -> None:
    from pmpe.barebones import default_template
    from pmpe.process_sources import build_source_manifest, raw_digest
    inputs, bindings = make_inputs(tmp_path)
    sandbox = StatefulSandbox()
    paths = {**inputs.source_paths, "stateful_adapter": Path(__file__).resolve()}
    manifest = build_source_manifest(default_template(), paths, inputs.execution_profile, sandbox=sandbox)
    inputs = replace(inputs, source_paths=paths, source_manifest=manifest)
    bindings[1]["source_manifest_digest"] = raw_digest(manifest)
    result = run_to_release_ready(contract=bound_contract(bindings), repository_root=tmp_path, workspace=tmp_path / "candidate", run_id="stateful-report",
        provider=ReplayProvider(), candidate_sandbox=sandbox, budget=BudgetCaps(max_attempts=1), process_gate_inputs=inputs)
    evidence = gates_for(tmp_path, result.run_id)[3]["evidence"]
    assert sandbox.reports == 1
    assert evidence["isolation_mode"] == "authorized_host_fallback"
    assert evidence["missing_isolations"] == ["namespaces", "network"]


def test_attested_fresh_generation_cannot_be_mechanical_pass(tmp_path: Path) -> None:
    from pmpe.process_evaluators import generation_provenance_result
    inputs, bindings = make_inputs(tmp_path)
    result = run_to_release_ready(contract=bound_contract(bindings), repository_root=tmp_path, workspace=tmp_path / "candidate", run_id="attested-fresh",
        provider=ReplayProvider(), candidate_sandbox=LocalSandbox(), budget=BudgetCaps(max_attempts=1), process_gate_inputs=inputs)
    evidence = gates_for(tmp_path, result.run_id)[2]["evidence"]
    ledger = EvidenceLedger.open_existing(tmp_path, result.run_id)
    from pmpe.barebones import default_template
    status, observed = generation_provenance_result(ledger=ledger, snapshot={"product.py": (tmp_path / "candidate/product.py").read_bytes()},
        origin={key: value.encode() for key, value in default_template().files.items()}, process_records=evidence["process_records"],
        criterion_ids=["AC-001"], criterion_results={"AC-001": ()}, attempt=1, generation_mode="fresh",
        provider_attestation={"kind": "live_model", "statement": "Operator attestation only"},
        provider_class="pmpe.cli.barebones_cmd.CommandModelProvider", contract_digest=canonical_digest(bound_contract(bindings)))
    assert status == "NOT_EVALUATED", observed


def test_uninventoried_adapter_cache_refuses_before_side_effects(tmp_path: Path) -> None:
    from pmpe.barebones import default_template
    from pmpe.process_sources import build_source_manifest, raw_digest
    inputs, bindings = make_inputs(tmp_path)
    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir()
    adapter = adapter_dir / "runner.py"
    adapter.write_text("# exact adapter\n")
    paths = {**inputs.source_paths, "provider": inputs.source_paths["adapter"], "adapter": adapter}
    manifest = build_source_manifest(default_template(), paths, inputs.execution_profile, sandbox=LocalSandbox())
    inputs = replace(inputs, source_paths=paths, source_manifest=manifest)
    bindings[1]["source_manifest_digest"] = raw_digest(manifest)
    cache = adapter_dir / "__pycache__"
    cache.mkdir()
    (cache / "runner.cpython-311.pyc").write_bytes(b"unbound bytecode")
    provider = ReplayProvider()
    with pytest.raises(ContractInvalidError, match="bytecode"):
        run_to_release_ready(contract=bound_contract(bindings), repository_root=tmp_path, workspace=tmp_path / "candidate", run_id="cache-gap",
            provider=provider, candidate_sandbox=LocalSandbox(), process_gate_inputs=inputs)
    assert provider.calls == 0
    assert not (tmp_path / "candidate").exists()
