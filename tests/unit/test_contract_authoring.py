"""Decision Contract Authoring and Approval Publisher seam."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pmpe.contracts.authoring import (
    approve_contract_draft,
    build_contract_draft,
    verify_contract_approval,
)
from pmpe.contracts.canonical import canonical_digest
from pmpe.contracts.model import load_contract
from pmpe.domain.errors import ContractViolation, SpecError

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "v2" / "contract_approved.json"


def _answers() -> dict[str, Any]:
    contract = json.loads(FIXTURE.read_text())
    for field in (
        "approved_at",
        "approved_by",
        "contract_status",
        "source_digest",
        "unresolved_questions",
    ):
        contract.pop(field)
    return contract


def test_missing_truth_returns_only_blocking_questions() -> None:
    answers = _answers()
    del answers["north_star_metric"]
    result = build_contract_draft(answers)
    assert result.status == "PRODUCT_INPUT_REQUIRED"
    assert result.draft is None
    assert [question.field for question in result.blocking_questions] == ["north_star_metric"]


def test_activity_north_star_is_blocked() -> None:
    answers = _answers()
    answers["north_star_metric"] = "Number of tasks created"
    result = build_contract_draft(answers)
    assert result.status == "PRODUCT_INPUT_REQUIRED"
    assert result.blocking_questions[0].field == "north_star_metric"
    assert "activity" in result.blocking_questions[0].reason


def test_uncovered_requirement_is_blocked() -> None:
    answers = _answers()
    answers["functional_requirements"].append(
        {"id": "FR-002", "title": "Second behavior", "description": "Needs evidence."}
    )
    result = build_contract_draft(answers)
    assert result.status == "PRODUCT_INPUT_REQUIRED"
    assert "FR-002" in result.blocking_questions[0].reason


def test_complete_answers_produce_schema_valid_draft(tmp_path: Path) -> None:
    result = build_contract_draft(_answers())
    assert result.status == "DRAFT_READY_FOR_APPROVAL"
    assert result.draft is not None
    assert result.draft["contract_status"] == "DRAFT"
    assert result.draft_digest == canonical_digest(result.draft)
    path = tmp_path / "draft.json"
    path.write_text(json.dumps(result.draft))
    contract = load_contract(path)
    assert not contract.runnable


def test_approval_is_bound_to_exact_draft_digest(tmp_path: Path) -> None:
    draft = build_contract_draft(_answers())
    assert draft.draft is not None and draft.draft_digest is not None
    approved = approve_contract_draft(
        draft.draft,
        expected_draft_digest=draft.draft_digest,
        approver="product-owner",
        approved_at="2026-08-19T12:00:00Z",
    )
    path = tmp_path / "approved.json"
    path.write_text(json.dumps(approved.contract))
    assert load_contract(path).runnable
    assert approved.receipt["draft_digest"] == draft.draft_digest
    assert approved.receipt["approved_contract_digest"] == canonical_digest(approved.contract)


def test_changed_draft_cannot_reuse_prior_approval() -> None:
    draft = build_contract_draft(_answers())
    assert draft.draft is not None and draft.draft_digest is not None
    changed = json.loads(json.dumps(draft.draft))
    changed["scope"].append("Unreviewed scope")
    with pytest.raises(ContractViolation, match="approved digest"):
        approve_contract_draft(
            changed,
            expected_draft_digest=draft.draft_digest,
            approver="product-owner",
            approved_at="2026-08-19T12:00:00Z",
        )


def test_approval_timestamp_must_be_timezone_bound() -> None:
    draft = build_contract_draft(_answers())
    assert draft.draft is not None and draft.draft_digest is not None
    with pytest.raises(ContractViolation, match="timestamp"):
        approve_contract_draft(
            draft.draft,
            expected_draft_digest=draft.draft_digest,
            approver="product-owner",
            approved_at="2026-08-19 12:00:00",
        )


def test_contract_id_cannot_escape_registry_paths() -> None:
    answers = _answers()
    answers["contract_id"] = "../../outside-registry"
    with pytest.raises(SpecError, match="contract_id"):
        build_contract_draft(answers)


def test_handoff_verifies_exact_receipt_and_expected_approver() -> None:
    draft = build_contract_draft(_answers())
    assert draft.draft is not None and draft.draft_digest is not None
    approved = approve_contract_draft(
        draft.draft,
        expected_draft_digest=draft.draft_digest,
        approver="product-owner",
        approved_at="2026-08-19T12:00:00Z",
    )

    assert (
        verify_contract_approval(
            approved.contract,
            approved.receipt,
            expected_approver="product-owner",
        )
        == approved.receipt["receipt_digest"]
    )
    with pytest.raises(ContractViolation, match="expected approver"):
        verify_contract_approval(
            approved.contract,
            approved.receipt,
            expected_approver="someone-else",
        )


def test_handoff_rejects_tampered_approval_receipt() -> None:
    draft = build_contract_draft(_answers())
    assert draft.draft is not None and draft.draft_digest is not None
    approved = approve_contract_draft(
        draft.draft,
        expected_draft_digest=draft.draft_digest,
        approver="product-owner",
        approved_at="2026-08-19T12:00:00Z",
    )
    tampered = dict(approved.receipt)
    tampered["approved_by"] = "attacker"
    with pytest.raises(ContractViolation, match="differs from its digest"):
        verify_contract_approval(
            approved.contract,
            tampered,
            expected_approver="product-owner",
        )
