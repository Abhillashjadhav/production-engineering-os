"""Deterministic admission compiler for repository-grounded architecture proposals."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any, Protocol

from jsonschema import Draft202012Validator

from pmpe.config import packaged_schema_dir
from pmpe.contracts.canonical import canonical_digest, canonical_json_bytes
from pmpe.repository.models import GovernanceObservation, RepositorySnapshot

from .models import (
    ARCHITECTURE_PLANES,
    ArchitectureCompilationResult,
    ArchitectureDiagnostic,
    ArchitectureDisposition,
    ArchitecturePack,
)

ARCHITECTURE_COMPILER_VERSION = "1.0.0"
_DECISION_CLASSES_REQUIRING_APPROVAL = frozenset(
    {
        "DATA_RETENTION",
        "IRREVERSIBLE",
        "PRODUCTION_INFRASTRUCTURE",
        "SECURITY_POLICY",
        "USER_VISIBLE",
        "VENDOR_LOCKING",
    }
)
_LIST_SECTIONS = (
    "components",
    "data_architecture",
    "api_architecture",
    "integration_architecture",
    "security_boundaries",
    "data_flows",
    "adrs",
    "approval_requests",
)


class ContractAdmission(Protocol):
    bundle_digest: str

    @property
    def engineering_admissible(self) -> bool: ...


class ArchitectureApprovalVerifier(Protocol):
    """External trust-root interface; the compiler can verify but cannot issue approval."""

    def verify(
        self,
        *,
        approval_ref: str,
        adr: Mapping[str, Any],
        contract_digest: str,
        repository_snapshot_digest: str,
    ) -> bool: ...


def _diagnostic(
    rule_id: str,
    disposition: ArchitectureDisposition,
    field_path: str,
    owner: str,
    explanation: str,
    next_action: str,
) -> ArchitectureDiagnostic:
    return ArchitectureDiagnostic(
        rule_id=rule_id,
        disposition=disposition,
        field_path=field_path,
        owner=owner,
        explanation=explanation,
        next_action=next_action,
    )


def _error(
    rule_id: str,
    field_path: str,
    explanation: str,
    next_action: str,
    *,
    owner: str = "ENGINEERING",
) -> ArchitectureDiagnostic:
    return _diagnostic(
        rule_id,
        ArchitectureDisposition.ERROR,
        field_path,
        owner,
        explanation,
        next_action,
    )


def _ids(value: Any) -> set[str]:
    return {str(key) for key in value} if isinstance(value, Mapping) else set()


def _nested_ids(bundle: Mapping[str, Any], *path: str) -> set[str]:
    value: Any = bundle
    for part in path:
        if not isinstance(value, Mapping):
            return set()
        value = value.get(part, {})
    return _ids(value)


def _architecture_references(bundle: Mapping[str, Any]) -> dict[str, set[str]]:
    requirements = (
        _ids(bundle.get("functional_requirements", {}))
        | _ids(bundle.get("non_functional_requirements", {}))
        | _nested_ids(bundle, "security", "requirements")
        | _nested_ids(bundle, "privacy", "requirements")
    )
    security_privacy = _nested_ids(bundle, "security", "requirements") | _nested_ids(
        bundle, "privacy", "requirements"
    )
    return {
        "requirements": requirements,
        "security_privacy": security_privacy,
        "data": _nested_ids(bundle, "data", "entities")
        | _nested_ids(bundle, "data", "requirements"),
        "apis": _ids(bundle.get("api_contracts", {})),
        "integrations": _ids(bundle.get("integrations", {})),
        "observability": _nested_ids(bundle, "observability", "requirements"),
        "rollback": _nested_ids(bundle, "rollback", "requirements"),
        "release": _nested_ids(bundle, "release", "expectations"),
    }


def _sort_strings(value: Any) -> Any:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return sorted(value)
    if isinstance(value, list):
        normalized = [_sort_strings(item) for item in value]
        if all(isinstance(item, Mapping) and "id" in item for item in normalized):
            return sorted(normalized, key=lambda item: str(item["id"]))
        if all(isinstance(item, Mapping) and "option" in item for item in normalized):
            return sorted(normalized, key=lambda item: str(item["option"]))
        return normalized
    if isinstance(value, Mapping):
        return {str(key): _sort_strings(child) for key, child in value.items()}
    return value


def _valid_boundary_path(path: str) -> bool:
    candidate = PurePosixPath(path)
    return bool(path) and not candidate.is_absolute() and ".." not in candidate.parts


def _item_ids(items: Any) -> set[str]:
    if not isinstance(items, list):
        return set()
    return {
        str(item.get("id", "")) for item in items if isinstance(item, Mapping) and item.get("id")
    }


def _duplicates(items: Any) -> set[str]:
    if not isinstance(items, list):
        return set()
    seen: set[str] = set()
    repeated: set[str] = set()
    for item in items:
        identifier = str(item.get("id", "")) if isinstance(item, Mapping) else ""
        if identifier in seen:
            repeated.add(identifier)
        seen.add(identifier)
    return repeated


def _append_once(
    diagnostics: list[ArchitectureDiagnostic], diagnostic: ArchitectureDiagnostic
) -> None:
    identity = (diagnostic.rule_id, diagnostic.field_path, diagnostic.explanation)
    if not any(
        (item.rule_id, item.field_path, item.explanation) == identity for item in diagnostics
    ):
        diagnostics.append(diagnostic)


class ArchitectureCompiler:
    """Compile an explicit proposal against immutable admitted inputs.

    This compiler normalizes and admits architecture; it intentionally does not
    invent choices. Choices that are irreversible or product/infra/security-owned
    remain visible in a digest-bound blocked pack until externally verified.
    """

    def __init__(self, approval_verifier: ArchitectureApprovalVerifier | None = None) -> None:
        schema = json.loads((packaged_schema_dir() / "architecture_pack.schema.json").read_text())
        self._schema = Draft202012Validator(schema)
        self._approval_verifier = approval_verifier

    def compile(
        self,
        contract_bundle: Mapping[str, Any],
        contract_validation: ContractAdmission,
        repository_snapshot: RepositorySnapshot,
        governance_observation: GovernanceObservation,
        proposal: Mapping[str, Any],
    ) -> ArchitectureCompilationResult:
        diagnostics: list[ArchitectureDiagnostic] = []
        try:
            contract_bytes = canonical_json_bytes(contract_bundle)
            contract = json.loads(contract_bytes)
            proposed = json.loads(canonical_json_bytes(proposal))
            contract_digest = canonical_digest(contract)
            proposal_digest = canonical_digest(proposed)
        except Exception:
            diagnostic = _error(
                "ARCH.INPUT.CANONICAL",
                "/",
                "Architecture inputs are outside the canonical JSON domain.",
                "Provide finite, interoperable JSON values and rerun compilation.",
            )
            return ArchitectureCompilationResult(
                compiler_version=ARCHITECTURE_COMPILER_VERSION,
                disposition=ArchitectureDisposition.ERROR,
                input_digest=canonical_digest({"input": "NON_CANONICAL"}),
                diagnostics=(diagnostic,),
                pack=None,
            )

        input_digest = canonical_digest(
            {
                "contract_digest": contract_digest,
                "governance_observation_digest": getattr(
                    governance_observation, "observation_output_digest", ""
                ),
                "proposal_digest": proposal_digest,
                "repository_snapshot_digest": getattr(repository_snapshot, "snapshot_digest", ""),
            }
        )
        self._validate_inputs(
            contract_digest,
            contract_validation,
            repository_snapshot,
            governance_observation,
            proposed,
            diagnostics,
        )
        if diagnostics:
            return self._result(input_digest, diagnostics, None)

        normalized = _sort_strings(copy.deepcopy(proposed))
        normalized["artifact_kind"] = "ARCHITECTURE_PACK"
        normalized["compiler_version"] = ARCHITECTURE_COMPILER_VERSION
        normalized.setdefault("approval_requests", [])
        normalized["disposition"] = ArchitectureDisposition.ADMITTED.value
        normalized["pack_digest"] = "sha256:" + "0" * 64

        self._validate_structure(normalized, diagnostics)
        if any(item.disposition is ArchitectureDisposition.ERROR for item in diagnostics):
            return self._result(input_digest, diagnostics, None)

        references = _architecture_references(contract)
        observed_boundaries = {
            path
            for candidate in repository_snapshot.boundary_candidates
            for path in candidate.evidence_paths
        }
        self._validate_identifiers(normalized, diagnostics)
        self._validate_references(normalized, references, observed_boundaries, diagnostics)
        self._validate_architecture_links(normalized, references, diagnostics)
        self._validate_planes_and_complexity(normalized, diagnostics)
        self._validate_adrs(normalized, diagnostics)
        self._validate_contract_coverage(normalized, references, diagnostics)
        self._validate_security(normalized, diagnostics)
        self._validate_approval_boundaries(
            normalized,
            contract_digest,
            repository_snapshot.snapshot_digest,
            diagnostics,
        )
        if any(item.disposition is ArchitectureDisposition.ERROR for item in diagnostics):
            return self._result(input_digest, diagnostics, None)

        disposition = (
            ArchitectureDisposition.PRODUCT_INPUT_REQUIRED
            if diagnostics
            else ArchitectureDisposition.ADMITTED
        )
        normalized["disposition"] = disposition.value
        normalized["approval_requests"] = sorted(
            normalized["approval_requests"], key=lambda item: str(item["id"])
        )
        normalized["pack_digest"] = canonical_digest(
            {key: value for key, value in normalized.items() if key != "pack_digest"}
        )
        final_schema_errors = sorted(
            self._schema.iter_errors(normalized), key=lambda error: list(error.absolute_path)
        )
        if final_schema_errors:
            for error in final_schema_errors:
                path = "/" + "/".join(str(part) for part in error.absolute_path)
                _append_once(
                    diagnostics,
                    _error(
                        "ARCH.STRUCTURE",
                        path,
                        f"ArchitecturePack violates its versioned schema: {error.message}",
                        "Correct the proposed architecture field and rerun compilation.",
                    ),
                )
            return self._result(input_digest, diagnostics, None)
        return self._result(
            input_digest,
            diagnostics,
            ArchitecturePack.from_dict(normalized),
            disposition=disposition,
        )

    def _result(
        self,
        input_digest: str,
        diagnostics: Sequence[ArchitectureDiagnostic],
        pack: ArchitecturePack | None,
        *,
        disposition: ArchitectureDisposition | None = None,
    ) -> ArchitectureCompilationResult:
        ordered = tuple(
            sorted(diagnostics, key=lambda item: (item.rule_id, item.field_path, item.explanation))
        )
        actual_disposition = disposition or (
            ArchitectureDisposition.ERROR
            if any(item.disposition is ArchitectureDisposition.ERROR for item in ordered)
            else ArchitectureDisposition.PRODUCT_INPUT_REQUIRED
        )
        return ArchitectureCompilationResult(
            compiler_version=ARCHITECTURE_COMPILER_VERSION,
            disposition=actual_disposition,
            input_digest=input_digest,
            diagnostics=ordered,
            pack=pack,
        )

    def _validate_inputs(
        self,
        contract_digest: str,
        validation: ContractAdmission,
        snapshot: RepositorySnapshot,
        governance: GovernanceObservation,
        proposal: Mapping[str, Any],
        diagnostics: list[ArchitectureDiagnostic],
    ) -> None:
        if getattr(validation, "bundle_digest", None) != contract_digest or not getattr(
            validation, "engineering_admissible", False
        ):
            diagnostics.append(
                _error(
                    "ARCH.INPUT.CONTRACT",
                    "/contract_digest",
                    "The contract does not match an engineering-admissible validation result.",
                    "Admit the exact canonical contract before compiling architecture.",
                    owner="PRODUCT",
                )
            )
        if type(snapshot) is not RepositorySnapshot:
            diagnostics.append(
                _error(
                    "ARCH.INPUT.REPOSITORY",
                    "/repository_snapshot_digest",
                    "Repository input is not a canonical RepositorySnapshot.",
                    "Run deterministic repository intelligence for the exact target commit.",
                )
            )
            return
        if type(governance) is not GovernanceObservation:
            diagnostics.append(
                _error(
                    "ARCH.INPUT.GOVERNANCE",
                    "/governance_observation_digest",
                    "Governance input is not a canonical GovernanceObservation.",
                    "Collect a current governance observation bound to the repository snapshot.",
                )
            )
            return
        try:
            snapshot.assessment_reference(governance)
        except (TypeError, ValueError) as exc:
            diagnostics.append(
                _error(
                    "ARCH.INPUT.REPOSITORY",
                    "/repository_snapshot_digest",
                    f"Repository/governance evidence is not admissible: {exc}",
                    "Supply complete, digest-valid, mutually bound repository evidence.",
                )
            )
        expected = {
            "contract_digest": contract_digest,
            "governance_observation_digest": governance.observation_output_digest,
            "repository_commit": snapshot.commit_sha,
            "repository_snapshot_digest": snapshot.snapshot_digest,
        }
        for key, value in expected.items():
            if proposal.get(key) != value:
                diagnostics.append(
                    _error(
                        "ARCH.INPUT.BINDING",
                        f"/{key}",
                        f"Architecture proposal {key} does not bind the admitted input.",
                        "Regenerate the proposal from the exact admitted contract and snapshot.",
                    )
                )

    def _validate_structure(
        self, pack: Mapping[str, Any], diagnostics: list[ArchitectureDiagnostic]
    ) -> None:
        if not pack.get("adrs"):
            diagnostics.append(
                _error(
                    "ARCH.ADR.REQUIRED",
                    "/adrs",
                    "ArchitecturePack has no ADRs.",
                    "Record at least one decision with alternatives, trade-offs, and impact.",
                )
            )
        threats = pack.get("threat_model", {})
        if not isinstance(threats, Mapping) or not threats.get("threats"):
            diagnostics.append(
                _error(
                    "ARCH.THREAT.GAP",
                    "/threat_model/threats",
                    "The threat model contains no threats.",
                    "Identify threats, mitigations, residual risk, and owners for each boundary.",
                    owner="SECURITY",
                )
            )
        for flow in pack.get("data_flows", []):
            if isinstance(flow, Mapping) and not flow.get("threat_refs"):
                diagnostics.append(
                    _error(
                        "ARCH.SECURITY.BOUNDARY",
                        f"/data_flows/{flow.get('id', '?')}/threat_refs",
                        "Cross-boundary data flow has no linked threat analysis.",
                        "Link the flow to a mitigation-bearing threat for every boundary.",
                        owner="SECURITY",
                    )
                )
        for error in sorted(
            self._schema.iter_errors(pack), key=lambda item: list(item.absolute_path)
        ):
            path = "/" + "/".join(str(part) for part in error.absolute_path)
            _append_once(
                diagnostics,
                _error(
                    "ARCH.STRUCTURE",
                    path,
                    f"Architecture proposal violates schema 1.0.0: {error.message}",
                    "Correct the proposed architecture field and rerun compilation.",
                ),
            )

    def _validate_identifiers(
        self, pack: Mapping[str, Any], diagnostics: list[ArchitectureDiagnostic]
    ) -> None:
        for section in _LIST_SECTIONS:
            for identifier in sorted(_duplicates(pack.get(section))):
                diagnostics.append(
                    _error(
                        "ARCH.ID.DUPLICATE",
                        f"/{section}/{identifier}",
                        f"Duplicate identifier '{identifier}' appears in {section}.",
                        "Assign stable unique identifiers within every architecture collection.",
                    )
                )
        threat_model = pack.get("threat_model", {})
        threats = threat_model.get("threats", []) if isinstance(threat_model, Mapping) else []
        for identifier in sorted(_duplicates(threats)):
            diagnostics.append(
                _error(
                    "ARCH.ID.DUPLICATE",
                    f"/threat_model/threats/{identifier}",
                    f"Duplicate threat identifier '{identifier}'.",
                    "Assign a stable unique identifier to every threat.",
                    owner="SECURITY",
                )
            )

    def _validate_references(
        self,
        pack: Mapping[str, Any],
        references: Mapping[str, set[str]],
        observed_boundaries: set[str],
        diagnostics: list[ArchitectureDiagnostic],
    ) -> None:
        traceable: list[tuple[str, Mapping[str, Any]]] = []
        for section in (
            "components",
            "data_architecture",
            "api_architecture",
            "integration_architecture",
            "security_boundaries",
            "data_flows",
            "adrs",
        ):
            for item in pack.get(section, []):
                if isinstance(item, Mapping):
                    traceable.append((section, item))
        for section in ("deployment", "observability", "rollback"):
            item = pack.get(section)
            if isinstance(item, Mapping):
                traceable.append((section, item))
        threat_model = pack.get("threat_model", {})
        for item in threat_model.get("threats", []) if isinstance(threat_model, Mapping) else []:
            if isinstance(item, Mapping):
                traceable.append(("threat_model/threats", item))
        for section, item in traceable:
            identifier = str(item.get("id", section))
            unknown_requirements = set(item.get("requirement_ids", [])) - references["requirements"]
            if unknown_requirements:
                diagnostics.append(
                    _error(
                        "ARCH.REFERENCE.REQUIREMENT",
                        f"/{section}/{identifier}/requirement_ids",
                        "Unknown requirement reference(s): "
                        + ", ".join(sorted(unknown_requirements)),
                        "Link the architecture element only to canonical contract requirements.",
                        owner="PRODUCT",
                    )
                )
            boundaries = set(item.get("repository_boundaries", []))
            invalid_paths = {path for path in boundaries if not _valid_boundary_path(str(path))}
            unknown_boundaries = boundaries - observed_boundaries
            if invalid_paths or unknown_boundaries:
                diagnostics.append(
                    _error(
                        "ARCH.REFERENCE.BOUNDARY",
                        f"/{section}/{identifier}/repository_boundaries",
                        "Repository boundary is unsafe or absent from exact-SHA evidence: "
                        + ", ".join(
                            sorted(str(item) for item in invalid_paths | unknown_boundaries)
                        ),
                        "Use a boundary evidenced by the admitted RepositorySnapshot.",
                    )
                )
        self._check_named_refs(
            pack, "data_architecture", "data_refs", references["data"], diagnostics
        )
        self._check_named_refs(
            pack, "api_architecture", "api_refs", references["apis"], diagnostics
        )
        self._check_named_refs(
            pack, "deployment", "release_refs", references["release"], diagnostics
        )
        self._check_named_refs(
            pack,
            "integration_architecture",
            "integration_refs",
            references["integrations"],
            diagnostics,
        )
        self._check_named_refs(
            pack,
            "observability",
            "observability_refs",
            references["observability"],
            diagnostics,
        )
        self._check_named_refs(
            pack, "rollback", "rollback_refs", references["rollback"], diagnostics
        )

    def _validate_architecture_links(
        self,
        pack: Mapping[str, Any],
        references: Mapping[str, set[str]],
        diagnostics: list[ArchitectureDiagnostic],
    ) -> None:
        component_ids = _item_ids(pack.get("components"))
        for section in (
            "data_architecture",
            "api_architecture",
            "integration_architecture",
        ):
            for item in pack.get(section, []):
                if not isinstance(item, Mapping):
                    continue
                unknown = set(item.get("component_ids", [])) - component_ids
                if unknown:
                    diagnostics.append(
                        _error(
                            "ARCH.REFERENCE.COMPONENT",
                            f"/{section}/{item.get('id', '?')}/component_ids",
                            "Unknown component reference(s): " + ", ".join(sorted(unknown)),
                            "Link the architecture mapping to admitted components.",
                        )
                    )
        for section in ("security_boundaries", "data_flows"):
            for item in pack.get(section, []):
                if not isinstance(item, Mapping):
                    continue
                unknown_data = set(item.get("data_refs", [])) - references["data"]
                if unknown_data:
                    diagnostics.append(
                        _error(
                            "ARCH.REFERENCE.CONTRACT",
                            f"/{section}/{item.get('id', '?')}/data_refs",
                            "Unknown data reference(s): " + ", ".join(sorted(unknown_data)),
                            "Reference only canonical contract data members.",
                            owner="PRODUCT",
                        )
                    )

    def _check_named_refs(
        self,
        pack: Mapping[str, Any],
        section: str,
        key: str,
        allowed: set[str],
        diagnostics: list[ArchitectureDiagnostic],
    ) -> None:
        raw = pack.get(section, [])
        items = raw if isinstance(raw, list) else [raw]
        for item in items:
            if not isinstance(item, Mapping):
                continue
            unknown = set(item.get(key, [])) - allowed
            if unknown:
                identifier = str(item.get("id", section))
                diagnostics.append(
                    _error(
                        "ARCH.REFERENCE.CONTRACT",
                        f"/{section}/{identifier}/{key}",
                        "Unknown contract reference(s): " + ", ".join(sorted(unknown)),
                        "Reference only canonical contract members.",
                        owner="PRODUCT",
                    )
                )

    def _validate_planes_and_complexity(
        self, pack: Mapping[str, Any], diagnostics: list[ArchitectureDiagnostic]
    ) -> None:
        components = pack.get("components", [])
        actual_planes = {
            str(item.get("plane", "")) for item in components if isinstance(item, Mapping)
        }
        missing = set(ARCHITECTURE_PLANES) - actual_planes
        if missing:
            diagnostics.append(
                _error(
                    "ARCH.PLANE.COVERAGE",
                    "/components",
                    "ArchitecturePack omits required plane(s): " + ", ".join(sorted(missing)),
                    "Add a requirement-linked component for each required architecture plane.",
                )
            )
        signatures: dict[tuple[Any, ...], str] = {}
        for item in components:
            if not isinstance(item, Mapping):
                continue
            signature = (
                item.get("plane"),
                tuple(item.get("requirement_ids", [])),
                tuple(item.get("repository_boundaries", [])),
                tuple(item.get("responsibilities", [])),
            )
            if signature in signatures:
                diagnostics.append(
                    _error(
                        "ARCH.UNNECESSARY_COMPLEXITY",
                        f"/components/{item.get('id', '?')}",
                        "Component duplicates the responsibility and impact of "
                        f"{signatures[signature]}.",
                        "Remove the redundant component or provide distinct "
                        "requirement-backed scope.",
                    )
                )
            signatures[signature] = str(item.get("id", "?"))

    def _validate_adrs(
        self, pack: Mapping[str, Any], diagnostics: list[ArchitectureDiagnostic]
    ) -> None:
        for adr in pack.get("adrs", []):
            if not isinstance(adr, Mapping):
                continue
            alternatives = adr.get("alternatives", [])
            outcomes = [
                str(item.get("outcome", "")) for item in alternatives if isinstance(item, Mapping)
            ]
            options = [
                str(item.get("option", "")) for item in alternatives if isinstance(item, Mapping)
            ]
            if outcomes.count("SELECTED") != 1 or "REJECTED" not in outcomes:
                diagnostics.append(
                    _error(
                        "ARCH.ADR.ALTERNATIVES",
                        f"/adrs/{adr.get('id', '?')}/alternatives",
                        "ADR must identify exactly one selected and at least one rejected option.",
                        "Record considered alternatives and their explicit trade-offs.",
                    )
                )
            if len(options) != len(set(options)):
                diagnostics.append(
                    _error(
                        "ARCH.ADR.ALTERNATIVES",
                        f"/adrs/{adr.get('id', '?')}/alternatives",
                        "ADR repeats the same option as multiple alternatives.",
                        "Collapse duplicate options into one trade-off analysis.",
                    )
                )

    def _validate_contract_coverage(
        self,
        pack: Mapping[str, Any],
        references: Mapping[str, set[str]],
        diagnostics: list[ArchitectureDiagnostic],
    ) -> None:
        coverage = (
            ("data_architecture", "data_refs", "data"),
            ("api_architecture", "api_refs", "apis"),
            ("integration_architecture", "integration_refs", "integrations"),
            ("deployment", "release_refs", "release"),
            ("observability", "observability_refs", "observability"),
            ("rollback", "rollback_refs", "rollback"),
        )
        for section, field, reference_type in coverage:
            raw = pack.get(section, [])
            items = raw if isinstance(raw, list) else [raw]
            covered = {
                str(ref)
                for item in items
                if isinstance(item, Mapping)
                for ref in item.get(field, [])
            }
            missing = references[reference_type] - covered
            if missing:
                diagnostics.append(
                    _error(
                        "ARCH.CONTRACT.COVERAGE",
                        f"/{section}",
                        f"Architecture omits contract {reference_type}: "
                        + ", ".join(sorted(missing)),
                        "Map every applicable contract member to components and repository impact.",
                        owner="PRODUCT",
                    )
                )
        threats = pack.get("threat_model", {}).get("threats", [])
        covered_security = {
            str(requirement)
            for threat in threats
            if isinstance(threat, Mapping)
            for requirement in threat.get("requirement_ids", [])
        }
        missing_security = references["security_privacy"] - covered_security
        if missing_security:
            diagnostics.append(
                _error(
                    "ARCH.THREAT.CONTRACT_COVERAGE",
                    "/threat_model/threats",
                    "Threat model omits security/privacy requirement(s): "
                    + ", ".join(sorted(missing_security)),
                    "Link contract security and privacy requirements to owned threats.",
                    owner="SECURITY",
                )
            )

    def _validate_security(
        self, pack: Mapping[str, Any], diagnostics: list[ArchitectureDiagnostic]
    ) -> None:
        component_ids = _item_ids(pack.get("components"))
        boundary_ids = _item_ids(pack.get("security_boundaries"))
        threats = pack.get("threat_model", {}).get("threats", [])
        threat_ids = _item_ids(threats)
        threat_boundaries = {
            str(boundary)
            for threat in threats
            if isinstance(threat, Mapping)
            for boundary in threat.get("trust_boundary_refs", [])
        }
        for boundary in pack.get("security_boundaries", []):
            if not isinstance(boundary, Mapping):
                continue
            endpoints = set(boundary.get("source_component_ids", [])) | set(
                boundary.get("target_component_ids", [])
            )
            unknown = endpoints - component_ids
            if unknown:
                diagnostics.append(
                    _error(
                        "ARCH.SECURITY.BOUNDARY",
                        f"/security_boundaries/{boundary.get('id', '?')}",
                        "Trust boundary references unknown component(s): "
                        + ", ".join(sorted(unknown)),
                        "Bind every trust-boundary endpoint to an admitted component.",
                        owner="SECURITY",
                    )
                )
            if set(boundary.get("source_component_ids", [])) & set(
                boundary.get("target_component_ids", [])
            ):
                diagnostics.append(
                    _error(
                        "ARCH.SECURITY.BOUNDARY",
                        f"/security_boundaries/{boundary.get('id', '?')}",
                        "Trust boundary places a component on both sides of the boundary.",
                        "Define distinct source and target trust zones.",
                        owner="SECURITY",
                    )
                )
            if str(boundary.get("id", "")) not in threat_boundaries:
                diagnostics.append(
                    _error(
                        "ARCH.THREAT.GAP",
                        f"/security_boundaries/{boundary.get('id', '?')}",
                        "Trust boundary has no linked threat analysis.",
                        "Add a threat with mitigation, residual risk, and named owner.",
                        owner="SECURITY",
                    )
                )
        declared_model_boundaries = set(pack.get("threat_model", {}).get("trust_boundary_refs", []))
        if declared_model_boundaries != boundary_ids:
            diagnostics.append(
                _error(
                    "ARCH.THREAT.GAP",
                    "/threat_model/trust_boundary_refs",
                    "Threat model boundary inventory does not exactly match "
                    "architecture boundaries.",
                    "Threat-model every declared boundary and remove unknown references.",
                    owner="SECURITY",
                )
            )
        for flow in pack.get("data_flows", []):
            if not isinstance(flow, Mapping):
                continue
            flow_boundaries = set(flow.get("trust_boundary_refs", []))
            flow_threats = set(flow.get("threat_refs", []))
            endpoints = {
                str(flow.get("source_component_id", "")),
                str(flow.get("target_component_id", "")),
            }
            if (
                endpoints - component_ids
                or flow_boundaries - boundary_ids
                or not flow_boundaries
                or not flow_threats
                or flow_threats - threat_ids
            ):
                diagnostics.append(
                    _error(
                        "ARCH.SECURITY.BOUNDARY",
                        f"/data_flows/{flow.get('id', '?')}",
                        "Cross-boundary data flow lacks valid components, boundary, "
                        "or threat links.",
                        "Link the flow to admitted endpoints and its mitigating threat analysis.",
                        owner="SECURITY",
                    )
                )
                continue
            covered = {
                str(boundary)
                for threat in threats
                if isinstance(threat, Mapping) and threat.get("id") in flow_threats
                for boundary in threat.get("trust_boundary_refs", [])
            }
            if not flow_boundaries <= covered:
                diagnostics.append(
                    _error(
                        "ARCH.SECURITY.BOUNDARY",
                        f"/data_flows/{flow.get('id', '?')}/threat_refs",
                        "The linked threats do not cover every boundary crossed by this flow.",
                        "Link a mitigation-bearing threat for each crossed trust boundary.",
                        owner="SECURITY",
                    )
                )

    def _validate_approval_boundaries(
        self,
        pack: dict[str, Any],
        contract_digest: str,
        snapshot_digest: str,
        diagnostics: list[ArchitectureDiagnostic],
    ) -> None:
        requests_by_decision = {
            str(item.get("decision_ref")): item
            for item in pack.get("approval_requests", [])
            if isinstance(item, Mapping)
        }
        for adr in pack.get("adrs", []):
            if not isinstance(adr, Mapping):
                continue
            decision_classes = set(adr.get("decision_classes", []))
            reversibility = str(adr.get("reversibility", ""))
            requires_approval = reversibility != "REVERSIBLE" or bool(
                decision_classes & _DECISION_CLASSES_REQUIRING_APPROVAL
            )
            if not requires_approval:
                continue
            approval_refs = [str(item) for item in adr.get("approval_refs", [])]
            verifier = self._approval_verifier
            verified = bool(approval_refs) and verifier is not None
            if approval_refs and verifier is not None:
                try:
                    verified = all(
                        verifier.verify(
                            approval_ref=approval_ref,
                            adr=copy.deepcopy(dict(adr)),
                            contract_digest=contract_digest,
                            repository_snapshot_digest=snapshot_digest,
                        )
                        for approval_ref in approval_refs
                    )
                except Exception:
                    verified = False
            if verified:
                continue
            adr_id = str(adr.get("id", "UNKNOWN"))
            owner = self._approval_owner(decision_classes)
            if adr_id not in requests_by_decision:
                request = {
                    "id": f"INPUT-{adr_id}",
                    "category": self._approval_category(reversibility, decision_classes),
                    "decision_ref": adr_id,
                    "owner": owner,
                    "reason": (
                        "The proposed decision is irreversible, vendor-locking, retention, "
                        "user-visible, security-policy, or production-infrastructure owned."
                    ),
                    "status": "INPUT_REQUIRED",
                }
                pack["approval_requests"].append(request)
                requests_by_decision[adr_id] = request
            diagnostics.append(
                _diagnostic(
                    "ARCH.APPROVAL.REQUIRED",
                    ArchitectureDisposition.PRODUCT_INPUT_REQUIRED,
                    f"/adrs/{adr_id}/approval_refs",
                    owner,
                    "A decision outside reversible technical authority lacks verified approval.",
                    "Obtain named, exact-subject approval through an external authority verifier.",
                )
            )

    @staticmethod
    def _approval_owner(decision_classes: set[str]) -> str:
        if "SECURITY_POLICY" in decision_classes:
            return "SECURITY"
        if "PRODUCTION_INFRASTRUCTURE" in decision_classes:
            return "INFRASTRUCTURE"
        return "PRODUCT"

    @staticmethod
    def _approval_category(reversibility: str, decision_classes: set[str]) -> str:
        if decision_classes:
            return sorted(decision_classes)[0]
        return "IRREVERSIBLE" if reversibility == "IRREVERSIBLE" else reversibility
