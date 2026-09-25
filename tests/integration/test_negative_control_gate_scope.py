"""Each negative_controls gate is judged only on its own mutants (Codex #220 P2)."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from pmpe.barebones import BudgetCaps, run_to_release_ready
from pmpe.contracts.acceptance import AcceptanceCompileError
from pmpe.evidence.process_gate_validation import snapshot_digest
from pmpe.process_gate_inputs import ProcessGateInputs
from tests.integration.test_process_gate_r4 import TaskReplayProvider, gates_for, task_fixture
from tests.integration.test_process_gate_runtime import LocalSandbox


def split_gates(contract: dict, mutants: dict) -> None:
    gate = contract["binary_release_gates"][0]
    for binding in gate["binding"]["mutants"]:
        binding["snapshot_digest"] = snapshot_digest(mutants[binding["id"]])
    split = []
    for index, mutant in enumerate(gate["binding"]["mutants"]):
        item = copy.deepcopy(gate)
        item["id"] = f"{gate['id']}-{index}"
        item["binding"]["mutants"] = [mutant]
        split.append(item)
    contract["binary_release_gates"] = split


def test_two_negative_control_gates_each_pass_on_their_own_mutants(tmp_path: Path) -> None:
    contract, template, mutants, product = task_fixture()
    split_gates(contract, mutants)
    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="two-negative-gates",
        provider=TaskReplayProvider(product),
        template=template,
        candidate_sandbox=LocalSandbox(),
        budget=BudgetCaps(max_attempts=1),
        process_gate_inputs=ProcessGateInputs(negative_controls=mutants),
    )
    gates = gates_for(tmp_path, result.run_id)
    assert len(gates) == 2
    assert [gate["status"] for gate in gates] == ["PASS", "PASS"], [
        gate["evidence"]["reasons"] for gate in gates
    ]
    assert [[m["mutant_id"] for m in gate["evidence"]["mutants"]] for gate in gates] == [
        ["persistence"],
        ["filtering"],
    ]


def test_mutant_id_reused_across_negative_control_gates_is_refused(tmp_path: Path) -> None:
    contract, template, mutants, product = task_fixture()
    split_gates(contract, mutants)
    contract["binary_release_gates"][1]["binding"]["mutants"][0]["id"] = "persistence"
    with pytest.raises(AcceptanceCompileError, match="RELEASE_GATE_BINDING_INVALID"):
        run_to_release_ready(
            contract=contract,
            repository_root=tmp_path,
            workspace=tmp_path / "candidate",
            run_id="reused-mutant-id",
            provider=TaskReplayProvider(product),
            template=template,
            candidate_sandbox=LocalSandbox(),
            budget=BudgetCaps(max_attempts=1),
            process_gate_inputs=ProcessGateInputs(negative_controls=mutants),
        )
