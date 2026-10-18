"""Built-in product admission and required checks (SYS-02, issue #245)."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from pmpe.barebones import default_template
from pmpe.cli import main
from pmpe.contracts.canonical import canonical_digest
from pmpe.core_harness import compile_required_harness
from pmpe.product_checks import candidate_manifest_digest, evaluate_required_checks
from pmpe.product_profile import ProductProfileError, compile_product_profile
from pmpe.task_tracker_harness import fixed_template

ROOT = Path(__file__).resolve().parents[2]


def _e1() -> dict[str, object]:
    return dict(json.loads((ROOT / "examples/barebones/e1-contract.json").read_text()))


def _tracker() -> tuple[dict[str, object], dict[str, object]]:
    contract = json.loads(
        (ROOT / "examples/pmos-task-tracker/approved/contract-approved.json").read_text()
    )
    mapping = json.loads(
        (ROOT / "examples/pmos-task-tracker/mapped/core-harness-mapping.json").read_text()
    )
    return contract, mapping


def test_profiles_bind_exact_template_and_trusted_harness() -> None:
    e1 = _e1()
    profile = compile_product_profile(
        "barebones-health-v1", contract=e1, template=default_template(), harness_plan=None
    )
    assert profile.template_version == "barebones-1"
    assert profile.capability_ids == ("e1.health",)
    assert profile.manifest_digest == canonical_digest(profile.manifest)
    assert profile.manifest["permitted_dependencies"] == ["python-stdlib"]
    assert profile.manifest["lockfiles"] == []
    assert profile.manifest["runtime_integrations"] == []
    assert profile.manifest["configuration_schema"]["additionalProperties"] is False
    assert "delivery" in {item.stage for item in profile.checks}
    assert all(item.required for item in profile.checks)
    readiness = json.loads((ROOT / "examples/barebones/readiness-contract.json").read_text())
    readiness_profile = compile_product_profile(
        "barebones-health-v1", contract=readiness, template=default_template(), harness_plan=None
    )
    assert readiness_profile.criterion_ids == ("AC-001", "AC-002", "AC-003")

    tracker, mapping = _tracker()
    harness = compile_required_harness(tracker, mapping)
    assert harness is not None
    profile = compile_product_profile(
        "pmos-task-tracker-v1", contract=tracker, template=fixed_template(), harness_plan=harness
    )
    assert profile.capability_ids == (
        "task.complete",
        "task.create",
        "task.filter",
        "task.persist",
        "task.repeat",
        "task.validate",
    )
    assert profile.criterion_ids == tuple(f"AC-{n:03d}" for n in range(1, 15))
    assert profile.harness_digest == tracker["required_harness_digest"]
    assert profile.manifest["entrypoint"] == ["python", "product.py", "--store", "<local-path>"]


def test_profile_rejects_mismatch_and_capability_gap_before_execution() -> None:
    tracker, mapping = _tracker()
    harness = compile_required_harness(tracker, mapping)
    assert harness is not None
    with pytest.raises(ProductProfileError, match="template"):
        compile_product_profile(
            "pmos-task-tracker-v1",
            contract=tracker,
            template=default_template(),
            harness_plan=harness,
        )
    with pytest.raises(ProductProfileError, match="harness"):
        compile_product_profile(
            "pmos-task-tracker-v1", contract=tracker, template=fixed_template(), harness_plan=None
        )
    mutated = json.loads(json.dumps(tracker))
    mutated["functional_requirements"].append(
        {
            "id": "FR-999",
            "capability": "account.multi_user",
            "title": "Users",
            "description": "Private users",
        }
    )
    with pytest.raises(ProductProfileError, match="account.multi_user"):
        compile_product_profile(
            "pmos-task-tracker-v1",
            contract=mutated,
            template=fixed_template(),
            harness_plan=harness,
        )
    with pytest.raises(ProductProfileError, match="health"):
        compile_product_profile(
            "barebones-health-v1", contract=tracker, template=default_template(), harness_plan=None
        )


def test_missing_or_untrusted_observations_never_qualify() -> None:
    profile = compile_product_profile(
        "barebones-health-v1", contract=_e1(), template=default_template(), harness_plan=None
    )
    source = {"product.py": b"def health():\n    return {'status': 'ok'}\n"}
    report = evaluate_required_checks(
        profile,
        candidate_digest=candidate_manifest_digest(source),
        source_files=source,
        acceptance_observations={},
        security_findings=(),
    )
    assert report.candidate_qualified is False
    assert report.delivery_qualified is False
    assert {result.status for result in report.results} >= {"PASS", "BLOCKED"}
    assert report.binding_digest == canonical_digest(report.binding)
    assert (
        next(item for item in report.results if item.check_id == "functional-acceptance").status
        == "BLOCKED"
    )

    observation = {
        "AC-001": {
            "criterion_id": "AC-001",
            "assertions_passed": True,
            "response_digest": canonical_digest({"status": "ok"}),
        }
    }
    report = evaluate_required_checks(
        profile,
        candidate_digest=candidate_manifest_digest(source),
        source_files=source,
        acceptance_observations=observation,
        security_findings=(),
    )
    assert report.candidate_qualified is True
    assert report.delivery_qualified is False
    assert (
        next(item for item in report.results if item.check_id == "functional-acceptance").status
        == "PASS"
    )
    assert (
        next(item for item in report.results if item.check_id == "dependency-security").status
        == "BLOCKED"
    )


def test_syntax_or_security_failure_blocks_candidate_and_binding_tampering() -> None:
    profile = compile_product_profile(
        "barebones-health-v1", contract=_e1(), template=default_template(), harness_plan=None
    )
    observation = {
        "AC-001": {
            "criterion_id": "AC-001",
            "assertions_passed": True,
            "response_digest": canonical_digest({"status": "ok"}),
        }
    }
    source = {"product.py": b"def health(:\n"}
    result = evaluate_required_checks(
        profile,
        candidate_digest=candidate_manifest_digest(source),
        source_files=source,
        acceptance_observations=observation,
        security_findings=("SEC_TEST",),
    )
    assert result.candidate_qualified is False
    assert (
        next(item for item in result.results if item.check_id == "python-syntax").status == "FAIL"
    )
    assert (
        next(item for item in result.results if item.check_id == "source-security").status == "FAIL"
    )
    with pytest.raises(ProductProfileError, match="binding"):
        evaluate_required_checks(
            replace(profile, manifest_digest="sha256:" + "0" * 64),
            candidate_digest=candidate_manifest_digest({}),
            source_files={},
            acceptance_observations={},
            security_findings=(),
        )
    with pytest.raises(ProductProfileError, match="candidate manifest binding"):
        evaluate_required_checks(
            profile,
            candidate_digest=candidate_manifest_digest({}),
            source_files=source,
            acceptance_observations=observation,
            security_findings=(),
        )


def test_cli_compiles_profile_and_rejects_mismatch_before_provider(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    contract = ROOT / "examples/barebones/e1-contract.json"
    assert main(["barebones", "compile", str(contract), "--profile", "barebones-health-v1"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["product_profile"]["profile_id"] == "barebones-health-v1"
    assert output["product_profile"]["manifest_digest"].startswith("sha256:")

    marker = tmp_path / "called"
    command = tmp_path / "provider.py"
    command.write_text(f"from pathlib import Path; Path({str(marker)!r}).touch()")
    assert (
        main(
            [
                "barebones",
                "run",
                str(contract),
                "--profile",
                "pmos-task-tracker-v1",
                "--workspace",
                str(tmp_path / "candidate"),
                "--run-id",
                "profile-mismatch",
                "--repository-root",
                str(tmp_path),
                "--approval-receipt",
                str(ROOT / "examples/barebones/e1-approval-receipt.json"),
                "--expected-approver",
                "fixture-human",
                "--provider-command",
                f"{sys.executable} {command}",
            ]
        )
        == 3
    )
    output = json.loads(capsys.readouterr().out)
    assert output["cause"] == "CONTRACT_INVALID"
    assert "template" in output["detail"]
    assert not marker.exists()
