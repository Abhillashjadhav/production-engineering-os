"""Semantic validation of a normalized MvpSpec.

Every rule is deterministic and named; the rule id lands in the issue code so any
verdict is explainable. Three outcomes:

- errors    -> block the run (contradictions, broken references)
- warnings  -> logged, never block
- questions -> a human owns the answer; the orchestrator escalates them
"""

from __future__ import annotations

import re

from pmpe.domain.models import (
    IssueKind,
    MvpSpec,
    ValidationIssue,
    ValidationReport,
)

_ACTIVITY_TERMS = (
    "signup",
    "sign-up",
    "sign up",
    "click",
    "pageview",
    "page view",
    "session",
    "login",
    "log-in",
    "log in",
    "download",
    "install",
    "visit",
    "impression",
)
_OUTCOME_TERMS = (
    "complete",
    "completed",
    "finish",
    "resolved",
    "achiev",
    "succeed",
    "success",
    "retain",
    "retention",
    "convert",
    "revenue",
    "outcome",
    "saved",
    "recovered",
    "detected",
)
_VAGUE_AC_TERMS = ("fast", "easy", "intuitive", "user-friendly", "nice", "feel", "seamless")
_OBSERVABLE_AC_MARKERS = ("then", "return", "status", "response", "error", "stored", "reject")
_EXTERNAL_DEPENDENCY_KEYWORDS = (
    "postgres",
    "mysql",
    "redis",
    "stripe",
    "s3",
    "oauth",
    "smtp",
    "kafka",
    "rabbitmq",
    "elasticsearch",
    "sqlite",
)
_RECOMMENDED_FIELDS = (
    "success_metrics",
    "leading_metrics",
    "guardrails",
    "constraints",
    "assumptions",
    "dependencies",
    "risks",
)
_SUPPORTED_DEPLOYMENT_TARGETS = ("local",)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_RESERVED_FIELDS = ("id", "created_at", "updated_at")
_REQUIREMENT_ID_RE = re.compile(r"^[A-Z]+-\d+$")
_DEPENDENT_ENTITY_CAPABILITIES = (
    "entity.read",
    "entity.update",
    "entity.delete",
    "entity.list",
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().casefold())


