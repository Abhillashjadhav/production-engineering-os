"""Authoritative backend API for the non-technical PMOS experience.

The browser is deliberately a thin client. Question selection, conversion into
the versioned ProductDecisionContract shape, digest presentation, approval, and
ProductChangeRequest creation all happen here and reuse the existing contract
domain APIs.
"""

from __future__ import annotations

import copy
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pmpe.contracts.authoring import (
    approve_contract_draft,
    build_contract_draft,
    verify_contract_approval,
    write_json_atomic,
)
from pmpe.contracts.canonical import strict_loads
from pmpe.contracts.change_request import ChangeRequestStore
from pmpe.domain.errors import ContractViolation, SpecError
from pmpe.domain.serialize import jsonable
from pmpe.guided.native_intake import LocalCanonicalIntake
from pmpe.guided.questions import (
    FIELDS,
    as_lines,
    as_text,
    next_question,
    normalize_answers,
    question_for,
    questionnaire,
)
from pmpe.personal.catalog import workflow_catalog_payload

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_PCR_REQUIRED_FIELDS = (
    "engineering_finding",
    "reason",
    "engineering_consequences",
    "recommended_technical_default",
    "decision_owner",
)


def _approval_card(draft: dict[str, Any], digest: str) -> dict[str, Any]:
    risk_levels = {str(item.get("level", "medium")) for item in draft["known_risks"]}
    impact_level = "high" if "high" in risk_levels else "bounded"
    return {
        "approval_action": "Freeze this product decision and make it eligible for engineering",
        "cost": {
            "estimated_external_cost": "0",
            "mode": "connector-free local",
            "note": (
                "Authoring makes no model, connector, purchase, or cloud call. "
                "Downstream engineering cost is not included."
            ),
        },
        "digest": digest,
        "evidence": {
            "acceptance_criteria": len(draft["acceptance_criteria"]),
            "golden_cases": len(draft["golden_cases"]),
            "release_gates": len(draft["binary_release_gates"]),
            "source_digest": draft["source_digest"],
        },
        "impact": {
            "affected_requirements": len(draft["functional_requirements"]),
            "level": impact_level,
            "summary": draft["desired_outcome"],
        },
        "validity": {
            "expires_at": None,
            "policy": "Non-expiring local artifact; every handoff re-verifies its exact receipt.",
        },
        "permissions": {
            "allowed": [
                "Read answers submitted in this local session",
                (
                    "Write draft, approval receipt, approved contract, and change "
                    "requests to the chosen workspace"
                ),
            ],
            "not_allowed": [
                "Network or connector access",
                "Email, calendar, purchase, merge, or deployment",
                "Approval of content other than the exact digest shown",
            ],
        },
        "reversibility": {
            "level": "controlled",
            "summary": (
                "Approval is immutable. Any product change must use a "
                "ProductChangeRequest and a new contract version."
            ),
        },
    }


