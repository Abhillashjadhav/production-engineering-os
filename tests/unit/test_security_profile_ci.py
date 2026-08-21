from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pmpe.contracts.digest import canonical_digest
from pmpe.orchestration.lifecycle import BudgetPolicy, LifecycleControlPlane, LifecycleState
from pmpe.privacy.retention import RetentionController
from pmpe.telemetry.events import EventLog
from scripts.ci.evaluate_security_profile import (
    _observed_architecture_edges,
    _privacy_evidence_from_artifact,
)
from scripts.ci.verify_privacy_controls import _inventory_telemetry_fields

SHA = "d" * 40


def test_architecture_observer_resolves_relative_imports(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("")
    (source / "worker.py").write_text("from ..guided import api\n")

    assert ("orchestration", "interfaces") in _observed_architecture_edges(tmp_path)


def test_architecture_observer_checks_both_repository_planes(tmp_path: Path) -> None:
    os_source = tmp_path / "src" / "pmpe" / "orchestration"
    product_source = tmp_path / "products" / "pm-evals-web" / "backend" / "src" / "pm_evals_reports"
    os_source.mkdir(parents=True)
    product_source.mkdir(parents=True)
    (product_source / "__init__.py").write_text("")
    (os_source / "worker.py").write_text("import pm_evals_reports\n")
    (product_source / "app.py").write_text("from pmpe.contracts import digest\n")

    edges = _observed_architecture_edges(tmp_path)

    assert ("orchestration", "product") in edges
    assert ("product", "core") in edges


def test_architecture_observer_accounts_for_dynamic_imports(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "literal.py").write_text(
        'import importlib\nimportlib.import_module("pmpe.guided.api")\n'
    )
    (source / "unresolved.py").write_text(
        "import importlib\nimportlib.import_module(module_name)\n"
    )

    edges = _observed_architecture_edges(tmp_path)

    assert ("orchestration", "interfaces") in edges
    assert ("orchestration", "unresolved_dynamic") in edges


def test_architecture_observer_resolves_relative_dynamic_imports(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "relative.py").write_text(
        'import importlib\nimportlib.import_module("..guided.api", __package__)\n'
    )

    assert ("orchestration", "interfaces") in _observed_architecture_edges(tmp_path)


def test_retention_controller_deletes_expired_and_preserves_current_data(tmp_path: Path) -> None:
    now = datetime(2030, 1, 31, tzinfo=UTC)
    expired = tmp_path / "expired.json"
    current = tmp_path / "current.json"
    expired.write_text("expired")
    current.write_text("current")
    old = (now - timedelta(days=31)).timestamp()
    recent = (now - timedelta(days=29)).timestamp()
    os.utime(expired, (old, old))
    os.utime(current, (recent, recent))

    result = RetentionController(retention_days=30).purge(tmp_path, now=now)

    assert result.deleted == ("expired.json",)
    assert result.retained == ("current.json",)
    assert not expired.exists()
    assert current.exists()


def test_event_log_enforces_retention_on_the_actual_runs_root(tmp_path: Path) -> None:
    now = datetime(2030, 1, 31, tzinfo=UTC)
    expired = tmp_path / "expired-run" / "events.jsonl"
    current_run = tmp_path / "current-run"
    expired.parent.mkdir()
    expired.write_text("{}\n")
    old = (now - timedelta(days=31)).timestamp()
    os.utime(expired, (old, old))

    EventLog(
        current_run,
        retention_days=30,
        trusted_clock=lambda: now,
    )

    assert not expired.exists()


def test_phase_zero_create_enforces_retention_on_shipped_lifecycle_root(tmp_path: Path) -> None:
    now = datetime(2030, 1, 31, tzinfo=UTC)
    expired = tmp_path / "expired-run" / "lifecycle-events.jsonl"
    expired.parent.mkdir()
    expired.write_text("{}\n")
    old = (now - timedelta(days=31)).timestamp()
    os.utime(expired, (old, old))
    budget = BudgetPolicy(
        version="budget-v1",
        limits={
            "tokens": 100,
            "credits": 10,
            "elapsed_seconds": 3600,
            "external_compute_seconds": 600,
            "spend_microunits": 1000,
        },
        repair_attempts_per_finding=2,
        repair_attempts_per_stage=3,
        reserved_safety_units=10,
        approved_by="delivery-owner",
    )

    LifecycleControlPlane.create(
        tmp_path / "current-run",
        run_id="privacy-retention-run",
        subject_digest="sha256:" + "1" * 64,
        initial_state=LifecycleState.CONTRACT_RECEIVED,
        budget_policy=budget,
        retention_days=30,
        trusted_clock=lambda: now,
    )

    assert not expired.exists()


def test_privacy_verifier_inventories_real_product_telemetry(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "context.py").write_text(
        'events.emit("escalation", escalation_id="E", step="build", reason="policy")\n'
    )

    assert _inventory_telemetry_fields(tmp_path) == (
        "escalation_id",
        "reason",
        "step",
    )


def test_privacy_verifier_tracks_aliased_event_emitters(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "context.py").write_text(
        'emit = ctx.events.emit\nemit("result", email="synthetic@example.invalid")\n'
    )

    assert _inventory_telemetry_fields(tmp_path) == ("email",)


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
