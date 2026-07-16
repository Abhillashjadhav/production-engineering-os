"""PD-06/PD-07: findings lifecycle, reconciliation policy, fixer allowlist,
same-candidate enforcement, evidence ledger."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pmpe.assurance.findings import (
    FindingsStore,
    FindingTransitionError,
    SameCandidateViolation,
)
from pmpe.assurance.fixer_gate import FixerGate, FixScopeViolation
from pmpe.assurance.reconcile import OwnerDecision, reconcile
from pmpe.contracts.change_request import ChangeRequestStore
from pmpe.engineering.ledger import EvidenceLedger

DIGEST = "sha256:aaaa"


def _finding(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "severity": "low",
        "blocking": False,
        "file": "app/api.py",
        "line": 10,
        "evidence": "quoted code",
        "failure_mechanism": "input X -> wrong output Y",
        "affected_requirement": "FR-001",
        "recommended_fix_direction": "guard the input",
        "mechanically_fixable": True,
        "requires_product_decision": False,
        "title": "unguarded input",
    }
    base.update(overrides)
    return base


@pytest.fixture()
def store(tmp_path: Path) -> FindingsStore:
    return FindingsStore(tmp_path / "run")


# --- intake -----------------------------------------------------------------------------


def test_intake_assigns_ids_and_preserves_originals(store: FindingsStore) -> None:
    accepted = store.intake("v2-code-reviewer", DIGEST, [_finding(), _finding(line=20)])
    assert [f.finding_id for f in accepted] == ["RF-001", "RF-002"]
    originals = store.originals("v2-code-reviewer")
    assert len(originals["findings"]) == 2
    # mutating working copies never rewrites the original review
    store.set_status("RF-001", "ACCEPTED", decided_by="policy", reason="low+mechanical")
    assert "status" not in store.originals("v2-code-reviewer")["findings"][0]


def test_intake_rejects_candidate_digest_mismatch(store: FindingsStore) -> None:
    store.intake("v2-code-reviewer", DIGEST, [_finding()])
    with pytest.raises(SameCandidateViolation):
        store.intake("v2-eval-integrity-auditor", "sha256:bbbb", [_finding()])


# --- status transitions -------------------------------------------------------------------


def test_legal_lifecycle_proposed_accepted_fixed_verified(store: FindingsStore) -> None:
    (finding,) = store.intake("v2-code-reviewer", DIGEST, [_finding()])
    store.set_status(finding.finding_id, "ACCEPTED", decided_by="owner", reason="fix it")
    store.record_fixed(finding.finding_id, fixer="v2-approved-findings-fixer", commits=["abc"])
    store.record_verified(finding.finding_id, verifier="v2-code-reviewer")
    assert store.get(finding.finding_id).status == "VERIFIED"


@pytest.mark.parametrize(
    ("from_status", "action"),
    [
        ("PROPOSED", "fix"),  # cannot fix an undecided finding
        ("REJECTED", "fix"),
        ("PRODUCT_DECISION_REQUIRED", "fix"),
        ("ACCEPTED", "verify"),  # cannot verify before a fix exists
    ],
)
def test_illegal_transitions_raise(store: FindingsStore, from_status: str, action: str) -> None:
    (finding,) = store.intake("v2-code-reviewer", DIGEST, [_finding()])
    if from_status != "PROPOSED":
        store.set_status(finding.finding_id, from_status, decided_by="owner", reason="test setup")
    with pytest.raises(FindingTransitionError):
        if action == "fix":
            store.record_fixed(finding.finding_id, fixer="fixer", commits=["x"])
        else:
            store.record_verified(finding.finding_id, verifier="someone")


def test_verifier_cannot_be_the_fixer(store: FindingsStore) -> None:
    (finding,) = store.intake("v2-code-reviewer", DIGEST, [_finding()])
    store.set_status(finding.finding_id, "ACCEPTED", decided_by="owner", reason="ok")
    store.record_fixed(finding.finding_id, fixer="v2-approved-findings-fixer", commits=["a"])
    with pytest.raises(FindingTransitionError, match="fixer"):
        store.record_verified(finding.finding_id, verifier="v2-approved-findings-fixer")


# --- reconciliation ------------------------------------------------------------------------


def test_low_mechanical_findings_auto_accept_by_policy(tmp_path: Path) -> None:
    store = FindingsStore(tmp_path / "run")
    store.intake("v2-code-reviewer", DIGEST, [_finding()])
    result = reconcile(store, decisions={}, pcr_store=None)
    assert result.accepted == ["RF-001"]
    finding = store.get("RF-001")
    assert finding.status == "ACCEPTED"
    assert "policy" in (finding.decided_by or "")


def test_medium_findings_require_recorded_owner_decision(tmp_path: Path) -> None:
    store = FindingsStore(tmp_path / "run")
    store.intake("v2-code-reviewer", DIGEST, [_finding(severity="medium", blocking=True)])
    undecided = reconcile(store, decisions={}, pcr_store=None)
    assert undecided.undecided == ["RF-001"]

    decided = reconcile(
        store,
        decisions={"RF-001": OwnerDecision(status="ACCEPTED", owner="abhillash", reason="real")},
        pcr_store=None,
    )
    assert decided.accepted == ["RF-001"]
    assert store.get("RF-001").decided_by == "abhillash"


def test_rejection_requires_owner_and_reason(tmp_path: Path) -> None:
    store = FindingsStore(tmp_path / "run")
    store.intake("v2-code-reviewer", DIGEST, [_finding(severity="high")])
    result = reconcile(
        store,
        decisions={
            "RF-001": OwnerDecision(status="REJECTED", owner="abhillash", reason="false positive")
        },
        pcr_store=None,
    )
    assert result.rejected == ["RF-001"]


def test_product_decision_findings_become_change_requests(tmp_path: Path) -> None:
    store = FindingsStore(tmp_path / "run")
    pcrs = ChangeRequestStore(tmp_path / "run")
    store.intake(
        "v2-product-conformance-reviewer",
        DIGEST,
        [_finding(requires_product_decision=True, title="AC-003 wording ambiguous")],
    )
    result = reconcile(
        store,
        decisions={},
        pcr_store=pcrs,
        contract_id="PDC-TEST-001",
        contract_version=1,
        decision_owner="abhillash",
    )
    assert result.product_decisions == ["RF-001"]
    assert store.get("RF-001").status == "PRODUCT_DECISION_REQUIRED"
    pcr_list = pcrs.list()
    assert len(pcr_list) == 1
    assert "RF-001" in pcr_list[0].engineering_finding


def test_duplicates_are_linked_not_erased(tmp_path: Path) -> None:
    store = FindingsStore(tmp_path / "run")
    store.intake("v2-code-reviewer", DIGEST, [_finding()])
    store.intake("v2-architecture-simplicity-reviewer", DIGEST, [_finding()])
    result = reconcile(store, decisions={}, pcr_store=None)
    assert result.duplicates == ["RF-002"]
    duplicate = store.get("RF-002")
    assert duplicate.status == "DUPLICATE"
    assert duplicate.duplicate_of == "RF-001"
    assert store.get("RF-001").status == "ACCEPTED"
    assert len(store.all()) == 2  # nothing erased


# --- fixer allowlist -----------------------------------------------------------------------


def test_fixer_gate_exposes_only_accepted_ids(tmp_path: Path) -> None:
    store = FindingsStore(tmp_path / "run")
    store.intake(
        "v2-code-reviewer",
        DIGEST,
        [_finding(), _finding(line=99, severity="high", title="other")],
    )
    reconcile(store, decisions={}, pcr_store=None)  # accepts only the low one
    gate = FixerGate(store)
    scope = gate.scope()
    assert scope.finding_ids == ["RF-001"]
    assert "app/api.py" in scope.allowed_files


def test_fix_outside_accepted_ids_is_rejected(tmp_path: Path) -> None:
    store = FindingsStore(tmp_path / "run")
    store.intake("v2-code-reviewer", DIGEST, [_finding(severity="high")])
    gate = FixerGate(store)
    with pytest.raises(FixScopeViolation, match="RF-001"):
        gate.record_fix("RF-001", fixer="fixer", commits=["a"], changed_files=["app/api.py"])


def test_fix_touching_files_outside_scope_is_rejected(tmp_path: Path) -> None:
    store = FindingsStore(tmp_path / "run")
    store.intake("v2-code-reviewer", DIGEST, [_finding()])
    reconcile(store, decisions={}, pcr_store=None)
    gate = FixerGate(store)
    with pytest.raises(FixScopeViolation, match="unrelated"):
        gate.record_fix(
            "RF-001",
            fixer="fixer",
            commits=["a"],
            changed_files=["app/api.py", "app/unrelated.py"],
        )


def test_in_scope_fix_records_fixed(tmp_path: Path) -> None:
    store = FindingsStore(tmp_path / "run")
    store.intake("v2-code-reviewer", DIGEST, [_finding()])
    reconcile(store, decisions={}, pcr_store=None)
    gate = FixerGate(store)
    gate.record_fix("RF-001", fixer="fixer", commits=["abc"], changed_files=["app/api.py"])
    assert store.get("RF-001").status == "FIXED"
    assert store.get("RF-001").fix_commits == ["abc"]


# --- evidence ledger -----------------------------------------------------------------------


def test_ledger_records_structured_events(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path / "run", run_id="eng-001")
    ledger.record(
        stage="architecture",
        agent="v2-system-architect",
        action="submit",
        input_digests={"contract": DIGEST},
        output_digests={"architecture_pack": "sha256:cccc"},
        verdict="accepted",
        next_state="plan",
    )
    events = ledger.read_all()
    assert len(events) == 1
    event = events[0]
    for key in (
        "run_id",
        "ts",
        "stage",
        "agent",
        "action",
        "input_digests",
        "output_digests",
        "verdict",
        "next_state",
    ):
        assert key in event, key
    assert event["run_id"] == "eng-001"


def test_ledger_is_append_only(tmp_path: Path) -> None:
    ledger = EvidenceLedger(tmp_path / "run", run_id="eng-001")
    ledger.record(stage="a", agent="x", action="one")
    ledger.record(stage="b", agent="y", action="two")
    assert [e["action"] for e in ledger.read_all()] == ["one", "two"]
