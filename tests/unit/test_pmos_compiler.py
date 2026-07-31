"""Issue #76: loss-aware PMOS V1/V2/V3 compilation and migration evidence."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
BUNDLE_SCHEMA = json.loads((ROOT / "schemas" / "pmos_contract_bundle.schema.json").read_text())
MANIFEST_SCHEMA = json.loads((ROOT / "schemas" / "pmos_contract_manifest.schema.json").read_text())
FIXED_TIME = "2026-07-31T08:00:00Z"

LEGACY_CASES = (
    ("PMOS_V1", "1.0", FIXTURES / "minimal_valid_spec.json"),
    ("PMOS_V2", "1", FIXTURES / "v2" / "contract_approved.json"),
    ("PMOS_V3", "1", FIXTURES / "v3" / "fullstack_contract_approved.json"),
)


def _module(name: str) -> ModuleType:
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        pytest.fail(f"issue #76 module {name!r} is not implemented", pytrace=False)


def _compiler() -> Any:
    module = _module("pmpe.contracts.compiler")
    compiler_type = getattr(module, "CanonicalCompiler", None)
    assert compiler_type is not None, "CanonicalCompiler is not implemented"
    return compiler_type()


def _compile(path: Path) -> Any:
    return _compiler().compile(
        path.read_bytes(),
        content_type="application/json",
        received_at=FIXED_TIME,
        source_name=path.name,
    )


def _schema_errors(instance: Any, schema: dict[str, Any]) -> list[str]:
    return [
        f"{error.json_path}: {error.message}"
        for error in Draft202012Validator(schema).iter_errors(instance)
    ]


def _manifest_projection(manifest: dict[str, Any]) -> dict[str, Any]:
    projected = copy.deepcopy(manifest)
    del projected["manifest_digest"]
    return projected


def test_issue76_public_compiler_components_exist() -> None:
    compiler = _module("pmpe.contracts.compiler")
    migrations = _module("pmpe.contracts.migrations")
    canonical = _module("pmpe.contracts.canonical")
    for name in (
        "CanonicalCompiler",
        "CompilationBlocked",
        "CompilationDiagnostic",
        "CompilationResult",
        "SourceFormat",
    ):
        assert hasattr(compiler, name), f"missing compiler component: {name}"
    for name in ("MigrationError", "MigrationRegistry", "MigrationStep"):
        assert hasattr(migrations, name), f"missing migration component: {name}"
    for name in ("canonical_digest", "canonical_json_bytes", "strict_loads"):
        assert hasattr(canonical, name), f"missing canonicalization component: {name}"


@pytest.mark.parametrize(("expected_format", "expected_version", "fixture"), LEGACY_CASES)
def test_supported_legacy_contract_compiles_to_schema_valid_draft(
    expected_format: str,
    expected_version: str,
    fixture: Path,
) -> None:
    result = _compile(fixture)
    assert result.source_format.value == expected_format
    assert result.source_version == expected_version
    assert result.bundle["contract_status"] == "DRAFT"
    assert result.blocked is True
    assert result.bundle["unresolved_product_truth"]
    assert _schema_errors(result.bundle, BUNDLE_SCHEMA) == []
    assert _schema_errors(result.manifest, MANIFEST_SCHEMA) == []


@pytest.mark.parametrize(("_format", "_version", "fixture"), LEGACY_CASES)
def test_same_source_and_toolchain_are_byte_deterministic(
    _format: str,
    _version: str,
    fixture: Path,
) -> None:
    first = _compile(fixture)
    second = _compile(fixture)
    assert first.bundle_bytes == second.bundle_bytes
    assert first.manifest_bytes == second.manifest_bytes
    assert first.bundle_digest == second.bundle_digest
    assert first.manifest_digest == second.manifest_digest
    assert first.evidence == second.evidence


@pytest.mark.parametrize(("_format", "_version", "fixture"), LEGACY_CASES)
def test_source_formatting_and_key_order_do_not_change_compilation(
    _format: str,
    _version: str,
    fixture: Path,
) -> None:
    data = json.loads(fixture.read_text())
    reordered = dict(reversed(list(data.items())))
    rendered = json.dumps(reordered, indent=4).encode()
    original = _compile(fixture)
    changed_format = _compiler().compile(
        rendered,
        content_type="application/json",
        received_at=FIXED_TIME,
        source_name=fixture.name,
    )
    assert changed_format.bundle_bytes == original.bundle_bytes
    assert changed_format.manifest_bytes == original.manifest_bytes
    assert changed_format.evidence["source_digest"] == original.evidence["source_digest"]


def test_v1_exact_scope_is_mapped_without_defaults() -> None:
    result = _compile(FIXTURES / "minimal_valid_spec.json")
    source = json.loads((FIXTURES / "minimal_valid_spec.json").read_text())
    assert result.bundle["scope"] == {
        "in_scope": source["scope"],
        "non_goals": source["non_goals"],
    }
    rendered = json.dumps(result.bundle, sort_keys=True)
    assert "TBD" not in rendered
    assert "TODO" not in rendered
    assert "unknown" not in rendered.lower()


def test_v2_required_approvals_and_source_approver_are_preserved() -> None:
    result = _compile(FIXTURES / "v2" / "contract_approved.json")
    source = json.loads((FIXTURES / "v2" / "contract_approved.json").read_text())
    assert result.bundle["provenance"]["source_approved_by"] == source["approved_by"]
    assert result.bundle["required_approvals"] == {
        "APPROVAL-REQ-001": {
            "purpose": source["required_approvals"][0]["for"],
            "role": source["required_approvals"][0]["role"],
        }
    }


def test_v3_api_and_backend_capability_values_are_preserved() -> None:
    result = _compile(FIXTURES / "v3" / "fullstack_contract_approved.json")
    source = json.loads((FIXTURES / "v3" / "fullstack_contract_approved.json").read_text())
    assert result.bundle["api_contracts"]["API-1"] == {
        "method": source["api_contracts"][0]["method"],
        "path": source["api_contracts"][0]["path"],
        "purpose": source["api_contracts"][0]["purpose"],
    }
    assert result.bundle["backend_capabilities"]["CAPABILITY-BC-1"] == {
        "description": source["backend_capabilities"][0]["description"]
    }
    mapping = result.bundle["source_identity_mappings"]["SOURCE-MAP-CAPABILITY-BC-1"]
    assert mapping["source_id"] == "BC-1"
    assert mapping["source_pointer"] == "/backend_capabilities/0"
    assert mapping["canonical_pointer"] == "/backend_capabilities/CAPABILITY-BC-1"


@pytest.mark.parametrize(("_format", "_version", "fixture"), LEGACY_CASES)
def test_every_source_field_is_mapped_or_preserved_in_a_blocking_diagnostic(
    _format: str,
    _version: str,
    fixture: Path,
) -> None:
    result = _compile(fixture)
    source = json.loads(fixture.read_text())
    covered = set(result.evidence["mapped_source_paths"])
    covered.update(diagnostic.source_path for diagnostic in result.diagnostics)
    assert {f"/{key}" for key in source} <= covered
    for diagnostic in result.diagnostics:
        assert diagnostic.blocking
        assert diagnostic.source_path.startswith("/") or diagnostic.source_path == ""
        assert diagnostic.message
        assert "secret" not in diagnostic.message.lower()


def test_missing_canonical_truth_is_explicit_and_never_gets_a_source_value() -> None:
    result = _compile(FIXTURES / "minimal_valid_spec.json")
    absent = [
        item
        for item in result.bundle["unresolved_product_truth"].values()
        if item["reason_code"] == "REQUIRED_PRODUCT_TRUTH_ABSENT"
    ]
    assert absent
    assert all("source_pointer" not in item for item in absent)
    assert all("source_value" not in item for item in absent)
    assert all(item["target_pointer"].startswith("/") for item in absent)


def test_supplied_unmapped_truth_is_preserved_exactly() -> None:
    fixture = FIXTURES / "minimal_valid_spec.json"
    source = json.loads(fixture.read_text())
    result = _compile(fixture)
    diagnostic = next(
        item
        for item in result.bundle["unresolved_product_truth"].values()
        if item.get("source_pointer") == "/product_name"
    )
    assert diagnostic["source_value"] == source["product_name"]
    assert diagnostic["reason_code"] in {"AMBIGUOUS_MAPPING", "SOURCE_FIELD_UNMAPPED"}


def test_unknown_source_field_fails_closed_with_pointer_and_no_artifact() -> None:
    compiler = _module("pmpe.contracts.compiler")
    blocked_type = compiler.CompilationBlocked
    source = json.loads((FIXTURES / "minimal_valid_spec.json").read_text())
    source["surprise_product_truth"] = "must not disappear"
    with pytest.raises(blocked_type) as raised:
        _compiler().compile(
            json.dumps(source).encode(),
            content_type="application/json",
            received_at=FIXED_TIME,
            source_name="unknown.json",
        )
    assert raised.value.bundle is None
    assert any(
        diagnostic.code == "SOURCE_FIELD_UNKNOWN"
        and diagnostic.source_path == "/surprise_product_truth"
        for diagnostic in raised.value.diagnostics
    )


@pytest.mark.parametrize(
    ("fixture", "version_field", "unsupported"),
    [
        (FIXTURES / "minimal_valid_spec.json", "spec_version", "2.0"),
        (FIXTURES / "v2" / "contract_approved.json", "contract_version", 2),
        (FIXTURES / "v3" / "fullstack_contract_approved.json", "contract_version", 9),
    ],
)
def test_unsupported_source_version_fails_closed(
    fixture: Path,
    version_field: str,
    unsupported: Any,
) -> None:
    compiler = _module("pmpe.contracts.compiler")
    blocked_type = compiler.CompilationBlocked
    source = json.loads(fixture.read_text())
    source[version_field] = unsupported
    with pytest.raises(blocked_type) as raised:
        _compiler().compile(
            json.dumps(source).encode(),
            content_type="application/json",
            received_at=FIXED_TIME,
            source_name=fixture.name,
        )
    assert any(
        diagnostic.code == "UNSUPPORTED_SOURCE_VERSION" for diagnostic in raised.value.diagnostics
    )


def test_ambiguous_source_shape_fails_closed() -> None:
    compiler = _module("pmpe.contracts.compiler")
    blocked_type = compiler.CompilationBlocked
    ambiguous = {
        "spec_version": "1.0",
        "contract_version": 1,
        "contract_id": "PDC-AMBIGUOUS",
    }
    with pytest.raises(blocked_type) as raised:
        _compiler().compile(
            json.dumps(ambiguous).encode(),
            content_type="application/json",
            received_at=FIXED_TIME,
            source_name="ambiguous.json",
        )
    assert any(
        diagnostic.code == "AMBIGUOUS_SOURCE_FORMAT" for diagnostic in raised.value.diagnostics
    )


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b'{"spec_version":"1.0","spec_version":"1.0"}', "DUPLICATE_OBJECT_KEY"),
        (b'{"spec_version": NaN}', "NON_JSON_NUMBER"),
        (b'{"spec_version":"\\ud800"}', "INVALID_UNICODE"),
        (b'{"spec_version":"1.0"', "MALFORMED_SOURCE"),
    ],
)
def test_malformed_or_non_interoperable_json_fails_before_detection(
    payload: bytes,
    code: str,
) -> None:
    compiler = _module("pmpe.contracts.compiler")
    blocked_type = compiler.CompilationBlocked
    with pytest.raises(blocked_type) as raised:
        _compiler().compile(
            payload,
            content_type="application/json",
            received_at=FIXED_TIME,
            source_name="invalid.json",
        )
    assert raised.value.diagnostics[0].code == code
    assert raised.value.bundle is None


def test_yaml_v1_is_supported_with_duplicate_aware_parsing() -> None:
    source = json.loads((FIXTURES / "minimal_valid_spec.json").read_text())
    yaml = _module("yaml")
    payload = yaml.safe_dump(source, sort_keys=False).encode()
    result = _compiler().compile(
        payload,
        content_type="application/yaml",
        received_at=FIXED_TIME,
        source_name="v1.yaml",
    )
    assert result.source_format.value == "PMOS_V1"
    assert _schema_errors(result.bundle, BUNDLE_SCHEMA) == []


def test_duplicate_yaml_key_fails_closed() -> None:
    compiler = _module("pmpe.contracts.compiler")
    blocked_type = compiler.CompilationBlocked
    with pytest.raises(blocked_type) as raised:
        _compiler().compile(
            b"spec_version: '1.0'\nspec_version: '1.0'\n",
            content_type="application/yaml",
            received_at=FIXED_TIME,
            source_name="duplicate.yaml",
        )
    assert raised.value.diagnostics[0].code == "DUPLICATE_OBJECT_KEY"


def test_rfc8785_vectors_cover_numbers_escapes_and_utf16_key_order() -> None:
    canonical = _module("pmpe.contracts.canonical")
    value = {
        "\u20ac": "Euro Sign",
        "\r": "Carriage Return",
        "\ufb33": "Hebrew Letter Dalet With Dagesh",
        "1": 1.0,
        "\U0001f600": "Emoji",
        "\u0080": "Control",
        "\u00f6": "Latin Small Letter O With Diaeresis",
    }
    rendered = canonical.canonical_json_bytes(value)
    assert rendered == (
        b'{"\\r":"Carriage Return","1":1,"\xc2\x80":"Control",'
        b'"\xc3\xb6":"Latin Small Letter O With Diaeresis",'
        b'"\xe2\x82\xac":"Euro Sign","\xf0\x9f\x98\x80":"Emoji",'
        b'"\xef\xac\xb3":"Hebrew Letter Dalet With Dagesh"}'
    )


def test_manifest_digest_bindings_recompute_from_exact_projections() -> None:
    canonical = _module("pmpe.contracts.canonical")
    result = _compile(FIXTURES / "v2" / "contract_approved.json")
    assert result.manifest["bundle"]["content_digest"] == canonical.canonical_digest(result.bundle)
    assert result.manifest["approval_digest"] == canonical.canonical_digest(
        result.bundle.get("approvals", {})
    )
    assert result.manifest["manifest_digest"] == canonical.canonical_digest(
        _manifest_projection(result.manifest)
    )


@pytest.mark.parametrize(("_format", "_version", "fixture"), LEGACY_CASES)
def test_complete_compiler_evidence_binds_versions_rules_digests_and_diagnostics(
    _format: str,
    _version: str,
    fixture: Path,
) -> None:
    result = _compile(fixture)
    evidence = result.evidence
    assert evidence["source_format"] == result.source_format.value
    assert evidence["source_version"] == result.source_version
    assert evidence["source_digest"].startswith("sha256:")
    assert evidence["compiler_id"] == "pmpe-pmos-compiler"
    assert evidence["compiler_version"]
    assert evidence["rule_version"]
    assert evidence["migration_path"]
    assert evidence["bundle_digest"] == result.bundle_digest
    assert evidence["manifest_digest"] == result.manifest_digest
    assert evidence["diagnostics"] == [diagnostic.as_dict() for diagnostic in result.diagnostics]


def test_migration_registry_is_ordered_pure_and_refuses_downgrade() -> None:
    migrations = _module("pmpe.contracts.migrations")
    registry = migrations.MigrationRegistry()

    def add_middle(value: dict[str, Any]) -> dict[str, Any]:
        return {**value, "middle": True}

    def add_final(value: dict[str, Any]) -> dict[str, Any]:
        return {**value, "final": True}

    registry.register(migrations.MigrationStep("1.0.0", "1.1.0", "RULE-A", add_middle))
    registry.register(migrations.MigrationStep("1.1.0", "2.0.0", "RULE-B", add_final))
    source = {"source": True}
    migrated, path = registry.migrate(source, "1.0.0", "2.0.0")
    assert source == {"source": True}
    assert migrated == {"source": True, "middle": True, "final": True}
    assert path == ("RULE-A", "RULE-B")
    with pytest.raises(migrations.MigrationError, match="downgrade"):
        registry.migrate(source, "2.0.0", "1.0.0")


def test_migration_registry_rejects_ambiguous_and_reordered_paths() -> None:
    migrations = _module("pmpe.contracts.migrations")
    registry = migrations.MigrationRegistry()

    def identity(value: dict[str, Any]) -> dict[str, Any]:
        return dict(value)

    registry.register(migrations.MigrationStep("1.0.0", "1.1.0", "RULE-A", identity))
    registry.register(migrations.MigrationStep("1.1.0", "2.0.0", "RULE-B", identity))
    with pytest.raises(migrations.MigrationError, match="order"):
        registry.register(migrations.MigrationStep("0.9.0", "1.0.0", "RULE-OLD", identity))
    with pytest.raises(migrations.MigrationError, match="ambiguous"):
        registry.register(migrations.MigrationStep("1.0.0", "1.5.0", "RULE-X", identity))


def test_source_change_changes_source_bundle_and_manifest_digests() -> None:
    fixture = FIXTURES / "minimal_valid_spec.json"
    source = json.loads(fixture.read_text())
    original = _compile(fixture)
    source["scope"].append("Second exact scope item")
    changed = _compiler().compile(
        json.dumps(source).encode(),
        content_type="application/json",
        received_at=FIXED_TIME,
        source_name=fixture.name,
    )
    assert original.evidence["source_digest"] != changed.evidence["source_digest"]
    assert original.bundle_digest != changed.bundle_digest
    assert original.manifest_digest != changed.manifest_digest


def test_no_ordinary_rejected_payload_digest_appears_in_diagnostics() -> None:
    compiler = _module("pmpe.contracts.compiler")
    blocked_type = compiler.CompilationBlocked
    payload = b'{"spec_version":"9.9","secret_value":"do-not-retain"}'
    ordinary_digest = hashlib.sha256(payload).hexdigest()
    with pytest.raises(blocked_type) as raised:
        _compiler().compile(
            payload,
            content_type="application/json",
            received_at=FIXED_TIME,
            source_name="rejected.json",
        )
    rendered = json.dumps(
        [diagnostic.as_dict() for diagnostic in raised.value.diagnostics],
        sort_keys=True,
    )
    assert ordinary_digest not in rendered
    assert "do-not-retain" not in rendered
