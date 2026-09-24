"""Typed FullStackProductContract model and loader (V3, PD-V3).

Structure is enforced by the schema; *runnability* is semantic: only an
APPROVED contract with a named approver and zero blocking unresolved questions
may enter an engineering run. Cross-reference rules between the journey,
screens, and UI states are the UX architecture stage's job
(``pmpe.fullstack.journey``), not the loader's.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pmpe.config import packaged_schema_dir
from pmpe.contracts.digest import canonical_digest
from pmpe.domain.errors import SpecError
from pmpe.ingestion.schema import SchemaValidator


@dataclass(frozen=True)
class JourneyStep:
    step_id: str
    description: str
    screen_id: str


@dataclass(frozen=True)
class Screen:
    screen_id: str
    name: str
    purpose: str
    states: tuple[str, ...]


@dataclass(frozen=True)
class BackendCapability:
    capability_id: str
    description: str


@dataclass(frozen=True)
class DataEntity:
    entity_id: str
    name: str
    persistence: str  # "none" | "ephemeral_session" | "permanent"


@dataclass(frozen=True)
class ApiContract:
    api_id: str
    method: str
    path: str
    purpose: str


@dataclass(frozen=True)
class FullStackReleaseGate:
    id: str
    description: str


@dataclass(frozen=True)
class FullStackQuestion:
    id: str
    question: str
    blocking: bool
    resolution: str = ""


@dataclass(frozen=True)
class DeploymentTarget:
    kind: str  # "local_preview" | "containerized_preview" | "cloud"
    description: str


@dataclass(frozen=True)
class FullStackProductContract:
    contract_id: str
    contract_version: int
    contract_status: str
    approved_at: str
    approved_by: str
    product_name: str
    problem: str
    target_user: str
    primary_journey: tuple[JourneyStep, ...]
    screens: tuple[Screen, ...]
    ui_states: tuple[str, ...]
    backend_capabilities: tuple[BackendCapability, ...]
    data_entities: tuple[DataEntity, ...]
    api_contracts: tuple[ApiContract, ...]
    accessibility_requirements: tuple[str, ...]
    responsive_requirements: tuple[str, ...]
    binary_release_gates: tuple[FullStackReleaseGate, ...]
    guardrails: tuple[str, ...]
    deployment_target: DeploymentTarget
    out_of_scope: tuple[str, ...]
    unresolved_questions: tuple[FullStackQuestion, ...]
    required_approvals: tuple[str, ...]
    raw: dict[str, Any] = field(repr=False)

    @property
    def blockers(self) -> list[str]:
        problems: list[str] = []
        if self.contract_status != "APPROVED":
            problems.append(
                f"contract_status is {self.contract_status}; only APPROVED contracts run"
            )
        if not self.approved_by.strip():
            problems.append("no named approver")
        for q in self.unresolved_questions:
            if q.blocking and not q.resolution.strip():
                problems.append(f"blocking question {q.id} is unresolved: {q.question}")
        return problems

    @property
    def runnable(self) -> bool:
        return not self.blockers

    @property
    def digest(self) -> str:
        return canonical_digest(self.raw)

    def screen(self, screen_id: str) -> Screen | None:
        return next((s for s in self.screens if s.screen_id == screen_id), None)


def fullstack_schema_path() -> Path:
    return packaged_schema_dir() / "fullstack_product_contract.schema.json"


_UNIQUE_ID_SECTIONS = (
    ("primary_journey", "step_id"),
    ("screens", "screen_id"),
    ("backend_capabilities", "capability_id"),
    ("data_entities", "entity_id"),
    ("api_contracts", "api_id"),
    ("binary_release_gates", "id"),
    ("unresolved_questions", "id"),
)


def load_fullstack_contract(path: Path) -> FullStackProductContract:
    """Load + schema-validate + type a full-stack contract. Raises SpecError on
    structural problems; semantic runnability is reported via ``blockers``."""
    try:
        data: Any = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecError(f"cannot read full-stack contract {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecError(f"full-stack contract {path} must be a JSON object")
    errors = SchemaValidator(fullstack_schema_path()).validate(data)
    for section, key in _UNIQUE_ID_SECTIONS:
        seen: set[str] = set()
        for item in data.get(section, []):
            item_id = str(item.get(key, ""))
            if item_id in seen:
                errors.append(f"{section}: duplicate {key} '{item_id}'")
            seen.add(item_id)
    if errors:
        raise SpecError(f"full-stack contract {path} violates the schema", errors)

    return FullStackProductContract(
        contract_id=data["contract_id"],
        contract_version=int(data["contract_version"]),
        contract_status=data["contract_status"],
        approved_at=data["approved_at"],
        approved_by=data["approved_by"],
        product_name=data["product_name"],
        problem=data["problem"],
        target_user=data["target_user"],
        primary_journey=tuple(
            JourneyStep(
                step_id=s["step_id"],
                description=s["description"],
                screen_id=s["screen_id"],
            )
            for s in data["primary_journey"]
        ),
        screens=tuple(
            Screen(
                screen_id=s["screen_id"],
                name=s["name"],
                purpose=s["purpose"],
                states=tuple(s["states"]),
            )
            for s in data["screens"]
        ),
        ui_states=tuple(data["ui_states"]),
        backend_capabilities=tuple(
            BackendCapability(capability_id=c["capability_id"], description=c["description"])
            for c in data["backend_capabilities"]
        ),
        data_entities=tuple(
            DataEntity(
                entity_id=e["entity_id"],
                name=e["name"],
                persistence=e["persistence"],
            )
            for e in data["data_entities"]
        ),
        api_contracts=tuple(
            ApiContract(
                api_id=a["api_id"],
                method=a["method"],
                path=a["path"],
                purpose=a["purpose"],
            )
            for a in data["api_contracts"]
        ),
        accessibility_requirements=tuple(data["accessibility_requirements"]),
        responsive_requirements=tuple(data["responsive_requirements"]),
        binary_release_gates=tuple(
            FullStackReleaseGate(id=g["id"], description=g["description"])
            for g in data["binary_release_gates"]
        ),
        guardrails=tuple(data["guardrails"]),
        deployment_target=DeploymentTarget(
            kind=data["deployment_target"]["kind"],
            description=data["deployment_target"]["description"],
        ),
        out_of_scope=tuple(data["out_of_scope"]),
        unresolved_questions=tuple(
            FullStackQuestion(
                id=q["id"],
                question=q["question"],
                blocking=bool(q["blocking"]),
                resolution=q.get("resolution", ""),
            )
            for q in data["unresolved_questions"]
        ),
        required_approvals=tuple(data["required_approvals"]),
        raw=data,
    )
