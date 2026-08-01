"""Issue #64 RED contract for deterministic repository intelligence."""

from __future__ import annotations

import importlib
import json
import signal
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _api() -> ModuleType:
    try:
        return importlib.import_module("pmpe.repository")
    except ModuleNotFoundError:
        pytest.fail(
            "issue #64 repository-intelligence API is not implemented",
            pytrace=False,
        )


def _git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _write(repo: Path, relative: str, content: str | bytes) -> None:
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content)


def _commit(repo: Path, message: str = "fixture") -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _init_repo(tmp_path: Path, *, mixed: bool = True) -> Path:
    repo = tmp_path / "fixture-repo"
    repo.mkdir()
    _git(repo, "init", "-q", "--initial-branch=main")
    _git(repo, "config", "user.email", "fixture@localhost")
    _git(repo, "config", "user.name", "Fixture")
    _write(repo, "README.md", "# Fixture\n")
    if mixed:
        _write(
            repo,
            "pyproject.toml",
            "[project]\nname='fixture'\nversion='1.0.0'\ndependencies=[]\n",
        )
        _write(repo, "src/widget/__init__.py", '"""Widget package."""\n')
        _write(repo, "tests/unit/test_widget.py", "def test_widget():\n    assert True\n")
        _write(
            repo,
            "packages/web/package.json",
            json.dumps({"name": "web", "version": "1.0.0", "scripts": {"test": "vitest"}}),
        )
        _write(repo, "packages/web/package-lock.json", '{"lockfileVersion":3}\n')
        _write(repo, "packages/web/src/index.ts", "export const ok = true;\n")
        _write(
            repo,
            "services/api/openapi.json",
            '{"openapi":"3.1.0","info":{"title":"Fixture","version":"1"},"paths":{}}\n',
        )
        _write(repo, "services/api/migrations/001_create.sql", "create table item(id int);\n")
        _write(repo, "Dockerfile", "FROM python:3.11-slim\nHEALTHCHECK CMD true\n")
        _write(repo, "compose.yaml", "services:\n  api:\n    build: .\n")
        _write(
            repo,
            ".github/workflows/ci.yml",
            "name: ci\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n",
        )
        _write(repo, ".github/CODEOWNERS", "/src/ @platform\n")
        _write(repo, "docs/adr/0001.md", "# ADR 0001\n")
        _write(repo, "ops/alerts.yaml", "alerts:\n  - name: api-down\n")
        _write(repo, "ops/slo.yaml", "availability: 99.9\n")
        _write(repo, "scripts/generate_client.py", "# deterministic generator entrypoint\n")
    _commit(repo)
    return repo


def _config(**changes: Any) -> Any:
    api = _api()
    base = api.ScanConfig(
        repository="example/fixture",
        default_branch="main",
        max_files=1_000,
        max_total_bytes=10_000_000,
        max_file_bytes=1_000_000,
        max_commands=5_000,
        command_timeout_seconds=10,
        max_path_depth=32,
    )
    return replace(base, **changes)


def _scan(repo: Path, **changes: Any) -> Any:
    return _api().RepositoryScanner(config=_config(**changes)).scan(repo, commit="HEAD")


