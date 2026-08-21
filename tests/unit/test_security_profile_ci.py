from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import pmpe.privacy.retention as retention_module
from pmpe.contracts.digest import canonical_digest
from pmpe.orchestration.lifecycle import BudgetPolicy, LifecycleControlPlane, LifecycleState
from pmpe.privacy.retention import RetentionController
from pmpe.telemetry.events import EventLog
from scripts.ci.evaluate_security_profile import (
    _observed_architecture_edges,
    _privacy_evidence_from_artifact,
)
from scripts.ci.observe_runtime_residency import _observe
from scripts.ci.verify_privacy_controls import _inventory_telemetry_fields

SHA = "d" * 40


class _FakeAws:
    def __init__(self, *, region: str = "ap-south-1", corrupt_download: bool = False) -> None:
        self.region = region
        self.corrupt_download = corrupt_download
        self.calls: list[tuple[str, ...]] = []
        self.objects: dict[str, bytes] = {}

    def __call__(self, command: tuple[str, ...]) -> str:
        self.calls.append(command)
        operation = command[:2]
        if operation == ("sts", "get-caller-identity"):
            return json.dumps(
                {
                    "Account": "123456789012",
                    "Arn": "arn:aws:sts::123456789012:assumed-role/peos-residency/github",
                }
            )
        if operation == ("s3api", "get-bucket-location"):
            return self.region
        if operation == ("s3api", "put-object"):
            key = command[command.index("--key") + 1]
            source = Path(command[command.index("--body") + 1])
            self.objects[key] = source.read_bytes()
            return "{}"
        if operation == ("s3api", "get-object"):
            key = command[command.index("--key") + 1]
            target = Path(command[-1])
            payload = self.objects[key]
            target.write_bytes(b"corrupt" if self.corrupt_download else payload)
            return "{}"
        if operation == ("s3api", "delete-object"):
            key = command[command.index("--key") + 1]
            self.objects.pop(key, None)
            return "{}"
        raise AssertionError(f"unexpected AWS command: {command}")


def _runtime_residency_config(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "authority": "aws-s3-runtime-storage-observer/v1",
                "environment_id": "production-engineering-os-residency-proof",
                "provider": "aws",
                "service": "s3",
                "expected_provider_region": "ap-south-1",
            }
        )
    )
    return path


def test_runtime_residency_comes_from_authenticated_aws_bucket_metadata(tmp_path: Path) -> None:
    aws = _FakeAws()

    evidence = _observe(
        candidate_sha=SHA,
        runtime_config_path=_runtime_residency_config(tmp_path / "runtime-residency.json"),
        bucket="peos-residency-proof",
        aws_command=aws,
    )

    assert evidence["authority"] == "aws-s3-runtime-storage-observer/v1"
    assert evidence["observed_provider_region"] == "ap-south-1"
    assert evidence["observed_residency"] == "IN"
    assert evidence["storage_probe_passed"] is True
    assert evidence["provider_identity_digest"].startswith("sha256:")
    assert evidence["authenticated_metadata_digest"].startswith("sha256:")
    assert evidence["storage_endpoint_digest"].startswith("sha256:")
    assert evidence["evidence_digest"] == canonical_digest(
        {key: value for key, value in evidence.items() if key != "evidence_digest"}
    )
    assert not aws.objects
    assert ("s3api", "get-bucket-location") == aws.calls[1][:2]
    assert any(command[:2] == ("s3api", "put-object") for command in aws.calls)
    assert any(command[:2] == ("s3api", "get-object") for command in aws.calls)
    assert any(command[:2] == ("s3api", "delete-object") for command in aws.calls)


def test_runtime_residency_rejects_a_non_mumbai_bucket_even_if_config_claims_india(
    tmp_path: Path,
) -> None:
    config = _runtime_residency_config(tmp_path / "runtime-residency.json")
    value = json.loads(config.read_text())
    value["storage_region"] = "IN"
    config.write_text(json.dumps(value))
    aws = _FakeAws(region="eu-west-1")

    with pytest.raises(ValueError, match="authenticated AWS bucket region"):
        _observe(
            candidate_sha=SHA,
            runtime_config_path=config,
            bucket="peos-residency-proof",
            aws_command=aws,
        )

    assert not any(command[:2] == ("s3api", "put-object") for command in aws.calls)


