"""Issue #127: one-command PMOS-to-local-product evidence workflow."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pmpe.contracts.canonical import canonical_digest
from pmpe.full_product import (
    FullProductError,
    run_full_product_quickstart,
    verify_full_product_quickstart,
)


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
    assert (
        verify_full_product_quickstart(output, expected_digest=manifest["manifest_digest"])
        == manifest["manifest_digest"]
    )


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


@pytest.mark.parametrize("stage_id", ["workflow-execution", "runtime-assurance"])
def test_full_product_verifier_rejects_unbound_assurance_stage(
    repo_root: Path, tmp_path: Path, stage_id: str
) -> None:
    output = tmp_path / "full-product"
    manifest = run_full_product_quickstart(output, repo_root=repo_root)
    stage = next(item for item in manifest["stages"] if item["stage_id"] == stage_id)
    index_path = output / stage["artifact"]
    index = json.loads(index_path.read_text())
    directory = output / index["directory"]
    report_path = directory / index["report"]
    report = json.loads(report_path.read_text())
    report["product_contract_binding"]["approved_contract_digest"] = "sha256:unbound"
    report_path.write_text(json.dumps(report))
    report_relative = report_path.relative_to(directory).as_posix()
    report_entry = next(item for item in index["files"] if item["path"] == report_relative)
    report_entry["digest"] = f"sha256:{hashlib.sha256(report_path.read_bytes()).hexdigest()}"
    report_entry["size"] = report_path.stat().st_size
    index_path.write_text(json.dumps(index))
    stage["artifact_digest"] = canonical_digest(index)
    manifest_projection = dict(manifest)
    manifest_projection.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_digest(manifest_projection)
    (output / "full-product-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(FullProductError, match="semantic verification failed"):
        verify_full_product_quickstart(output, expected_digest=str(manifest["manifest_digest"]))
