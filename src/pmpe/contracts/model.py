"""Typed ProductDecisionContract model and loader.

Structure is enforced by the schema; *runnability* is semantic: only an APPROVED
contract with a named approver and zero unresolved product-critical questions may
enter an engineering run (PD-03 rule 1/6). Product behaviour comes from this
document only — never inferred from chat history or repository code (rule 7).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pmpe.config import packaged_schema_dir
from pmpe.contracts.canonical import CanonicalInputError, strict_loads
from pmpe.domain.errors import SpecError
from pmpe.ingestion.schema import SchemaValidator

_SAFE_CONTRACT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_ID_COLLECTIONS = (
    "functional_requirements",
    "acceptance_criteria",
    "binary_release_gates",
    "scored_eval_rubric",
    "non_functional_requirements",
    "approved_product_decisions",
    "unresolved_questions",
)


@dataclass(frozen=True)
class ContractRequirement:
    id: str
    title: str
    description: str = ""
    capability: str = ""
    entity: str = ""


@dataclass(frozen=True)
class ContractCriterion:
    id: str
    requirement: str
    criterion: str


@dataclass(frozen=True)
class ReleaseGate:
    id: str
    description: str


@dataclass(frozen=True)
class UnresolvedQuestion:
    id: str
    question: str
    product_critical: bool
    resolution: str = ""


@dataclass
class ProductDecisionContract:
    contract_id: str
    contract_version: int
    contract_status: str
    approved_at: str
    approved_by: str
    source_digest: str
    product_name: str
    problem: str
    target_user: str
    desired_outcome: str
    scope: list[str]
    out_of_scope: list[str]
    functional_requirements: list[ContractRequirement]
    acceptance_criteria: list[ContractCriterion]
    binary_release_gates: list[ReleaseGate]
    north_star_metric: str
    unresolved_questions: list[UnresolvedQuestion]
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def blockers(self) -> list[str]:
        """Reasons this contract may not enter an engineering run (empty = runnable)."""
        blockers: list[str] = []
        if self.contract_status != "APPROVED":
            blockers.append(
                f"contract_status is '{self.contract_status}' — only APPROVED contracts "
                "can enter an engineering run"
            )
        if self.contract_status == "APPROVED" and not self.approved_by.strip():
            blockers.append("APPROVED contract has no named approver (approved_by is empty)")
        if self.contract_status == "APPROVED" and not self.approved_at.strip():
            blockers.append("APPROVED contract has no approval timestamp (approved_at is empty)")
        for question in self.unresolved_questions:
            if question.product_critical and not question.resolution.strip():
                blockers.append(
                    f"unresolved product-critical question {question.id}: {question.question}"
                )
        return blockers

    @property
    def runnable(self) -> bool:
        return not self.blockers

    def requirement_ids(self) -> list[str]:
        return [r.id for r in self.functional_requirements]

    def criteria_for(self, requirement_id: str) -> list[ContractCriterion]:
        return [c for c in self.acceptance_criteria if c.requirement == requirement_id]


def contract_schema_path() -> Path:
    return packaged_schema_dir() / "product_decision_contract.schema.json"


def load_contract(path: Path) -> ProductDecisionContract:
    """Load + schema-validate + type a contract. Raises SpecError on structural
    problems; semantic runnability is reported via ``blockers``, not exceptions."""
    try:
        data: Any = strict_loads(Path(path).read_bytes(), "application/json")
    except (OSError, CanonicalInputError) as exc:
        raise SpecError(f"cannot read contract {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecError(f"contract {path} must be a JSON object")
    errors = SchemaValidator(contract_schema_path()).validate(data)
    contract_id = data.get("contract_id")
    if not isinstance(contract_id, str) or not _SAFE_CONTRACT_ID.fullmatch(contract_id):
        errors.append("contract_id: unsafe or unbounded identifier")
    for collection in _ID_COLLECTIONS:
        seen: set[str] = set()
        for item in data.get(collection, []):
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id", ""))
            if item_id in seen:
                errors.append(f"{collection}: duplicate id '{item_id}'")
            seen.add(item_id)
    if errors:
        raise SpecError(f"contract {path} violates the schema", errors)

    return ProductDecisionContract(
        contract_id=data["contract_id"],
        contract_version=int(data["contract_version"]),
        contract_status=data["contract_status"],
        approved_at=data["approved_at"],
        approved_by=data["approved_by"],
        source_digest=data["source_digest"],
        product_name=data["product_name"],
        problem=data["problem"],
        target_user=data["target_user"],
        desired_outcome=data["desired_outcome"],
        scope=list(data["scope"]),
        out_of_scope=list(data["out_of_scope"]),
        functional_requirements=[
            ContractRequirement(
                id=r["id"],
                title=r["title"],
                description=r.get("description", ""),
                capability=r.get("capability", ""),
                entity=r.get("entity", ""),
            )
            for r in data["functional_requirements"]
        ],
        acceptance_criteria=[
            ContractCriterion(id=c["id"], requirement=c["requirement"], criterion=c["criterion"])
            for c in data["acceptance_criteria"]
        ],
        binary_release_gates=[
            ReleaseGate(id=g["id"], description=g["description"])
            for g in data["binary_release_gates"]
        ],
        north_star_metric=data["north_star_metric"],
        unresolved_questions=[
            UnresolvedQuestion(
                id=q["id"],
                question=q["question"],
                product_critical=bool(q["product_critical"]),
                resolution=q.get("resolution", ""),
            )
            for q in data["unresolved_questions"]
        ],
        raw=data,
    )
