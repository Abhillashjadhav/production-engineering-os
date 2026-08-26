from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pmpe.barebones import RunState, run_to_release_ready
from pmpe.contracts.canonical import canonical_digest
from pmpe.evals import real_behavior_drift_eval as drift_eval

_METADATA = {
    "provider": "scripted-fixture",
    "model": "deterministic-e1",
    "prompt_version": "e1-v1",
}


class E1Provider:
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if purpose == "code":
            return {
                "request_digest": request["request_digest"],
                "provider_metadata": _METADATA,
                "files": {
                    "product.py": (
                        '"""E1 health product."""\n\n'
                        "def health() -> dict[str, str]:\n"
                        '    return {"status": "ok"}\n'
                    )
                },
            }
        return {
            "request_digest": request["request_digest"],
            "summary": "Deterministic evidence passed; human may release.",
            "provider_metadata": _METADATA,
        }


class ReadinessProvider:
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if purpose == "code":
            return {
                "request_digest": request["request_digest"],
                "provider_metadata": _METADATA,
                "files": {
                    "product.py": (
                        '"""Readiness evidence product."""\n\n'
                        "def health() -> dict[str, object]:\n"
                        "    return {\n"
                        '        "status": "ok",\n'
                        '        "component": "readiness-api",\n'
                        '        "checks": ["contract", "sandbox"],\n'
                        "    }\n"
                    )
                },
            }
        return {
            "request_digest": request["request_digest"],
            "summary": "Deterministic readiness evidence passed.",
            "provider_metadata": _METADATA,
        }


def _prove_private_source_wrapper_with_nested_candidate_sandbox(tmp_path: Path) -> None:
    environment = drift_eval._sanitized_environment()
    git_executable = shutil.which("git", path=environment.get("PATH"))
    bwrap_executable = shutil.which("bwrap", path=environment.get("PATH"))
    assert git_executable is not None
    assert bwrap_executable is not None
    git_head = drift_eval._checked_output(
        [git_executable, "rev-parse", "HEAD"],
        environment=environment,
    )
    source_checkout = tmp_path / "source-snapshot"

    try:
        identity = drift_eval._materialize_source_snapshot(
            source_checkout,
            git_executable=git_executable,
            git_head=git_head,
            environment=environment,
        )
        provider = source_checkout / "examples/barebones/e1-provider.py"
        original_provider = provider.read_bytes()
        mutation = (
            "from pathlib import Path;"
            f"path=Path({str(provider)!r});"
            "path.chmod(0o644);path.write_text('tampered')"
        )

        mutation_exit, _ = drift_eval._snapshot_command(
            [sys.executable, "-I", "-c", mutation],
            bwrap_executable=bwrap_executable,
            environment=environment,
            expected_tree_digest=identity["tree_digest"],
            source_checkout=source_checkout,
            timeout=30,
        )

        assert mutation_exit != 0
        assert provider.read_bytes() == original_provider

        evidence_root = tmp_path / "snapshot-evidence"
        candidate = tmp_path / "snapshot-candidate"
        provider_command = f"{shlex.quote(sys.executable)} {shlex.quote(str(provider))}"
        exit_code, output = drift_eval._snapshot_command(
            [
                *drift_eval._pmpe_command(source_checkout),
                "barebones",
                "run",
                str(source_checkout / "examples/barebones/e1-contract.json"),
                "--workspace",
                str(candidate),
                "--run-id",
                "snapshot-nested-sandbox",
                "--repository-root",
                str(evidence_root),
                "--approval-receipt",
                str(source_checkout / "examples/barebones/e1-approval-receipt.json"),
                "--expected-approver",
                "fixture-human",
                "--provider-command",
                provider_command,
                "--provider-timeout",
                "30",
            ],
            bwrap_executable=bwrap_executable,
            environment=environment,
            expected_tree_digest=identity["tree_digest"],
            source_checkout=source_checkout,
            timeout=120,
        )

        assert exit_code == 0, output
        result = json.loads(output)
        assert result["state"] == "RELEASE_READY"
    finally:
        if source_checkout.exists():
            for path in sorted(source_checkout.rglob("*"), key=lambda item: len(item.parts)):
                if not path.is_symlink():
                    path.chmod(0o755 if path.is_dir() else 0o644)
            source_checkout.chmod(0o755)


def test_e1_real_contract_reaches_release_ready(tmp_path: Path) -> None:
    contract = {
        "contract_id": "PMOS-E1",
        "functional_requirements": {"FR-001": {"statement": "health reports ok"}},
        "acceptance_criteria": {
            "AC-001": {
                "requirement_refs": ["FR-001"],
                "given": [{"path": "service.running", "operator": "eq", "value": True}],
                "when": {"action": "health", "arguments": {}},
                "then": [{"path": "result.status", "operator": "eq", "value": "ok"}],
            }
        },
    }

    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="e1-real-contract",
        provider=E1Provider(),
    )

    assert result.state is RunState.RELEASE_READY
    assert result.cause == "PASS"
    assert result.attempts == 1
    assert result.model_calls == 2
    assert result.evidence_path.is_file()
    assert "status" not in result.annotation
    events = [json.loads(line) for line in result.evidence_path.read_text().splitlines()]
    coder = next(event for event in events if event["event_type"] == "coder_completed")
    release = next(event for event in events if event["event_type"] == "release_ready")
    assert events[0]["payload"]["approval"]["status"] == "UNVERIFIED_DIRECT_CALL"
    assert coder["payload"]["provider_behavior"]["purpose"] == "code"
    request_blob = coder["payload"]["request_blob_digest"]
    response_blob = coder["payload"]["response_blob_digest"]
    assert set(coder["blob_digests"]) == {request_blob, response_blob}
    request = json.loads((tmp_path / ".pmpe/blobs" / request_blob[7:]).read_text())
    request_body = {key: value for key, value in request.items() if key != "request_digest"}
    assert request["request_digest"] == canonical_digest(request_body)
    assert release["payload"]["provider_behavior"]["purpose"] == "advisory_review"
    assert coder["payload"]["provider_behavior"]["request_digest"].startswith("sha256:")
    assert release["payload"]["provider_behavior"]["output_digest"].startswith("sha256:")
    if os.environ.get("PMPE_TEST_REAL_SANDBOX") == "true":
        _prove_private_source_wrapper_with_nested_candidate_sandbox(tmp_path / "source-gate")


def test_materially_different_readiness_contract_reaches_release_ready(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    contract_path = root / "examples/barebones/readiness-contract.json"
    receipt_path = root / "examples/barebones/readiness-approval-receipt.json"
    contract = json.loads(contract_path.read_text())
    receipt_source = receipt_path.read_bytes()

    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="readiness-real-contract",
        provider=ReadinessProvider(),
        approval_receipt=json.loads(receipt_source),
        approval_authority="fixture-human",
        approval_receipt_bytes=receipt_source,
    )

    assert result.state is RunState.RELEASE_READY
    assert result.cause == "PASS"
    assert result.telemetry["structured_criteria_count"] == 3
    events = [json.loads(line) for line in result.evidence_path.read_text().splitlines()]
    assert events[0]["payload"]["approval"]["status"] == "VERIFIED"
