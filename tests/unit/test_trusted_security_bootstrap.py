from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.ci.verify_trusted_security_bootstrap import (
    BootstrapVerificationError,
    verify_locked_dependency_coverage,
    verify_trusted_security,
)

NOW = datetime(2026, 8, 28, 19, 0, tzinfo=UTC)


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repository(root: Path, files: dict[str, str]) -> str:
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "fixture@example.invalid")
    _git(root, "config", "user.name", "Fixture")
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "fixture")
    return _git(root, "rev-parse", "HEAD")


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(candidate: Path) -> dict[str, object]:
    files = {
        path.relative_to(candidate).as_posix(): _digest(path)
        for relative in ("requirements.lock", "pyproject.toml", "scripts/ci", "src")
        for path in sorted(
            (candidate / relative).rglob("*")
            if (candidate / relative).is_dir()
            else [candidate / relative]
        )
        if path.is_file()
    }
    shell: dict[str, object] = {
        "approved_by": "repository-owner",
        "approved_candidate_sha": _git(candidate, "rev-parse", "HEAD"),
        "approved_pr_number": 133,
        "expires_at": "2026-09-30T00:00:00Z",
        "files": files,
        "justification": "One-time exact verifier bootstrap for PR #133.",
        "schema_version": "trusted-security-bootstrap/v1",
    }
    encoded = json.dumps(shell, sort_keys=True, separators=(",", ":")).encode()
    return {**shell, "manifest_digest": "sha256:" + hashlib.sha256(encoded).hexdigest()}


def _roots(tmp_path: Path) -> tuple[Path, str, Path, str, Path]:
    trusted = tmp_path / "trusted"
    base_sha = _repository(
        trusted,
        {
            "requirements.lock": "trusted-lock\n",
            "pyproject.toml": "[project]\nname='trusted'\n",
            "security/security-profile-policy.json": "{}\n",
            "security/secret-allowlist.json": "[]\n",
        },
    )
    candidate = tmp_path / "candidate"
    head_sha = _repository(
        candidate,
        {
            "requirements.lock": "candidate-lock\n",
            "pyproject.toml": "[project]\nname='candidate'\n",
            "scripts/ci/evaluate_security_profile.py": "print('profile')\n",
            "scripts/ci/verify_privacy_controls.py": "print('privacy')\n",
            "scripts/ci/verify_repository_secrets.py": "print('secrets')\n",
            "src/pmpe/__init__.py": "\n",
            "src/pmpe/quality/security_profiles.py": "RULES = ()\n",
        },
    )
    manifest_path = trusted / "security" / "trusted-security-bootstrap.json"
    manifest_path.write_text(json.dumps(_manifest(candidate), indent=2, sort_keys=True) + "\n")
    _git(trusted, "add", ".")
    _git(trusted, "commit", "-qm", "manifest")
    base_sha = _git(trusted, "rev-parse", "HEAD")
    return trusted, base_sha, candidate, head_sha, manifest_path


def test_exact_bootstrap_manifest_selects_only_the_approved_candidate_runtime(
    tmp_path: Path,
) -> None:
    trusted, base_sha, candidate, head_sha, manifest = _roots(tmp_path)

    report = verify_trusted_security(
        trusted_root=trusted,
        candidate_root=candidate,
        manifest_path=manifest,
        base_sha=base_sha,
        candidate_sha=head_sha,
        pr_number=133,
        trusted_clock=lambda: NOW,
    )

    assert report["mode"] == "BOOTSTRAP_PINNED_CANDIDATE"
    assert report["runner_root"] == str(candidate.resolve())
    assert report["candidate_sha"] == head_sha
    assert report["manifest_file_count"] == 7


@pytest.mark.parametrize("mutation", ["modify", "add"])
def test_bootstrap_rejects_changed_or_unmanifested_execution_files(
    tmp_path: Path,
    mutation: str,
) -> None:
    trusted, base_sha, candidate, head_sha, manifest = _roots(tmp_path)
    if mutation == "modify":
        (candidate / "scripts/ci/evaluate_security_profile.py").write_text("print('bypass')\n")
    else:
        (candidate / "src/sitecustomize.py").write_text("raise SystemExit('bypass')\n")
    _git(candidate, "add", ".")
    _git(candidate, "commit", "-qm", mutation)
    head_sha = _git(candidate, "rev-parse", "HEAD")

    with pytest.raises(BootstrapVerificationError, match="manifest"):
        verify_trusted_security(
            trusted_root=trusted,
            candidate_root=candidate,
            manifest_path=manifest,
            base_sha=base_sha,
            candidate_sha=head_sha,
            pr_number=133,
            trusted_clock=lambda: NOW,
        )


