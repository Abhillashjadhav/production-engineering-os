"""Executable contract for the PMOS authoring and migration documentation."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from pmpe.contracts import canonical_digest
from pmpe.contracts.compiler import CanonicalCompiler, CompilationBlocked
from pmpe.validation import (
    ApprovalAuthorityGrant,
    ApprovalRequirementGrant,
    ValidationContext,
    default_rule_registry,
)

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "pmos-contract-authoring.md"
EXAMPLES = ROOT / "examples" / "pmos-contracts"
VALID_BUNDLE = EXAMPLES / "canonical-bundle-1.0.0.json"
VALID_MANIFEST = EXAMPLES / "canonical-manifest-1.0.0.json"
OUTDATED_V2 = EXAMPLES / "invalid" / "outdated-v2-contract.json"
MISSING_APPROVAL_V2 = EXAMPLES / "invalid" / "missing-approval-v2-contract.json"


def _json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text())
    assert isinstance(value, dict)
    return value


def _schema(name: str) -> dict[str, object]:
    return _json(ROOT / "schemas" / name)


def _required_field_names(node: object) -> set[str]:
    if isinstance(node, dict):
        own = {
            item
            for item in node.get("required", [])
            if isinstance(node.get("required"), list) and isinstance(item, str)
        }
        return own | set().union(*(_required_field_names(value) for value in node.values()))
    if isinstance(node, list):
        return set().union(*(_required_field_names(value) for value in node))
    return set()


def _diagnostic_codes(path: Path) -> set[str]:
    compiler = CanonicalCompiler()
    with pytest.raises(CompilationBlocked) as raised:
        compiler.compile(
            path.read_bytes(),
            content_type="application/json",
            received_at="2026-08-01T00:00:00Z",
            source_name=path.name,
        )
    return {item.code for item in raised.value.diagnostics}


def test_documentation_covers_the_versioned_contract_and_operator_workflow() -> None:
    text = DOC.read_text()
    required_headings = {
        "# PMOS contract authoring, validation, and migration",
        "## Ownership boundary",
        "## Canonical bundle 1.0.0",
        "## Canonical manifest 1.0.0",
        "## Approvals and open questions",
        "## Validate and interpret diagnostics",
        "## Migrate V1, V2, and V3 inputs",
        "## Extensions",
        "## Security and privacy",
        "## Observability, release, and rollback",
    }
    assert required_headings <= set(text.splitlines())
    assert "PRODUCT_INPUT_REQUIRED" in text
    assert "UNSUPPORTED_SOURCE_VERSION" in text
    assert "SOURCE_SCHEMA_INVALID" in text
    assert "Direct canonical-bundle intake is not implemented" in text
    assert "AMBIGUOUS_SOURCE_FORMAT" in text

    schemas = (
        _schema("pmos_contract_bundle.schema.json"),
        _schema("pmos_contract_manifest.schema.json"),
    )
    documented_fields = set().union(
        *(set(schema["properties"]) | _required_field_names(schema) for schema in schemas)
    )
    for field in documented_fields:
        assert f"`{field}`" in text, f"undocumented canonical field: {field}"

    for linked_path in (
        "../schemas/pmos_contract_bundle.schema.json",
        "../schemas/pmos_contract_manifest.schema.json",
        "../examples/pmos-contracts/canonical-bundle-1.0.0.json",
        "../examples/pmos-contracts/canonical-manifest-1.0.0.json",
        "../examples/pmos-contracts/invalid/outdated-v2-contract.json",
        "../examples/pmos-contracts/invalid/missing-approval-v2-contract.json",
    ):
        assert f"]({linked_path})" in text
        assert (DOC.parent / linked_path).resolve().is_file()


def test_canonical_examples_validate_and_the_manifest_binds_the_bundle() -> None:
    bundle = _json(VALID_BUNDLE)
    manifest = _json(VALID_MANIFEST)
    assert (
        list(Draft202012Validator(_schema("pmos_contract_bundle.schema.json")).iter_errors(bundle))
        == []
    )
    assert (
        list(
            Draft202012Validator(_schema("pmos_contract_manifest.schema.json")).iter_errors(
                manifest
            )
        )
        == []
    )

    assert manifest["bundle"]["content_digest"] == canonical_digest(bundle)  # type: ignore[index]
    assert manifest["approval_digest"] == canonical_digest(bundle["approvals"])
    projection = dict(manifest)
    manifest_digest = projection.pop("manifest_digest")
    assert manifest_digest == canonical_digest(projection)

    context = ValidationContext(
        lineage_id="LINEAGE-SYNTHETIC-001",
        ingestion_attempt_id="ATTEMPT-SYNTHETIC-001",
        bundle_digest=canonical_digest(bundle),
        evaluated_at="2026-08-01T00:00:00Z",
        lineage_received_at="2026-07-30T00:00:00Z",
        authority_grants=(
            ApprovalAuthorityGrant(
                actor_id="OWNER-PRODUCT-001",
                role="PRODUCT_OWNER",
                authority_policy_id="AUTH-POLICY-CONTRACT-001",
                authority_policy_version="1.0.0",
                valid_from="2026-01-01T00:00:00Z",
                expires_at="2027-01-01T00:00:00Z",
            ),
            ApprovalAuthorityGrant(
                actor_id="OWNER-PRODUCT-001",
                role="METRIC_POLICY_OWNER",
                authority_policy_id="AUTH-POLICY-METRIC-001",
                authority_policy_version="1.0.0",
                valid_from="2026-01-01T00:00:00Z",
                expires_at="2027-01-01T00:00:00Z",
            ),
        ),
        approval_requirement_grants=(
            ApprovalRequirementGrant(
                requirement_id="APPROVAL-REQ-CONTRACT",
                approval_id="APR-CONTRACT-001",
            ),
        ),
    )
    findings = {}
    for rule in default_rule_registry().rules:
        rule_findings = rule.evaluator(copy.deepcopy(bundle), context)
        if rule_findings:
            findings[rule.rule_id] = rule_findings
    assert findings == {}, tuple(findings)


def test_direct_canonical_service_input_is_honestly_documented_as_unsupported() -> None:
    assert _diagnostic_codes(VALID_BUNDLE) == {"AMBIGUOUS_SOURCE_FORMAT"}


def test_planted_outdated_version_fails_with_documented_compiler_diagnostic() -> None:
    assert _diagnostic_codes(OUTDATED_V2) == {"UNSUPPORTED_SOURCE_VERSION"}


def test_planted_missing_approval_fails_with_documented_compiler_diagnostic() -> None:
    assert _diagnostic_codes(MISSING_APPROVAL_V2) == {"SOURCE_SCHEMA_INVALID"}
