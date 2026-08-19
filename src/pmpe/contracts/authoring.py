"""Deterministic PMOS decision-contract authoring and digest-bound approval."""

from __future__ import annotations

import copy
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pmpe.contracts.canonical import (
    CanonicalInputError,
    canonical_digest,
    canonical_json_bytes,
    strict_loads,
)
from pmpe.contracts.model import load_contract
from pmpe.domain.errors import ContractViolation, SpecError

_REQUIRED_ANSWER_FIELDS = {
    "acceptance_criteria": "What observable acceptance criteria prove each requirement?",
    "binary_release_gates": "Which binary gates must pass before release?",
    "desired_outcome": "What user outcome should change if this works?",
    "functional_requirements": "What behaviors must the product provide?",
    "golden_cases": "Which representative cases must remain correct?",
    "guardrails": "Which safety or quality limits must not be crossed?",
    "known_risks": "What known risks must engineering and release account for?",
    "leading_metrics": "Which early measures indicate movement toward the outcome?",
    "non_functional_requirements": "What reliability, security, latency, or scale is required?",
    "north_star_metric": "Which outcome metric best represents delivered user value?",
    "out_of_scope": "What is explicitly excluded from this version?",
    "problem": "What customer problem are we solving, and why does it matter?",
    "product_name": "What should this product or capability be called?",
    "required_approvals": "Which roles must approve high-impact actions or release?",
    "scope": "What is included in the first version?",
    "scored_eval_rubric": "Which quality dimensions require scored evaluation?",
    "target_user": "Who specifically experiences the problem?",
}

_ACTIVITY_METRIC_TERMS = (
    "number of prompts",
    "prompts generated",
    "number of tasks created",
    "tasks created",
    "number of logins",
    "daily active users",
)

_SAFE_CONTRACT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class BlockingQuestion:
    question_id: str
    field: str
    question: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {
            "field": self.field,
            "question": self.question,
            "question_id": self.question_id,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ContractDraftResult:
    status: str
    draft: dict[str, Any] | None
    draft_digest: str | None
    blocking_questions: tuple[BlockingQuestion, ...]
    source_map: dict[str, str]


@dataclass(frozen=True)
class ContractApprovalResult:
    contract: dict[str, Any]
    receipt: dict[str, Any]


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _question(field: str, reason: str, index: int) -> BlockingQuestion:
    return BlockingQuestion(
        question_id=f"Q-{index:03d}",
        field=field,
        question=_REQUIRED_ANSWER_FIELDS.get(field, f"Supply explicit product truth for {field}."),
        reason=reason,
    )


def _semantic_questions(answers: dict[str, Any]) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    requirements = answers.get("functional_requirements")
    criteria = answers.get("acceptance_criteria")
    if isinstance(requirements, list) and isinstance(criteria, list):
        requirement_ids = {
            str(item.get("id", "")) for item in requirements if isinstance(item, dict)
        }
        criterion_refs = {
            str(item.get("requirement", "")) for item in criteria if isinstance(item, dict)
        }
        unknown = sorted(criterion_refs - requirement_ids)
        uncovered = sorted(requirement_ids - criterion_refs)
        if unknown:
            findings.append(
                (
                    "acceptance_criteria",
                    f"Acceptance criteria reference unknown requirement {unknown[0]}.",
                )
            )
        if uncovered:
            findings.append(
                (
                    "acceptance_criteria",
                    f"Requirement {uncovered[0]} has no acceptance criterion.",
                )
            )
    metric = answers.get("north_star_metric")
    if isinstance(metric, str) and any(term in metric.lower() for term in _ACTIVITY_METRIC_TERMS):
        findings.append(
            (
                "north_star_metric",
                "The proposed North Star is an activity measure, not an outcome.",
            )
        )
    return findings


def build_contract_draft(answers: dict[str, Any]) -> ContractDraftResult:
    if not isinstance(answers, dict):
        raise SpecError("contract answers must be a JSON object")
    raw_findings = [
        (field, "Required product truth is missing.")
        for field in sorted(_REQUIRED_ANSWER_FIELDS)
        if not _present(answers.get(field))
    ]
    raw_findings.extend(_semantic_questions(answers))
    questions = tuple(
        _question(field, reason, index)
        for index, (field, reason) in enumerate(raw_findings, start=1)
    )
    source_map = {
        f"/{field}": f"/answers/{field}"
        for field in sorted(_REQUIRED_ANSWER_FIELDS)
        if field in answers
    }
    if questions:
        return ContractDraftResult(
            status="PRODUCT_INPUT_REQUIRED",
            draft=None,
            draft_digest=None,
            blocking_questions=questions,
            source_map=source_map,
        )

    source_digest = canonical_digest(answers)
    contract_id = str(
        answers.get("contract_id") or f"PDC-{source_digest.removeprefix('sha256:')[:12].upper()}"
    )
    if not _SAFE_CONTRACT_ID.fullmatch(contract_id):
        raise SpecError(
            "contract_id must be a bounded identifier containing only letters, digits, . _ : or -"
        )
    version = answers.get("contract_version", 1)
    if type(version) is not int or version < 1:
        raise SpecError("contract_version must be a positive integer")
    draft: dict[str, Any] = {
        "acceptance_criteria": copy.deepcopy(answers["acceptance_criteria"]),
        "approved_at": "",
        "approved_by": "",
        "approved_product_decisions": copy.deepcopy(answers.get("approved_product_decisions", [])),
        "binary_release_gates": copy.deepcopy(answers["binary_release_gates"]),
        "contract_id": contract_id,
        "contract_status": "DRAFT",
        "contract_version": version,
        "desired_outcome": answers["desired_outcome"],
        "functional_requirements": copy.deepcopy(answers["functional_requirements"]),
        "golden_cases": copy.deepcopy(answers["golden_cases"]),
        "guardrails": copy.deepcopy(answers["guardrails"]),
        "known_risks": copy.deepcopy(answers["known_risks"]),
        "leading_metrics": copy.deepcopy(answers["leading_metrics"]),
        "non_functional_requirements": copy.deepcopy(answers["non_functional_requirements"]),
        "north_star_metric": answers["north_star_metric"],
        "out_of_scope": copy.deepcopy(answers["out_of_scope"]),
        "problem": answers["problem"],
        "product_name": answers["product_name"],
        "required_approvals": copy.deepcopy(answers["required_approvals"]),
        "scope": copy.deepcopy(answers["scope"]),
        "scored_eval_rubric": copy.deepcopy(answers["scored_eval_rubric"]),
        "source_digest": source_digest,
        "target_user": answers["target_user"],
        "unresolved_questions": [],
    }
    _validate_contract_object(draft)
    return ContractDraftResult(
        status="DRAFT_READY_FOR_APPROVAL",
        draft=draft,
        draft_digest=canonical_digest(draft),
        blocking_questions=(),
        source_map=source_map,
    )


def approve_contract_draft(
    draft: dict[str, Any],
    *,
    expected_draft_digest: str,
    approver: str,
    approved_at: str,
) -> ContractApprovalResult:
    if not isinstance(draft, dict):
        raise ContractViolation("contract draft must be a JSON object")
    if draft.get("contract_status") != "DRAFT":
        raise ContractViolation("only a DRAFT contract can be approved")
    actual_draft_digest = canonical_digest(draft)
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_draft_digest):
        raise ContractViolation("expected draft digest is malformed")
    if actual_draft_digest != expected_draft_digest:
        raise ContractViolation("draft content differs from the explicitly approved digest")
    if not approver.strip() or not _valid_rfc3339(approved_at):
        raise ContractViolation("approval requires a named approver and timestamp")
    approved = copy.deepcopy(draft)
    approved["contract_status"] = "APPROVED"
    approved["approved_by"] = approver.strip()
    approved["approved_at"] = approved_at.strip()
    _validate_contract_object(approved)
    approved_digest = canonical_digest(approved)
    receipt = {
        "approved_at": approved_at.strip(),
        "approved_by": approver.strip(),
        "approved_contract_digest": approved_digest,
        "contract_id": approved["contract_id"],
        "contract_version": approved["contract_version"],
        "decision": "APPROVED",
        "draft_digest": actual_draft_digest,
        "schema_version": "1.0.0",
    }
    receipt["receipt_digest"] = canonical_digest(receipt)
    return ContractApprovalResult(contract=approved, receipt=receipt)


