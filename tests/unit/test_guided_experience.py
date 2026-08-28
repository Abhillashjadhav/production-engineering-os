"""Issue #120: guided PMOS authoring, approval, PCR, and canonical intake."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from pmpe.contracts.canonical import canonical_digest
from pmpe.domain.errors import ContractViolation, SpecError
from pmpe.guided.experience import GuidedExperience
from pmpe.guided.server import serve

ROOT = Path(__file__).resolve().parents[2]


def _answers() -> dict[str, str]:
    return {
        "acceptance_criteria": (
            "Given complete answers, review shows the exact digest and decision impact.\n"
            "Given an approved contract, a product change creates a PCR without mutating it."
        ),
        "binary_release_gates": "All acceptance tests pass\nZero blocking accessibility issues",
        "desired_outcome": "A PM can approve a bounded product decision without learning JSON.",
        "functional_requirements": (
            "Review the exact approval digest\nRecord product changes after approval"
        ),
        "golden_cases": "guided-basic\nchange-after-approval",
        "guardrails": "Zero unauthorized external actions\nNo silent contract mutation",
        "known_risks": "A user may approve an incomplete decision",
        "leading_metrics": "Median time to approved contract\nFirst-pass answer completion rate",
        "non_functional_requirements": ("Keyboard accessible\nUsable on a 320 pixel wide viewport"),
        "north_star_metric": (
            "Percentage of product decisions approved with complete traceable evidence"
        ),
        "out_of_scope": "Automatic production deployment\nConnector writes",
        "problem": "PMOS contract JSON is difficult for non-technical product managers to author.",
        "product_name": "PMOS Guided",
        "required_approvals": "Product owner",
        "scope": "Guided authoring\nExact digest approval\nProductChangeRequest creation",
        "scored_eval_rubric": "Plain-language clarity\nMobile usability",
        "target_user": "Product managers who do not write contract JSON",
    }


def test_guided_flow_returns_one_blocking_question_at_a_time(tmp_path: Path) -> None:
    experience = GuidedExperience(tmp_path)
    first = experience.review({})
    assert first["status"] == "PRODUCT_INPUT_REQUIRED"
    assert first["question"]["field"] == "product_name"
    assert "question" in first and "draft" not in first

    partial = experience.review({"product_name": "PMOS Guided"})
    assert partial["question"]["field"] == "target_user"


def test_complete_answers_return_exact_five_part_approval_card(tmp_path: Path) -> None:
    result = GuidedExperience(tmp_path).review(_answers())
    assert result["status"] == "DRAFT_READY_FOR_APPROVAL"
    card = result["approval_card"]
    assert set(card) == {
        "approval_action",
        "cost",
        "digest",
        "evidence",
        "impact",
        "permissions",
        "reversibility",
        "validity",
    }
    assert card["digest"] == canonical_digest(result["draft"])
    assert card["cost"]["estimated_external_cost"] == "0"
    assert "Network or connector access" in card["permissions"]["not_allowed"]


def test_criteria_count_is_a_guided_blocking_question(tmp_path: Path) -> None:
    answers = _answers()
    answers["acceptance_criteria"] = "Only one proof"
    result = GuidedExperience(tmp_path).review(answers)
    assert result["status"] == "PRODUCT_INPUT_REQUIRED"
    assert result["question"]["field"] == "acceptance_criteria"
    assert "exactly one" in result["question"]["reason"]


def test_approval_and_change_request_use_canonical_domain_paths(tmp_path: Path) -> None:
    experience = GuidedExperience(tmp_path)
    review = experience.review(_answers())
    digest = review["approval_card"]["digest"]
    approved = experience.approve(
        expected_digest=digest,
        approver="product-owner",
        approved_at="2026-08-19T12:00:00Z",
    )
    assert approved["status"] == "APPROVED"
    receipt = approved["receipt"]
    assert receipt["draft_digest"] == digest

    change = experience.create_change_request(
        {
            "approved_contract_digest": approved["approved_contract_digest"],
            "affected_requirement_ids": "FR-001",
            "engineering_finding": "The mobile browser cannot expose a required native API.",
            "reason": "Choosing a fallback changes the approved user experience.",
            "options": "Use file upload\nRequire a desktop browser",
            "engineering_consequences": "The primary journey and tests differ.",
            "recommended_technical_default": "Use file upload",
            "decision_owner": "product-owner",
        }
    )
    assert change["change_request"]["request_id"] == "PCR-001"
    approved_contracts = list(tmp_path.glob("approved/*/contract-approved.json"))
    assert len(approved_contracts) == 1
    assert (
        canonical_digest(json.loads(approved_contracts[0].read_text()))
        == approved["approved_contract_digest"]
    )


def test_approval_is_idempotent_but_cannot_overwrite_contract_version(tmp_path: Path) -> None:
    experience = GuidedExperience(tmp_path)
    review = experience.review(_answers())
    digest = review["approval_card"]["digest"]
    first = experience.approve(
        expected_digest=digest,
        approver="product-owner",
        approved_at="2026-08-19T12:00:00Z",
    )
    repeated = experience.approve(
        expected_digest=digest,
        approver="product-owner",
        approved_at="2026-08-19T12:00:00Z",
    )
    assert repeated == first
    with pytest.raises(ContractViolation, match="expected approver|immutable approval"):
        experience.approve(
            expected_digest=digest,
            approver="different-owner",
            approved_at="2026-08-19T12:00:00Z",
        )


def test_guided_workspace_rejects_symbolic_link(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    link = tmp_path / "link"
    link.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ContractViolation, match="symbolic link"):
        GuidedExperience(link)


def test_unknown_digest_cannot_approve_or_create_change_request(tmp_path: Path) -> None:
    experience = GuidedExperience(tmp_path)
    with pytest.raises(ContractViolation, match="reviewed draft"):
        experience.approve(expected_digest="sha256:" + "0" * 64, approver="owner")
    with pytest.raises(ContractViolation, match="approved contract"):
        experience.create_change_request(
            {"approved_contract_digest": "sha256:" + "0" * 64, "options": "a"}
        )


def test_malformed_digest_cannot_escape_the_draft_workspace(tmp_path: Path) -> None:
    experience = GuidedExperience(tmp_path / "workspace")
    with pytest.raises(ContractViolation, match="malformed"):
        experience.approve(expected_digest="../../outside", approver="owner")
    assert not (tmp_path / "outside.json").exists()


def test_change_request_requires_complete_decision_input(tmp_path: Path) -> None:
    experience = GuidedExperience(tmp_path)
    review = experience.review(_answers())
    approved = experience.approve(
        expected_digest=review["approval_card"]["digest"],
        approver="product-owner",
        approved_at="2026-08-19T12:00:00Z",
    )
    with pytest.raises(ContractViolation, match="engineering_finding"):
        experience.create_change_request(
            {
                "approved_contract_digest": approved["approved_contract_digest"],
                "options": "Use file upload",
            }
        )


def _canonical_pair() -> tuple[dict[str, Any], dict[str, Any]]:
    bundle = json.loads(
        (ROOT / "examples" / "pmos-contracts" / "canonical-bundle-1.0.0.json").read_text()
    )
    manifest = json.loads(
        (ROOT / "examples" / "pmos-contracts" / "canonical-manifest-1.0.0.json").read_text()
    )
    return bundle, manifest


def test_native_canonical_bundle_and_manifest_are_validated_without_claiming_admission(
    tmp_path: Path,
) -> None:
    bundle, manifest = _canonical_pair()
    result = GuidedExperience(tmp_path).intake_canonical(
        json.dumps(bundle, indent=2), json.dumps(manifest, indent=2)
    )
    assert result["status"] == "VALIDATED_PENDING_GOVERNED_ADMISSION"
    assert result["bundle_digest"] == canonical_digest(bundle)
    validated = tmp_path / "canonical-intake" / "validated"
    assert len(list(validated.glob("*/bundle.json"))) == 1


def test_ambiguous_or_lossy_canonical_input_is_quarantined_with_diagnostics(
    tmp_path: Path,
) -> None:
    bundle, manifest = _canonical_pair()
    manifest = copy.deepcopy(manifest)
    manifest["bundle"]["content_digest"] = "sha256:" + "0" * 64
    projection = dict(manifest)
    projection.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_digest(projection)
    result = GuidedExperience(tmp_path).intake_canonical(json.dumps(bundle), json.dumps(manifest))
    assert result["status"] == "QUARANTINED"
    assert any(item["code"] == "BUNDLE_DIGEST_MISMATCH" for item in result["diagnostics"])
    quarantine = tmp_path / "canonical-intake" / "quarantine" / result["quarantine_handle"]
    assert (quarantine / "bundle.upload").exists()
    assert (quarantine / "diagnostics.json").exists()


def test_duplicate_json_key_is_quarantined_before_schema_validation(tmp_path: Path) -> None:
    _bundle, manifest = _canonical_pair()
    result = GuidedExperience(tmp_path).intake_canonical(
        '{"schema_version":"1.0.0","schema_version":"1.0.0"}',
        json.dumps(manifest),
    )
    assert result["status"] == "QUARANTINED"
    assert result["diagnostics"][0]["code"] == "DUPLICATE_OBJECT_KEY"


def test_native_intake_rejects_symlinked_validated_artifact_directory(
    tmp_path: Path,
) -> None:
    bundle, manifest = _canonical_pair()
    intake_root = tmp_path / "canonical-intake"
    experience = GuidedExperience(tmp_path)
    outside = tmp_path / "outside-validated"
    outside.mkdir()
    digest_name = canonical_digest(bundle).removeprefix("sha256:")
    (intake_root / "validated" / digest_name).symlink_to(outside, target_is_directory=True)

    with pytest.raises(ContractViolation, match="must not be a symbolic link"):
        experience.intake_canonical(json.dumps(bundle), json.dumps(manifest))
    assert list(outside.iterdir()) == []


def test_native_intake_rejects_symlinked_quarantine_artifact_directory(
    tmp_path: Path,
) -> None:
    bundle, manifest = _canonical_pair()
    manifest = copy.deepcopy(manifest)
    manifest["bundle"]["content_digest"] = "sha256:" + "0" * 64
    projection = dict(manifest)
    projection.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_digest(projection)
    bundle_payload = json.dumps(bundle).encode()
    manifest_payload = json.dumps(manifest).encode()
    handle_digest = hashlib.sha256(bundle_payload + b"\0" + manifest_payload).hexdigest()
    handle = f"QUARANTINE-{handle_digest[:20].upper()}"
    intake_root = tmp_path / "canonical-intake"
    experience = GuidedExperience(tmp_path)
    outside = tmp_path / "outside-quarantine"
    outside.mkdir()
    (intake_root / "quarantine" / handle).symlink_to(outside, target_is_directory=True)

    with pytest.raises(ContractViolation, match="must not be a symbolic link"):
        experience.intake_canonical(bundle_payload.decode(), manifest_payload.decode())
    assert list(outside.iterdir()) == []


def test_static_surface_is_mobile_first_and_exposes_all_approval_dimensions() -> None:
    static = ROOT / "src" / "pmpe" / "guided" / "static"
    html = (static / "index.html").read_text()
    css = (static / "styles.css").read_text()
    script = (static / "app.js").read_text()
    assert 'name="viewport"' in html
    assert "aria-live" in html
    assert "Impact" in html and "Reversibility" in html
    assert "Evidence" in html and "Cost" in html and "Permissions" in html
    assert "@media (min-width: 720px)" in css
    assert "/api/guided/approve" in script
    assert "Browse workflow packs" in html
    assert "/api/workflows/catalog" in script


@pytest.mark.parametrize("host", ("::1", "127.0.0.2", "localhost", "not-a-host"))
def test_guided_server_rejects_unsupported_hosts_before_binding(tmp_path: Path, host: str) -> None:
    with pytest.raises(SpecError, match="127.0.0.1"):
        serve(tmp_path, host, 0)


def test_guided_catalog_exposes_governed_tier_two_and_three_packs(tmp_path: Path) -> None:
    catalog = GuidedExperience(tmp_path).workflow_catalog()
    assert catalog["schema_version"] == "1.0.0"
    workflows = catalog["workflows"]
    assert isinstance(workflows, list) and len(workflows) == 21
    assert {item["tier"] for item in workflows} == {1, 2, 3}
    assert all(item["required_inputs"] and item["recovery"] for item in workflows)