def test_runtime_residency_deletes_probe_when_readback_fails(tmp_path: Path) -> None:
    aws = _FakeAws(corrupt_download=True)

    with pytest.raises(ValueError, match="storage probe readback failed"):
        _observe(
            candidate_sha=SHA,
            runtime_config_path=_runtime_residency_config(
                tmp_path / "runtime-residency.json"
            ),
            bucket="peos-residency-proof",
            aws_command=aws,
        )

    assert not aws.objects


def test_architecture_observer_resolves_relative_imports(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("")
    (source / "worker.py").write_text("from ..guided import api\n")

    assert ("orchestration", "interfaces") in _observed_architecture_edges(tmp_path)


def test_architecture_observer_resolves_names_imported_from_a_package(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "worker.py").write_text("from pmpe import guided\n")

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


def test_architecture_observer_discovers_product_namespace_packages(tmp_path: Path) -> None:
    os_source = tmp_path / "src" / "pmpe" / "orchestration"
    product_source = tmp_path / "products" / "pm-evals-web" / "backend" / "src" / "pm_evals_reports"
    os_source.mkdir(parents=True)
    product_source.mkdir(parents=True)
    (os_source / "worker.py").write_text("import pm_evals_reports.summary\n")
    (product_source / "summary.py").write_text("REPORT = {}\n")

    assert ("orchestration", "product") in _observed_architecture_edges(tmp_path)


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


@pytest.mark.parametrize(
    "source_text",
    [
        'import importlib as il\nil.import_module("pmpe.guided.api")\n',
        'from importlib import import_module as load\nload("pmpe.guided.api")\n',
        'import importlib\nloader = importlib.import_module\nloader("pmpe.guided.api")\n',
        'from importlib import import_module\nloader = import_module\nloader("pmpe.guided.api")\n',
    ],
)
def test_architecture_observer_resolves_dynamic_import_function_aliases(
    tmp_path: Path,
    source_text: str,
) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "dynamic_alias.py").write_text(source_text)

    assert ("orchestration", "interfaces") in _observed_architecture_edges(tmp_path)


