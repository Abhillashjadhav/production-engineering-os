"""Core typed models. Pure data — no I/O, no business logic beyond trivial properties."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class IssueKind(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    QUESTION = "question"


# --- specification -------------------------------------------------------------------


@dataclass(frozen=True)
class UserStory:
    id: str
    as_a: str
    i_want: str
    so_that: str


@dataclass(frozen=True)
class AcceptanceCriterion:
    id: str
    requirement: str
    criterion: str


@dataclass(frozen=True)
class FunctionalRequirement:
    id: str
    title: str
    capability: str
    entity: str | None = None
    description: str = ""


@dataclass(frozen=True)
class EntityField:
    name: str
    type: str
    required: bool = False
    default: str | None = None


@dataclass
class Entity:
    name: str
    fields: list[EntityField]


@dataclass(frozen=True)
class NonFunctionalRequirement:
    id: str
    category: str
    requirement: str


@dataclass(frozen=True)
class SpecRisk:
    description: str
    level: RiskLevel = RiskLevel.MEDIUM


@dataclass
class MvpSpec:
    spec_version: str
    product_name: str
    problem_statement: str
    target_user: str
    user_outcome: str
    business_outcome: str
    scope: list[str]
    non_goals: list[str]
    user_stories: list[UserStory]
    acceptance_criteria: list[AcceptanceCriterion]
    functional_requirements: list[FunctionalRequirement]
    north_star_metric: str
    priority: str
    target_platform: str
    deployment_target: str
    hypothesis: str = ""
    entities: list[Entity] = field(default_factory=list)
    non_functional_requirements: list[NonFunctionalRequirement] = field(default_factory=list)
    success_metrics: list[str] = field(default_factory=list)
    leading_metrics: list[str] = field(default_factory=list)
    guardrails: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    risks: list[SpecRisk] = field(default_factory=list)
    preferred_stack: str = "python-stdlib"

    def entity(self, name: str) -> Entity | None:
        return next((e for e in self.entities if e.name == name), None)

    def criteria_for(self, requirement_id: str) -> list[AcceptanceCriterion]:
        return [ac for ac in self.acceptance_criteria if ac.requirement == requirement_id]


# --- validation ----------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    kind: IssueKind
    field: str = ""


@dataclass
class ValidationReport:
    errors: list[ValidationIssue]
    warnings: list[ValidationIssue]
    questions: list[ValidationIssue]

    @property
    def ok(self) -> bool:
        return not self.errors


# --- planning ------------------------------------------------------------------------


@dataclass
class PlanTask:
    id: str
    title: str
    component: str
    kind: str  # scaffold | test | feature
    requirement_ids: list[str]
    depends_on: list[str]
    complexity: str  # S | M | L


@dataclass
class EngineeringPlan:
    tasks: list[PlanTask]
    order: list[str]
    graph: dict[str, list[str]]
    components: list[str]
    data_model: list[str]
    apis: list[str]
    risks: list[str]

    def task(self, task_id: str) -> PlanTask:
        return next(t for t in self.tasks if t.id == task_id)


# --- architecture --------------------------------------------------------------------


@dataclass
class Adr:
    id: str
    title: str
    context: str
    decision: str
    consequences: str
    risk: RiskLevel
    reversibility: str  # reversible | irreversible
    requirement_ids: list[str] = field(default_factory=list)


@dataclass
class ArchitectureDoc:
    overview: str
    components: dict[str, str]
    implications: dict[str, str]  # security / scalability / reliability / maintainability


@dataclass
class ArchitectureOutput:
    doc: ArchitectureDoc
    adrs: list[Adr]
    escalations: list[Escalation]


# --- generation ----------------------------------------------------------------------


@dataclass(frozen=True)
class GeneratedFile:
    path: str  # workspace-relative, forward slashes
    content: str
    kind: str  # test | code | doc | deploy


@dataclass
class GeneratedTests:
    files: list[GeneratedFile]
    tests_by_requirement: dict[str, list[str]]


@dataclass
class Implementation:
    files_by_task: dict[str, list[GeneratedFile]]
    code_by_requirement: dict[str, list[str]]


# --- escalation / approval -----------------------------------------------------------


@dataclass
class Escalation:
    id: str
    risk: RiskLevel
    reason: str
    step: str
    context: dict[str, Any]
    created_at: str = ""


@dataclass(frozen=True)
class PolicyDecision:
    decision_type: str
    level: RiskLevel
    rule_id: str
    justification: str