def verify_contract_approval(
    contract: dict[str, Any],
    receipt: dict[str, Any],
    *,
    expected_approver: str,
) -> str:
    """Verify the exact approval record before an approved contract enters PEOS.

    The expected approver is supplied by the handoff operator's authority boundary; a
    self-declared APPROVED field in the contract is not sufficient.
    """

    required = {
        "approved_at",
        "approved_by",
        "approved_contract_digest",
        "contract_id",
        "contract_version",
        "decision",
        "draft_digest",
        "receipt_digest",
        "schema_version",
    }
    if set(receipt) != required:
        raise ContractViolation("approval receipt has an unexpected shape")
    claimed_receipt_digest = receipt["receipt_digest"]
    unsigned = dict(receipt)
    unsigned.pop("receipt_digest")
    if not isinstance(claimed_receipt_digest, str) or not _DIGEST.fullmatch(claimed_receipt_digest):
        raise ContractViolation("approval receipt digest is malformed")
    if canonical_digest(unsigned) != claimed_receipt_digest:
        raise ContractViolation("approval receipt content differs from its digest")
    approved_digest = canonical_digest(contract)
    if (
        receipt["schema_version"] != "1.0.0"
        or receipt["decision"] != "APPROVED"
        or receipt["approved_contract_digest"] != approved_digest
        or contract.get("contract_status") != "APPROVED"
        or receipt["contract_id"] != contract.get("contract_id")
        or receipt["contract_version"] != contract.get("contract_version")
        or receipt["approved_by"] != contract.get("approved_by")
        or receipt["approved_at"] != contract.get("approved_at")
    ):
        raise ContractViolation("approval receipt is not bound to the approved contract")
    if not isinstance(receipt["draft_digest"], str) or not _DIGEST.fullmatch(
        receipt["draft_digest"]
    ):
        raise ContractViolation("approval receipt draft digest is malformed")
    reconstructed_draft = copy.deepcopy(contract)
    reconstructed_draft["contract_status"] = "DRAFT"
    reconstructed_draft["approved_by"] = ""
    reconstructed_draft["approved_at"] = ""
    if canonical_digest(reconstructed_draft) != receipt["draft_digest"]:
        raise ContractViolation("approval receipt is not bound to the exact reviewed draft")
    authority = expected_approver.strip()
    if not authority or receipt["approved_by"] != authority:
        raise ContractViolation("approval receipt is not from the expected approver")
    return claimed_receipt_digest


def _valid_rfc3339(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return bool(value.strip()) and parsed.tzinfo is not None


def _validate_contract_object(contract: dict[str, Any]) -> None:
    descriptor, name = tempfile.mkstemp(prefix="pmpe-contract-", suffix=".json")
    path = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(contract) + b"\n")
        load_contract(path)
    finally:
        path.unlink(missing_ok=True)


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        loaded = strict_loads(Path(path).read_bytes(), "application/json")
    except (OSError, CanonicalInputError) as exc:
        raise SpecError(f"cannot read JSON object {path}") from exc
    return loaded


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