class RequirementValidator:
    def validate(self, spec: MvpSpec) -> ValidationReport:
        errors: list[ValidationIssue] = []
        warnings: list[ValidationIssue] = []
        questions: list[ValidationIssue] = []

        self._check_contradictions(spec, errors)
        self._check_requirement_criteria_links(spec, errors)
        self._check_requirement_id_format(spec, errors)
        self._check_entities(spec, errors)
        self._check_capability_dependencies(spec, errors)
        self._check_identifiers(spec, errors)
        self._check_health_capability(spec, warnings)
        self._check_nsm(spec, questions)
        self._check_ac_testability(spec, questions)
        self._check_dependencies(spec, warnings)
        self._check_deployment_target(spec, questions)
        self._check_recommended_fields(spec, warnings)

        return ValidationReport(errors=errors, warnings=warnings, questions=questions)

    # --- rules ------------------------------------------------------------------

    def _check_contradictions(self, spec: MvpSpec, errors: list[ValidationIssue]) -> None:
        non_goals = {_norm(g): g for g in spec.non_goals}
        for item in spec.scope:
            hit = non_goals.get(_norm(item))
            if hit is not None:
                errors.append(
                    ValidationIssue(
                        code="CONTRADICTION",
                        message=(
                            f"'{item}' appears in scope AND in non_goals ('{hit}') — "
                            "the spec contradicts itself; a product decision is required"
                        ),
                        kind=IssueKind.ERROR,
                        field="scope",
                    )
                )

    def _check_requirement_criteria_links(
        self, spec: MvpSpec, errors: list[ValidationIssue]
    ) -> None:
        fr_ids = {fr.id for fr in spec.functional_requirements}
        for ac in spec.acceptance_criteria:
            if ac.requirement not in fr_ids:
                errors.append(
                    ValidationIssue(
                        code="AC_UNKNOWN_REQUIREMENT",
                        message=(
                            f"{ac.id} references requirement '{ac.requirement}' "
                            "which does not exist"
                        ),
                        kind=IssueKind.ERROR,
                        field="acceptance_criteria",
                    )
                )
        covered = {ac.requirement for ac in spec.acceptance_criteria}
        for fr in spec.functional_requirements:
            if fr.id not in covered:
                errors.append(
                    ValidationIssue(
                        code="FR_WITHOUT_AC",
                        message=f"{fr.id} ('{fr.title}') has no acceptance criteria",
                        kind=IssueKind.ERROR,
                        field="functional_requirements",
                    )
                )

    def _check_entities(self, spec: MvpSpec, errors: list[ValidationIssue]) -> None:
        declared = {e.name for e in spec.entities}
        for fr in spec.functional_requirements:
            if not fr.capability.startswith("entity."):
                continue
            if not fr.entity:
                errors.append(
                    ValidationIssue(
                        code="MISSING_ENTITY",
                        message=f"{fr.id} uses capability '{fr.capability}' but names no entity",
                        kind=IssueKind.ERROR,
                        field="functional_requirements",
                    )
                )
            elif fr.entity not in declared:
                errors.append(
                    ValidationIssue(
                        code="MISSING_ENTITY",
                        message=(
                            f"{fr.id} references entity '{fr.entity}' which is not declared "
                            "in entities[] — the data model is incomplete"
                        ),
                        kind=IssueKind.ERROR,
                        field="entities",
                    )
                )

    def _check_requirement_id_format(self, spec: MvpSpec, errors: list[ValidationIssue]) -> None:
        """FR ids become traceability keys and Covers: markers — one grammar owns them."""
        for fr in spec.functional_requirements:
            if not _REQUIREMENT_ID_RE.match(fr.id):
                errors.append(
                    ValidationIssue(
                        code="REQUIREMENT_ID_FORMAT",
                        message=(
                            f"requirement id '{fr.id}' must match PREFIX-NUMBER "
                            "(e.g. FR-001) — it keys traceability and test markers"
                        ),
                        kind=IssueKind.ERROR,
                        field="functional_requirements",
                    )
                )

    def _check_capability_dependencies(self, spec: MvpSpec, errors: list[ValidationIssue]) -> None:
        """V1 tests and verifies entities end-to-end through their create capability."""
        by_entity: dict[str, set[str]] = {}
        for fr in spec.functional_requirements:
            if fr.entity and fr.capability.startswith("entity."):
                by_entity.setdefault(fr.entity, set()).add(fr.capability)
        for entity, caps in sorted(by_entity.items()):
            dependents = sorted(c for c in caps if c in _DEPENDENT_ENTITY_CAPABILITIES)
            if dependents and "entity.create" not in caps:
                errors.append(
                    ValidationIssue(
                        code="CAPABILITY_DEPENDENCY",
                        message=(
                            f"entity '{entity}' declares {', '.join(dependents)} but not "
                            "entity.create — V1 cannot generate verifiable tests or a "
                            "user journey without a way to create the entity"
                        ),
                        kind=IssueKind.ERROR,
                        field="functional_requirements",
                    )
                )

    def _check_health_capability(self, spec: MvpSpec, warnings: list[ValidationIssue]) -> None:
        if spec.target_platform == "api" and not any(
            fr.capability == "health.check" for fr in spec.functional_requirements
        ):
            warnings.append(
                ValidationIssue(
                    code="MISSING_HEALTH_CHECK",
                    message=(
                        "no health.check requirement: deployment verification falls back "
                        "to TCP readiness instead of a health endpoint"
                    ),
                    kind=IssueKind.WARNING,
                    field="functional_requirements",
                )
            )

    def _check_identifiers(self, spec: MvpSpec, errors: list[ValidationIssue]) -> None:
        """Entity and field names become code and SQL identifiers — constrain them."""
        for entity in spec.entities:
            names = [("entity", entity.name)] + [("field", f.name) for f in entity.fields]
            for kind, name in names:
                if not _IDENTIFIER_RE.match(name):
                    errors.append(
                        ValidationIssue(
                            code="INVALID_IDENTIFIER",
                            message=(
                                f"{kind} name '{name}' is not a valid identifier "
                                "(letters, digits, underscores; must start with a letter)"
                            ),
                            kind=IssueKind.ERROR,
                            field="entities",
                        )
                    )
            for f in entity.fields:
                if f.name in _RESERVED_FIELDS:
                    errors.append(
                        ValidationIssue(
                            code="INVALID_IDENTIFIER",
                            message=(
                                f"field name '{f.name}' on entity '{entity.name}' is "
                                "reserved (generated automatically)"
                            ),
                            kind=IssueKind.ERROR,
                            field="entities",
                        )
                    )

    def _check_nsm(self, spec: MvpSpec, questions: list[ValidationIssue]) -> None:
        nsm = _norm(spec.north_star_metric)
        has_activity = any(term in nsm for term in _ACTIVITY_TERMS)
        has_outcome = any(term in nsm for term in _OUTCOME_TERMS)
        if has_activity and not has_outcome:
            questions.append(
                ValidationIssue(
                    code="NSM_ACTIVITY_ONLY",
                    message=(
                        "north_star_metric measures activity, not an outcome: "
                        f"'{spec.north_star_metric}'. What user/business outcome should it "
                        "represent instead?"
                    ),
                    kind=IssueKind.QUESTION,
                    field="north_star_metric",
                )
            )

    def _check_ac_testability(self, spec: MvpSpec, questions: list[ValidationIssue]) -> None:
        for ac in spec.acceptance_criteria:
            text = _norm(ac.criterion)
            has_digit = bool(re.search(r"\d", text))
            vague = any(term in text for term in _VAGUE_AC_TERMS)
            observable = any(marker in text for marker in _OBSERVABLE_AC_MARKERS)
            if (vague and not has_digit) or (not observable and not has_digit):
                questions.append(
                    ValidationIssue(
                        code="AC_UNTESTABLE",
                        message=(
                            f"{ac.id} is not verifiable as written: '{ac.criterion}'. "
                            "What observable behavior or measurable threshold defines pass?"
                        ),
                        kind=IssueKind.QUESTION,
                        field="acceptance_criteria",
                    )
                )

    def _check_dependencies(self, spec: MvpSpec, warnings: list[ValidationIssue]) -> None:
        declared = _norm(" ".join(spec.dependencies))
        for fr in spec.functional_requirements:
            text = _norm(f"{fr.title} {fr.description}")
            for keyword in _EXTERNAL_DEPENDENCY_KEYWORDS:
                if keyword in text and keyword not in declared:
                    warnings.append(
                        ValidationIssue(
                            code="MISSING_DEPENDENCY",
                            message=(
                                f"{fr.id} mentions '{keyword}' but dependencies[] does not "
                                "declare it"
                            ),
                            kind=IssueKind.WARNING,
                            field="dependencies",
                        )
                    )

    def _check_deployment_target(self, spec: MvpSpec, questions: list[ValidationIssue]) -> None:
        if spec.deployment_target not in _SUPPORTED_DEPLOYMENT_TARGETS:
            questions.append(
                ValidationIssue(
                    code="UNSUPPORTED_DEPLOYMENT",
                    message=(
                        f"deployment_target '{spec.deployment_target}' is not supported in V1 "
                        "(local only). Approve to continue with a local deployment plus a "
                        "deployable artifact, or change the spec."
                    ),
                    kind=IssueKind.QUESTION,
                    field="deployment_target",
                )
            )

    def _check_recommended_fields(self, spec: MvpSpec, warnings: list[ValidationIssue]) -> None:
        for name in _RECOMMENDED_FIELDS:
            if not getattr(spec, name):
                warnings.append(
                    ValidationIssue(
                        code="MISSING_RECOMMENDED",
                        message=f"recommended field '{name}' is missing or empty",
                        kind=IssueKind.WARNING,
                        field=name,
                    )
                )
