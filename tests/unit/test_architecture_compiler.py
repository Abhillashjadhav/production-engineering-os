"""Issue #66 red-first contract for deterministic ArchitecturePack compilation."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from pmpe.contracts.canonical import canonical_digest
from pmpe.repository.models import (
    AdapterMetadata,
    BoundaryCandidate,
    GovernanceObservation,
    InventoryCategory,
    LocalState,
    RepositorySnapshot,
    ToolVersion,
)

ROOT = Path(__file__).resolve().parents[2]
VALID_BUNDLE = ROOT / "tests" / "fixtures" / "pmos" / "v1" / "valid_bundle.json"


def _api() -> Any:
    try:
        from pmpe import architecture
    except (ImportError, ModuleNotFoundError):
        pytest.fail("issue #66 architecture compiler is not implemented", pytrace=False)
    return architecture


def _contract() -> dict[str, Any]:
    return json.loads(VALID_BUNDLE.read_text())


def _snapshot() -> RepositorySnapshot:
    snapshot = RepositorySnapshot(
        repository="Abhillashjadhav/production-engineering-os",
        commit_sha="a" * 40,
        tree_sha="b" * 40,
        git_object_format="sha1",
        default_branch="main",
        default_branch_source="symbolic-ref",
        scanner_version="1.0.0",
        scan_configuration_digest="sha256:" + "1" * 64,
        adapter_set_digest="sha256:" + "2" * 64,
        implementation_digest="sha256:" + "3" * 64,
        tracked_tree_digest="sha256:" + "4" * 64,
        scanned_content_digest="sha256:" + "5" * 64,
        scan_scope="FULL_TRACKED_TREE",
        included_paths=("src/pmpe/contracts/model.py",),
        tooling_digest="sha256:" + "6" * 64,
        tool_versions=(ToolVersion(tool="git", version="2.50.0"),),
        adapters=(
            AdapterMetadata(
                adapter_id="python",
                version="1.0.0",
                detector_version="1.0.0",
                file_patterns=("*.py",),
                supported_categories=("architecture_boundaries",),
            ),
        ),
        command_provenance=(),
        inventory={"architecture_boundaries": InventoryCategory(status="SUPPORTED", items=())},
        findings=(),
        boundary_candidates=(
            BoundaryCandidate(
                kind="PACKAGE",
                name="src/pmpe/contracts",
                evidence_paths=("src/pmpe/contracts/model.py",),
                confidence="HIGH",
                detector_id="python",
                detector_version="1.0.0",
            ),
        ),
        unsupported_categories=(),
        disposition="COMPLETE",
        redaction={"status": "SANITIZED"},
        snapshot_digest="",
    )
    payload = snapshot.as_dict()
    payload.pop("snapshot_digest")
    return replace(snapshot, snapshot_digest=canonical_digest(payload))


def _governance(snapshot: RepositorySnapshot) -> GovernanceObservation:
    observation = GovernanceObservation(
        observation_id="OBS-ARCH-001",
        observed_at="2026-08-02T00:00:00Z",
        repository=snapshot.repository,
        ref="refs/heads/main",
        repository_snapshot_digest=snapshot.snapshot_digest,
        repository_snapshot_commit=snapshot.commit_sha,
        local_state=LocalState(
            index_dirty=False,
            worktree_dirty=False,
            untracked=False,
            head_sha=snapshot.commit_sha,
            git_object_format="sha1",
        ),
        current_branch="main",
        configured_remotes=("origin",),
        local_branches=(),
        worktrees=(),
        command_provenance=(),
        remote_branches=(),
        remote_default_branch="main",
        pull_requests=(),
        issues=(),
        governance={},
        query_provenance=(),
        remote_observed_at="2026-08-02T00:00:00Z",
        remote_query_coverage=("branches", "pull_requests", "issues"),
        remote_collection_provenance={},
        unknowns=(),
        collector_version="1.0.0",
        collector_implementation_digest="sha256:" + "7" * 64,
        tool_identity="github-api",
        api_query_version="2022-11-28",
        observation_input_digest="sha256:" + "8" * 64,
        observation_output_digest="",
        disposition="COMPLETE",
        redaction={"status": "SANITIZED"},
    )
    payload = observation.as_dict()
    payload.pop("observation_output_digest")
    return replace(observation, observation_output_digest=canonical_digest(payload))


def _proposal(
    contract: dict[str, Any], snapshot: RepositorySnapshot, governance: Any
) -> dict[str, Any]:
    boundary = "src/pmpe/contracts"
    components = [
        {
            "id": f"COMP-{plane}",
            "name": f"{plane.title()} plane",
            "plane": plane,
            "responsibilities": [f"Enforce the contract-defined {plane.lower()} concern."],
            "requirement_ids": ["FR-001"],
            "repository_boundaries": [boundary],
        }
        for plane in ("CONTROL", "EXECUTION", "EVIDENCE", "SECURITY", "DEPLOYMENT", "OBSERVABILITY")
    ]
    return {
        "schema_version": "1.0.0",
        "pack_id": "ARCH-BUNDLE-TASKFLOW-001",
        "contract_digest": canonical_digest(contract),
        "repository_snapshot_digest": snapshot.snapshot_digest,
        "repository_commit": snapshot.commit_sha,
        "governance_observation_digest": governance.observation_output_digest,
        "components": components,
        "data_architecture": [
            {
                "id": "DATA-ARCH-001",
                "data_refs": ["ENTITY-CONTRACT", "DATA-001"],
                "component_ids": ["COMP-EXECUTION"],
                "requirement_ids": ["FR-001"],
                "repository_boundaries": [boundary],
            }
        ],
        "api_architecture": [
            {
                "id": "API-ARCH-001",
                "api_refs": ["API-CONTRACT-INTAKE"],
                "component_ids": ["COMP-EXECUTION"],
                "requirement_ids": ["FR-001"],
                "repository_boundaries": [boundary],
            }
        ],
        "integration_architecture": [
            {
                "id": "INT-ARCH-001",
                "integration_refs": ["INT-PMOS-001"],
                "component_ids": ["COMP-EXECUTION"],
                "requirement_ids": ["FR-001"],
                "repository_boundaries": [boundary],
            }
        ],
        "security_boundaries": [
            {
                "id": "TB-001",
                "name": "Contract intake boundary",
                "source_component_ids": ["COMP-CONTROL"],
                "target_component_ids": ["COMP-EXECUTION"],
                "data_refs": ["ENTITY-CONTRACT"],
                "requirement_ids": ["FR-001"],
                "repository_boundaries": [boundary],
            }
        ],
        "data_flows": [
            {
                "id": "FLOW-001",
                "source_component_id": "COMP-CONTROL",
                "target_component_id": "COMP-EXECUTION",
                "data_refs": ["ENTITY-CONTRACT"],
                "trust_boundary_refs": ["TB-001"],
                "threat_refs": ["THREAT-001"],
                "requirement_ids": ["FR-001"],
            }
        ],
        "deployment": {
            "design": "Use only the contract-declared local preview target.",
            "release_refs": ["REL-001"],
            "requirement_ids": ["FR-001"],
            "repository_boundaries": [boundary],
        },
        "observability": {
            "design": "Implement the contract-declared admission outcome signal.",
            "observability_refs": ["OBS-001"],
            "requirement_ids": ["FR-001"],
            "repository_boundaries": [boundary],
        },
        "rollback": {
            "design": "Implement only the contract-declared schema rollback requirement.",
            "rollback_refs": ["ROLLBACK-001"],
            "requirement_ids": ["FR-001"],
            "repository_boundaries": [boundary],
        },
        "adrs": [
            {
                "id": "ADR-ARCH-001",
                "title": "Retain the existing contract boundary",
                "context": (
                    "Repository evidence locates the admitted contract model at this boundary."
                ),
                "decision": "Extend the existing boundary without adding a parallel subsystem.",
                "alternatives": [
                    {
                        "option": "Extend the existing contract boundary",
                        "outcome": "SELECTED",
                        "tradeoffs": ["Smallest repository impact"],
                    },
                    {
                        "option": "Add a parallel contract subsystem",
                        "outcome": "REJECTED",
                        "tradeoffs": ["Duplicates an evidenced responsibility"],
                    },
                ],
                "reversibility": "REVERSIBLE",
                "requirement_ids": ["FR-001"],
                "repository_boundaries": [boundary],
                "approval_refs": [],
            }
        ],
        "threat_model": {
            "methodology": "STRIDE",
            "trust_boundary_refs": ["TB-001"],
            "category_assessments": [
                {
                    "trust_boundary_ref": "TB-001",
                    "category": category,
                    "disposition": "MITIGATED" if category == "TAMPERING" else "NOT_APPLICABLE",
                    "rationale": (
                        "Integrity risk is mitigated by digest validation."
                        if category == "TAMPERING"
                        else "No applicable attack path exists in the admitted local boundary."
                    ),
                    "threat_refs": ["THREAT-001"] if category == "TAMPERING" else [],
                }
                for category in (
                    "SPOOFING",
                    "TAMPERING",
                    "REPUDIATION",
                    "INFORMATION_DISCLOSURE",
                    "DENIAL_OF_SERVICE",
                    "ELEVATION_OF_PRIVILEGE",
                )
            ],
            "threats": [
                {
                    "id": "THREAT-001",
                    "category": "TAMPERING",
                    "asset": "Admitted contract",
                    "entry_point": "Contract intake boundary",
                    "trust_boundary_refs": ["TB-001"],
                    "requirement_ids": ["FR-001", "PRIV-001", "SEC-001"],
                    "mitigation": "Validate the immutable contract digest before use.",
                    "residual_risk": (
                        "Malformed inputs are rejected; parser defects remain possible."
                    ),
                    "owner": "SECURITY",
                }
            ],
        },
        "approval_requests": [],
    }


def _compile(proposal: dict[str, Any]) -> Any:
    api = _api()
    contract = _contract()
    snapshot = _snapshot()
    governance = _governance(snapshot)
    proposal["contract_digest"] = canonical_digest(contract)
    proposal["repository_snapshot_digest"] = snapshot.snapshot_digest
    proposal["repository_commit"] = snapshot.commit_sha
    proposal["governance_observation_digest"] = governance.observation_output_digest
    validation = SimpleNamespace(
        bundle_digest=canonical_digest(contract), engineering_admissible=True
    )
    return api.ArchitectureCompiler().compile(
        contract,
        validation,
        snapshot,
        governance,
        proposal,
    )


def test_valid_architecture_pack_is_admitted_digest_bound_and_deterministic() -> None:
    api = _api()
    contract = _contract()
    snapshot = _snapshot()
    governance = _governance(snapshot)
    proposal = _proposal(contract, snapshot, governance)
    validation = SimpleNamespace(
        bundle_digest=canonical_digest(contract), engineering_admissible=True
    )

    first = api.ArchitectureCompiler().compile(contract, validation, snapshot, governance, proposal)
    second = api.ArchitectureCompiler().compile(
        contract, validation, snapshot, governance, copy.deepcopy(proposal)
    )

    assert first.disposition.value == "ADMITTED"
    assert first.pack is not None
    assert first.as_dict() == second.as_dict()
    assert first.pack.digest_is_valid()
    assert first.pack.contract_digest == canonical_digest(contract)
    assert first.pack.repository_snapshot_digest == snapshot.snapshot_digest
    assert {item["plane"] for item in first.pack.components} == set(api.ARCHITECTURE_PLANES)
    boundary_contract = first.pack.boundary_contract()
    assert boundary_contract["architecture_pack_digest"] == first.pack.pack_digest
    assert {item["component_id"] for item in boundary_contract["components"]} == {
        item["id"] for item in first.pack.components
    }
    with pytest.raises(TypeError):
        first.pack.components[0]["plane"] = "MUTATED"


def test_compiler_does_not_mutate_any_input() -> None:
    contract = _contract()
    snapshot = _snapshot()
    governance = _governance(snapshot)
    proposal = _proposal(contract, snapshot, governance)
    original_contract = copy.deepcopy(contract)
    original_proposal = copy.deepcopy(proposal)
    validation = SimpleNamespace(
        bundle_digest=canonical_digest(contract), engineering_admissible=True
    )

    _api().ArchitectureCompiler().compile(contract, validation, snapshot, governance, proposal)

    assert contract == original_contract
    assert proposal == original_proposal


@pytest.mark.parametrize(
    ("mutation", "rule_id"),
    [
        (lambda pack: pack.update(adrs=[]), "ARCH.ADR.REQUIRED"),
        (
            lambda pack: pack["components"][0].update(requirement_ids=["FR-UNKNOWN"]),
            "ARCH.REFERENCE.REQUIREMENT",
        ),
        (
            lambda pack: pack["components"][0].update(
                repository_boundaries=["src/unobserved/vendor.py"]
            ),
            "ARCH.REFERENCE.BOUNDARY",
        ),
        (
            lambda pack: pack["threat_model"].update(threats=[]),
            "ARCH.THREAT.GAP",
        ),
        (
            lambda pack: pack["data_flows"][0].update(threat_refs=[]),
            "ARCH.SECURITY.BOUNDARY",
        ),
    ],
)
def test_invalid_architecture_proposals_fail_closed(mutation: Any, rule_id: str) -> None:
    contract = _contract()
    snapshot = _snapshot()
    governance = _governance(snapshot)
    proposal = _proposal(contract, snapshot, governance)
    mutation(proposal)

    result = _compile(proposal)

    assert result.disposition.value == "ERROR"
    assert rule_id in {item.rule_id for item in result.diagnostics}
    assert result.pack is None


def test_irreversible_or_vendor_locking_choice_requests_named_input() -> None:
    contract = _contract()
    snapshot = _snapshot()
    governance = _governance(snapshot)
    proposal = _proposal(contract, snapshot, governance)
    proposal["adrs"][0]["reversibility"] = "VENDOR_LOCKING"

    result = _compile(proposal)

    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert result.pack is not None
    assert result.pack.digest_is_valid()
    blocker = next(item for item in result.diagnostics if item.rule_id == "ARCH.APPROVAL.REQUIRED")
    assert blocker.owner == "PRODUCT"
    assert blocker.field_path == "/adrs/ADR-ARCH-001/approval_refs"
    assert blocker.next_action
    assert result.pack.disposition == "PRODUCT_INPUT_REQUIRED"
    assert result.pack.approval_requests[0]["decision_ref"] == "ADR-ARCH-001"


def test_user_visible_or_retention_decisions_are_not_silently_defaulted() -> None:
    contract = _contract()
    snapshot = _snapshot()
    governance = _governance(snapshot)
    proposal = _proposal(contract, snapshot, governance)
    proposal["adrs"][0]["decision_classes"] = ["DATA_RETENTION", "USER_VISIBLE"]

    result = _compile(proposal)

    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert "ARCH.APPROVAL.REQUIRED" in {item.rule_id for item in result.diagnostics}


def test_each_approval_authority_gets_a_separate_request() -> None:
    contract = _contract()
    snapshot = _snapshot()
    governance = _governance(snapshot)
    proposal = _proposal(contract, snapshot, governance)
    proposal["adrs"][0]["decision_classes"] = [
        "PRODUCTION_INFRASTRUCTURE",
        "SECURITY_POLICY",
    ]

    result = _compile(proposal)

    assert result.disposition.value == "PRODUCT_INPUT_REQUIRED"
    assert result.pack is not None
    assert {
        (request["category"], request["owner"]) for request in result.pack.approval_requests
    } == {
        ("PRODUCTION_INFRASTRUCTURE", "INFRASTRUCTURE"),
        ("SECURITY_POLICY", "SECURITY"),
    }


def test_data_flow_must_match_referenced_boundary_endpoints() -> None:
    contract = _contract()
    snapshot = _snapshot()
    governance = _governance(snapshot)
    proposal = _proposal(contract, snapshot, governance)
    proposal["security_boundaries"][0].update(
        source_component_ids=["COMP-EVIDENCE"],
        target_component_ids=["COMP-SECURITY"],
    )

    result = _compile(proposal)

    assert result.disposition.value == "ERROR"
    assert "ARCH.SECURITY.BOUNDARY" in {item.rule_id for item in result.diagnostics}


def test_stride_requires_explicit_category_disposition_per_boundary() -> None:
    contract = _contract()
    snapshot = _snapshot()
    governance = _governance(snapshot)
    proposal = _proposal(contract, snapshot, governance)
    proposal["threat_model"]["category_assessments"].pop()

    result = _compile(proposal)

    assert result.disposition.value == "ERROR"
    assert "ARCH.THREAT.STRIDE_COVERAGE" in {item.rule_id for item in result.diagnostics}


def test_boundary_names_are_admitted_and_evidence_paths_are_preserved() -> None:
    contract = _contract()
    snapshot = _snapshot()
    governance = _governance(snapshot)
    proposal = _proposal(contract, snapshot, governance)

    result = _compile(proposal)

    assert result.pack is not None
    assert result.pack.repository_boundary_evidence == (
        {
            "boundary": "src/pmpe/contracts",
            "confidence": "HIGH",
            "detector_id": "python",
            "detector_version": "1.0.0",
            "evidence_paths": ("src/pmpe/contracts/model.py",),
            "kind": "PACKAGE",
        },
    )

    proposal["components"][0]["repository_boundaries"] = ["src/pmpe/contracts/model.py"]
    rejected = _compile(proposal)
    assert rejected.disposition.value == "ERROR"
    assert "ARCH.REFERENCE.BOUNDARY" in {item.rule_id for item in rejected.diagnostics}


def test_duplicate_component_is_rejected_as_unnecessary_complexity() -> None:
    contract = _contract()
    snapshot = _snapshot()
    governance = _governance(snapshot)
    proposal = _proposal(contract, snapshot, governance)
    duplicate = copy.deepcopy(proposal["components"][0])
    duplicate["id"] = "COMP-REDUNDANT"
    proposal["components"].append(duplicate)

    result = _compile(proposal)

    assert result.disposition.value == "ERROR"
    assert "ARCH.UNNECESSARY_COMPLEXITY" in {item.rule_id for item in result.diagnostics}


def test_unadmitted_or_mismatched_inputs_cannot_compile() -> None:
    api = _api()
    contract = _contract()
    snapshot = _snapshot()
    governance = _governance(snapshot)
    proposal = _proposal(contract, snapshot, governance)
    validation = SimpleNamespace(bundle_digest="sha256:" + "0" * 64, engineering_admissible=True)

    result = api.ArchitectureCompiler().compile(
        contract, validation, snapshot, governance, proposal
    )

    assert result.disposition.value == "ERROR"
    assert "ARCH.INPUT.CONTRACT" in {item.rule_id for item in result.diagnostics}
    assert result.pack is None


def test_architecture_pack_schema_is_packaged_and_versioned() -> None:
    schema_path = ROOT / "src" / "pmpe" / "schemas" / "architecture_pack.schema.json"
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    assert schema["$id"].endswith("/architecture-pack/1.0.0/schema.json")
    assert schema["properties"]["schema_version"]["const"] == "1.0.0"