def test_exact_sha_snapshot_is_byte_deterministic_and_has_no_timestamp(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    first = _scan(repo)
    second = _scan(repo)
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.snapshot_digest == second.snapshot_digest
    assert first.commit_sha == _git(repo, "rev-parse", "HEAD")
    assert "observed_at" not in first.as_dict()
    assert "worktree" not in first.as_dict()
    assert "pull_requests" not in first.as_dict()


def test_equivalent_ref_and_exact_sha_produce_same_snapshot(tmp_path: Path) -> None:
    api = _api()
    repo = _init_repo(tmp_path)
    commit_sha = _git(repo, "rev-parse", "HEAD")
    from_ref = api.RepositoryScanner(config=_config()).scan(repo, commit="HEAD")
    from_sha = api.RepositoryScanner(config=_config()).scan(repo, commit=commit_sha)
    assert from_ref.canonical_bytes() == from_sha.canonical_bytes()


def test_scoped_scan_is_explicitly_partial_and_keeps_full_tree_binding(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    full = _scan(repo)
    scoped = _scan(repo, include_paths=("src",))
    assert scoped.scan_scope == "INCLUDED_PATHS"
    assert scoped.included_paths == ("src",)
    assert scoped.disposition == "PARTIAL"
    assert scoped.tracked_tree_digest == full.tracked_tree_digest
    assert scoped.scanned_content_digest != full.scanned_content_digest
    assert any(item.code == "SCAN.SCOPED_PARTIAL" for item in scoped.findings)


def test_dirty_tracked_content_does_not_change_exact_commit_snapshot(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    before = _scan(repo)
    _write(repo, "README.md", "dirty worktree value\n")
    after = _scan(repo)
    assert before.canonical_bytes() == after.canonical_bytes()
    assert (repo / "README.md").read_text() == "dirty worktree value\n"


def test_new_commit_changes_tree_and_snapshot_digests(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    first = _scan(repo)
    _write(repo, "README.md", "# Changed\n")
    _commit(repo, "change tracked content")
    second = _scan(repo)
    assert first.commit_sha != second.commit_sha
    assert first.tracked_tree_digest != second.tracked_tree_digest
    assert first.snapshot_digest != second.snapshot_digest


def test_replace_refs_cannot_change_an_exact_commit_snapshot(tmp_path: Path) -> None:
    api = _api()
    repo = _init_repo(tmp_path)
    original = _git(repo, "rev-parse", "HEAD")
    baseline = api.RepositoryScanner(config=_config()).scan(repo, commit=original)
    _write(repo, "README.md", "# Replacement content\n")
    replacement = _commit(repo, "replacement target")
    _git(repo, "replace", original, replacement)
    with_replacement = api.RepositoryScanner(config=_config()).scan(repo, commit=original)
    assert with_replacement.canonical_bytes() == baseline.canonical_bytes()
    assert with_replacement.commit_sha == original


def test_sha256_repository_is_exactly_bound_or_fails_explicitly(tmp_path: Path) -> None:
    repo = tmp_path / "sha256-repo"
    repo.mkdir()
    result = subprocess.run(
        ["git", "init", "-q", "--object-format=sha256", "--initial-branch=main"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip("installed Git explicitly does not support SHA-256 repositories")
    _git(repo, "config", "user.email", "fixture@localhost")
    _git(repo, "config", "user.name", "Fixture")
    _write(repo, "README.md", "# SHA-256 fixture\n")
    _commit(repo, "sha256 fixture")
    snapshot = _scan(repo)
    assert snapshot.git_object_format == "sha256"
    assert len(snapshot.commit_sha) == 64
    assert len(snapshot.tree_sha) == 64
    assert snapshot.disposition != "ERROR"


def test_adapter_order_does_not_change_output_but_version_does(tmp_path: Path) -> None:
    api = _api()
    repo = _init_repo(tmp_path)
    adapters = api.default_adapters()
    first = api.RepositoryScanner(config=_config(), adapters=adapters).scan(repo, commit="HEAD")
    reordered = api.RepositoryScanner(config=_config(), adapters=tuple(reversed(adapters))).scan(
        repo, commit="HEAD"
    )
    assert first.canonical_bytes() == reordered.canonical_bytes()

    changed = (replace(adapters[0], version="99.0.0"), *adapters[1:])
    versioned = api.RepositoryScanner(config=_config(), adapters=changed).scan(repo, commit="HEAD")
    assert first.adapter_set_digest != versioned.adapter_set_digest
    assert first.snapshot_digest != versioned.snapshot_digest


def test_output_affecting_injected_implementation_changes_provenance_digest(
    tmp_path: Path,
) -> None:
    api = _api()
    adapters = importlib.import_module("pmpe.repository.adapters")
    repo = _init_repo(tmp_path)

    def first_evaluator(_context: Any) -> Any:
        return adapters.AdapterResult()

    def second_evaluator(context: Any) -> Any:
        assert context.files or not context.files
        return adapters.AdapterResult()

    metadata = {
        "adapter_id": "test.same-declaration",
        "version": "1.0.0",
        "file_patterns": ("*",),
        "supported_categories": ("repository_topology",),
    }
    first = api.RepositoryScanner(
        config=_config(), adapters=(api.RepositoryAdapter(evaluator=first_evaluator, **metadata),)
    ).scan(repo, commit="HEAD")
    second = api.RepositoryScanner(
        config=_config(), adapters=(api.RepositoryAdapter(evaluator=second_evaluator, **metadata),)
    ).scan(repo, commit="HEAD")
    assert first.adapter_set_digest == second.adapter_set_digest
    assert first.implementation_digest != second.implementation_digest
    assert first.snapshot_digest != second.snapshot_digest


def test_all_audit_categories_are_present_and_active_work_is_separate(tmp_path: Path) -> None:
    api = _api()
    snapshot = _scan(_init_repo(tmp_path))
    assert set(snapshot.inventory) == set(api.AUDIT_CATEGORIES)
    active = snapshot.inventory["active_divergent_work"]
    assert active.status == "UNSUPPORTED"
    assert "GovernanceObservation" in active.reason


def test_inventory_and_boundary_candidates_have_exact_file_evidence(tmp_path: Path) -> None:
    snapshot = _scan(_init_repo(tmp_path))
    boundaries = snapshot.boundary_candidates
    assert {item.kind for item in boundaries} >= {"PACKAGE", "SERVICE", "APPLICATION"}
    assert all(item.evidence_paths for item in boundaries)
    assert all(item.confidence in {"HIGH", "MEDIUM", "LOW"} for item in boundaries)
    for item in snapshot.inventory["languages_build_ecosystems"].items:
        assert item.path
        assert item.file_digest.startswith("sha256:")
        assert item.detector_id and item.detector_version


def test_adapter_metadata_is_versioned_and_declares_supported_categories(
    tmp_path: Path,
) -> None:
    snapshot = _scan(_init_repo(tmp_path))
    adapter_ids = {item.adapter_id for item in snapshot.adapters}
    assert adapter_ids >= {
        "core.repository-topology",
        "stack.python",
        "stack.node-web",
        "stack.docker-compose",
        "delivery.ci",
        "interface.schema-api",
        "integration.manifest-declarations",
        "repository.pmpe",
    }
    assert all(item.version and item.file_patterns for item in snapshot.adapters)
    assert all(item.supported_categories for item in snapshot.adapters)
    assert all(item.failure_behavior == "VISIBLE_PARTIAL_OR_BLOCKED" for item in snapshot.adapters)


def test_snapshot_binds_implementation_modules_and_runtime_tool_versions(tmp_path: Path) -> None:
    scanner = importlib.import_module("pmpe.repository.scanner")
    repository_scanner = scanner.RepositoryScanner(config=_config())
    snapshot = repository_scanner.scan(_init_repo(tmp_path), commit="HEAD")
    assert set(scanner.IMPLEMENTATION_MODULES) == {
        "repository.adapters",
        "repository.models",
        "repository.redaction",
        "repository.scanner",
        "contracts.canonical",
    }
    assert snapshot.implementation_digest == scanner._implementation_digest(
        repository_scanner._extension_implementation_evidence
    )
    assert {item.tool for item in snapshot.tool_versions} == {
        "git",
        "python",
        "pyyaml",
        "rfc8785",
    }


def test_api_data_generated_client_migration_and_contract_sync_are_inventory_items(
    tmp_path: Path,
) -> None:
    snapshot = _scan(_init_repo(tmp_path))
    kinds = {item.kind for item in snapshot.inventory["apis_data"].items}
    assert {"OPENAPI", "MIGRATION_SIGNAL", "CODE_GENERATOR_SIGNAL"} <= kinds
    assert all(
        item.confidence == "MEDIUM"
        for item in snapshot.inventory["apis_data"].items
        if item.kind.endswith("_SIGNAL")
    )


def test_integration_declarations_and_codeowners_are_evidence_backed(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _write(
        repo,
        "packages/web/package.json",
        json.dumps(
            {
                "name": "web",
                "dependencies": {"example-sdk": "1.0.0"},
                "scripts": {"test": "vitest"},
            }
        ),
    )
    _commit(repo, "integration declaration")
    snapshot = _scan(repo)
    assert any(
        item.kind == "EXTERNAL_DEPENDENCY_DECLARATION"
        for item in snapshot.inventory["integrations"].items
    )
    assert any(item.kind == "OWNERSHIP_AREA" for item in snapshot.boundary_candidates)


def test_non_github_ci_is_not_reported_as_ci_absent(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, ".gitlab-ci.yml", "test:\n  script: pytest\n")
    _commit(repo, "gitlab ci")
    snapshot = _scan(repo)
    assert any(
        item.kind == "CI_WORKFLOW" for item in snapshot.inventory["delivery_environments"].items
    )
    assert not any(item.code == "DELIVERY.CI_ABSENT" for item in snapshot.findings)


def test_ci_comments_do_not_become_security_test_or_rollback_controls(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(
        repo,
        ".github/workflows/ci.yml",
        "name: empty\non: [push]\njobs: {}\n# test security rollback\n",
    )
    _write(repo, "Dockerfile", "# HEALTHCHECK CMD false\nFROM scratch\n")
    _commit(repo, "comment-only CI claims")
    snapshot = _scan(repo)
    kinds = {item.kind for category in snapshot.inventory.values() for item in category.items}
    assert "CI_TEST_MAPPING_SIGNAL" not in kinds
    assert "SECURITY_CONTROL_SIGNAL" not in kinds
    assert "ROLLBACK_SIGNAL" not in kinds
    assert "HEALTH_CHECK" not in kinds
    assert any(item.code == "SECURITY.CONTROL_EVIDENCE_ABSENT" for item in snapshot.findings)
    assert any(item.code == "DELIVERY.ROLLBACK_EVIDENCE_ABSENT" for item in snapshot.findings)


def test_recursive_workflow_alias_is_cycle_bounded_and_deterministic(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(
        repo,
        ".github/workflows/ci.yml",
        "on: [push]\njobs: &jobs\n  recursive: *jobs\n",
    )
    _commit(repo, "recursive workflow")
    first = _scan(repo)
    second = _scan(repo)
    assert first.canonical_bytes() == second.canonical_bytes()
    assert not any(item.code == "ADAPTER.FAILURE" for item in first.findings)


def test_disabled_docker_healthcheck_is_not_positive_health_evidence(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, "Dockerfile", "FROM scratch\nHEALTHCHECK NONE\n")
    _commit(repo, "disabled health check")
    snapshot = _scan(repo)
    kinds = {item.kind for item in snapshot.inventory["observability_operations"].items}
    assert "HEALTH_CHECK" not in kinds
    assert "HEALTH_CHECK_DISABLED_SIGNAL" in kinds
    assert any(
        item.code == "OPERATIONS.OBSERVABILITY_EVIDENCE_ABSENT" for item in snapshot.findings
    )


def test_malformed_openapi_is_blocked_and_never_emitted_as_api_evidence(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, "openapi.yaml", "# not an OpenAPI declaration\n{}\n")
    _commit(repo, "invalid API declaration")
    snapshot = _scan(repo)
    assert snapshot.disposition == "BLOCKED"
    assert any(item.code == "INTERFACE.DECLARATION_INVALID" for item in snapshot.findings)
    assert not any(item.kind == "OPENAPI" for item in snapshot.inventory["apis_data"].items)


@pytest.mark.parametrize(
    "payload",
    [
        '{"openapi":"future","info":{"title":"x","version":"1"},"paths":{}}',
        '{"openapi":"3.1.0","info":{"title":"x","version":"1"},"paths":{"bad":[]}}',
    ],
)
def test_invalid_openapi_version_or_paths_are_not_high_confidence_evidence(
    tmp_path: Path,
    payload: str,
) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, "openapi.json", payload)
    _commit(repo, "invalid OpenAPI semantics")
    snapshot = _scan(repo)
    assert snapshot.disposition == "BLOCKED"
    assert not any(item.kind == "OPENAPI" for item in snapshot.inventory["apis_data"].items)


def test_tests_delivery_security_observability_and_governance_are_evidence_backed(
    tmp_path: Path,
) -> None:
    snapshot = _scan(_init_repo(tmp_path))
    assert snapshot.inventory["tests_quality"].items
    assert snapshot.inventory["delivery_environments"].items
    assert snapshot.inventory["security_privacy"].items
    assert snapshot.inventory["observability_operations"].items
    assert snapshot.inventory["documentation_governance"].items


def test_missing_ci_and_missing_test_categories_are_findings_not_guesses(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    snapshot = _scan(repo)
    codes = {item.code for item in snapshot.findings}
    assert "DELIVERY.CI_ABSENT" in codes
    assert "QUALITY.TEST_CATEGORY_ABSENT" in codes
    assert all(item.evidence_refs for item in snapshot.findings)
    assert all(item.confidence in {"HIGH", "MEDIUM", "LOW"} for item in snapshot.findings)


def test_multiple_lockfiles_version_drift_and_duplicate_config_are_risk_signals(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _write(repo, "packages/admin/package.json", '{"name":"admin","engines":{"node":"20"}}')
    _write(repo, "packages/admin/yarn.lock", "# yarn lock\n")
    _write(repo, ".python-version", "3.12\n")
    _commit(repo, "add drift fixtures")
    snapshot = _scan(repo)
    codes = {item.code for item in snapshot.findings}
    assert "DEPENDENCY.MULTIPLE_LOCK_ECOSYSTEMS" in codes
    assert "RUNTIME.VERSION_DRIFT_SIGNAL" in codes


def test_unknown_ecosystem_is_explicitly_unsupported(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, "main.unknownlang", "opaque\n")
    _commit(repo, "unknown stack")
    snapshot = _scan(repo)
    category = snapshot.inventory["languages_build_ecosystems"]
    assert category.status == "UNSUPPORTED"
    assert snapshot.disposition == "BLOCKED"
    assert category.reason


def test_shell_source_without_adapter_is_blocked_not_reported_absent(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, "deploy.sh", "#!/bin/sh\necho deploy\n")
    _commit(repo, "unsupported shell stack")
    snapshot = _scan(repo)
    assert snapshot.disposition == "BLOCKED"
    assert snapshot.inventory["languages_build_ecosystems"].status == "UNSUPPORTED"
    assert any(item.code == "STACK.UNSUPPORTED_FILE_TYPE" for item in snapshot.findings)


@pytest.mark.parametrize("manifest", ["Makefile", "WORKSPACE", "BUILD.bazel", "Jenkinsfile"])
def test_extensionless_unsupported_ecosystem_is_blocked(tmp_path: Path, manifest: str) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, manifest, "unsupported build definition\n")
    _commit(repo, f"add {manifest}")
    snapshot = _scan(repo)
    assert snapshot.disposition == "BLOCKED"
    assert any(
        item.code == "STACK.UNSUPPORTED_ECOSYSTEM" and manifest in item.evidence_refs
        for item in snapshot.findings
    )


def test_source_names_containing_test_are_not_high_confidence_test_evidence(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, "src/testimonial.py", "VALUE = 'not a test'\n")
    _write(repo, "packages/latest.ts", "export const value = 'not a test';\n")
    _commit(repo, "ordinary source names")
    snapshot = _scan(repo)
    test_paths = {
        item.path
        for item in snapshot.inventory["tests_quality"].items
        if item.kind.endswith("TEST_FILE_SIGNAL")
    }
    assert "src/testimonial.py" not in test_paths
    assert "packages/latest.ts" not in test_paths


def test_malformed_manifest_and_workflow_are_visible_findings(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _write(repo, "packages/web/package.json", "{not-json")
    _write(repo, ".github/workflows/ci.yml", "jobs: [\n")
    _commit(repo, "malformed inputs")
    snapshot = _scan(repo)
    codes = {item.code for item in snapshot.findings}
    assert "MANIFEST.MALFORMED" in codes
    assert "WORKFLOW.MALFORMED" in codes
    assert snapshot.disposition in {"PARTIAL", "BLOCKED"}


def test_adapter_failure_is_visible_and_cannot_remove_categories(tmp_path: Path) -> None:
    api = _api()
    repo = _init_repo(tmp_path)

    @api.repository_adapter(
        adapter_id="test.exploding",
        version="1.0.0",
        file_patterns=("**/*",),
        supported_categories=("security_privacy",),
    )
    def exploding(_context: Any) -> Any:
        raise RuntimeError("detector failed")

    snapshot = api.RepositoryScanner(
        config=_config(), adapters=(*api.default_adapters(), exploding)
    ).scan(repo, commit="HEAD")
    assert set(snapshot.inventory) == set(api.AUDIT_CATEGORIES)
    assert snapshot.disposition in {"PARTIAL", "BLOCKED"}
    assert any(item.code == "ADAPTER.FAILURE" for item in snapshot.findings)


@pytest.mark.parametrize(
    ("config_change", "expected_code"),
    [
        ({"max_files": 2}, "BUDGET.FILE_COUNT"),
        ({"max_directories": 1}, "BUDGET.DIRECTORY_COUNT"),
        ({"max_total_bytes": 16}, "BUDGET.TOTAL_BYTES"),
        ({"max_file_bytes": 8}, "BUDGET.FILE_BYTES"),
        ({"max_tree_output_bytes": 32}, "BUDGET.TREE_OUTPUT_BYTES"),
        ({"max_path_depth": 1}, "BUDGET.PATH_DEPTH"),
        ({"max_commands": 2}, "BUDGET.COMMAND_COUNT"),
    ],
)
def test_budget_exhaustion_is_explicit_partial_result(
    tmp_path: Path,
    config_change: dict[str, int],
    expected_code: str,
) -> None:
    snapshot = _scan(_init_repo(tmp_path), **config_change)
    assert snapshot.disposition in {"PARTIAL", "BLOCKED"}
    assert any(item.code == expected_code for item in snapshot.findings)
    assert set(snapshot.inventory) == set(_api().AUDIT_CATEGORIES)


def test_bounded_tree_enumeration_is_byte_deterministic(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    first = _scan(repo, max_tree_output_bytes=64)
    second = _scan(repo, max_tree_output_bytes=64)
    assert first.canonical_bytes() == second.canonical_bytes()
    assert any(item.code == "BUDGET.TREE_OUTPUT_BYTES" for item in first.findings)


def test_binary_files_are_structural_evidence_but_never_decoded(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _write(repo, "assets/blob.bin", b"\x00ghp_0123456789abcdefghijklmnop\xff")
    _commit(repo, "binary")
    snapshot = _scan(repo)
    payload = snapshot.canonical_bytes()
    assert b"ghp_0123456789abcdefghijklmnop" not in payload
    assert any(
        item.kind == "BINARY_FILE" for item in snapshot.inventory["repository_topology"].items
    )


def test_submodule_gitlink_is_inventory_only_and_never_executed(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    commit_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-index", "--add", "--cacheinfo", f"160000,{commit_sha},vendor/example")
    _git(repo, "commit", "-q", "-m", "gitlink")
    snapshot = _scan(repo)
    assert any(item.kind == "SUBMODULE" for item in snapshot.inventory["repository_topology"].items)


def test_symlink_escape_is_refused_without_following_target(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    outside = tmp_path / "outside-secret"
    outside.write_text("outside value")
    (repo / "escape").symlink_to(outside)
    _commit(repo, "escaping symlink")
    snapshot = _scan(repo)
    assert snapshot.disposition == "BLOCKED"
    assert any(item.code == "SECURITY.SYMLINK_ESCAPE" for item in snapshot.findings)
    assert "outside value" not in snapshot.canonical_bytes().decode()


def test_configured_paths_must_be_repository_relative_and_contained(tmp_path: Path) -> None:
    api = _api()
    repo = _init_repo(tmp_path)
    with pytest.raises(api.RepositorySecurityError, match="contained"):
        api.RepositoryScanner(config=_config(include_paths=("../outside",))).scan(
            repo, commit="HEAD"
        )


def test_planted_credentials_never_appear_in_snapshot(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    secret = "ghp_0123456789abcdefghijklmnop"
    _write(repo, ".env.example", f"API_KEY={secret}\n")
    _write(repo, "private.pem", "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----\n")
    _commit(repo, "secret shapes")
    payload = _scan(repo).canonical_bytes().decode()
    assert secret not in payload
    assert "PRIVATE KEY" not in payload
    assert "redaction" in payload.lower()


def test_redaction_failure_blocks_artifact_creation(tmp_path: Path) -> None:
    api = _api()
    repo = _init_repo(tmp_path)

    class BrokenRedactor:
        version = "broken"

        def sanitize(self, _value: Any) -> Any:
            raise RuntimeError("redaction unavailable")

    with pytest.raises(api.RepositorySecurityError, match="redaction"):
        api.RepositoryScanner(config=_config(), redactor=BrokenRedactor()).scan(repo, commit="HEAD")


class _FixedClock:
    def now(self) -> str:
        return "2026-08-01T00:00:00Z"


class _FixedIds:
    def new_id(self) -> str:
        return "OBS-000001"


class _FakeRemote:
    tool_identity = "fake-github-readonly/1.0"
    api_version = "github-rest/2026-03-10"

    def collect(
        self,
        repository: str,
        ref: str,
        **bounds: Any,
    ) -> dict[str, Any]:
        assert repository == "example/fixture"
        assert bounds["timeout_seconds"] > 0
        assert bounds["max_output_bytes"] > 0
        assert bounds["max_items"] > 0
        return {
            "complete": True,
            "repository": repository,
            "ref": ref,
            "observed_at": "2026-08-01T00:00:00Z",
            "coverage": ["remote_branches", "pull_requests", "issues", "governance"],
            "remote_branches": [{"name": "origin/feature", "sha": "a" * 40}],
            "pull_requests": [{"number": 7, "draft": True, "head": "a" * 40}],
            "issues": [{"number": 8, "state": "OPEN"}],
            "governance": {
                "branch_protection": {"observed": True, "required_checks": ["ci"]},
                "review_policy": {"required_approvals": 1},
                "database_note": (
                    "DATABASE_URL=postgres://database-user:database-password@db.invalid/app"
                    "?sslmode=require&token=query-secret"
                ),
                "azure_note": "AccountName=demo;AccountKey=azure-secret-value==;Endpoint=x",
                "odbc_note": "Driver=x;UID=demo;PWD={odbc secret value};Server=db",
                "cookie_note": "Cookie: session=cookie-secret; theme=dark",
                "aws_note": "aws_secret_access_key=aws-secret-value",
            },
            "query_provenance": [
                {
                    "surface": "remote_branches",
                    "query": (
                        'branches {"token":"query-json-secret","password":"pass-json-secret"}'
                    ),
                    "cursor": "branches-page-1",
                    "page": 1,
                    "has_next_page": False,
                    "result_count": 1,
                },
                {
                    "surface": "pull_requests",
                    "query": "pulls",
                    "cursor": "pulls-page-1",
                    "page": 1,
                    "has_next_page": False,
                    "result_count": 1,
                },
                {
                    "surface": "issues",
                    "query": "issues",
                    "cursor": "issues-page-1",
                    "page": 1,
                    "has_next_page": False,
                    "result_count": 1,
                },
                {
                    "surface": "governance",
                    "query": "protection",
                    "cursor": "governance-page-1",
                    "page": 1,
                    "has_next_page": False,
                    "result_count": 1,
                },
            ],
            "unknowns": [
                {"fact": "secret_scanning", "status": "BLOCKED", "reason": "permission denied"}
            ],
            "safe_url": "https://user:password@example.invalid/repo?token=secret-value",
            "signed_url": "https://storage.example.invalid/blob?sv=1&sig=signed-secret",
            "authorization": "Basic dXNlcjpwYXNzd29yZA==",
            "x-api-key": "unstructured-bare-secret",
            "note": "Authorization: Basic dXNlcjpwYXNzd29yZA==",
            "comment": "glpat-0123456789abcdefghijkl",
        }


class _DeniedRemote:
    tool_identity = "fake-github-readonly/1.0"
    api_version = "github-rest/2026-03-10"

    def collect(self, _repository: str, _ref: str, **_bounds: Any) -> dict[str, Any]:
        raise PermissionError("token ghp_0123456789abcdefghijklmnop denied")


class _PartialRemote(_FakeRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        payload = super().collect(repository, ref, **bounds)
        payload.pop("complete")
        payload["query_provenance"][0]["has_next_page"] = True
        return payload


class _StaleRemote(_FakeRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        payload = super().collect(repository, ref, **bounds)
        payload["observed_at"] = "2026-07-31T00:00:00Z"
        return payload


class _SingleSurfaceRemote(_FakeRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        payload = super().collect(repository, ref, **bounds)
        payload["query_provenance"] = payload["query_provenance"][:1]
        return payload


class _CountMismatchRemote(_FakeRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        payload = super().collect(repository, ref, **bounds)
        payload["query_provenance"][0]["result_count"] = 0
        return payload


class _EmptyGovernanceRemote(_FakeRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        payload = super().collect(repository, ref, **bounds)
        payload["governance"] = {}
        payload["query_provenance"][-1]["result_count"] = 0
        payload["unknowns"] = []
        return payload


class _UnknownGovernanceRemote(_FakeRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        payload = super().collect(repository, ref, **bounds)
        payload["governance"] = {
            "branch_protection": "UNKNOWN",
            "review_policy": {"required_approvals": 1},
        }
        payload["unknowns"] = []
        return payload


class _HangingRemote(_FakeRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        time.sleep(30)
        return super().collect(repository, ref, **bounds)


class _MismatchedRemote(_FakeRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        payload = super().collect(repository, ref, **bounds)
        payload["repository"] = "different/repository"
        return payload


class _DuplicateRemote(_FakeRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        payload = super().collect(repository, ref, **bounds)
        payload["remote_branches"].append(dict(payload["remote_branches"][0]))
        payload["query_provenance"][0]["result_count"] = 2
        return payload


def _observe(repo: Path, remote: Any = None) -> Any:
    api = _api()
    return api.GovernanceCollector(
        repository="example/fixture",
        clock=_FixedClock(),
        id_provider=_FixedIds(),
        remote_provider=remote,
    ).observe(repo, ref="main")


def test_governance_observation_records_dirty_index_worktree_and_untracked_state(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _write(repo, "README.md", "staged\n")
    _git(repo, "add", "README.md")
    _write(repo, "README.md", "staged and unstaged\n")
    _write(repo, "untracked.txt", "untracked\n")
    before = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    observation = _observe(repo)
    after = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    assert before == after
    assert observation.local_state.index_dirty is True
    assert observation.local_state.worktree_dirty is True
    assert observation.local_state.untracked is True
    assert observation.observed_at == "2026-08-01T00:00:00Z"
    assert observation.observation_id == "OBS-000001"
    assert observation.artifact_kind == "GOVERNANCE_OBSERVATION"
    assert observation.disposition == "PARTIAL"
    assert any(item.fact == "remote_governance" for item in observation.unknowns)


def test_gitlink_state_is_explicitly_unknown_instead_of_silently_clean(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    commit_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-index", "--add", "--cacheinfo", f"160000,{commit_sha},deps/sub")
    _git(repo, "commit", "-q", "-m", "gitlink fixture")
    observation = _observe(repo)
    assert observation.disposition == "BLOCKED"
    assert any(item.fact == "submodule_worktree_state" for item in observation.unknowns)


def test_branch_divergence_and_additional_worktrees_are_mutable_observations(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "switch", "-q", "-c", "feature")
    _write(repo, "feature.txt", "feature\n")
    _commit(repo, "feature")
    _git(repo, "switch", "-q", "main")
    _write(repo, "main.txt", "main\n")
    _commit(repo, "main")
    observation = _observe(repo)
    feature = next(item for item in observation.local_branches if item.name == "feature")
    assert feature.ahead >= 1 and feature.behind >= 1
    assert observation.worktrees
    assert "local_branches" not in _scan(repo).as_dict()


def test_remote_metadata_records_tool_query_cursor_and_redacts_secrets(tmp_path: Path) -> None:
    observation = _observe(_init_repo(tmp_path), _FakeRemote())
    payload = observation.canonical_bytes().decode()
    assert observation.tool_identity == "fake-github-readonly/1.0"
    assert observation.api_query_version == "github-rest/2026-03-10"
    assert observation.query_provenance[0].surface == "remote_branches"
    assert observation.query_provenance[0].cursor == "branches-page-1"
    assert observation.observation_input_digest.startswith("sha256:")
    assert observation.observation_output_digest.startswith("sha256:")
    assert "ghp_0123456789abcdefghijklmnop" not in payload
    assert "dXNlcjpwYXNzd29yZA==" not in payload
    assert "secret-value" not in payload
    assert "signed-secret" not in payload
    assert "unstructured-bare-secret" not in payload
    assert "glpat-0123456789abcdefghijkl" not in payload
    assert "database-user" not in payload
    assert "database-password" not in payload
    assert "query-secret" not in payload
    assert "azure-secret-value" not in payload
    assert "odbc secret value" not in payload
    assert "cookie-secret" not in payload
    assert "aws-secret-value" not in payload
    assert "query-json-secret" not in payload
    assert "pass-json-secret" not in payload
    assert "[REDACTED_URL]" in payload
    assert "[REDACTED]" in payload


def test_unproven_remote_pagination_is_blocked_not_complete(tmp_path: Path) -> None:
    observation = _observe(_init_repo(tmp_path), _PartialRemote())
    assert observation.disposition == "BLOCKED"
    assert any(item.fact == "remote_metadata_completeness" for item in observation.unknowns)


def test_stale_remote_metadata_is_blocked_not_complete(tmp_path: Path) -> None:
    observation = _observe(_init_repo(tmp_path), _StaleRemote())
    assert observation.disposition == "BLOCKED"
    assert any(item.fact == "remote_metadata_completeness" for item in observation.unknowns)


@pytest.mark.parametrize("remote", [_SingleSurfaceRemote(), _CountMismatchRemote()])
def test_remote_completeness_requires_per_surface_count_bound_pagination(
    tmp_path: Path,
    remote: Any,
) -> None:
    observation = _observe(_init_repo(tmp_path), remote)
    assert observation.disposition == "BLOCKED"
    assert any(item.fact == "remote_metadata_completeness" for item in observation.unknowns)


@pytest.mark.parametrize("remote", [_EmptyGovernanceRemote(), _UnknownGovernanceRemote()])
def test_empty_or_unknown_governance_is_explicitly_blocked(
    tmp_path: Path,
    remote: Any,
) -> None:
    observation = _observe(_init_repo(tmp_path), remote)
    assert observation.disposition == "BLOCKED"
    assert any(item.fact == "remote_governance_completeness" for item in observation.unknowns)


def test_remote_provider_timeout_is_bounded_and_visible(tmp_path: Path) -> None:
    api = _api()
    repo = _init_repo(tmp_path)
    started = time.monotonic()
    observation = api.GovernanceCollector(
        repository="example/fixture",
        clock=_FixedClock(),
        id_provider=_FixedIds(),
        remote_provider=_HangingRemote(),
        command_timeout_seconds=1,
    ).observe(repo, ref="main")
    assert time.monotonic() - started < 4
    assert observation.disposition == "BLOCKED"
    assert any(item.fact == "remote_governance" for item in observation.unknowns)


@pytest.mark.parametrize("remote", [_MismatchedRemote(), _DuplicateRemote()])
def test_remote_identity_mismatch_or_duplicate_inventory_fails_closed(
    tmp_path: Path, remote: Any
) -> None:
    observation = _observe(_init_repo(tmp_path), remote)
    assert observation.disposition == "BLOCKED"
    assert any(item.fact == "remote_metadata_shape" for item in observation.unknowns)


def test_remote_provider_cancellation_terminates_the_isolated_process() -> None:
    api = _api()

    class CancelSoon:
        started = time.monotonic()

        def cancelled(self) -> bool:
            return time.monotonic() - self.started > 0.2

    collector = api.GovernanceCollector(
        repository="example/fixture",
        clock=_FixedClock(),
        id_provider=_FixedIds(),
        remote_provider=_HangingRemote(),
        command_timeout_seconds=10,
        cancellation=CancelSoon(),
    )
    started = time.monotonic()
    with pytest.raises(api.RepositoryIntelligenceError, match="cancelled"):
        collector._collect_remote_bounded("main")
    assert time.monotonic() - started < 4


def test_remote_permission_denial_is_blocked_unknown_not_inferred(tmp_path: Path) -> None:
    observation = _observe(_init_repo(tmp_path), _DeniedRemote())
    assert observation.disposition == "BLOCKED"
    assert any(item.status in {"BLOCKED", "UNKNOWN"} for item in observation.unknowns)
    assert observation.remote_branches == ()
    assert "ghp_0123456789abcdefghijklmnop" not in observation.canonical_bytes().decode()


def test_observation_is_reproducible_only_from_matching_recorded_inputs(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    first = _observe(repo, _FakeRemote())
    second = _observe(repo, _FakeRemote())
    assert first.canonical_bytes() == second.canonical_bytes()
    _write(repo, "untracked.txt", "new observation input\n")
    changed = _observe(repo, _FakeRemote())
    assert first.observation_input_digest != changed.observation_input_digest
    assert first.observation_output_digest != changed.observation_output_digest


def test_scan_and_observation_never_create_branches_commits_or_remote_mutations(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    before_head = _git(repo, "rev-parse", "HEAD")
    before_branches = _git(repo, "for-each-ref", "--format=%(refname)", "refs/heads")
    before_status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    _scan(repo)
    _observe(repo, _FakeRemote())
    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert _git(repo, "for-each-ref", "--format=%(refname)", "refs/heads") == before_branches
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == before_status


def test_governance_observation_does_not_refresh_index_bytes_or_mtime(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    index = repo / ".git" / "index"
    before_bytes = index.read_bytes()
    before_mtime = index.stat().st_mtime_ns
    _observe(repo)
    assert index.read_bytes() == before_bytes
    assert index.stat().st_mtime_ns == before_mtime


def test_governance_observation_disables_repository_fsmonitor_hook(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    marker = tmp_path / "fsmonitor-must-not-run"
    hook = tmp_path / "hostile-fsmonitor.sh"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\nexit 0\n")
    hook.chmod(0o755)
    _git(repo, "config", "core.fsmonitor", str(hook))
    _observe(repo)
    assert not marker.exists()


def test_governance_refuses_repository_content_filters_without_executing_them(
    tmp_path: Path,
) -> None:
    api = _api()
    repo = _init_repo(tmp_path)
    marker = tmp_path / "content-filter-must-not-run"
    _write(repo, ".gitattributes", "README.md filter=hostile\n")
    _commit(repo, "content filter attributes")
    _git(repo, "config", "filter.hostile.clean", f"touch {marker}; cat")
    _write(repo, "README.md", "dirty content\n")
    before_head = _git(repo, "rev-parse", "HEAD")
    before_index = (repo / ".git" / "index").read_bytes()
    with pytest.raises(api.RepositorySecurityError, match="content filters"):
        _observe(repo)
    assert not marker.exists()
    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert (repo / ".git" / "index").read_bytes() == before_index
    assert (repo / "README.md").read_text() == "dirty content\n"


def test_bounded_git_termination_targets_the_isolated_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scanner = importlib.import_module("pmpe.repository.scanner")
    governance = importlib.import_module("pmpe.repository.governance")
    calls: list[tuple[int, signal.Signals]] = []

    def record_group(pid: int, action: signal.Signals) -> None:
        calls.append((pid, action))

    class Process:
        pid = 4242

        def send_signal(self, _action: signal.Signals) -> None:
            pytest.fail("process-only fallback must not be used when process groups are available")

    monkeypatch.setattr(scanner.os, "killpg", record_group)
    scanner._signal_process_group(Process(), signal.SIGTERM)
    monkeypatch.setattr(governance.os, "killpg", record_group)
    governance._signal_process_group(Process(), signal.SIGKILL)
    assert calls == [(4242, signal.SIGTERM), (4242, signal.SIGKILL)]


def test_bounded_git_termination_falls_back_to_the_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scanner = importlib.import_module("pmpe.repository.scanner")
    governance = importlib.import_module("pmpe.repository.governance")
    calls: list[signal.Signals] = []

    def denied_group(_pid: int, _action: signal.Signals) -> None:
        raise OSError("group signalling unavailable")

    class Process:
        pid = 4242

        def send_signal(self, action: signal.Signals) -> None:
            calls.append(action)

        def kill(self) -> None:
            pytest.fail("parent kill is unnecessary when send_signal succeeds")

    monkeypatch.setattr(scanner.os, "killpg", denied_group)
    scanner._signal_process_group(Process(), signal.SIGTERM)
    monkeypatch.setattr(governance.os, "killpg", denied_group)
    governance._signal_process_group(Process(), signal.SIGKILL)
    assert calls == [signal.SIGTERM, signal.SIGKILL]


def test_invalid_governance_ref_is_rejected_before_git_comparison(tmp_path: Path) -> None:
    api = _api()
    repo = _init_repo(tmp_path)
    with pytest.raises(api.RepositorySecurityError, match="ref"):
        api.GovernanceCollector(
            repository="example/fixture",
            clock=_FixedClock(),
            id_provider=_FixedIds(),
        ).observe(repo, ref="--output=outside")


def test_scanner_does_not_execute_tracked_project_code(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    marker = tmp_path / "must-not-exist"
    _write(repo, "setup.py", f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n")
    _commit(repo, "hostile project code")
    _scan(repo)
    assert not marker.exists()


class _MissingGitRunner:
    identity = "missing-git"

    def run(self, _args: tuple[str, ...], _cwd: Path, _timeout: int) -> Any:
        raise FileNotFoundError("git is not installed")


class _TimeoutRunner:
    identity = "timeout-git"

    def run(self, args: tuple[str, ...], _cwd: Path, _timeout: int) -> Any:
        return _api().CommandResult(args=args, returncode=124, stdout="", stderr="", timed_out=True)


class _MalformedRunner:
    identity = "malformed-git"

    def run(self, args: tuple[str, ...], _cwd: Path, _timeout: int) -> Any:
        return _api().CommandResult(args=args, returncode=0, stdout="not-a-sha\n", stderr="")


@pytest.mark.parametrize("runner", [_MissingGitRunner(), _TimeoutRunner(), _MalformedRunner()])
def test_missing_git_timeout_or_malformed_output_fails_closed(
    tmp_path: Path,
    runner: Any,
) -> None:
    api = _api()
    repo = _init_repo(tmp_path)
    with pytest.raises(api.RepositoryIntelligenceError):
        api.RepositoryScanner(config=_config(), command_runner=runner).scan(repo, commit="HEAD")


def test_invalid_repository_fails_closed(tmp_path: Path) -> None:
    api = _api()
    with pytest.raises(api.RepositoryIntelligenceError, match="Git repository"):
        api.RepositoryScanner(config=_config()).scan(tmp_path, commit="HEAD")


def test_cancellation_is_visible_and_never_silently_partial(tmp_path: Path) -> None:
    api = _api()
    repo = _init_repo(tmp_path)

    class Cancelled:
        def cancelled(self) -> bool:
            return True

    snapshot = api.RepositoryScanner(config=_config(), cancellation=Cancelled()).scan(
        repo, commit="HEAD"
    )
    assert snapshot.disposition == "BLOCKED"
    assert any(item.code == "SCAN.CANCELLED" for item in snapshot.findings)


def test_cancellation_terminates_bounded_enumeration_and_preserves_repository(
    tmp_path: Path,
) -> None:
    api = _api()
    repo = _init_repo(tmp_path)
    before_head = _git(repo, "rev-parse", "HEAD")
    before_index = (repo / ".git" / "index").read_bytes()
    before_status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")

    class CancelDuringTree:
        calls = 0

        def cancelled(self) -> bool:
            self.calls += 1
            return self.calls > 1

    snapshot = api.RepositoryScanner(config=_config(), cancellation=CancelDuringTree()).scan(
        repo, commit="HEAD"
    )
    assert snapshot.disposition == "BLOCKED"
    assert any(item.code == "SCAN.CANCELLED" and item.blocking for item in snapshot.findings)
    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert (repo / ".git" / "index").read_bytes() == before_index
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == before_status


def test_cancellation_terminates_an_ordinary_bounded_git_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scanner = importlib.import_module("pmpe.repository.scanner")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text("#!/bin/sh\nsleep 30\n")
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:/usr/bin:/bin")

    class CancelSoon:
        started = time.monotonic()

        def cancelled(self) -> bool:
            return time.monotonic() - self.started > 0.2

    started = time.monotonic()
    result = scanner.SubprocessCommandRunner().run(
        ("git", "version"), tmp_path, 10, cancellation=CancelSoon()
    )
    assert time.monotonic() - started < 4
    assert result.returncode == 126
    assert result.timed_out is False


def test_cancellation_during_final_adapter_blocks_snapshot_finalization(tmp_path: Path) -> None:
    api = _api()
    adapters = importlib.import_module("pmpe.repository.adapters")
    repo = _init_repo(tmp_path)
    before_head = _git(repo, "rev-parse", "HEAD")
    before_status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")

    class CancellationAfterAdapter:
        started = time.monotonic()

        def cancelled(self) -> bool:
            return time.monotonic() - self.started > 0.2

    cancellation = CancellationAfterAdapter()

    def evaluate(_context: Any) -> Any:
        time.sleep(30)
        return adapters.AdapterResult()

    final_adapter = api.RepositoryAdapter(
        adapter_id="test.final-cancellation",
        version="1.0.0",
        file_patterns=("*",),
        supported_categories=("repository_topology",),
        evaluator=evaluate,
    )
    snapshot = api.RepositoryScanner(
        config=_config(),
        adapters=(final_adapter,),
        cancellation=cancellation,
    ).scan(repo, commit="HEAD")
    assert snapshot.disposition == "BLOCKED"
    assert any(item.code == "SCAN.CANCELLED" and item.blocking for item in snapshot.findings)
    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == before_status


def test_governance_cancellation_terminates_bounded_command_and_preserves_repository(
    tmp_path: Path,
) -> None:
    api = _api()
    repo = _init_repo(tmp_path)
    before_head = _git(repo, "rev-parse", "HEAD")
    before_index = (repo / ".git" / "index").read_bytes()

    class CancelInsideCommand:
        calls = 0

        def cancelled(self) -> bool:
            self.calls += 1
            return self.calls > 1

    collector = api.GovernanceCollector(
        repository="example/fixture",
        clock=_FixedClock(),
        id_provider=_FixedIds(),
        cancellation=CancelInsideCommand(),
    )
    with pytest.raises(api.RepositoryIntelligenceError, match="cancelled"):
        collector.observe(repo, ref="main")
    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert (repo / ".git" / "index").read_bytes() == before_index


def test_git_readers_disable_lazy_fetch_and_repository_defined_accelerators() -> None:
    scanner = importlib.import_module("pmpe.repository.scanner")
    governance = importlib.import_module("pmpe.repository.governance")
    scanner_environment = scanner.SubprocessCommandRunner._environment()
    assert scanner_environment["GIT_NO_LAZY_FETCH"] == "1"
    assert scanner_environment["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert scanner_environment["GIT_CONFIG_VALUE_0"] == "false"
    governance_runner = governance.GovernanceCommandRunner()
    assert scanner_environment["GIT_CONFIG_VALUE_5"] == "false"
    assert governance_runner.identity.endswith("1.5.0")


def test_artifact_maps_cannot_be_mutated_after_digest_binding(tmp_path: Path) -> None:
    snapshot = _scan(_init_repo(tmp_path))
    observation = _observe(tmp_path / "fixture-repo")
    with pytest.raises(TypeError):
        snapshot.inventory["repository_topology"] = snapshot.inventory[  # type: ignore[index]
            "repository_topology"
        ]
    with pytest.raises(TypeError):
        observation.governance["branch_protection"] = "changed"  # type: ignore[index]
    assert snapshot.snapshot_digest in snapshot.canonical_bytes().decode()
    assert observation.observation_output_digest in observation.canonical_bytes().decode()


def test_snapshot_and_observation_references_form_a_narrow_lifecycle_seam(
    tmp_path: Path,
) -> None:
    api = _api()
    repo = _init_repo(tmp_path)
    snapshot = _scan(repo)
    observation = api.GovernanceCollector(
        repository="example/fixture",
        snapshot=snapshot,
        clock=_FixedClock(),
        id_provider=_FixedIds(),
    ).observe(repo, ref="main")
    reference = snapshot.assessment_reference(observation)
    assert reference == {
        "repository_snapshot_digest": snapshot.snapshot_digest,
        "repository_commit": snapshot.commit_sha,
        "governance_observation_id": observation.observation_id,
        "governance_observation_digest": observation.observation_output_digest,
    }
    assert "architecture" not in reference
    assert "recommendation" not in reference


def test_snapshot_rejects_governance_observation_from_another_repository(
    tmp_path: Path,
) -> None:
    api = _api()
    snapshot = _scan(_init_repo(tmp_path))
    observation = api.GovernanceCollector(
        repository="different/repository",
        clock=_FixedClock(),
        id_provider=_FixedIds(),
    ).observe(tmp_path / "fixture-repo", ref="main")
    with pytest.raises(ValueError, match="repositories do not match"):
        snapshot.assessment_reference(observation)