def test_protected_base_verifier_never_falls_back_to_candidate(tmp_path: Path) -> None:
    trusted, _, candidate, head_sha, manifest = _roots(tmp_path)
    for relative in (
        "scripts/ci/evaluate_security_profile.py",
        "scripts/ci/verify_privacy_controls.py",
        "scripts/ci/verify_repository_secrets.py",
        "src/pmpe/quality/security_profiles.py",
    ):
        path = trusted / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("TRUSTED = True\n")
    _git(trusted, "add", ".")
    _git(trusted, "commit", "-qm", "protected verifier")
    base_sha = _git(trusted, "rev-parse", "HEAD")
    (candidate / "scripts/ci/evaluate_security_profile.py").write_text(
        "raise SystemExit('bypass')\n"
    )
    _git(candidate, "add", ".")
    _git(candidate, "commit", "-qm", "candidate bypass")
    head_sha = _git(candidate, "rev-parse", "HEAD")

    report = verify_trusted_security(
        trusted_root=trusted,
        candidate_root=candidate,
        manifest_path=manifest,
        base_sha=base_sha,
        candidate_sha=head_sha,
        pr_number=999,
        trusted_clock=lambda: NOW,
    )

    assert report["mode"] == "PROTECTED_BASE"
    assert report["runner_root"] == str(trusted.resolve())


def test_partial_protected_verifier_fails_without_bootstrap_fallback(tmp_path: Path) -> None:
    trusted, _, candidate, head_sha, manifest = _roots(tmp_path)
    path = trusted / "scripts/ci/evaluate_security_profile.py"
    path.parent.mkdir(parents=True)
    path.write_text("TRUSTED = True\n")
    _git(trusted, "add", ".")
    _git(trusted, "commit", "-qm", "partial verifier")
    base_sha = _git(trusted, "rev-parse", "HEAD")

    with pytest.raises(BootstrapVerificationError, match="partial"):
        verify_trusted_security(
            trusted_root=trusted,
            candidate_root=candidate,
            manifest_path=manifest,
            base_sha=base_sha,
            candidate_sha=head_sha,
            pr_number=133,
            trusted_clock=lambda: NOW,
        )


def test_bootstrap_rejects_manifest_outside_the_protected_base(tmp_path: Path) -> None:
    trusted, base_sha, candidate, head_sha, manifest = _roots(tmp_path)
    external_manifest = tmp_path / "candidate-selected-manifest.json"
    external_manifest.write_bytes(manifest.read_bytes())

    with pytest.raises(BootstrapVerificationError, match="protected-base file"):
        verify_trusted_security(
            trusted_root=trusted,
            candidate_root=candidate,
            manifest_path=external_manifest,
            base_sha=base_sha,
            candidate_sha=head_sha,
            pr_number=133,
            trusted_clock=lambda: NOW,
        )


def test_exact_checkout_rejects_untracked_candidate_files(tmp_path: Path) -> None:
    trusted, base_sha, candidate, head_sha, manifest = _roots(tmp_path)
    (candidate / "sitecustomize.py").write_text("raise SystemExit('ambient startup')\n")

    with pytest.raises(BootstrapVerificationError, match="clean exact commit"):
        verify_trusted_security(
            trusted_root=trusted,
            candidate_root=candidate,
            manifest_path=manifest,
            base_sha=base_sha,
            candidate_sha=head_sha,
            pr_number=133,
            trusted_clock=lambda: NOW,
        )


def test_trusted_workflow_has_no_candidate_authority() -> None:
    workflow = Path(".github/workflows/trusted-security.yml").read_text()
    finalizer = Path(".github/workflows/trusted-security-finalizer.yml").read_text()
    legacy_workflow = Path(".github/workflows/ci.yml").read_text()

    assert "pull_request_target:" in workflow
    assert "types: [opened, reopened, synchronize, ready_for_review, edited]" in workflow
    assert "merge_group:" in workflow
    assert "run-name: trusted-security:" in workflow
    assert "types: [checks_requested]" in workflow
    assert "github.event.merge_group.base_sha" in workflow
    assert "github.event.merge_group.head_sha" in workflow
    assert "contents: read" in workflow
    assert "checks: write" in workflow
    assert "persist-credentials: false" in workflow
    assert "github.event.pull_request.base.sha" in workflow
    assert "github.event.pull_request.head.sha" in workflow
    assert "trusted/scripts/ci/verify_trusted_security_bootstrap.py" in workflow
    assert "--no-deps --disable-pip" in workflow
    assert "${{ secrets." not in workflow
    assert "pull_request:" not in workflow.replace("pull_request_target:", "")
    assert "git merge" not in workflow.lower()
    assert "gh pr merge" not in workflow.lower()
    assert "merge-pull-request" not in workflow.lower()
    assert "deploy" not in workflow.lower()
    assert "  trusted-security-runner:\n    name: trusted-security-runner\n" in workflow
    assert '"/repos/$GITHUB_REPOSITORY/check-runs"' in workflow
    assert '"/repos/$GITHUB_REPOSITORY/check-runs/$CHECK_RUN_ID"' in workflow
    assert "-f name=security" in workflow
    assert '-f head_sha="$CANDIDATE_SHA"' in workflow
    assert '-f external_id="$GITHUB_RUN_ID:$GITHUB_RUN_ATTEMPT"' in workflow
    assert "-f status=in_progress" in workflow
    assert "--jq .id" in workflow
    assert "if: always()" in workflow
    assert "job.status == 'success'" in workflow
    assert "-f status=completed" in workflow
    assert '-f conclusion="$CHECK_CONCLUSION"' in workflow
    assert "  security:\n    name: security\n" not in workflow
    assert "  security:\n" not in legacy_workflow
    assert "  security-static:\n    name: security-static\n" in legacy_workflow
    assert "workflow_run:" in finalizer
    assert 'workflows: ["Trusted Security"]' in finalizer
    assert "types: [completed]" in finalizer
    assert "checks: write" in finalizer
    assert "github.event.workflow_run.event" in finalizer
    assert "pull_request_target|merge_group" in finalizer
    assert "github.event.workflow_run.display_title" in finalizer
    assert "${SOURCE_DISPLAY_TITLE#trusted-security:}" in finalizer
    assert "github.event.workflow_run.pull_requests[0]" not in finalizer
    assert "github.event.workflow_run.run_attempt" in finalizer
    assert 'source_external_id="$SOURCE_RUN_ID:$SOURCE_RUN_ATTEMPT"' in finalizer
    assert 'select(.external_id == \\"$source_external_id\\")' in finalizer
    assert '-f external_id="$source_external_id"' in finalizer
    assert "github.run_attempt" in workflow
    assert "--verify-dependency-coverage" in workflow
    assert "--ignore-installed" in workflow
    assert "python -m pip check" in workflow
    assert "candidate-closure-venv" in workflow
    assert "-r candidate/requirements.lock" in workflow
    assert "candidate-pip-check.txt" in workflow
    assert "missing_conclusion=failure" in finalizer
    assert '-f conclusion="$missing_conclusion"' in finalizer
    assert "--method PATCH" in finalizer
    assert "actions/checkout" not in finalizer
    assert "candidate/" not in finalizer
    assert "pip install" not in finalizer
    assert "python " not in finalizer


