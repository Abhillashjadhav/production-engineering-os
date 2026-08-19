"""Issue #127: one-command PMOS-to-local-product evidence workflow."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from pmpe.contracts.canonical import canonical_digest
from pmpe.engineering.candidate import tree_content_digest
from pmpe.full_product import (
    FullProductError,
    run_full_product_quickstart,
    verify_full_product_quickstart,
)


def _rebuild_stage(
    output: Path,
    manifest: dict[str, Any],
    stage_id: str,
    changed_paths: tuple[Path, ...],
) -> str:
    stages = manifest["stages"]
    assert isinstance(stages, list)
    stage = next(item for item in stages if item["stage_id"] == stage_id)
    index_path = output / stage["artifact"]
    index = json.loads(index_path.read_text())
    directory = output / index["directory"]
    for path in changed_paths:
        relative = path.relative_to(directory).as_posix()
        entry = next(item for item in index["files"] if item["path"] == relative)
        entry["digest"] = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        entry["size"] = path.stat().st_size
    index_path.write_text(json.dumps(index))
    stage["artifact_digest"] = canonical_digest(index)
    manifest_projection = dict(manifest)
    manifest_projection.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_digest(manifest_projection)
    (output / "full-product-manifest.json").write_text(json.dumps(manifest))
    return str(manifest["manifest_digest"])


def test_full_product_quickstart_runs_and_reverifies(repo_root: Path, tmp_path: Path) -> None:
    output = tmp_path / "full-product"
    manifest = run_full_product_quickstart(output, repo_root=repo_root)
    assert manifest["status"] == "VERIFIED_LOCAL_PRODUCT"
    assert manifest["workflow_pack_count"] == 21
    assert manifest["external_provider_writes"] == 0
    assert [stage["stage_id"] for stage in manifest["stages"]] == [
        "decision-contract",
        "approval-receipt",
        "engineering-handoff",
        "workflow-execution",
        "runtime-assurance",
        "engineering-verification",
        "local-deployment",
    ]
    deployment = json.loads((output / "local-product" / "deployment-result.json").read_text())
    assert deployment["result"]["healthy"] is True
    assert deployment["result"]["journey_passed"] is True
    assert deployment["contract_digest"] == manifest["stages"][0]["artifact_digest"]
    contract = json.loads((output / "decision" / "contract.json").read_text())
    engineering = json.loads(
        (output / "local-product" / "engineering-verification.json").read_text()
    )
    approved_spec = next(
        item for item in contract["approved_product_decisions"] if item["id"] == "APD-SPEC-001"
    )
    assert approved_spec["decision"] == (
        f"Build the exact TaskFlow specification {engineering['source_spec_digest']}."
    )
    workflow_report = json.loads(
        (output / "workflows" / "personal-execution-report.json").read_text()
    )
    workflow_report_projection = dict(workflow_report)
    workflow_report_digest = workflow_report_projection.pop("report_digest")
    assert canonical_digest(workflow_report_projection) == workflow_report_digest
    assert (
        verify_full_product_quickstart(output, expected_digest=manifest["manifest_digest"])
        == manifest["manifest_digest"]
    )


def test_full_product_quickstart_rejects_file_output(repo_root: Path, tmp_path: Path) -> None:
    output = tmp_path / "not-a-directory"
    output.write_text("occupied by a file")
    with pytest.raises(FullProductError, match="output must be a directory"):
        run_full_product_quickstart(output, repo_root=repo_root)


def test_full_product_quickstart_rejects_dangling_symlink_output(
    repo_root: Path, tmp_path: Path
) -> None:
    output = tmp_path / "dangling-output"
    output.symlink_to(tmp_path / "missing-target", target_is_directory=True)
    with pytest.raises(FullProductError, match="output must be a directory"):
        run_full_product_quickstart(output, repo_root=repo_root)


def test_full_product_quickstart_normalizes_malformed_yaml(tmp_path: Path) -> None:
    repo_root = tmp_path / "malformed-repo"
    examples = repo_root / "examples"
    examples.mkdir(parents=True)
    (examples / "taskflow_mvp_spec.yaml").write_text("scope: [unterminated\n")
    with pytest.raises(FullProductError, match="input or output is invalid"):
        run_full_product_quickstart(tmp_path / "output", repo_root=repo_root)


def test_full_product_verifier_rejects_tampered_deployment(repo_root: Path, tmp_path: Path) -> None:
    output = tmp_path / "full-product"
    run_full_product_quickstart(output, repo_root=repo_root)
    deployment = output / "local-product" / "deployment-result.json"
    value = json.loads(deployment.read_text())
    value["result"]["healthy"] = False
    deployment.write_text(json.dumps(value))
    manifest_path = output / "full-product-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["stages"][-1]["artifact_digest"] = canonical_digest(value)
    projection = dict(manifest)
    projection.pop("manifest_digest")
    original_trusted_digest = manifest["manifest_digest"]
    manifest["manifest_digest"] = canonical_digest(projection)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(FullProductError, match="trusted expected digest"):
        verify_full_product_quickstart(output, expected_digest=original_trusted_digest)


def test_full_product_verifier_rejects_tampered_retained_candidate(
    repo_root: Path, tmp_path: Path
) -> None:
    output = tmp_path / "full-product"
    manifest = run_full_product_quickstart(output, repo_root=repo_root)
    (output / "local-product" / "workspace" / "app" / "api.py").write_text(
        "# tampered after deployment\n"
    )
    with pytest.raises(FullProductError, match="semantic verification failed"):
        verify_full_product_quickstart(output, expected_digest=manifest["manifest_digest"])


def test_full_product_verifier_rejects_reintroduced_bytecode(
    repo_root: Path, tmp_path: Path
) -> None:
    output = tmp_path / "full-product"
    manifest = run_full_product_quickstart(output, repo_root=repo_root)
    cache = output / "local-product" / "workspace" / "app" / "__pycache__"
    cache.mkdir()
    (cache / "api.cpython-311.pyc").write_bytes(b"unverified executable bytecode")
    with pytest.raises(FullProductError, match="contains executable bytecode"):
        verify_full_product_quickstart(output, expected_digest=manifest["manifest_digest"])


@pytest.mark.parametrize(
    "relative",
    ["workflows/workflow-results.json", "runtime/runtime-events.jsonl"],
)
def test_full_product_verifier_requires_all_indexed_evidence(
    repo_root: Path, tmp_path: Path, relative: str
) -> None:
    output = tmp_path / "full-product"
    manifest = run_full_product_quickstart(output, repo_root=repo_root)
    (output / relative).unlink()
    with pytest.raises(FullProductError, match="evidence index path is missing"):
        verify_full_product_quickstart(output, expected_digest=manifest["manifest_digest"])


def test_full_product_verifier_rejects_nested_index_name(repo_root: Path, tmp_path: Path) -> None:
    output = tmp_path / "full-product"
    manifest = run_full_product_quickstart(output, repo_root=repo_root)
    nested = output / "runtime" / "untrusted"
    nested.mkdir()
    (nested / "evidence-index.json").write_text("{}")
    with pytest.raises(FullProductError, match="does not exactly cover"):
        verify_full_product_quickstart(output, expected_digest=manifest["manifest_digest"])


def test_full_product_verifier_rejects_directory_symlink(repo_root: Path, tmp_path: Path) -> None:
    output = tmp_path / "full-product"
    manifest = run_full_product_quickstart(output, repo_root=repo_root)
    outside = tmp_path / "outside"
    outside.mkdir()
    (output / "runtime" / "untrusted").symlink_to(outside, target_is_directory=True)
    with pytest.raises(FullProductError, match="refuses symbolic link"):
        verify_full_product_quickstart(output, expected_digest=manifest["manifest_digest"])


def test_full_product_verifier_rejects_indexed_directory_symlink(
    repo_root: Path, tmp_path: Path
) -> None:
    output = tmp_path / "full-product"
    manifest = run_full_product_quickstart(output, repo_root=repo_root)
    runtime = output / "runtime"
    retained_runtime = output / "retained-runtime"
    runtime.rename(retained_runtime)
    runtime.symlink_to(retained_runtime, target_is_directory=True)
    with pytest.raises(FullProductError, match="refuses symbolic link"):
        verify_full_product_quickstart(output, expected_digest=manifest["manifest_digest"])


def test_full_product_verifier_rejects_retained_workspace_symlinks(
    repo_root: Path, tmp_path: Path
) -> None:
    output = tmp_path / "full-product"
    manifest = run_full_product_quickstart(output, repo_root=repo_root)
    workspace = output / "local-product" / "workspace"
    outside_file = tmp_path / "outside.py"
    outside_file.write_text("# outside retained candidate\n")
    nested_link = workspace / "outside.py"
    nested_link.symlink_to(outside_file)
    with pytest.raises(FullProductError, match="refuses symbolic link"):
        verify_full_product_quickstart(output, expected_digest=manifest["manifest_digest"])
    nested_link.unlink()
    retained_workspace = tmp_path / "retained-workspace"
    workspace.rename(retained_workspace)
    workspace.symlink_to(retained_workspace, target_is_directory=True)
    with pytest.raises(FullProductError, match="refuses symbolic link"):
        verify_full_product_quickstart(output, expected_digest=manifest["manifest_digest"])


@pytest.mark.parametrize(
    ("stage_id", "source_name"),
    [
        ("workflow-execution", "synthetic-personal-input.json"),
        ("runtime-assurance", "synthetic-runtime-input.json"),
    ],
)
def test_full_product_verifier_rejects_fixture_not_bound_to_execution(
    repo_root: Path, tmp_path: Path, stage_id: str, source_name: str
) -> None:
    output = tmp_path / "full-product"
    manifest = run_full_product_quickstart(output, repo_root=repo_root)
    stage = next(item for item in manifest["stages"] if item["stage_id"] == stage_id)
    index_path = output / stage["artifact"]
    index = json.loads(index_path.read_text())
    directory = output / index["directory"]
    source_path = directory / source_name
    source = json.loads(source_path.read_text())
    if stage_id == "runtime-assurance":
        source["contract"]["outcome"] = "Tampered after runtime execution."
    else:
        source["tampered_after_execution"] = True
    source_path.write_text(json.dumps(source))
    binding_path = directory / "product-contract-binding.json"
    binding = json.loads(binding_path.read_text())
    binding["source_fixture_digest"] = canonical_digest(source)
    binding_path.write_text(json.dumps(binding))
    for path in (source_path, binding_path):
        relative = path.relative_to(directory).as_posix()
        entry = next(item for item in index["files"] if item["path"] == relative)
        entry["digest"] = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
        entry["size"] = path.stat().st_size
    index_path.write_text(json.dumps(index))
    stage["artifact_digest"] = canonical_digest(index)
    manifest_projection = dict(manifest)
    manifest_projection.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_digest(manifest_projection)
    (output / "full-product-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(FullProductError, match="semantic verification failed"):
        verify_full_product_quickstart(output, expected_digest=str(manifest["manifest_digest"]))


def test_full_product_verifier_recomputes_workflow_result_digest(
    repo_root: Path, tmp_path: Path
) -> None:
    output = tmp_path / "full-product"
    manifest = run_full_product_quickstart(output, repo_root=repo_root)
    stage = next(item for item in manifest["stages"] if item["stage_id"] == "workflow-execution")
    index_path = output / stage["artifact"]
    index = json.loads(index_path.read_text())
    directory = output / index["directory"]
    results_path = directory / "workflow-results.json"
    results = json.loads(results_path.read_text())
    results["results"][0]["output"]["headline"] = "Tampered after execution."
    results_path.write_text(json.dumps(results))
    entry = next(item for item in index["files"] if item["path"] == "workflow-results.json")
    entry["digest"] = f"sha256:{hashlib.sha256(results_path.read_bytes()).hexdigest()}"
    entry["size"] = results_path.stat().st_size
    index_path.write_text(json.dumps(index))
    stage["artifact_digest"] = canonical_digest(index)
    manifest_projection = dict(manifest)
    manifest_projection.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_digest(manifest_projection)
    (output / "full-product-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(FullProductError, match="semantic verification failed"):
        verify_full_product_quickstart(output, expected_digest=str(manifest["manifest_digest"]))


def test_full_product_verifier_recompiles_task_graph(repo_root: Path, tmp_path: Path) -> None:
    output = tmp_path / "full-product"
    manifest = run_full_product_quickstart(output, repo_root=repo_root)
    task_graph_path = output / "workflows" / "task-graph.json"
    results_path = output / "workflows" / "workflow-results.json"
    report_path = output / "workflows" / "personal-execution-report.json"
    task_graph = json.loads(task_graph_path.read_text())
    packet = task_graph["tasks"][0]
    packet["objective"] = "Tampered objective that the retained contract did not compile."
    packet_projection = dict(packet)
    packet_projection.pop("packet_digest")
    packet["packet_digest"] = canonical_digest(packet_projection)
    task_graph["task_graph_digest"] = canonical_digest({"tasks": task_graph["tasks"]})
    task_graph_path.write_text(json.dumps(task_graph))
    results = json.loads(results_path.read_text())
    result = next(item for item in results["results"] if item["task_id"] == packet["task_id"])
    result["packet_digest"] = packet["packet_digest"]
    result_projection = dict(result)
    result_projection.pop("result_digest")
    result["result_digest"] = canonical_digest(result_projection)
    results_path.write_text(json.dumps(results))
    report = json.loads(report_path.read_text())
    report["task_graph_digest"] = task_graph["task_graph_digest"]
    report["result_digests"] = [item["result_digest"] for item in results["results"]]
    report_projection = dict(report)
    report_projection.pop("report_digest")
    report["report_digest"] = canonical_digest(report_projection)
    report_path.write_text(json.dumps(report))
    expected = _rebuild_stage(
        output,
        manifest,
        "workflow-execution",
        (task_graph_path, results_path, report_path),
    )
    with pytest.raises(FullProductError, match="semantic verification failed"):
        verify_full_product_quickstart(output, expected_digest=expected)


def test_full_product_verifier_requires_one_result_per_task(
    repo_root: Path, tmp_path: Path
) -> None:
    output = tmp_path / "full-product"
    manifest = run_full_product_quickstart(output, repo_root=repo_root)
    results_path = output / "workflows" / "workflow-results.json"
    report_path = output / "workflows" / "personal-execution-report.json"
    results = json.loads(results_path.read_text())
    results["results"].pop()
    results_path.write_text(json.dumps(results))
    report = json.loads(report_path.read_text())
    report["result_digests"] = [item["result_digest"] for item in results["results"]]
    report_projection = dict(report)
    report_projection.pop("report_digest")
    report["report_digest"] = canonical_digest(report_projection)
    report_path.write_text(json.dumps(report))
    expected = _rebuild_stage(output, manifest, "workflow-execution", (results_path, report_path))
    with pytest.raises(FullProductError, match="semantic verification failed"):
        verify_full_product_quickstart(output, expected_digest=expected)


def test_full_product_verifier_fails_closed_on_malformed_worker_output(
    repo_root: Path, tmp_path: Path
) -> None:
    output = tmp_path / "full-product"
    manifest = run_full_product_quickstart(output, repo_root=repo_root)
    results_path = output / "workflows" / "workflow-results.json"
    report_path = output / "workflows" / "personal-execution-report.json"
    results = json.loads(results_path.read_text())
    result = results["results"][0]
    result["output"]["details"] = "malformed"
    result_projection = dict(result)
    result_projection.pop("result_digest")
    result["result_digest"] = canonical_digest(result_projection)
    results_path.write_text(json.dumps(results))
    report = json.loads(report_path.read_text())
    report["result_digests"] = [item["result_digest"] for item in results["results"]]
    report_projection = dict(report)
    report_projection.pop("report_digest")
    report["report_digest"] = canonical_digest(report_projection)
    report_path.write_text(json.dumps(report))
    expected = _rebuild_stage(output, manifest, "workflow-execution", (results_path, report_path))
    with pytest.raises(FullProductError, match="semantic verification failed"):
        verify_full_product_quickstart(output, expected_digest=expected)


def test_full_product_verifier_replays_runtime_semantics(repo_root: Path, tmp_path: Path) -> None:
    output = tmp_path / "full-product"
    manifest = run_full_product_quickstart(output, repo_root=repo_root)
    events_path = output / "runtime" / "runtime-events.jsonl"
    report_path = output / "runtime" / "runtime-assurance-report.json"
    first_event_line = events_path.read_bytes().splitlines()[0]
    first_event = json.loads(first_event_line)
    events_path.write_bytes(first_event_line + b"\n")
    report = json.loads(report_path.read_text())
    report["event_count"] = 1
    report["event_registry_head"] = first_event["event_digest"]
    report_path.write_text(json.dumps(report))
    expected = _rebuild_stage(output, manifest, "runtime-assurance", (events_path, report_path))
    with pytest.raises(FullProductError, match="semantic verification failed"):
        verify_full_product_quickstart(output, expected_digest=expected)


def test_full_product_verifier_rejects_malformed_manifest_types(
    repo_root: Path, tmp_path: Path
) -> None:
    output = tmp_path / "full-product"
    manifest = run_full_product_quickstart(output, repo_root=repo_root)
    manifest["pending_approvals"] = "1"
    projection = dict(manifest)
    projection.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_digest(projection)
    (output / "full-product-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(FullProductError, match="value types"):
        verify_full_product_quickstart(output, expected_digest=str(manifest["manifest_digest"]))


def test_full_product_verifier_matches_pending_approval_count(
    repo_root: Path, tmp_path: Path
) -> None:
    output = tmp_path / "full-product"
    manifest = run_full_product_quickstart(output, repo_root=repo_root)
    manifest["pending_approvals"] = 1
    projection = dict(manifest)
    projection.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_digest(projection)
    (output / "full-product-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(FullProductError, match="semantic verification failed"):
        verify_full_product_quickstart(output, expected_digest=str(manifest["manifest_digest"]))


def test_full_product_verifier_rejects_malformed_deployment_result(
    repo_root: Path, tmp_path: Path
) -> None:
    output = tmp_path / "full-product"
    manifest = run_full_product_quickstart(output, repo_root=repo_root)
    stages = manifest["stages"]
    stage = next(item for item in stages if item["stage_id"] == "local-deployment")
    deployment_path = output / stage["artifact"]
    deployment = json.loads(deployment_path.read_text())
    deployment["result"] = []
    deployment_path.write_text(json.dumps(deployment))
    stage["artifact_digest"] = canonical_digest(deployment)
    projection = dict(manifest)
    projection.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_digest(projection)
    (output / "full-product-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(FullProductError, match="deployment result is not an object"):
        verify_full_product_quickstart(output, expected_digest=str(manifest["manifest_digest"]))


def test_full_product_verifier_binds_generated_test_result(repo_root: Path, tmp_path: Path) -> None:
    output = tmp_path / "full-product"
    manifest = run_full_product_quickstart(output, repo_root=repo_root)
    result_path = output / "local-product" / "generated-test-result.json"
    result = json.loads(result_path.read_text())
    result["returncode"] = 1
    result["status"] = "FAIL"
    result_path.write_text(json.dumps(result))
    with pytest.raises(FullProductError, match="semantic verification failed"):
        verify_full_product_quickstart(output, expected_digest=str(manifest["manifest_digest"]))


def test_full_product_verifier_rejects_malformed_engineering_findings(
    repo_root: Path, tmp_path: Path
) -> None:
    output = tmp_path / "full-product"
    manifest = run_full_product_quickstart(output, repo_root=repo_root)
    stages = manifest["stages"]
    stage = next(item for item in stages if item["stage_id"] == "engineering-verification")
    engineering_path = output / stage["artifact"]
    engineering = json.loads(engineering_path.read_text())
    engineering["final_review"]["findings"] = [None]
    engineering_path.write_text(json.dumps(engineering))
    stage["artifact_digest"] = canonical_digest(engineering)
    projection = dict(manifest)
    projection.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_digest(projection)
    (output / "full-product-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(FullProductError, match="final review findings are malformed"):
        verify_full_product_quickstart(output, expected_digest=str(manifest["manifest_digest"]))


def test_full_product_verifier_binds_tests_to_candidate(repo_root: Path, tmp_path: Path) -> None:
    output = tmp_path / "full-product"
    manifest = run_full_product_quickstart(output, repo_root=repo_root)
    workspace = output / "local-product" / "workspace"
    (workspace / "app" / "api.py").write_text("this is invalid python !!!\n")
    candidate_digest = tree_content_digest(workspace)
    stages = manifest["stages"]
    engineering_stage = next(
        item for item in stages if item["stage_id"] == "engineering-verification"
    )
    engineering_path = output / engineering_stage["artifact"]
    engineering = json.loads(engineering_path.read_text())
    engineering["candidate_digest"] = candidate_digest
    engineering_path.write_text(json.dumps(engineering))
    engineering_stage["artifact_digest"] = canonical_digest(engineering)
    deployment_stage = next(item for item in stages if item["stage_id"] == "local-deployment")
    deployment_path = output / deployment_stage["artifact"]
    deployment = json.loads(deployment_path.read_text())
    deployment["candidate_digest"] = candidate_digest
    deployment_path.write_text(json.dumps(deployment))
    deployment_stage["artifact_digest"] = canonical_digest(deployment)
    projection = dict(manifest)
    projection.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_digest(projection)
    (output / "full-product-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(FullProductError, match="semantic verification failed"):
        verify_full_product_quickstart(output, expected_digest=str(manifest["manifest_digest"]))


def test_full_product_verifier_rejects_malformed_handoff_objects(
    repo_root: Path, tmp_path: Path
) -> None:
    output = tmp_path / "full-product"
    manifest = run_full_product_quickstart(output, repo_root=repo_root)
    stages = manifest["stages"]
    stage = next(item for item in stages if item["stage_id"] == "engineering-handoff")
    handoff_path = output / stage["artifact"]
    handoff = json.loads(handoff_path.read_text())
    handoff["contract"] = []
    handoff_path.write_text(json.dumps(handoff))
    stage["artifact_digest"] = canonical_digest(handoff)
    projection = dict(manifest)
    projection.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_digest(projection)
    (output / "full-product-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(FullProductError, match="handoff contract or approval"):
        verify_full_product_quickstart(output, expected_digest=str(manifest["manifest_digest"]))
