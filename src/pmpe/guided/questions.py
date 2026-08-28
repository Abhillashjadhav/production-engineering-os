"""Plain-language question catalogue and UX-only contract-shape adapter."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

AnswerKind = Literal["short_text", "long_text", "line_list", "requirements", "criteria"]


@dataclass(frozen=True)
class GuidedQuestion:
    field: str
    label: str
    prompt: str
    reason: str
    answer_kind: AnswerKind
    placeholder: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


FIELDS: tuple[GuidedQuestion, ...] = (
    GuidedQuestion(
        "product_name",
        "Product name",
        "What should we call this product or capability?",
        "A stable name keeps the decision and its evidence identifiable.",
        "short_text",
        "Example: Release confidence assistant",
    ),
    GuidedQuestion(
        "target_user",
        "Primary user",
        "Who experiences the problem most directly?",
        "A specific user prevents a solution designed for everyone and no one.",
        "short_text",
        "Example: Product managers shipping AI features",
    ),
    GuidedQuestion(
        "problem",
        "Problem",
        "What recurring problem are they facing, and why does it matter?",
        "PMOS must understand the problem before accepting a solution.",
        "long_text",
        "Describe the situation, pain, and consequence.",
    ),
    GuidedQuestion(
        "desired_outcome",
        "Desired outcome",
        "What should become observably better for that user?",
        "Approval is tied to an outcome, not merely to shipping features.",
        "long_text",
        "Example: A PM can make a release decision from verified evidence in 10 minutes.",
    ),
    GuidedQuestion(
        "north_star_metric",
        "North Star outcome",
        "Which outcome metric best proves that user value was delivered?",
        "Activity counts such as prompts or logins do not prove an outcome.",
        "long_text",
        "Example: Percentage of release decisions made with complete verified evidence.",
    ),
    GuidedQuestion(
        "leading_metrics",
        "Leading measures",
        "Which early measures show movement toward the outcome?",
        "Leading measures help detect progress before the North Star moves.",
        "line_list",
        "One measure per line\nMedian evidence collection time\nFirst-pass review rate",
    ),
    GuidedQuestion(
        "guardrails",
        "Guardrails",
        "What must not get worse while improving the outcome?",
        "Guardrails bound quality, safety, privacy, and cost.",
        "line_list",
        "One guardrail per line\nZero unauthorized writes\nP95 latency below 3 seconds",
    ),
    GuidedQuestion(
        "scope",
        "First-version scope",
        "What is included in the first version?",
        "Explicit scope makes the engineering handoff bounded.",
        "line_list",
        "One item per line",
    ),
    GuidedQuestion(
        "out_of_scope",
        "Not in this version",
        "What are we deliberately excluding?",
        "Non-goals prevent silent scope expansion.",
        "line_list",
        "One exclusion per line",
    ),
    GuidedQuestion(
        "functional_requirements",
        "Required behaviours",
        "What must the product let the user do?",
        "Each behaviour becomes a traceable requirement.",
        "requirements",
        (
            "One behaviour per line\nReview an exact approval digest\n"
            "Create a change request after approval"
        ),
    ),
    GuidedQuestion(
        "acceptance_criteria",
        "Proof for each behaviour",
        "How will we know each required behaviour works?",
        "Every requirement needs one observable acceptance criterion.",
        "criteria",
        "One criterion per requirement, in the same order",
    ),
    GuidedQuestion(
        "non_functional_requirements",
        "Quality requirements",
        "What reliability, accessibility, security, latency, or scale is required?",
        "Engineering needs quality constraints as well as behaviours.",
        "line_list",
        "One quality requirement per line",
    ),
    GuidedQuestion(
        "known_risks",
        "Known risks",
        "What could cause harm, failure, or rework?",
        "Named risks make the approval impact legible.",
        "line_list",
        "One risk per line",
    ),
    GuidedQuestion(
        "binary_release_gates",
        "Release gates",
        "Which checks must pass before release?",
        "Binary gates stop a plausible narrative from replacing evidence.",
        "line_list",
        "One pass/fail gate per line",
    ),
    GuidedQuestion(
        "scored_eval_rubric",
        "Quality rubric",
        "Which qualities need a scored review?",
        "Scored qualities cover important behaviours that are not purely binary.",
        "line_list",
        "One quality per line",
    ),
    GuidedQuestion(
        "golden_cases",
        "Representative cases",
        "Which examples must remain correct over time?",
        "Golden cases protect the product from regressions.",
        "line_list",
        "One case or fixture reference per line",
    ),
    GuidedQuestion(
        "required_approvals",
        "Human approvals",
        "Which roles must approve release or other high-impact actions?",
        "High-impact actions need explicit human authority.",
        "line_list",
        "One role per line\nProduct owner\nSecurity owner",
    ),
)
_BY_FIELD = {item.field: item for item in FIELDS}


def as_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def as_lines(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [
        line.strip(" \t-\u2022") for line in as_text(value).splitlines() if line.strip(" \t-\u2022")
    ]


def question_for(field: str, reason: str | None = None) -> GuidedQuestion:
    base = _BY_FIELD[field]
    return GuidedQuestion(
        field=base.field,
        label=base.label,
        prompt=base.prompt,
        reason=reason or base.reason,
        answer_kind=base.answer_kind,
        placeholder=base.placeholder,
    )


def next_question(raw_answers: dict[str, Any]) -> GuidedQuestion | None:
    for item in FIELDS:
        if not as_text(raw_answers.get(item.field)) and not as_lines(raw_answers.get(item.field)):
            return item
    requirements = as_lines(raw_answers.get("functional_requirements"))
    criteria = as_lines(raw_answers.get("acceptance_criteria"))
    if len(criteria) != len(requirements):
        return question_for(
            "acceptance_criteria",
            f"Supply exactly one proof for each behaviour ({len(requirements)} required; "
            f"{len(criteria)} supplied).",
        )
    return None


def _numbered(lines: list[str], prefix: str, mapper: Any) -> list[dict[str, Any]]:
    return [mapper(f"{prefix}-{index:03d}", value, index) for index, value in enumerate(lines, 1)]


def normalize_answers(raw_answers: dict[str, Any]) -> dict[str, Any]:
    requirements = as_lines(raw_answers["functional_requirements"])
    criteria = as_lines(raw_answers["acceptance_criteria"])
    return {
        "product_name": as_text(raw_answers["product_name"]),
        "target_user": as_text(raw_answers["target_user"]),
        "problem": as_text(raw_answers["problem"]),
        "desired_outcome": as_text(raw_answers["desired_outcome"]),
        "north_star_metric": as_text(raw_answers["north_star_metric"]),
        "leading_metrics": as_lines(raw_answers["leading_metrics"]),
        "guardrails": as_lines(raw_answers["guardrails"]),
        "scope": as_lines(raw_answers["scope"]),
        "out_of_scope": as_lines(raw_answers["out_of_scope"]),
        "functional_requirements": _numbered(
            requirements,
            "FR",
            lambda identifier, value, index: {
                "capability": f"product.behaviour.{index:03d}",
                "description": value,
                "id": identifier,
                "title": value[:100],
            },
        ),
        "acceptance_criteria": _numbered(
            criteria,
            "AC",
            lambda identifier, value, index: {
                "criterion": value,
                "id": identifier,
                "requirement": f"FR-{index:03d}",
            },
        ),
        "non_functional_requirements": _numbered(
            as_lines(raw_answers["non_functional_requirements"]),
            "NFR",
            lambda identifier, value, _index: {
                "category": "quality",
                "id": identifier,
                "requirement": value,
            },
        ),
        "known_risks": [
            {"description": value, "level": "high"}
            for value in as_lines(raw_answers["known_risks"])
        ],
        "binary_release_gates": _numbered(
            as_lines(raw_answers["binary_release_gates"]),
            "GATE",
            lambda identifier, value, _index: {"description": value, "id": identifier},
        ),
        "scored_eval_rubric": _numbered(
            as_lines(raw_answers["scored_eval_rubric"]),
            "RUB",
            lambda identifier, value, _index: {
                "criterion": value,
                "id": identifier,
                "scale": "1-5",
            },
        ),
        "golden_cases": as_lines(raw_answers["golden_cases"]),
        "required_approvals": [
            {"for": "release and high-impact actions", "role": value.lower().replace(" ", "-")}
            for value in as_lines(raw_answers["required_approvals"])
        ],
    }


def questionnaire() -> dict[str, Any]:
    return {
        "question_count": len(FIELDS),
        "questions": [item.as_dict() for item in FIELDS],
        "schema_version": "1.0.0",
    }
