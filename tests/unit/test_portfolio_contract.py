"""Portfolio Auditor M1 — the ProductDecisionContract, locked via OS mechanisms.

The auditor's contract is a standard pmpe ProductDecisionContract (JSON,
schema-validated, digest-locked through ContractStore) — not a bespoke
contract system. These tests prove: the shipped contract is APPROVED and
runnable, it pins the carried-over product decisions PD-PA-01..07, it locks
and fails closed on post-lock mutation (PD-03), and the auditor bundle binds
both the contract digest and the policy digest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pmpe.portfolio.contract import (
    AuditorBundle,
    contract_path,
    load_auditor_bundle,
    product_root,
)

from pmpe.contracts.model import load_contract
from pmpe.contracts.store import ContractStore, ContractViolation

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestShippedContract:
    def test_contract_lives_under_the_product_root(self) -> None:
        assert contract_path() == product_root() / "contract.json"
        assert contract_path().is_file()

    def test_contract_loads_and_is_runnable(self) -> None:
        contract = load_contract(contract_path())
        assert contract.contract_id == "PDC-PORTFOLIO-AUDITOR-V1"
        assert contract.contract_status == "APPROVED"
        assert contract.runnable, contract.blockers

    def test_contract_pins_pd_pa_decisions(self) -> None:
        contract = load_contract(contract_path())
        decision_ids = {d["id"] for d in contract.raw["approved_product_decisions"]}
        expected = {f"PD-PA-{i:02d}" for i in range(1, 8)}
        assert expected <= decision_ids

    def test_contract_declares_fixture_only_scope(self) -> None:
        raw = load_contract(contract_path()).raw
        out_of_scope = " ".join(raw["out_of_scope"]).lower()
        assert "real repositor" in out_of_scope

    def test_every_functional_requirement_has_acceptance_criteria(self) -> None:
        contract = load_contract(contract_path())
        for fr_id in contract.requirement_ids():
            assert contract.criteria_for(fr_id), f"{fr_id} has no acceptance criteria"


class TestContractLock:
    def test_contract_locks_for_a_run_and_verifies_unchanged(self, tmp_path: Path) -> None:
        store = ContractStore(tmp_path / "store")
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        record = store.lock_for_run(contract_path(), run_dir)
        assert record.contract_id == "PDC-PORTFOLIO-AUDITOR-V1"
        assert record.digest.startswith("sha256:")
        assert store.verify_unchanged(run_dir).digest == record.digest

    def test_post_lock_mutation_fails_closed(self, tmp_path: Path) -> None:
        store = ContractStore(tmp_path / "store")
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        store.lock_for_run(contract_path(), run_dir)
        locked = run_dir / "contract.json"
        data = json.loads(locked.read_text())
        data["north_star_metric"] = "tampered"
        locked.write_text(json.dumps(data))
        with pytest.raises(ContractViolation):
            store.verify_unchanged(run_dir)


class TestAuditorBundle:
    def test_bundle_binds_contract_and_policy_digests(self) -> None:
        bundle = load_auditor_bundle()
        assert isinstance(bundle, AuditorBundle)
        assert bundle.contract.contract_id == "PDC-PORTFOLIO-AUDITOR-V1"
        assert bundle.contract_digest.startswith("sha256:")
        assert bundle.policy.digest.startswith("sha256:")
        # Rebinding is deterministic.
        again = load_auditor_bundle()
        assert again.contract_digest == bundle.contract_digest
        assert again.policy.digest == bundle.policy.digest

    def test_bundle_refuses_a_foreign_product_root(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_auditor_bundle(tmp_path)