def _write_dependency_metadata(root: Path) -> None:
    (root / "pyproject.toml").write_text(
        "[build-system]\n"
        'requires = ["setuptools==83.0.0"]\n'
        'build-backend = "setuptools.build_meta"\n\n'
        "[project]\n"
        'name = "candidate"\n'
        'version = "1.0.0"\n'
        'dependencies = ["PyYAML==6.0.3"]\n\n'
        "[project.optional-dependencies]\n"
        'dev = ["pytest==9.1.1"]\n'
    )
    (root / "requirements.lock").write_text(
        "pyyaml==6.0.3 \\\n    --hash=sha256:" + "1" * 64 + "\n"
        "pytest==9.1.1 \\\n    --hash=sha256:" + "2" * 64 + "\n"
        "setuptools==83.0.0 \\\n    --hash=sha256:" + "3" * 64 + "\n"
    )


def test_dependency_coverage_binds_every_declared_exact_pin(tmp_path: Path) -> None:
    _write_dependency_metadata(tmp_path)

    report = verify_locked_dependency_coverage(
        candidate_root=tmp_path,
        candidate_sha="a" * 40,
    )

    assert report["coverage_passed"] is True
    assert report["declared_dependency_count"] == 3


def test_dependency_coverage_rejects_unlocked_declaration(tmp_path: Path) -> None:
    _write_dependency_metadata(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text().replace(
            'dependencies = ["PyYAML==6.0.3"]',
            'dependencies = ["PyYAML==6.0.3", "requests==2.32.5"]',
        )
    )

    with pytest.raises(BootstrapVerificationError, match="absent from the hash lock"):
        verify_locked_dependency_coverage(candidate_root=tmp_path, candidate_sha="a" * 40)


def test_dependency_coverage_rejects_unpinned_declaration(tmp_path: Path) -> None:
    _write_dependency_metadata(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace("PyYAML==6.0.3", "PyYAML>=6.0"))

    with pytest.raises(BootstrapVerificationError, match="exact version pins"):
        verify_locked_dependency_coverage(candidate_root=tmp_path, candidate_sha="a" * 40)


def test_dependency_coverage_rejects_dangling_transitive_reference(tmp_path: Path) -> None:
    _write_dependency_metadata(tmp_path)
    lock = tmp_path / "requirements.lock"
    lock.write_text(lock.read_text() + "    # via missing-parent\n")

    with pytest.raises(BootstrapVerificationError, match="dangling transitive"):
        verify_locked_dependency_coverage(candidate_root=tmp_path, candidate_sha="a" * 40)


@pytest.mark.parametrize(
    "continuation",
    [
        "    --index-url https://example.invalid/simple\n",
        "    --hash=sha256:not-a-digest\n",
    ],
)
def test_dependency_coverage_rejects_untrusted_lock_options(
    tmp_path: Path,
    continuation: str,
) -> None:
    _write_dependency_metadata(tmp_path)
    lock = tmp_path / "requirements.lock"
    lock.write_text(
        lock.read_text().replace("    --hash=sha256:", continuation + "    --hash=sha256:", 1)
    )

    with pytest.raises(BootstrapVerificationError, match="continuation"):
        verify_locked_dependency_coverage(candidate_root=tmp_path, candidate_sha="a" * 40)
