"""Issue #127: one-command PMOS-to-local-product evidence workflow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
    assert deployment["healthy"] is True
    assert deployment["journey_passed"] is True
    assert verify_full_product_quickstart(output) == manifest["manifest_digest"]


def test_full_product_verifier_rejects_tampered_deployment(repo_root: Path, tmp_path: Path) -> None:
    output = tmp_path / "full-product"
    run_full_product_quickstart(output, repo_root=repo_root)
    deployment = output / "local-product" / "deployment-result.json"
    value = json.loads(deployment.read_text())
    value["healthy"] = False
    deployment.write_text(json.dumps(value))
    with pytest.raises(FullProductError, match="artifact digest mismatch"):
        verify_full_product_quickstart(output)
