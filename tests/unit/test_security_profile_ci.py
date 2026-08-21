from __future__ import annotations

import json
from pathlib import Path

import pytest

from pmpe.contracts.digest import canonical_digest
from scripts.ci.evaluate_security_profile import (
    _observed_architecture_edges,
    _privacy_evidence_from_artifact,
)

SHA = "d" * 40


def test_architecture_observer_resolves_relative_imports(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("")
    (source / "worker.py").write_text("from ..guided import api\n")

    assert ("orchestration", "interfaces") in _observed_architecture_edges(tmp_path)


def test_privacy_evidence_requires_executed_exact_candidate_artifact(tmp_path: Path) -> None:
    policy_path = tmp_path / "security-profile-policy.json"
    verifier_path = tmp_path / "verify_privacy_controls.py"
    policy_path.write_text("{}")
    verifier_path.write_text("# verifier\n")
    artifact_path = tmp_path / "privacy-evidence.json"
    artifact = {
        "candidate_sha": SHA,
        "classification": "INTERNAL",
        "deletion_test_passed": True,
        "emitted_telemetry": ["latency_ms", "outcome", "run_id"],
        "policy_file_digest": "sha256:" + "0" * 64,
        "residency": "IN",
        "retention_days": 30,
        "verifier_file_digest": "sha256:" + "0" * 64,
    }
    artifact["evidence_digest"] = canonical_digest(artifact)
    artifact_path.write_text(json.dumps(artifact))

    with pytest.raises(ValueError, match="privacy verifier artifact"):
        _privacy_evidence_from_artifact(
            artifact_path,
            candidate_sha=SHA,
            policy_path=policy_path,
            verifier_path=verifier_path,
        )


def test_ci_executes_privacy_verifier_before_composed_profile() -> None:
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/ci.yml").read_text()

    verifier = workflow.index("python scripts/ci/verify_privacy_controls.py")
    composed = workflow.index("python scripts/ci/evaluate_security_profile.py")
    assert verifier < composed
    assert "--privacy-evidence /tmp/security-profile/privacy-evidence.json" in workflow
