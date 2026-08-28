"""Explicit, loss-aware adapters for the repository's PMOS V1, V2, and V3 shapes."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class SourceFormat(StrEnum):
    PMOS_V1 = "PMOS_V1"
    PMOS_V2 = "PMOS_V2"
    PMOS_V3 = "PMOS_V3"


@dataclass(frozen=True)
class AdapterDiagnostic:
    code: str
    source_path: str
    target_path: str
    message: str
    blocking: bool = True
    source_value: Any = None
    preserves_source_value: bool = False


class AdapterConversionError(ValueError):
    def __init__(self, diagnostic: AdapterDiagnostic) -> None:
        self.diagnostic = diagnostic
        super().__init__(diagnostic.message)


@dataclass
class AdapterOutput:
    mapped_sections: dict[str, Any] = field(default_factory=dict)
    source_identity_mappings: dict[str, Any] = field(default_factory=dict)
    mapped_source_paths: set[str] = field(default_factory=set)
    diagnostics: list[AdapterDiagnostic] = field(default_factory=list)


class SourceAdapter(Protocol):
    source_format: SourceFormat
    source_version: str
    rule_version: str
    known_top_level_fields: frozenset[str]

    def adapt(self, source: dict[str, Any]) -> AdapterOutput: ...


_CANONICAL_TARGETS = {
    "acceptance_criteria": "/acceptance_criteria",
    "accessibility_requirements": "/ux/accessibility",
    "api_contracts": "/api_contracts",
    "approved_at": "/approvals",
    "approved_by": "/approvals",
    "approved_product_decisions": "/product_decisions",
    "assumptions": "/assumptions",
    "backend_capabilities": "/backend_capabilities",
    "binary_release_gates": "/quality_assurance/release_gates",
    "business_outcome": "/product/outcome/business_outcome",
    "constraints": "/technical_constraints",
    "contract_id": "/bundle_id",
    "contract_status": "/contract_status",
    "contract_version": "/provenance/source_version",
    "data_entities": "/data/entities",
    "dependencies": "/dependencies",
    "deployment_target": "/release/deployment_target",
    "desired_outcome": "/product/outcome/customer_outcome",
    "entities": "/data/entities",
    "functional_requirements": "/functional_requirements",
    "golden_cases": "/quality_assurance/golden_cases",
    "guardrails": "/guardrails",
    "hypothesis": "/product/hypothesis",
    "known_risks": "/risks",
    "leading_metrics": "/metrics/leading",
    "non_functional_requirements": "/non_functional_requirements",
    "non_goals": "/scope/non_goals",
    "north_star_metric": "/metrics/north_stars",
    "out_of_scope": "/scope/non_goals",
    "preferred_stack": "/technical_constraints",
    "primary_journey": "/ux/primary_journey",
    "priority": "/product/priority",
    "problem": "/product/problem/statement",
    "problem_statement": "/product/problem/statement",
    "product_name": "/product/product_name",
    "required_approvals": "/required_approvals",
    "responsive_requirements": "/ux/responsive_requirements",
    "risks": "/risks",
    "scope": "/scope/in_scope",
    "scored_eval_rubric": "/quality_assurance/evaluation_rubrics",
    "screens": "/ux/screens",
    "source_digest": "/provenance/source_digest",
    "spec_version": "/provenance/source_version",
    "success_metrics": "/metrics/success",
    "target_platform": "/product/target_platform",
    "target_user": "/product/target_customers",
    "ui_states": "/ux/ui_states",
    "unresolved_questions": "/open_questions",
    "user_outcome": "/product/outcome/customer_outcome",
    "user_stories": "/ux/user_stories",
}


def _safe_id(prefix: str, source_id: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]+", "-", source_id.upper()).strip("-")
    if not normalized:
        raise AdapterConversionError(
            AdapterDiagnostic(
                code="SOURCE_ID_INVALID",
                source_path="",
                target_path="",
                message="source identifier cannot produce a stable canonical identifier",
            )
        )
    return f"{prefix}-{normalized}"


def _insert_identity(
    target: dict[str, Any],
    canonical_id: str,
    value: dict[str, Any],
    *,
    source_path: str,
) -> None:
    if canonical_id in target:
        raise AdapterConversionError(
            AdapterDiagnostic(
                code="SOURCE_ID_COLLISION",
                source_path=source_path,
                target_path=f"/{canonical_id}",
                message="multiple source identifiers map to one canonical identifier",
            )
        )
    target[canonical_id] = value


def _preserve_unmapped(
    source: dict[str, Any],
    output: AdapterOutput,
) -> None:
    for key in sorted(source):
        pointer = f"/{key}"
        if pointer in output.mapped_source_paths:
            continue
        output.diagnostics.append(
            AdapterDiagnostic(
                code="SOURCE_FIELD_UNMAPPED",
                source_path=pointer,
                target_path=_CANONICAL_TARGETS.get(key, ""),
                message="supplied source truth has no exact mapping in the canonical core",
                source_value=source[key],
                preserves_source_value=True,
            )
        )


class V1Adapter:
    source_format = SourceFormat.PMOS_V1
    source_version = "1.0"
    rule_version = "PMOS-V1-1.0-TO-CANONICAL-1.0.0"
    known_top_level_fields = frozenset(
        {
            "spec_version",
            "product_name",
            "problem_statement",
            "target_user",
            "user_outcome",
            "business_outcome",
            "hypothesis",
            "scope",
            "non_goals",
            "user_stories",
            "acceptance_criteria",
            "functional_requirements",
            "entities",
            "non_functional_requirements",
            "success_metrics",
            "north_star_metric",
            "leading_metrics",
            "guardrails",
            "constraints",
            "assumptions",
            "dependencies",
            "risks",
            "priority",
            "target_platform",
            "preferred_stack",
            "deployment_target",
        }
    )

    def adapt(self, source: dict[str, Any]) -> AdapterOutput:
        output = AdapterOutput()
        output.mapped_sections["scope"] = {
            "in_scope": list(source["scope"]),
            "non_goals": list(source["non_goals"]),
        }
        output.mapped_source_paths.update({"/scope", "/non_goals", "/spec_version"})
        _preserve_unmapped(source, output)
        return output


class V2Adapter:
    source_format = SourceFormat.PMOS_V2
    source_version = "1"
    rule_version = "PMOS-V2-1-TO-CANONICAL-1.0.0"
    known_top_level_fields = frozenset(
        {
            "contract_version",
            "contract_id",
            "contract_status",
            "approved_at",
            "approved_by",
            "source_digest",
            "product_name",
            "problem",
            "target_user",
            "desired_outcome",
            "scope",
            "out_of_scope",
            "functional_requirements",
            "acceptance_criteria",
            "binary_release_gates",
            "scored_eval_rubric",
            "golden_cases",
            "north_star_metric",
            "leading_metrics",
            "guardrails",
            "non_functional_requirements",
            "known_risks",
            "approved_product_decisions",
            "unresolved_questions",
            "required_approvals",
        }
    )

    def adapt(self, source: dict[str, Any]) -> AdapterOutput:
        output = AdapterOutput()
        output.mapped_sections["scope"] = {
            "in_scope": list(source["scope"]),
            "non_goals": list(source["out_of_scope"]),
        }
        output.mapped_source_paths.update(
            {"/scope", "/out_of_scope", "/contract_id", "/contract_version"}
        )
        output.source_identity_mappings["SOURCE-MAP-CONTRACT"] = {
            "canonical_pointer": "/bundle_id",
            "source_id": source["contract_id"],
            "source_pointer": "/contract_id",
            "source_version": source["contract_version"],
        }
        approvals: dict[str, Any] = {}
        for index, item in enumerate(source["required_approvals"], start=1):
            approvals[f"APPROVAL-REQ-{index:03d}"] = {
                "purpose": item["for"],
                "role": item["role"],
            }
        output.mapped_sections["required_approvals"] = approvals
        output.mapped_source_paths.add("/required_approvals")
        _preserve_unmapped(source, output)
        return output


class V3Adapter:
    source_format = SourceFormat.PMOS_V3
    source_version = "1"
    rule_version = "PMOS-V3-1-TO-CANONICAL-1.0.0"
    known_top_level_fields = frozenset(
        {
            "contract_version",
            "contract_id",
            "contract_status",
            "approved_at",
            "approved_by",
            "product_name",
            "problem",
            "target_user",
            "primary_journey",
            "screens",
            "ui_states",
            "backend_capabilities",
            "data_entities",
            "api_contracts",
            "accessibility_requirements",
            "responsive_requirements",
            "binary_release_gates",
            "guardrails",
            "deployment_target",
            "out_of_scope",
            "unresolved_questions",
            "required_approvals",
        }
    )

    def adapt(self, source: dict[str, Any]) -> AdapterOutput:
        output = AdapterOutput()
        output.mapped_source_paths.update({"/contract_id", "/contract_version"})
        output.source_identity_mappings["SOURCE-MAP-CONTRACT"] = {
            "canonical_pointer": "/bundle_id",
            "source_id": source["contract_id"],
            "source_pointer": "/contract_id",
            "source_version": source["contract_version"],
        }
        capabilities: dict[str, Any] = {}
        for index, item in enumerate(source["backend_capabilities"]):
            canonical_id = _safe_id("CAPABILITY", item["capability_id"])
            _insert_identity(
                capabilities,
                canonical_id,
                {"description": item["description"]},
                source_path=f"/backend_capabilities/{index}/capability_id",
            )
            output.source_identity_mappings[f"SOURCE-MAP-{canonical_id}"] = {
                "canonical_pointer": f"/backend_capabilities/{canonical_id}",
                "source_id": item["capability_id"],
                "source_pointer": f"/backend_capabilities/{index}",
            }
        output.mapped_sections["backend_capabilities"] = capabilities
        output.mapped_source_paths.add("/backend_capabilities")
        apis: dict[str, Any] = {}
        for index, item in enumerate(source["api_contracts"]):
            normalized_source_id = item["api_id"]
            if normalized_source_id.upper().startswith("API-"):
                normalized_source_id = normalized_source_id[4:]
            canonical_id = _safe_id("API", normalized_source_id)
            _insert_identity(
                apis,
                canonical_id,
                {
                    "method": item["method"],
                    "path": item["path"],
                    "purpose": item["purpose"],
                },
                source_path=f"/api_contracts/{index}/api_id",
            )
            output.source_identity_mappings[f"SOURCE-MAP-{canonical_id}"] = {
                "canonical_pointer": f"/api_contracts/{canonical_id}",
                "source_id": item["api_id"],
                "source_pointer": f"/api_contracts/{index}",
            }
        output.mapped_sections["api_contracts"] = apis
        output.mapped_source_paths.add("/api_contracts")
        _preserve_unmapped(source, output)
        return output


class AdapterRegistry:
    def __init__(self, adapters: tuple[SourceAdapter, ...] | None = None) -> None:
        registered = adapters or (V1Adapter(), V2Adapter(), V3Adapter())
        self._adapters = {
            (adapter.source_format, adapter.source_version): adapter for adapter in registered
        }

    def get(self, source_format: SourceFormat, source_version: str) -> SourceAdapter | None:
        return self._adapters.get((source_format, source_version))
