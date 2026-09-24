"""Normalize a schema-valid raw mapping into the typed MvpSpec.

Normalization is deliberately mechanical: trim strings, assign missing IDs
deterministically, apply defaults. It never invents product content.
"""

from __future__ import annotations

from typing import Any

from pmpe.domain.models import (
    AcceptanceCriterion,
    Entity,
    EntityField,
    FunctionalRequirement,
    MvpSpec,
    NonFunctionalRequirement,
    RiskLevel,
    SpecRisk,
    UserStory,
)


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _clean_list(values: Any) -> list[str]:
    return [_clean(v) for v in (values or []) if _clean(v)]


def _assign_ids(items: list[dict[str, Any]], prefix: str) -> None:
    """Give every item a unique id, preserving explicit ones."""
    taken = {str(item["id"]) for item in items if item.get("id")}
    counter = 1
    for item in items:
        if item.get("id"):
            continue
        while f"{prefix}-{counter:03d}" in taken:
            counter += 1
        item["id"] = f"{prefix}-{counter:03d}"
        taken.add(item["id"])


def normalize_spec(data: dict[str, Any]) -> MvpSpec:
    stories_raw = [dict(s) for s in data.get("user_stories", [])]
    _assign_ids(stories_raw, "US")
    stories = [
        UserStory(
            id=_clean(s["id"]),
            as_a=_clean(s.get("as_a")),
            i_want=_clean(s.get("i_want")),
            so_that=_clean(s.get("so_that")),
        )
        for s in stories_raw
    ]

    acs_raw = [dict(a) for a in data.get("acceptance_criteria", [])]
    _assign_ids(acs_raw, "AC")
    acs = [
        AcceptanceCriterion(
            id=_clean(a["id"]),
            requirement=_clean(a.get("requirement")),
            criterion=_clean(a.get("criterion")),
        )
        for a in acs_raw
    ]

    frs_raw = [dict(f) for f in data.get("functional_requirements", [])]
    _assign_ids(frs_raw, "FR")
    frs = [
        FunctionalRequirement(
            id=_clean(f["id"]),
            title=_clean(f.get("title")),
            capability=_clean(f.get("capability")),
            entity=_clean(f["entity"]) if f.get("entity") else None,
            description=_clean(f.get("description")),
        )
        for f in frs_raw
    ]

    entities = [
        Entity(
            name=_clean(e.get("name")),
            fields=[
                EntityField(
                    name=_clean(fld.get("name")),
                    type=_clean(fld.get("type")),
                    required=bool(fld.get("required", False)),
                    default=_clean(fld["default"]) if fld.get("default") is not None else None,
                )
                for fld in e.get("fields", [])
            ],
        )
        for e in data.get("entities", [])
    ]

    nfrs_raw = [dict(n) for n in data.get("non_functional_requirements", [])]
    _assign_ids(nfrs_raw, "NFR")
    nfrs = [
        NonFunctionalRequirement(
            id=_clean(n["id"]),
            category=_clean(n.get("category")),
            requirement=_clean(n.get("requirement")),
        )
        for n in nfrs_raw
    ]

    risks = [
        SpecRisk(
            description=_clean(r.get("description")),
            level=RiskLevel(_clean(r.get("level")) or "medium"),
        )
        for r in data.get("risks", [])
    ]

    return MvpSpec(
        spec_version=_clean(data.get("spec_version")),
        product_name=_clean(data.get("product_name")),
        problem_statement=_clean(data.get("problem_statement")),
        target_user=_clean(data.get("target_user")),
        user_outcome=_clean(data.get("user_outcome")),
        business_outcome=_clean(data.get("business_outcome")),
        hypothesis=_clean(data.get("hypothesis")),
        scope=_clean_list(data.get("scope")),
        non_goals=_clean_list(data.get("non_goals")),
        user_stories=stories,
        acceptance_criteria=acs,
        functional_requirements=frs,
        entities=entities,
        non_functional_requirements=nfrs,
        success_metrics=_clean_list(data.get("success_metrics")),
        north_star_metric=_clean(data.get("north_star_metric")),
        leading_metrics=_clean_list(data.get("leading_metrics")),
        guardrails=_clean_list(data.get("guardrails")),
        constraints=_clean_list(data.get("constraints")),
        assumptions=_clean_list(data.get("assumptions")),
        dependencies=_clean_list(data.get("dependencies")),
        risks=risks,
        priority=_clean(data.get("priority")),
        target_platform=_clean(data.get("target_platform")),
        preferred_stack=_clean(data.get("preferred_stack")) or "python-stdlib",
        deployment_target=_clean(data.get("deployment_target")),
    )
