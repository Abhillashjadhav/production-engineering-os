"""Configuration-driven mapping from product eval facts to RunEnvelope V0.2."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field, JsonValue, field_validator, model_validator

from .models import (
    OPAQUE_IDENTIFIER_PATTERN,
    CaseRef,
    ChangeManifest,
    ComparisonRef,
    EvalConcern,
    EvalLayer,
    EvalMethod,
    EvaluationRef,
    EvidenceRef,
    Location,
    Observation,
    ObservationStatus,
    ProductRef,
    Provenance,
    Remediation,
    RunEnvelope,
    StrictModel,
    validate_redacted_text,
)

MAX_ADAPTER_INPUT_BYTES = 5 * 1024 * 1024
_ALL_STATUSES: frozenset[ObservationStatus] = frozenset(
    {"PASS", "FAIL", "BLOCKED", "NOT_EVALUATED"}
)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"adapter JSON contains duplicate key: {key}")
        result[key] = value
    return result


def _load_json(path: Path) -> object:
    data = path.read_bytes()
    if len(data) > MAX_ADAPTER_INPUT_BYTES:
        raise ValueError("adapter input exceeds the 5 MB limit")
    try:
        return json.loads(data, object_pairs_hook=_reject_duplicate_keys)
    except UnicodeDecodeError as exc:
        raise ValueError("adapter input must be UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("adapter input is not valid JSON") from exc


class AdapterProduct(StrictModel):
    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    environment: str = Field(min_length=1)
    freshness_sla_seconds: int = Field(ge=60, le=31 * 24 * 60 * 60)


class CheckDefinition(StrictModel):
    id: str = Field(min_length=1)
    layer: EvalLayer
    concern: EvalConcern
    suite_id: str = Field(min_length=1)
    suite_version: str = Field(min_length=1)
    method: EvalMethod
    component_id: str = Field(min_length=1)
    stage_id: str = Field(min_length=1)
    stage_index: int = Field(ge=1)
    parameter_id: str = Field(min_length=1)
    owner_id: str = Field(min_length=1)
    fix_location: str = Field(min_length=1, max_length=240)
    depends_on: list[str] = Field(default_factory=list)
    threshold: float | None = None
    tolerance: float = Field(default=0.0, ge=0.0)
    unit: str = ""
    higher_is_better: bool = True
    required: bool = True
    current_summary_by_status: dict[ObservationStatus, str]
    expected_summary: str = Field(min_length=1, max_length=500)
    remediation: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_summaries(self) -> CheckDefinition:
        missing = _ALL_STATUSES - set(self.current_summary_by_status)
        if missing:
            raise ValueError(
                "current_summary_by_status must define every status: " + ", ".join(sorted(missing))
            )
        return self


class AdapterSettings(StrictModel):
    mapper_version: Literal["0.1"] = "0.1"
    adapter_id: str = Field(min_length=1)
    adapter_version: str = Field(min_length=1)
    product: AdapterProduct
    case_types: dict[str, list[str]]
    definitions: list[CheckDefinition] = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_definition_graph(self) -> AdapterSettings:
        by_id = {item.id: item for item in self.definitions}
        if len(by_id) != len(self.definitions):
            raise ValueError("adapter definition IDs must be unique")
        if not self.case_types:
            raise ValueError("adapter settings require at least one case type")
        covered: set[str] = set()
        for case_type, definition_ids in self.case_types.items():
            if not case_type or not definition_ids:
                raise ValueError("case types and their definition lists must not be empty")
            if len(definition_ids) != len(set(definition_ids)):
                raise ValueError(f"adapter case type {case_type} repeats a definition")
            unknown_case_definitions = sorted(set(definition_ids) - set(by_id))
            if unknown_case_definitions:
                raise ValueError(
                    f"adapter case type {case_type} has unknown definitions: "
                    + ", ".join(unknown_case_definitions)
                )
            covered.update(definition_ids)
        if covered != set(by_id):
            raise ValueError("every adapter definition must belong to a case type")
        for case_type, definition_ids in self.case_types.items():
            selected = set(definition_ids)
            for definition_id in definition_ids:
                missing_dependencies = set(by_id[definition_id].depends_on) - selected
                if missing_dependencies:
                    raise ValueError(
                        f"adapter case type {case_type} omits dependencies for {definition_id}: "
                        + ", ".join(sorted(missing_dependencies))
                    )
        remaining = {item.id: len(item.depends_on) for item in self.definitions}
        dependents: dict[str, list[str]] = defaultdict(list)
        for item in self.definitions:
            if len(item.depends_on) != len(set(item.depends_on)):
                raise ValueError(f"adapter definition {item.id} repeats a dependency")
            unknown = sorted(set(item.depends_on) - set(by_id))
            if unknown:
                raise ValueError(
                    f"adapter definition {item.id} has unknown dependencies: " + ", ".join(unknown)
                )
            for dependency_id in item.depends_on:
                if by_id[dependency_id].stage_index >= item.stage_index:
                    raise ValueError(f"adapter dependency {dependency_id} must precede {item.id}")
                dependents[dependency_id].append(item.id)
        ready = deque(item_id for item_id, count in remaining.items() if count == 0)
        visited = 0
        while ready:
            item_id = ready.popleft()
            visited += 1
            for dependent_id in dependents[item_id]:
                remaining[dependent_id] -= 1
                if remaining[dependent_id] == 0:
                    ready.append(dependent_id)
        if visited != len(by_id):
            raise ValueError("adapter definition dependency graph contains a cycle")
        return self

    def digest(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
        return "sha256:" + hashlib.sha256(canonical).hexdigest()


class NormalizedCheck(StrictModel):
    definition_id: str = Field(min_length=1)
    status: ObservationStatus
    current_value: float | None = None
    expected_value: float | None = None
    reason_code: str = Field(min_length=1)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_value(self) -> NormalizedCheck:
        if self.status in {"PASS", "FAIL"} and self.current_value is None:
            raise ValueError("PASS and FAIL normalized checks require current_value")
        return self


class NormalizedCase(StrictModel):
    case_type: str = Field(min_length=1)
    case: CaseRef
    checks: list[NormalizedCheck] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_checks(self) -> NormalizedCase:
        ids = [item.definition_id for item in self.checks]
        if len(ids) != len(set(ids)):
            raise ValueError("normalized case contains duplicate definition IDs")
        return self


class NormalizedRun(StrictModel):
    format_version: Literal["normalized-eval-run/0.1"] = "normalized-eval-run/0.1"
    run_id: str = Field(pattern=OPAQUE_IDENTIFIER_PATTERN)
    observed_at: AwareDatetime
    product_version: str = Field(min_length=1)
    comparison: ComparisonRef
    change_manifest: ChangeManifest
    provenance: Provenance
    cases: list[NormalizedCase] = Field(min_length=1, max_length=2000)

    @field_validator("run_id")
    @classmethod
    def redact_run_identifier(cls, value: str) -> str:
        return validate_redacted_text(value)


def load_adapter_settings(path: Path) -> AdapterSettings:
    return AdapterSettings.model_validate(_load_json(path))


def load_normalized_run(path: Path) -> NormalizedRun:
    return NormalizedRun.model_validate(_load_json(path))


def _observation_id(case: CaseRef, definition_id: str) -> str:
    canonical = json.dumps(
        [
            case.case_id,
            case.use_case_id,
            case.segment,
            case.input_fingerprint,
            definition_id,
        ],
        separators=(",", ":"),
    ).encode()
    return "obs-" + hashlib.sha256(canonical).hexdigest()


def map_normalized_run(settings: AdapterSettings, run: NormalizedRun) -> RunEnvelope:
    """Map normalized facts with no product-specific code branches."""

    definitions = {item.id: item for item in settings.definitions}
    observations: list[Observation] = []
    metadata: dict[str, JsonValue] = {
        "id": settings.adapter_id,
        "version": settings.adapter_version,
        "settings_digest": settings.digest(),
    }
    for normalized_case in run.cases:
        provided = {item.definition_id: item for item in normalized_case.checks}
        selected_ids = settings.case_types.get(normalized_case.case_type)
        if selected_ids is None:
            raise ValueError(f"normalized run has unknown case type: {normalized_case.case_type}")
        unknown = sorted(set(provided) - set(selected_ids))
        if unknown:
            raise ValueError("normalized run has unknown definitions: " + ", ".join(unknown))
        for definition in (definitions[definition_id] for definition_id in selected_ids):
            check = provided.get(definition.id)
            if check is None:
                status: ObservationStatus = "BLOCKED" if definition.required else "NOT_EVALUATED"
                current_value = None
                expected_value = None
                reason_code = (
                    "ADAPTER_REQUIRED_CHECK_MISSING"
                    if definition.required
                    else "ADAPTER_OPTIONAL_CHECK_NOT_EVALUATED"
                )
                evidence_refs: list[EvidenceRef] = []
            else:
                status = check.status
                current_value = check.current_value
                expected_value = check.expected_value
                reason_code = check.reason_code
                evidence_refs = check.evidence_refs
            extensions: dict[str, JsonValue] = {"adapter": metadata}
            observations.append(
                Observation(
                    observation_id=_observation_id(normalized_case.case, definition.id),
                    case=normalized_case.case,
                    evaluation=EvaluationRef(
                        layer=definition.layer,
                        concern=definition.concern,
                        suite_id=definition.suite_id,
                        suite_version=definition.suite_version,
                        method=definition.method,
                    ),
                    location=Location(
                        component_id=definition.component_id,
                        stage_id=definition.stage_id,
                        stage_index=definition.stage_index,
                        parameter_id=definition.parameter_id,
                        owner_id=definition.owner_id,
                        fix_location=definition.fix_location,
                    ),
                    status=status,
                    current_value=current_value,
                    expected_value=expected_value,
                    current_summary=definition.current_summary_by_status[status],
                    expected_summary=definition.expected_summary,
                    threshold=definition.threshold,
                    tolerance=definition.tolerance,
                    unit=definition.unit,
                    higher_is_better=definition.higher_is_better,
                    required=definition.required,
                    reason_code=reason_code,
                    depends_on=[
                        _observation_id(normalized_case.case, dependency_id)
                        for dependency_id in definition.depends_on
                    ],
                    evidence_refs=evidence_refs,
                    cause_signals=[],
                    remediation=Remediation(action=definition.remediation),
                    extensions=extensions,
                )
            )
    if len(observations) > 2000:
        raise ValueError("mapped run exceeds the RunEnvelope observation limit")
    return RunEnvelope(
        run_id=run.run_id,
        comparison=run.comparison,
        observed_at=run.observed_at,
        product=ProductRef(
            id=settings.product.id,
            display_name=settings.product.display_name,
            version=run.product_version,
            environment=settings.product.environment,
            freshness_sla_seconds=settings.product.freshness_sla_seconds,
        ),
        change_manifest=run.change_manifest,
        provenance=run.provenance,
        observations=observations,
    )