class GuidedExperience:
    """File-backed local PMOS API used by both the CLI server and unit tests."""

    def __init__(self, workspace: Path) -> None:
        requested_workspace = Path(workspace)
        if requested_workspace.is_symlink():
            raise ContractViolation("guided workspace must not be a symbolic link")
        self.workspace = requested_workspace.resolve()
        self.workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.drafts = self.workspace / "drafts"
        self.approved = self.workspace / "approved"
        for directory in (self.workspace, self.drafts, self.approved):
            if directory.is_symlink():
                raise ContractViolation("guided workspace directories must not be symbolic links")
            directory.mkdir(exist_ok=True, mode=0o700)
            os.chmod(directory, 0o700)
        self._write_lock = threading.Lock()
        self.intake = LocalCanonicalIntake(self.workspace / "canonical-intake")

    @staticmethod
    def questionnaire() -> dict[str, Any]:
        return questionnaire()

    @staticmethod
    def workflow_catalog() -> dict[str, object]:
        return workflow_catalog_payload()

    def review(self, raw_answers: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(raw_answers, dict):
            raise SpecError("guided answers must be an object")
        current_question = next_question(raw_answers)
        answered = sum(
            1
            for item in FIELDS
            if as_text(raw_answers.get(item.field)) or as_lines(raw_answers.get(item.field))
        )
        if current_question is not None:
            return {
                "answered": answered,
                "question": current_question.as_dict(),
                "remaining": max(1, len(FIELDS) - answered),
                "status": "PRODUCT_INPUT_REQUIRED",
                "total": len(FIELDS),
            }
        normalized = normalize_answers(raw_answers)
        result = build_contract_draft(normalized)
        if result.draft is None:
            blocking = result.blocking_questions[0]
            guided = question_for(blocking.field, blocking.reason)
            return {
                "answered": answered,
                "question": guided.as_dict(),
                "remaining": len(result.blocking_questions),
                "status": result.status,
                "total": len(FIELDS),
            }
        if result.draft_digest is None:
            raise SpecError("contract authoring returned a draft without a digest")
        draft_path = self.drafts / f"{result.draft_digest.removeprefix('sha256:')}.json"
        write_json_atomic(draft_path, result.draft)
        return {
            "approval_card": _approval_card(result.draft, result.draft_digest),
            "draft": copy.deepcopy(result.draft),
            "status": result.status,
        }

    def approve(
        self,
        *,
        expected_digest: str,
        approver: str,
        approved_at: str | None = None,
    ) -> dict[str, Any]:
        if not _DIGEST.fullmatch(expected_digest):
            raise ContractViolation("expected draft digest is malformed")
        draft_path = self.drafts / f"{expected_digest.removeprefix('sha256:')}.json"
        if not draft_path.exists():
            raise ContractViolation("no locally reviewed draft matches the supplied digest")
        draft = strict_loads(draft_path.read_bytes(), "application/json")
        with self._write_lock:
            target_name = f"{draft['contract_id']}-v{draft['contract_version']}"
            target = self.approved / target_name
            contract_path = target / "contract-approved.json"
            receipt_path = target / "approval-receipt.json"
            if target.exists():
                if target.is_symlink() or not contract_path.exists() or not receipt_path.exists():
                    raise ContractViolation("existing approval record is incomplete or unsafe")
                existing_contract = strict_loads(contract_path.read_bytes(), "application/json")
                existing_receipt = strict_loads(receipt_path.read_bytes(), "application/json")
                verify_contract_approval(
                    existing_contract,
                    existing_receipt,
                    expected_approver=approver,
                )
                same_request = existing_receipt["draft_digest"] == expected_digest and (
                    approved_at is None or existing_receipt["approved_at"] == approved_at
                )
                if not same_request:
                    raise ContractViolation(
                        "this contract version already has an immutable approval record"
                    )
                result_contract = existing_contract
                result_receipt = existing_receipt
                return self._approval_response(result_contract, result_receipt)
            result = approve_contract_draft(
                draft,
                expected_draft_digest=expected_digest,
                approver=approver,
                approved_at=approved_at or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            )
            target.mkdir(parents=False, exist_ok=False, mode=0o700)
            os.chmod(target, 0o700)
            write_json_atomic(contract_path, result.contract)
            write_json_atomic(receipt_path, result.receipt)
        return self._approval_response(result.contract, result.receipt)

    @staticmethod
    def _approval_response(contract: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
        return {
            "approved_contract_digest": receipt["approved_contract_digest"],
            "contract_id": contract["contract_id"],
            "contract_version": contract["contract_version"],
            "next_action": "A ProductChangeRequest is required for any product change.",
            "receipt": receipt,
            "status": "APPROVED",
        }

    def create_change_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        approved_digest = as_text(payload.get("approved_contract_digest"))
        approved_record = self._find_approved(approved_digest)
        if approved_record is None:
            raise ContractViolation("change request is not bound to a locally approved contract")
        contract, target = approved_record
        options = as_lines(payload.get("options"))
        if not options:
            raise ContractViolation("change request requires at least one explicit option")
        missing = [field for field in _PCR_REQUIRED_FIELDS if not as_text(payload.get(field))]
        if missing:
            raise ContractViolation("change request requires non-empty " + ", ".join(missing))
        affected = as_lines(payload.get("affected_requirement_ids"))
        known_requirements = {item["id"] for item in contract["functional_requirements"]}
        unknown = sorted(set(affected) - known_requirements)
        if unknown:
            raise ContractViolation(
                "change request references unknown requirement " + ", ".join(unknown)
            )
        with self._write_lock:
            pcr = ChangeRequestStore(target / "change-requests").create(
                source_contract_id=contract["contract_id"],
                source_contract_version=int(contract["contract_version"]),
                affected_requirement_ids=affected,
                engineering_finding=as_text(payload.get("engineering_finding")),
                reason=as_text(payload.get("reason")),
                options=options,
                engineering_consequences=as_text(payload.get("engineering_consequences")),
                recommended_technical_default=as_text(payload.get("recommended_technical_default")),
                decision_owner=as_text(payload.get("decision_owner")),
            )
        return {"change_request": jsonable(pcr), "status": "PRODUCT_CHANGE_REQUEST_CREATED"}

    def _find_approved(self, approved_digest: str) -> tuple[dict[str, Any], Path] | None:
        for receipt_path in sorted(self.approved.glob("*/approval-receipt.json")):
            receipt = strict_loads(receipt_path.read_bytes(), "application/json")
            if receipt.get("approved_contract_digest") != approved_digest:
                continue
            contract = strict_loads(
                (receipt_path.parent / "contract-approved.json").read_bytes(),
                "application/json",
            )
            verify_contract_approval(
                contract,
                receipt,
                expected_approver=str(contract.get("approved_by", "")),
            )
            return contract, receipt_path.parent
        return None

    def intake_canonical(self, bundle_text: str, manifest_text: str) -> dict[str, Any]:
        return self.intake.admit(bundle_text.encode(), manifest_text.encode())
