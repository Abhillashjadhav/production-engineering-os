"""One-command, evidence-bound PMOS-to-local-product quickstart."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from pmpe.contracts.authoring import (
    approve_contract_draft,
    build_contract_draft,
    load_json_object,
    verify_contract_approval,
    write_json_atomic,
)
from pmpe.contracts.canonical import canonical_digest
from pmpe.demo.synthetic import run_demo
from pmpe.deployment.local import LocalProcessDeployer
from pmpe.domain.errors import PmpeError
from pmpe.domain.serialize import jsonable
from pmpe.engineering.engine import EngineeringRun
from pmpe.implementation.agent import StdlibCrudGenerator
from pmpe.implementation.workspace import write_files
from pmpe.ingestion.normalizer import normalize_spec
from pmpe.personal.executor import run_personal_execution, write_personal_execution
from pmpe.personal.runtime.demo import run_runtime_demo
from pmpe.personal.synthetic import synthetic_personal_context
from pmpe.planning.planner import EngineeringPlanner
from pmpe.testing.architect import TestArchitect
from pmpe.validation.validator import RequirementValidator

_APPROVER = "quickstart-product-owner"
_APPROVED_AT = "2026-08-20T00:00:00+05:30"


class FullProductError(PmpeError):
    """The full-product workflow could not produce verified local evidence."""


def _artifact(root: Path, stage_id: str, path: Path) -> dict[str, str]:
    value = load_json_object(path)
    return {
        "artifact": path.relative_to(root).as_posix(),
        "artifact_digest": canonical_digest(value),
        "stage_id": stage_id,
        "status": "VERIFIED",
    }


def _decision_answers(repo_root: Path) -> dict[str, Any]:
    contract = load_json_object(repo_root / "examples" / "v2-demo" / "contract.json")
    for field in (
        "approved_at",
        "approved_by",
        "contract_status",
        "source_digest",
        "unresolved_questions",
    ):
        contract.pop(field, None)
    return contract


def _write_decision_and_handoff(root: Path, repo_root: Path) -> tuple[Path, Path, Path]:
    result = build_contract_draft(_decision_answers(repo_root))
    if result.draft is None or result.draft_digest is None:
        raise FullProductError("synthetic product truth did not produce an approvable contract")
    approved = approve_contract_draft(
        result.draft,
        expected_draft_digest=result.draft_digest,
        approver=_APPROVER,
        approved_at=_APPROVED_AT,
    )
    decision = root / "decision"
    contract_path = decision / "contract.json"
    receipt_path = decision / "approval-receipt.json"
    write_json_atomic(contract_path, approved.contract)
    write_json_atomic(receipt_path, approved.receipt)
    verify_contract_approval(approved.contract, approved.receipt, expected_approver=_APPROVER)
    handoff = decision / "engineering-handoff"
    EngineeringRun.start(
        contract_path,
        handoff,
        agents_dir=repo_root / ".claude" / "agents",
        approval_receipt_path=receipt_path,
        expected_approver=_APPROVER,
    )
    return contract_path, receipt_path, handoff / "run-state.json"


def _build_and_deploy_local_product(root: Path, repo_root: Path) -> Path:
    raw = yaml.safe_load((repo_root / "examples" / "taskflow_mvp_spec.yaml").read_text())
    if not isinstance(raw, dict):
        raise FullProductError("local product specification is not an object")
    spec = normalize_spec(raw)
    validation = RequirementValidator().validate(spec)
    if not validation.ok or validation.questions:
        raise FullProductError("local product specification requires unresolved product input")
    plan = EngineeringPlanner().plan(spec)
    generated_tests = TestArchitect().design(spec, plan)
    implementation = StdlibCrudGenerator().implement(spec, plan)
    workspace = root / "local-product" / "workspace"
    workspace.mkdir(parents=True)
    write_files(workspace, generated_tests.files)
    for task in plan.tasks:
        write_files(workspace, implementation.files_by_task.get(task.id, []))
    tests = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=120,
    )
    write_json_atomic(
        root / "local-product" / "generated-test-result.json",
        {
            "returncode": tests.returncode,
            "schema_version": "1.0.0",
            "status": "PASS" if tests.returncode == 0 else "FAIL",
        },
    )
    if tests.returncode != 0:
        raise FullProductError(f"generated product tests failed: {tests.stderr[-500:]}")
    deployer = LocalProcessDeployer()
    deployer.write_artifacts(workspace, spec)
    deployment = deployer.deploy(workspace, spec)
    deployment_path = root / "local-product" / "deployment-result.json"
    write_json_atomic(deployment_path, jsonable(deployment))
    if not (deployment.healthy and deployment.journey_passed):
        raise FullProductError(f"local product deployment failed: {deployment.details}")
    return deployment_path


def run_full_product_quickstart(
    output: Path, *, repo_root: Path, seed: int = 2026
) -> dict[str, Any]:
    root = Path(output)
    if root.exists() and any(root.iterdir()):
        raise FullProductError("full-product output directory must be empty")
    root.mkdir(parents=True, exist_ok=True)
    repo = Path(repo_root).resolve()

    contract_path, receipt_path, handoff_path = _write_decision_and_handoff(root, repo)

    workflows_root = root / "workflows"
    execution = run_personal_execution(synthetic_personal_context(seed))
    workflow_paths = write_personal_execution(workflows_root, execution)

    runtime_paths = run_runtime_demo(root / "runtime")
    run_demo(
        root / "engineering",
        contract=repo / "examples" / "v2-demo" / "contract.json",
        agents_dir=repo / ".claude" / "agents",
        evals_dir=repo / "evals",
    )
    deployment_path = _build_and_deploy_local_product(root, repo)

    stages = [
        _artifact(root, "decision-contract", contract_path),
        _artifact(root, "approval-receipt", receipt_path),
        _artifact(root, "engineering-handoff", handoff_path),
        _artifact(root, "workflow-execution", workflow_paths["report"]),
        _artifact(root, "runtime-assurance", runtime_paths["report"]),
        _artifact(root, "engineering-verification", root / "engineering" / "demo-report.json"),
        _artifact(root, "local-deployment", deployment_path),
    ]
    manifest: dict[str, Any] = {
        "external_provider_writes": 0,
        "label": "SYNTHETIC FULL-PRODUCT QUICKSTART — LOCAL VERIFICATION ONLY",
        "manifest_digest": "",
        "pending_approvals": len(execution.approvals),
        "schema_version": "1.0.0",
        "stages": stages,
        "status": "VERIFIED_LOCAL_PRODUCT",
        "workflow_pack_count": len(execution.results),
    }
    digest_payload = dict(manifest)
    digest_payload.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_digest(digest_payload)
    write_json_atomic(root / "full-product-manifest.json", manifest)
    verify_full_product_quickstart(root)
    return manifest


def _load_stage_artifacts(root: Path, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    stages = manifest.get("stages")
    if not isinstance(stages, list) or len(stages) != 7:
        raise FullProductError("full-product manifest must contain all seven stages")
    artifacts: dict[str, dict[str, Any]] = {}
    root_resolved = root.resolve()
    for stage in stages:
        if not isinstance(stage, dict) or set(stage) != {
            "artifact",
            "artifact_digest",
            "stage_id",
            "status",
        }:
            raise FullProductError("full-product stage has an unexpected shape")
        stage_id = stage["stage_id"]
        if not isinstance(stage_id, str) or stage_id in artifacts or stage["status"] != "VERIFIED":
            raise FullProductError("full-product stage identity or status is invalid")
        path = (root / str(stage["artifact"])).resolve()
        if not path.is_relative_to(root_resolved):
            raise FullProductError("full-product artifact escapes its output directory")
        value = load_json_object(path)
        if canonical_digest(value) != stage["artifact_digest"]:
            raise FullProductError(f"full-product artifact digest mismatch: {stage_id}")
        artifacts[stage_id] = value
    return artifacts


def verify_full_product_quickstart(output: Path) -> str:
    root = Path(output)
    manifest = load_json_object(root / "full-product-manifest.json")
    expected_keys = {
        "external_provider_writes",
        "label",
        "manifest_digest",
        "pending_approvals",
        "schema_version",
        "stages",
        "status",
        "workflow_pack_count",
    }
    if set(manifest) != expected_keys:
        raise FullProductError("full-product manifest has an unexpected shape")
    claimed = manifest["manifest_digest"]
    projection = dict(manifest)
    projection.pop("manifest_digest")
    if claimed != canonical_digest(projection):
        raise FullProductError("full-product manifest digest mismatch")
    artifacts = _load_stage_artifacts(root, manifest)
    expected_stages = {
        "approval-receipt",
        "decision-contract",
        "engineering-handoff",
        "engineering-verification",
        "local-deployment",
        "runtime-assurance",
        "workflow-execution",
    }
    if set(artifacts) != expected_stages:
        raise FullProductError("full-product manifest stage coverage is incomplete")

    contract = artifacts["decision-contract"]
    receipt = artifacts["approval-receipt"]
    verified_receipt = verify_contract_approval(contract, receipt, expected_approver=_APPROVER)
    handoff = artifacts["engineering-handoff"]
    workflows = artifacts["workflow-execution"]
    runtime = artifacts["runtime-assurance"]
    engineering = artifacts["engineering-verification"]
    deployment = artifacts["local-deployment"]
    checks = (
        manifest["schema_version"] == "1.0.0",
        manifest["status"] == "VERIFIED_LOCAL_PRODUCT",
        manifest["workflow_pack_count"] == 21,
        manifest["pending_approvals"] > 0,
        manifest["external_provider_writes"] == 0,
        handoff.get("contract", {}).get("digest") == canonical_digest(contract),
        handoff.get("approval", {}).get("receipt_digest") == verified_receipt,
        workflows.get("status") == "COMPLETED_WITH_PENDING_APPROVALS",
        workflows.get("evidence_complete") is True,
        workflows.get("unauthorized_external_actions") == 0,
        runtime.get("status") == "COMPLETED",
        runtime.get("calendar", {}).get("external_writes") == 0,
        runtime.get("learning", {}).get("installed_regression_cases") == 0,
        engineering.get("release_verdict") == "READY_FOR_PRODUCTION_APPROVAL",
        engineering.get("production_blocked") is True,
        all(engineering.get("release_gates", {}).values()),
        deployment.get("environment") == "local",
        deployment.get("healthy") is True,
        deployment.get("journey_passed") is True,
    )
    if not all(checks):
        raise FullProductError("full-product semantic verification failed")
    return str(claimed)