def test_architecture_observer_resolves_relative_dynamic_imports(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pmpe" / "orchestration"
    source.mkdir(parents=True)
    (source / "relative.py").write_text(
        'import importlib\nimportlib.import_module("..guided.api", __package__)\n'
    )

    assert ("orchestration", "interfaces") in _observed_architecture_edges(tmp_path)


def test_retention_controller_atomically_deletes_only_expired_completed_runs(
    tmp_path: Path,
) -> None:
    now = datetime(2030, 1, 31, tzinfo=UTC)
    completed = tmp_path / "completed-run"
    active = tmp_path / "active-run"
    completed.mkdir()
    active.mkdir()
    completed_ledger = completed / "lifecycle-events.jsonl"
    completed_artifact = completed / "recent-artifact.json"
    active_ledger = active / "lifecycle-events.jsonl"
    active_artifact = active / "old-artifact.json"
    completed_ledger.write_text('{"target":"COMPLETED"}\n')
    completed_artifact.write_text("recent but owned by an expired completed run")
    active_ledger.write_text('{"target":"IMPLEMENTATION_IN_PROGRESS"}\n')
    active_artifact.write_text("old but owned by an active run")
    old = (now - timedelta(days=31)).timestamp()
    recent = (now - timedelta(days=29)).timestamp()
    os.utime(completed_ledger, (old, old))
    os.utime(completed_artifact, (recent, recent))
    os.utime(active_ledger, (old, old))
    os.utime(active_artifact, (old, old))

    result = RetentionController(retention_days=30).purge(tmp_path, now=now)

    assert result.deleted == ("completed-run",)
    assert result.retained == ("active-run",)
    assert not completed.exists()
    assert active_ledger.exists()
    assert active_artifact.exists()


def test_retention_controller_preserves_a_locked_completed_run(tmp_path: Path) -> None:
    now = datetime(2030, 1, 31, tzinfo=UTC)
    completed = tmp_path / "completed-run"
    completed.mkdir()
    ledger = completed / "lifecycle-events.jsonl"
    ledger.write_text('{"target":"COMPLETED"}\n')
    old = (now - timedelta(days=31)).timestamp()
    os.utime(ledger, (old, old))

    with (completed / "lifecycle.lock").open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = RetentionController(retention_days=30).purge(tmp_path, now=now)

    assert result.deleted == ()
    assert result.retained == ("completed-run",)
    assert ledger.exists()


def test_retention_controller_deletes_expired_completed_engineering_runs(
    tmp_path: Path,
) -> None:
    now = datetime(2030, 1, 31, tzinfo=UTC)
    completed = tmp_path / "completed-engineering-run"
    completed.mkdir()
    state = completed / "run-state.json"
    state.write_text('{"stage":"complete"}\n')
    (completed / "artifact.json").write_text("belongs to the completed run")
    old = (now - timedelta(days=31)).timestamp()
    os.utime(state, (old, old))

    result = RetentionController(retention_days=30).purge(tmp_path, now=now)

    assert result.deleted == ("completed-engineering-run",)
    assert not completed.exists()


def test_retention_controller_tolerates_a_concurrently_removed_tombstone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tombstone = tmp_path / ".retention-delete-expired-raced"
    tombstone.mkdir()
    real_rmtree = retention_module.shutil.rmtree

    def raced_rmtree(path: Path) -> None:
        real_rmtree(path)
        raise FileNotFoundError(path)

    monkeypatch.setattr(retention_module.shutil, "rmtree", raced_rmtree)

    result = RetentionController(retention_days=30).purge(
        tmp_path,
        now=datetime(2030, 1, 31, tzinfo=UTC),
    )

    assert result.deleted == ()
    assert result.retained == ()


def test_event_log_enforces_retention_on_the_actual_runs_root(tmp_path: Path) -> None:
    now = datetime(2030, 1, 31, tzinfo=UTC)
    expired = tmp_path / "expired-run" / "lifecycle-events.jsonl"
    current_run = tmp_path / "current-run"
    expired.parent.mkdir()
    expired.write_text('{"target":"COMPLETED"}\n')
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
    expired.write_text('{"target":"COMPLETED"}\n')
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


def test_privacy_evidence_rejects_policy_copied_residency(tmp_path: Path) -> None:
    policy_path = tmp_path / "security-profile-policy.json"
    verifier_path = tmp_path / "verify_privacy_controls.py"
    policy_path.write_text("{}")
    verifier_path.write_text("# verifier\n")
    artifact_path = tmp_path / "privacy-evidence.json"
    artifact = {
        "candidate_sha": SHA,
        "classification": "INTERNAL",
        "deletion_test_passed": True,
        "emitted_telemetry": ["run_id"],
        "policy_file_digest": "sha256:" + hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        "residency": "IN",
        "retention_days": 30,
        "retention_test_passed": True,
        "telemetry_test_passed": True,
        "verifier_file_digest": "sha256:" + hashlib.sha256(verifier_path.read_bytes()).hexdigest(),
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

    residency = workflow.index("python scripts/ci/observe_runtime_residency.py")
    verifier = workflow.index("python scripts/ci/verify_privacy_controls.py")
    composed = workflow.index("python scripts/ci/evaluate_security_profile.py")
    assert residency < verifier < composed
    assert "--residency-evidence /tmp/security-profile/residency-evidence.json" in workflow
    assert "--privacy-evidence /tmp/security-profile/privacy-evidence.json" in workflow


def test_ci_keeps_editable_builds_inside_the_hash_lock() -> None:
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/ci.yml").read_text()
    pyproject = (root / "pyproject.toml").read_text()
    lockfile = (root / "requirements.lock").read_text()

    assert 'requires = ["setuptools==' in pyproject
    assert "setuptools==" in lockfile
    assert workflow.count("pip install --no-deps --no-build-isolation -e .") == 3
