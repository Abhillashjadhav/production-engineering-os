"""Core typed models. Pure data — no I/O, no business logic beyond trivial properties."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


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
