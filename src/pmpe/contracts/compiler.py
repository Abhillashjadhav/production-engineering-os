"""Deterministic, loss-aware PMOS legacy compiler and manifest emitter."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

from pmpe.config import packaged_schema_dir
from pmpe.contracts.adapters import (
    AdapterConversionError,
    AdapterDiagnostic,
    AdapterRegistry,
    SourceAdapter,
    SourceFormat,
)
from pmpe.contracts.canonical import (
    CanonicalInputError,
    canonical_digest,
    canonical_json_bytes,
    strict_loads,
)

BUNDLE_SCHEMA_ID = (
    "https://github.com/Abhillashjadhav/production-engineering-os/"
    "schemas/pmos_contract_bundle.schema.json"
)
MANIFEST_SCHEMA_ID = (
    "https://github.com/Abhillashjadhav/production-engineering-os/"
    "schemas/pmos_contract_manifest.schema.json"
)
COMPILER_ID = "pmpe-pmos-compiler"
COMPILER_VERSION = "1.0.0"
RULE_VERSION = "1.0.0"
CANONICAL_VERSION = "1.0.0"

_COMPLETE_SECTIONS = {
    "acceptance_criteria",
    "api_contracts",
    "approvals",
    "assumptions",
    "backend_capabilities",
    "data",
    "dependencies",
    "extensions",
    "functional_requirements",
    "guardrails",
    "integrations",
    "metrics",
    "non_functional_requirements",
    "observability",
    "open_questions",
    "privacy",
    "product",
    "product_decisions",
    "quality_assurance",
    "release",
    "required_approvals",
    "risks",
    "rollback",
    "scope",
    "security",
    "technical_constraints",
    "ux",
}


@dataclass(frozen=True)
class CompilationDiagnostic:
    code: str
    source_path: str
    target_path: str
    message: str
    blocking: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "blocking": self.blocking,
            "code": self.code,
            "message": self.message,
            "source_path": self.source_path,
            "target_path": self.target_path,
        }


@dataclass(frozen=True)
class CompilationResult:
    source_format: SourceFormat
    source_version: str
    bundle: dict[str, Any]
    manifest: dict[str, Any]
    bundle_bytes: bytes
    manifest_bytes: bytes
    bundle_digest: str
    manifest_digest: str
    diagnostics: tuple[CompilationDiagnostic, ...]
    evidence: dict[str, Any]
    blocked: bool

    @classmethod
    def from_artifacts(
        cls,
        bundle: dict[str, Any],
        manifest: dict[str, Any],
        evidence: dict[str, Any],
    ) -> CompilationResult:
        diagnostics = tuple(
            CompilationDiagnostic(
                code=item["code"],
                source_path=item["source_path"],
                target_path=item["target_path"],
                message=item["message"],
                blocking=bool(item["blocking"]),
            )
            for item in evidence["diagnostics"]
        )
        return cls(
            source_format=SourceFormat(evidence["source_format"]),
            source_version=str(evidence["source_version"]),
            bundle=bundle,
            manifest=manifest,
            bundle_bytes=canonical_json_bytes(bundle),
            manifest_bytes=canonical_json_bytes(manifest),
            bundle_digest=evidence["bundle_digest"],
            manifest_digest=evidence["manifest_digest"],
            diagnostics=diagnostics,
            evidence=evidence,
            blocked=bool(diagnostics),
        )


class CompilationBlockedError(ValueError):
    def __init__(
        self,
        diagnostics: list[CompilationDiagnostic],
        *,
        bundle: dict[str, Any] | None = None,
    ) -> None:
        self.diagnostics = tuple(diagnostics)
        self.bundle = bundle
        super().__init__("PMOS compilation blocked: " + "; ".join(d.code for d in diagnostics))


def _detect_format(source: dict[str, Any]) -> SourceFormat:
    if "spec_version" in source and "contract_version" in source:
        raise CompilationBlocked(
            [
                CompilationDiagnostic(
                    code="AMBIGUOUS_SOURCE_FORMAT",
                    source_path="",
                    target_path="",
                    message="source carries markers from multiple PMOS formats",
                )
            ]
        )
    markers: list[SourceFormat] = []
    if "spec_version" in source:
        markers.append(SourceFormat.PMOS_V1)
    if "contract_version" in source:
        v2_markers = {"desired_outcome", "functional_requirements", "scored_eval_rubric"}
        v3_markers = {"primary_journey", "screens", "api_contracts"}
        if v2_markers & source.keys():
            markers.append(SourceFormat.PMOS_V2)
        if v3_markers & source.keys():
            markers.append(SourceFormat.PMOS_V3)
    if len(set(markers)) != 1:
        raise CompilationBlocked(
            [
                CompilationDiagnostic(
                    code="AMBIGUOUS_SOURCE_FORMAT",
                    source_path="",
                    target_path="",
                    message="source format cannot be selected unambiguously",
                )
            ]
        )
    return markers[0]


def _source_version(source_format: SourceFormat, source: dict[str, Any]) -> str:
    if source_format is SourceFormat.PMOS_V1:
        return str(source.get("spec_version", ""))
    return str(source.get("contract_version", ""))


def _load_schema(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((packaged_schema_dir() / name).read_text())
    return loaded


def _pointer(parts: list[Any]) -> str:
    if not parts:
        return ""
    escaped = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(escaped)


def _unknown_paths(value: Any, schema: Any, parts: list[Any] | None = None) -> list[str]:
    path = parts or []
    unknown: list[str] = []
    if isinstance(value, dict) and isinstance(schema, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for key in value:
                if key not in properties:
                    unknown.append(_pointer([*path, key]))
            for key in value.keys() & properties.keys():
                unknown.extend(_unknown_paths(value[key], properties[key], [*path, key]))
    elif isinstance(value, list) and isinstance(schema, dict):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                unknown.extend(_unknown_paths(item, item_schema, [*path, index]))
    return unknown


def _source_schema(source_format: SourceFormat) -> dict[str, Any]:
    names = {
        SourceFormat.PMOS_V1: "mvp_spec.schema.json",
        SourceFormat.PMOS_V2: "product_decision_contract.schema.json",
        SourceFormat.PMOS_V3: "fullstack_product_contract.schema.json",
    }
    return _load_schema(names[source_format])


def _validate_source(
    source: dict[str, Any],
    source_format: SourceFormat,
    adapter: SourceAdapter,
) -> None:
    unknown = [_pointer([key]) for key in sorted(set(source) - set(adapter.known_top_level_fields))]
    schema = _source_schema(source_format)
    unknown.extend(path for path in _unknown_paths(source, schema) if path not in unknown)
    if unknown:
        raise CompilationBlocked(
            [
                CompilationDiagnostic(
                    code="SOURCE_FIELD_UNKNOWN",
                    source_path=path,
                    target_path="",
                    message="source contains a field outside the supported versioned shape",
                )
                for path in sorted(set(unknown))
            ]
        )
    errors = sorted(
        Draft202012Validator(schema).iter_errors(source),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise CompilationBlocked(
            [
                CompilationDiagnostic(
                    code="SOURCE_SCHEMA_INVALID",
                    source_path=_pointer(list(error.absolute_path)),
                    target_path="",
                    message=f"source violates the supported schema rule {error.validator}",
                )
                for error in errors
            ]
        )


def _safe_fragment(value: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]+", "-", value.upper()).strip("-")
    return normalized or "SOURCE"


def _unresolved(
    adapter_diagnostics: list[AdapterDiagnostic],
    mapped_sections: dict[str, Any],
) -> tuple[dict[str, Any], tuple[CompilationDiagnostic, ...]]:
    registry: dict[str, Any] = {}
    diagnostics: list[CompilationDiagnostic] = []
    for source_index, item in enumerate(adapter_diagnostics, start=1):
        record: dict[str, Any] = {
            "blocking": True,
            "question": "PMOS must approve an exact canonical mapping for this supplied truth.",
            "reason_code": item.code,
            "source_pointer": item.source_path,
            "source_value": copy.deepcopy(item.source_value),
        }
        if item.target_path:
            record["target_pointer"] = item.target_path
        registry[f"UNRESOLVED-SOURCE-{source_index:03d}"] = record
        diagnostics.append(
            CompilationDiagnostic(
                code=item.code,
                source_path=item.source_path,
                target_path=item.target_path,
                message=item.message,
            )
        )
    for absent_index, section in enumerate(
        sorted(_COMPLETE_SECTIONS - mapped_sections.keys()),
        start=1,
    ):
        target = f"/{section}"
        registry[f"UNRESOLVED-ABSENT-{absent_index:03d}"] = {
            "blocking": True,
            "question": f"PMOS must supply required canonical product truth for {target}.",
            "reason_code": "REQUIRED_PRODUCT_TRUTH_ABSENT",
            "target_pointer": target,
        }
        diagnostics.append(
            CompilationDiagnostic(
                code="REQUIRED_PRODUCT_TRUTH_ABSENT",
                source_path="",
                target_path=target,
                message="required canonical product truth is absent from the legacy source",
            )
        )
    return registry, tuple(diagnostics)


class CanonicalCompiler:
    def __init__(self, adapters: AdapterRegistry | None = None) -> None:
        self.adapters = adapters or AdapterRegistry()
        self._bundle_schema = _load_schema("pmos_contract_bundle.schema.json")
        self._manifest_schema = _load_schema("pmos_contract_manifest.schema.json")

    def compile(
        self,
        payload: bytes,
        *,
        content_type: str,
        received_at: str,
        source_name: str,
    ) -> CompilationResult:
        del source_name
        try:
            source = strict_loads(payload, content_type)
        except CanonicalInputError as exc:
            raise CompilationBlocked(
                [
                    CompilationDiagnostic(
                        code=exc.code,
                        source_path="",
                        target_path="",
                        message=str(exc),
                    )
                ]
            ) from exc
        source_format = _detect_format(source)
        source_version = _source_version(source_format, source)
        adapter = self.adapters.get(source_format, source_version)
        if adapter is None:
            raise CompilationBlocked(
                [
                    CompilationDiagnostic(
                        code="UNSUPPORTED_SOURCE_VERSION",
                        source_path=(
                            "/spec_version"
                            if source_format is SourceFormat.PMOS_V1
                            else "/contract_version"
                        ),
                        target_path="/schema_version",
                        message="source version has no registered adapter or migration path",
                    )
                ]
            )
        _validate_source(source, source_format, adapter)
        source_digest = canonical_digest(source)
        try:
            adapted = adapter.adapt(source)
        except AdapterConversionError as exc:
            item = exc.diagnostic
            raise CompilationBlocked(
                [
                    CompilationDiagnostic(
                        code=item.code,
                        source_path=item.source_path,
                        target_path=item.target_path,
                        message=item.message,
                    )
                ]
            ) from exc
        unresolved, diagnostics = _unresolved(
            adapted.diagnostics,
            adapted.mapped_sections,
        )
        source_id = str(
            source.get("contract_id")
            or f"SOURCE-V1-{source_digest.removeprefix('sha256:')[:16].upper()}"
        )
        bundle_fragment = _safe_fragment(source_id)
        bundle_id = f"BUNDLE-{bundle_fragment}-{source_digest.removeprefix('sha256:')[:12].upper()}"
        published_at = str(source.get("approved_at") or received_at)
        source_version_value = source[
            "spec_version" if source_format is SourceFormat.PMOS_V1 else "contract_version"
        ]
        provenance: dict[str, Any] = {
            "compiler_provenance": {
                "compiler_id": COMPILER_ID,
                "compiler_version": COMPILER_VERSION,
                "input_digest": source_digest,
            },
            "published_at": published_at,
            "source_digest": source_digest,
            "source_id": source_id,
            "source_system": "PM_AGENT_OS",
            "source_version": source_version_value,
        }
        if source.get("approved_by"):
            provenance["source_approved_by"] = source["approved_by"]
        bundle: dict[str, Any] = {
            **copy.deepcopy(adapted.mapped_sections),
            "bundle_id": bundle_id,
            "bundle_version": CANONICAL_VERSION,
            "canonical_json_profile": "RFC8785",
            "contract_status": "DRAFT",
            "provenance": provenance,
            "schema_id": BUNDLE_SCHEMA_ID,
            "schema_version": CANONICAL_VERSION,
            "source_identity_mappings": copy.deepcopy(adapted.source_identity_mappings),
            "unresolved_product_truth": unresolved,
        }
        self._ensure_valid(bundle, self._bundle_schema, "CANONICAL_BUNDLE_INVALID")
        bundle_digest = canonical_digest(bundle)
        manifest: dict[str, Any] = {
            "approval_digest": canonical_digest(bundle.get("approvals", {})),
            "approval_digest_scope": "CANONICAL_BUNDLE_APPROVALS_RFC8785",
            "bundle": {
                "bundle_id": bundle_id,
                "bundle_version": CANONICAL_VERSION,
                "content_digest": bundle_digest,
                "media_type": "application/json",
                "member_id": "MEMBER-CANONICAL-BUNDLE",
                "schema_id": BUNDLE_SCHEMA_ID,
                "schema_version": CANONICAL_VERSION,
            },
            "canonical_json_profile": "RFC8785",
            "created_at": received_at,
            "manifest_id": ("MANIFEST-" + source_digest.removeprefix("sha256:")[:20].upper()),
            "manifest_version": CANONICAL_VERSION,
            "members": {},
            "provenance": copy.deepcopy(provenance),
            "schema_id": MANIFEST_SCHEMA_ID,
            "schema_version": CANONICAL_VERSION,
        }
        manifest["manifest_digest"] = canonical_digest(manifest)
        self._ensure_valid(manifest, self._manifest_schema, "CANONICAL_MANIFEST_INVALID")
        evidence = {
            "bundle_digest": bundle_digest,
            "compiler_id": COMPILER_ID,
            "compiler_version": COMPILER_VERSION,
            "diagnostics": [diagnostic.as_dict() for diagnostic in diagnostics],
            "manifest_digest": manifest["manifest_digest"],
            "mapped_source_paths": sorted(adapted.mapped_source_paths),
            "migration_path": [adapter.rule_version],
            "rule_version": RULE_VERSION,
            "source_digest": source_digest,
            "source_format": source_format.value,
            "source_version": source_version,
            "source_version_value": source_version_value,
        }
        return CompilationResult(
            source_format=source_format,
            source_version=source_version,
            bundle=bundle,
            manifest=manifest,
            bundle_bytes=canonical_json_bytes(bundle),
            manifest_bytes=canonical_json_bytes(manifest),
            bundle_digest=bundle_digest,
            manifest_digest=manifest["manifest_digest"],
            diagnostics=diagnostics,
            evidence=evidence,
            blocked=True,
        )

    @staticmethod
    def _ensure_valid(instance: dict[str, Any], schema: dict[str, Any], code: str) -> None:
        errors = sorted(
            Draft202012Validator(schema).iter_errors(instance),
            key=lambda error: (
                tuple(str(part) for part in error.absolute_path),
                str(error.validator),
                error.message,
            ),
        )
        if errors:
            raise CompilationBlocked(
                [
                    CompilationDiagnostic(
                        code=code,
                        source_path="",
                        target_path=_pointer(list(error.absolute_path)),
                        message=(
                            f"compiler emitted data outside canonical schema rule {error.validator}"
                        ),
                    )
                    for error in errors
                ]
            )


CompilationBlocked = CompilationBlockedError


__all__ = [
    "CanonicalCompiler",
    "CompilationBlocked",
    "CompilationDiagnostic",
    "CompilationResult",
    "SourceFormat",
]
