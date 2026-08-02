"""Issue #64 RED contract for deterministic repository intelligence."""

from __future__ import annotations

import importlib
import json
import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from types import FunctionType, ModuleType
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
    assert ("git", "version") in {item.args for item in first.command_provenance}


def test_exact_sha_snapshot_does_not_depend_on_host_secret_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_repo(tmp_path)
    baseline = _scan(repo)
    monkeypatch.setenv("CLAUDESECRET", "repository")
    assert _scan(repo).canonical_bytes() == baseline.canonical_bytes()


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
    assert scoped.disposition == "BLOCKED"
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


def test_adapter_order_does_not_change_output_and_registry_is_sealed(tmp_path: Path) -> None:
    api = _api()
    canonical = importlib.import_module("pmpe.contracts.canonical")
    scanner = importlib.import_module("pmpe.repository.scanner")
    repo = _init_repo(tmp_path)
    adapters = api.default_adapters()
    first = api.RepositoryScanner(config=_config(), adapters=adapters).scan(repo, commit="HEAD")
    reordered = api.RepositoryScanner(config=_config(), adapters=tuple(reversed(adapters))).scan(
        repo, commit="HEAD"
    )
    assert first.canonical_bytes() == reordered.canonical_bytes()

    changed = (replace(adapters[0], version="99.0.0"), *adapters[1:])
    original_digest = canonical.canonical_digest(
        [asdict(scanner._metadata(item)) for item in adapters]
    )
    changed_digest = canonical.canonical_digest(
        [asdict(scanner._metadata(item)) for item in changed]
    )
    assert original_digest != changed_digest
    with pytest.raises(api.RepositorySecurityError, match="sealed built-in adapter registry"):
        api.RepositoryScanner(config=_config(), adapters=changed)


def test_unregistered_adapter_cannot_execute_or_mutate_the_repository(
    tmp_path: Path,
) -> None:
    api = _api()
    adapters = importlib.import_module("pmpe.repository.adapters")
    repo = _init_repo(tmp_path)
    marker = repo / "adapter-mutated.txt"

    def mutate_repository(_context: Any) -> Any:
        marker.write_text("mutation\n")
        return adapters.AdapterResult()

    unregistered = api.RepositoryAdapter(
        adapter_id="test.mutating-adapter",
        version="1.0.0",
        file_patterns=("*",),
        supported_categories=("repository_topology",),
        evaluator=mutate_repository,
    )
    before = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    with pytest.raises(api.RepositorySecurityError, match="sealed built-in adapter registry"):
        api.RepositoryScanner(config=_config(), adapters=(unregistered,))
    assert not marker.exists()
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == before


def test_implementation_provenance_is_independent_of_checkout_path(tmp_path: Path) -> None:
    scanner = importlib.import_module("pmpe.repository.scanner")
    source = "def evaluate(context):\n    return len(context)\n"
    implementations: list[Any] = []
    for name in ("clone-a", "clone-b"):
        source_path = tmp_path / name / "adapter.py"
        source_path.parent.mkdir()
        source_path.write_text(source)
        namespace: dict[str, Any] = {"__name__": "fixture.adapter"}
        exec(compile(source, str(source_path), "exec"), namespace)
        implementations.append(namespace["evaluate"])
    assert scanner._implementation_source_evidence(
        "adapter:test", implementations[0]
    ) == scanner._implementation_source_evidence("adapter:test", implementations[1])


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


def test_implementation_digest_binds_loaded_runtime_code_and_source_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scanner = importlib.import_module("pmpe.repository.scanner")
    original = scanner._implementation_digest()

    def assert_digest_changed_or_mutation_rejected() -> None:
        try:
            candidate = scanner._implementation_digest()
        except scanner.RepositorySecurityError as exc:
            assert "changed" in str(exc)
        else:
            assert candidate != original

    with monkeypatch.context() as runtime_patch:
        runtime_patch.setattr(scanner, "_valid_object_id", lambda _value, _format: True)
        assert_digest_changed_or_mutation_rejected()
    with monkeypatch.context() as runtime_patch:
        runtime_patch.setattr(scanner, "_OBJECT_FORMAT_LENGTH", {"sha1": 1, "sha256": 1})
        assert_digest_changed_or_mutation_rejected()
    redaction = importlib.import_module("pmpe.repository.redaction")
    with monkeypatch.context() as runtime_patch:
        runtime_patch.setattr(redaction.EvidenceRedactor, "_token", re.compile(r"changed"))
        assert_digest_changed_or_mutation_rejected()
    yaml_module = importlib.import_module("yaml")
    with monkeypatch.context() as runtime_patch:
        runtime_patch.setattr(yaml_module, "safe_load", lambda value: value)
        assert_digest_changed_or_mutation_rejected()
    with monkeypatch.context() as runtime_patch:
        runtime_patch.setattr(yaml_module, "load", lambda value, **_kwargs: value)
        assert_digest_changed_or_mutation_rejected()
    rfc8785_module = importlib.import_module("rfc8785")
    with monkeypatch.context() as runtime_patch:
        runtime_patch.setattr(rfc8785_module, "dumps", lambda value: b"changed")
        assert_digest_changed_or_mutation_rejected()
    rfc8785_impl = importlib.import_module("rfc8785._impl")
    with monkeypatch.context() as runtime_patch:
        runtime_patch.setattr(rfc8785_impl, "_serialize_str", lambda value, sink: None)
        assert_digest_changed_or_mutation_rejected()
    hashlib_module = importlib.import_module("hashlib")
    original_sha256 = hashlib_module.sha256
    with monkeypatch.context() as runtime_patch:
        runtime_patch.setattr(
            hashlib_module,
            "sha256",
            lambda payload=b"", *args, **kwargs: original_sha256(payload, *args, **kwargs),
        )
        assert_digest_changed_or_mutation_rejected()
    urllib_parse = importlib.import_module("urllib.parse")
    with monkeypatch.context() as runtime_patch:
        runtime_patch.setattr(urllib_parse, "uses_netloc", [*urllib_parse.uses_netloc, "custom"])
        assert_digest_changed_or_mutation_rejected()
    json_module = importlib.import_module("json")
    with monkeypatch.context() as runtime_patch:
        runtime_patch.setattr(json_module, "_default_decoder", json.JSONDecoder(strict=False))
        assert_digest_changed_or_mutation_rejected()
    with monkeypatch.context() as runtime_patch:
        runtime_patch.setattr(
            json_module._default_decoder,
            "scan_once",
            json.JSONDecoder(strict=False).scan_once,
        )
        assert_digest_changed_or_mutation_rejected()
    for module_name, attribute in (
        ("configparser", "ConfigParser"),
        ("datetime", "datetime"),
        ("fnmatch", "fnmatch"),
        ("json", "loads"),
        ("shlex", "split"),
        ("tomllib", "loads"),
        ("urllib.parse", "urlsplit"),
        ("urllib.parse", "_coerce_args"),
        ("_datetime", "datetime"),
        ("_json", "scanstring"),
        ("_sre", "compile"),
        ("math", "isfinite"),
        ("re._compiler", "_compile"),
        ("re._parser", "parse"),
    ):
        module = importlib.import_module(module_name)
        with monkeypatch.context() as runtime_patch:
            runtime_patch.setattr(module, attribute, lambda *_args, **_kwargs: {})
            assert_digest_changed_or_mutation_rejected()
    runtime_digest = scanner._module_runtime_digest("repository.scanner")
    with monkeypatch.context() as runtime_patch:
        runtime_patch.setattr(
            scanner,
            "_IMPLEMENTATION_PATHS",
            {"repository.scanner": Path("/different/checkout/scanner.py")},
        )
        runtime_patch.setattr(
            scanner,
            "_IMPORTED_SOURCE_DIGESTS",
            {"repository.scanner": "sha256:" + "f" * 64},
        )
        assert scanner._module_runtime_digest("repository.scanner") == runtime_digest

    mismatched_sources = dict(scanner._IMPORTED_SOURCE_DIGESTS)
    mismatched_sources["repository.scanner"] = "sha256:" + "0" * 64
    with pytest.raises(scanner.RepositorySecurityError, match="changed after"):
        scanner._implementation_module_evidence(
            scanner._IMPLEMENTATION_PATHS,
            mismatched_sources,
        )


def test_implementation_digest_rejects_replaced_output_module_before_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scanner = importlib.import_module("pmpe.repository.scanner")
    callback_ran = False

    class PlatformProxy:
        def python_version(self) -> str:
            nonlocal callback_ran
            callback_ran = True
            return "forged"

    monkeypatch.setattr(scanner, "platform", PlatformProxy())
    with pytest.raises(scanner.RepositorySecurityError, match="imported-module"):
        scanner._implementation_digest()
    assert callback_ran is False


def test_implementation_digest_seals_every_direct_module_attribute_before_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scanner = importlib.import_module("pmpe.repository.scanner")
    attributes = dict(scanner._SEALED_SCANNER_MODULE_ATTRIBUTE_NAMES)
    assert {"version", "PackageNotFoundError"} <= set(attributes["importlib_metadata"])
    assert "python_version" in attributes["platform"]
    assert "get_context" in attributes["multiprocessing"]
    assert "__version__" in attributes["yaml"]

    callback_ran = False
    original_version = scanner.importlib_metadata.version

    def version_proxy(distribution: str) -> str:
        nonlocal callback_ran
        callback_ran = True
        return original_version(distribution)

    monkeypatch.setattr(scanner.importlib_metadata, "version", version_proxy)
    with pytest.raises(scanner.RepositorySecurityError, match="attributes changed"):
        scanner.RepositoryScanner(config=_config())
    assert callback_ran is False


def test_implementation_digest_seals_adapter_isolation_and_yaml_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scanner = importlib.import_module("pmpe.repository.scanner")
    callback_ran = False
    original_context = scanner.multiprocessing.get_context

    def context_proxy(*args: Any, **kwargs: Any) -> Any:
        nonlocal callback_ran
        callback_ran = True
        return original_context(*args, **kwargs)

    with monkeypatch.context() as runtime_patch:
        runtime_patch.setattr(scanner.multiprocessing, "get_context", context_proxy)
        with pytest.raises(scanner.RepositorySecurityError, match="attributes changed"):
            scanner._implementation_digest()
        assert callback_ran is False
    with monkeypatch.context() as runtime_patch:
        runtime_patch.setattr(scanner.yaml, "__version__", "forged-version")
        with pytest.raises(scanner.RepositorySecurityError, match="attributes changed"):
            scanner._implementation_digest()


def test_implementation_digest_seals_returned_multiprocessing_context_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scanner = importlib.import_module("pmpe.repository.scanner")
    context = scanner._SEALED_MULTIPROCESSING_CONTEXT
    callback_ran = False

    def pipe_proxy(*args: Any, **kwargs: Any) -> Any:
        nonlocal callback_ran
        callback_ran = True
        return scanner.multiprocessing.Pipe(*args, **kwargs)

    with monkeypatch.context() as runtime_patch:
        runtime_patch.setattr(type(context), "Pipe", pipe_proxy)
        with pytest.raises(scanner.RepositorySecurityError, match="context or members changed"):
            scanner._implementation_digest()
        assert callback_ran is False

    with monkeypatch.context() as runtime_patch:
        runtime_patch.setitem(vars(context), "Pipe", pipe_proxy)
        with pytest.raises(
            scanner.RepositorySecurityError, match="runtime or context instance changed"
        ):
            scanner._sealed_fork_pipe(duplex=False)
        assert callback_ran is False

    with monkeypatch.context() as runtime_patch:
        runtime_patch.setattr(scanner.multiprocessing_connection, "Pipe", pipe_proxy)
        with pytest.raises(scanner.RepositorySecurityError, match="runtime or context"):
            scanner._sealed_fork_pipe(duplex=False)
        assert callback_ran is False

    replacement_context = type(context)()
    with monkeypatch.context() as runtime_patch:
        runtime_patch.setattr(scanner, "_SEALED_MULTIPROCESSING_CONTEXT", replacement_context)
        with pytest.raises(scanner.RepositorySecurityError, match="context or members changed"):
            scanner._implementation_digest()


def test_artifact_digest_verification_rejects_same_code_forged_globals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scanner = importlib.import_module("pmpe.repository.scanner")
    models = importlib.import_module("pmpe.repository.models")
    snapshot = _scan(_init_repo(tmp_path))
    callback_ran = False
    original = models.canonical_digest
    forged_globals = dict(original.__globals__)

    def forged_json_bytes(_value: Any) -> bytes:
        nonlocal callback_ran
        callback_ran = True
        return b"forged"

    forged_globals["canonical_json_bytes"] = forged_json_bytes
    forged = FunctionType(
        original.__code__,
        forged_globals,
        name=original.__name__,
        argdefs=original.__defaults__,
        closure=original.__closure__,
    )
    monkeypatch.setattr(models, "canonical_digest", forged)
    with pytest.raises(ValueError, match="artifact digest bindings changed"):
        snapshot.digest_is_valid()
    with pytest.raises(scanner.RepositorySecurityError, match="model digest bindings changed"):
        scanner._implementation_digest()
    assert callback_ran is False


def test_imported_non_callable_globals_are_sealed_before_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scanner = importlib.import_module("pmpe.repository.scanner")
    governance = importlib.import_module("pmpe.repository.governance")
    assert "AUDIT_CATEGORIES" in scanner._SEALED_SCANNER_EXTERNAL_GLOBAL_NAMES
    assert "UTC" in governance._SEALED_GOVERNANCE_EXTERNAL_GLOBAL_NAMES

    monkeypatch.setattr(scanner, "AUDIT_CATEGORIES", ("forged",))
    with pytest.raises(scanner.RepositorySecurityError, match="imported global bindings changed"):
        scanner._implementation_digest()


def test_governance_rejects_replaced_timezone_before_callbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    governance = importlib.import_module("pmpe.repository.governance")
    callback_ran = False

    class TimezoneProxy(tzinfo):
        def utcoffset(self, value: datetime | None) -> timedelta:
            nonlocal callback_ran
            callback_ran = True
            return timedelta(0)

    monkeypatch.setattr(governance, "UTC", TimezoneProxy())
    with pytest.raises(
        governance.RepositorySecurityError, match="imported global bindings changed"
    ):
        governance._governance_implementation_digest()
    assert callback_ran is False


def test_governance_digest_rejects_replaced_output_module_before_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    governance = importlib.import_module("pmpe.repository.governance")
    callback_ran = False

    class UuidProxy:
        def uuid4(self) -> Any:
            nonlocal callback_ran
            callback_ran = True
            return "forged"

    monkeypatch.setattr(governance, "uuid", UuidProxy())
    with pytest.raises(governance.RepositorySecurityError, match="imported-module"):
        governance._governance_implementation_digest()
    assert callback_ran is False


def test_governance_digest_rejects_in_place_module_attribute_before_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    governance = importlib.import_module("pmpe.repository.governance")
    attributes = dict(governance._SEALED_GOVERNANCE_MODULE_ATTRIBUTE_NAMES)
    assert "uuid4" in attributes["uuid"]
    assert "_sealed_multiprocessing_context" in governance._SEALED_GOVERNANCE_EXTERNAL_GLOBAL_NAMES
    callback_ran = False
    original_uuid4 = governance.uuid.uuid4

    def uuid_proxy() -> Any:
        nonlocal callback_ran
        callback_ran = True
        return original_uuid4()

    monkeypatch.setattr(governance.uuid, "uuid4", uuid_proxy)
    with pytest.raises(governance.RepositorySecurityError, match="attributes changed"):
        governance._governance_implementation_digest()
    assert callback_ran is False


def test_dormant_cancellation_signal_does_not_change_exact_snapshot(tmp_path: Path) -> None:
    api = _api()
    repo = _init_repo(tmp_path)
    baseline = api.RepositoryScanner(config=_config()).scan(repo, commit="HEAD")
    cancellable = api.RepositoryScanner(
        config=_config(),
        cancellation=api.CancellationSignal(),
    ).scan(repo, commit="HEAD")
    assert cancellable.canonical_bytes() == baseline.canonical_bytes()
    assert cancellable.implementation_digest == baseline.implementation_digest


def test_governance_provenance_binds_every_material_repository_module() -> None:
    governance = importlib.import_module("pmpe.repository.governance")
    assert set(governance.GOVERNANCE_IMPLEMENTATION_MODULES) == {
        "repository.governance",
        "repository.models",
        "repository.redaction",
        "repository.scanner",
        "contracts.canonical",
    }
    original = governance._governance_implementation_digest()

    def assert_digest_changed_or_mutation_rejected() -> None:
        try:
            candidate = governance._governance_implementation_digest()
        except governance.RepositorySecurityError as exc:
            assert "imported" in str(exc)
        else:
            assert candidate != original

    rfc8785_module = importlib.import_module("rfc8785")
    with pytest.MonkeyPatch.context() as runtime_patch:
        runtime_patch.setattr(rfc8785_module, "dumps", lambda value: b"changed")
        assert_digest_changed_or_mutation_rejected()
    with pytest.MonkeyPatch.context() as runtime_patch:
        runtime_patch.setattr(governance, "UTC", timezone(timedelta(hours=1)))
        assert_digest_changed_or_mutation_rejected()


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


def test_api_codegen_declarations_bind_tracked_inputs_outputs_and_exporter(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(
        repo,
        "products/web/package.json",
        json.dumps(
            {
                "name": "web",
                "scripts": {
                    "generate:api-types": (
                        "openapi-typescript ../backend/schema.json -o src/lib/api.ts"
                    )
                },
            }
        ),
    )
    _write(
        repo,
        "products/backend/schema.json",
        '{"$schema":"https://json-schema.org/draft/2020-12/schema"}',
    )
    _write(repo, "products/web/src/lib/api.ts", "export interface paths {}\n")
    _write(
        repo,
        "openapi.json",
        '{"openapi":"3.1.0","info":{"title":"Fixture","version":"1"},"paths":{}}',
    )
    _write(
        repo,
        "scripts/export_openapi.py",
        'target = root / "openapi.json"\ntarget.write_text("{}")\n',
    )
    _commit(repo, "code generation relationship")

    snapshot = _scan(repo)
    evidence = snapshot.inventory["apis_data"].items
    relationship = [
        item
        for item in evidence
        if item.location == "products/web/package.json#scripts.generate:api-types"
    ]
    assert {item.kind for item in relationship} == {
        "CODE_GENERATION_DECLARATION",
        "CODE_GENERATION_INPUT",
        "CODE_GENERATION_OUTPUT",
    }
    assert {item.path for item in relationship} == {
        "products/web/package.json",
        "products/backend/schema.json",
        "products/web/src/lib/api.ts",
    }
    export_relationship = [
        item for item in evidence if item.location == "scripts/export_openapi.py#export"
    ]
    assert {item.kind for item in export_relationship} == {
        "CODE_GENERATOR_SIGNAL",
        "CODE_GENERATION_OUTPUT",
    }
    assert all(item.confidence == "MEDIUM" for item in export_relationship)


def test_openapi_named_source_or_documentation_is_not_parsed_as_a_contract(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, "docs/openapi-guide.md", "# OpenAPI authoring guide\n")
    _write(repo, "src/openapi_helpers.py", "def helper() -> None:\n    pass\n")
    _commit(repo, "non-contract OpenAPI names")
    snapshot = _scan(repo)
    assert not any(
        item.code == "INTERFACE.DECLARATION_INVALID"
        and set(item.evidence_refs) & {"docs/openapi-guide.md", "src/openapi_helpers.py"}
        for item in snapshot.findings
    )


def test_binary_api_declaration_is_blocked_not_silently_omitted(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, "openapi.json", b'{"openapi":"3.1.0"}\0')
    _commit(repo, "binary API declaration")
    snapshot = _scan(repo)
    assert snapshot.disposition == "BLOCKED"
    assert any(
        item.code == "INTERFACE.DECLARATION_INVALID"
        and item.evidence_refs == ("openapi.json",)
        and item.blocking
        for item in snapshot.findings
    )


def test_incomplete_api_codegen_relationship_fails_closed(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(
        repo,
        "products/web/package.json",
        json.dumps(
            {
                "name": "web",
                "scripts": {
                    "generate:api-types": (
                        "openapi-typescript ../backend/missing.json -o src/lib/api-types.gen.ts"
                    )
                },
            }
        ),
    )
    _commit(repo, "incomplete code generation relationship")
    snapshot = _scan(repo)
    assert snapshot.disposition == "BLOCKED"
    assert any(
        item.code == "INTERFACE.CODEGEN_RELATIONSHIP_INCOMPLETE" for item in snapshot.findings
    )


def test_database_privacy_and_observability_subcategories_are_explicit(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, "schema.sql", "create table item(id integer);\n")
    _write(repo, "privacy.yaml", "retention_days: 30\n")
    _write(repo, "prometheus.yml", "scrape_configs: []\n")
    _commit(repo, "required audit subcategories")
    snapshot = _scan(repo)
    assert any(
        item.path == "schema.sql" and item.kind == "DATABASE_SCHEMA_SIGNAL"
        for item in snapshot.inventory["apis_data"].items
    )
    assert any(
        item.path == "privacy.yaml" and item.kind == "PRIVACY_CONTROL_SIGNAL"
        for item in snapshot.inventory["security_privacy"].items
    )
    assert any(
        item.path == "prometheus.yml" and item.kind == "OBSERVABILITY_CONFIG_SIGNAL"
        for item in snapshot.inventory["observability_operations"].items
    )


def test_nested_package_manifests_create_explicit_architecture_boundaries(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, "products/example/backend/pyproject.toml", "[project]\nname='backend'\n")
    _write(repo, "products/example/frontend/package.json", '{"name":"frontend"}\n')
    _write(repo, "products/example/e2e/package.json", '{"name":"e2e"}\n')
    _commit(repo, "nested package boundaries")
    snapshot = _scan(repo)
    boundaries = {item.name: item for item in snapshot.boundary_candidates}
    assert {
        "products/example/backend",
        "products/example/frontend",
        "products/example/e2e",
    } <= set(boundaries)
    assert boundaries["products/example/backend"].evidence_paths == (
        "products/example/backend/pyproject.toml",
    )
    assert boundaries["products/example/frontend"].evidence_paths == (
        "products/example/frontend/package.json",
    )
    assert boundaries["products/example/backend"].confidence == "HIGH"


def test_entry_points_and_test_coverage_configuration_are_explicit_inventory(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(
        repo,
        "services/api/pyproject.toml",
        (
            "[project]\nname='api'\nversion='1'\n"
            "[project.scripts]\napi='api.cli:main'\n"
            "[project.entry-points.'api.plugins']\nfixture='api.plugin:load'\n"
            "[tool.pytest.ini_options]\ntestpaths=['tests']\n"
            "[tool.coverage.run]\nbranch=true\n"
        ),
    )
    _write(
        repo,
        "services/worker/setup.cfg",
        (
            "[metadata]\nname = worker\n[tool:pytest]\ntestpaths = tests\n"
            "[coverage:run]\nbranch = true\n"
            "[options.entry_points]\nconsole_scripts =\n    worker = worker.cli:main\n"
        ),
    )
    _write(repo, "services/api/src/api/__main__.py", "raise SystemExit(0)\n")
    _write(
        repo,
        "apps/web/package.json",
        json.dumps(
            {
                "name": "web",
                "version": "1.0.0",
                "main": "src/index.js",
                "scripts": {
                    "start": "node src/index.js",
                    "test": "vitest",
                    "test:coverage": "vitest --coverage",
                },
                "vitest": {"globals": True},
                "nyc": {"all": True},
            }
        ),
    )
    _write(repo, "apps/web/playwright.config.ts", "export default {};\n")
    _write(repo, "apps/web/vitest.config.ts", "export default {};\n")
    _write(repo, ".coveragerc", "[run]\nbranch = True\n")
    _commit(repo, "entry-point and quality configuration evidence")

    snapshot = _scan(repo)
    architecture = {
        (item.path, item.kind) for item in snapshot.inventory["architecture_boundaries"].items
    }
    quality = {(item.path, item.kind) for item in snapshot.inventory["tests_quality"].items}
    assert (
        "services/api/pyproject.toml",
        "DECLARED_ENTRY_POINT",
    ) in architecture
    assert (
        "services/api/src/api/__main__.py",
        "ENTRY_POINT_FILE_SIGNAL",
    ) in architecture
    assert ("apps/web/package.json", "DECLARED_ENTRY_POINT") in architecture
    assert ("apps/web/package.json", "DECLARED_RUN_ENTRY_POINT") in architecture
    assert ("services/api/pyproject.toml", "TEST_CONFIGURATION") in quality
    assert ("services/api/pyproject.toml", "COVERAGE_CONFIGURATION") in quality
    assert ("services/worker/setup.cfg", "DECLARED_ENTRY_POINT") in architecture
    assert ("services/worker/setup.cfg", "TEST_CONFIGURATION") in quality
    assert ("services/worker/setup.cfg", "COVERAGE_CONFIGURATION") in quality
    assert ("apps/web/package.json", "DECLARED_TEST_COMMAND") in quality
    assert ("apps/web/package.json", "DECLARED_COVERAGE_COMMAND") in quality
    assert ("apps/web/package.json", "TEST_CONFIGURATION") in quality
    assert ("apps/web/package.json", "COVERAGE_CONFIGURATION") in quality
    assert ("apps/web/playwright.config.ts", "TEST_CONFIGURATION") in quality
    assert ("apps/web/vitest.config.ts", "TEST_CONFIGURATION") in quality
    assert (".coveragerc", "COVERAGE_CONFIGURATION") in quality


def test_dynamic_python_entry_points_are_explicitly_unsupported(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, "setup.py", "from setuptools import setup\nsetup(name='fixture')\n")
    _commit(repo, "dynamic Python packaging")
    snapshot = _scan(repo)
    assert snapshot.disposition == "BLOCKED"
    assert any(
        item.code == "ARCHITECTURE.DYNAMIC_ENTRY_POINTS_UNSUPPORTED"
        and item.evidence_refs == ("setup.py",)
        and item.blocking
        for item in snapshot.findings
    )


def test_every_recognized_nested_python_manifest_creates_a_package_boundary(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, "components/setup-project/setup.py", "from setuptools import setup\n")
    _write(repo, "components/config-project/setup.cfg", "[metadata]\nname = config-project\n")
    _write(repo, "components/pipfile-project/Pipfile", "[packages]\n")
    _write(repo, "components/requirements-project/requirements-dev.txt", "pytest==9.1.1\n")
    _commit(repo, "recognized nested Python boundaries")
    snapshot = _scan(repo)
    boundaries = {item.name: item for item in snapshot.boundary_candidates}
    expected = {
        "components/setup-project",
        "components/config-project",
        "components/pipfile-project",
        "components/requirements-project",
    }
    assert expected <= set(boundaries)
    assert all(boundaries[name].confidence == "HIGH" for name in expected)


def test_unhandled_required_subcategory_is_blocked_not_silently_absent(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, "data-model.yaml", "entities: []\n")
    _commit(repo, "unhandled data declaration")
    snapshot = _scan(repo)
    assert snapshot.disposition == "BLOCKED"
    assert snapshot.inventory["apis_data"].status == "BLOCKED"
    assert any(
        item.code == "AUDIT.UNSUPPORTED_SUBCATEGORY" and "data-model.yaml" in item.evidence_refs
        for item in snapshot.findings
    )


def test_every_required_internal_audit_subcategory_is_explicit(tmp_path: Path) -> None:
    snapshot = _scan(_init_repo(tmp_path, mixed=False))
    unsupported = {
        item.explanation
        for item in snapshot.findings
        if item.code == "AUDIT.REQUIRED_SUBCATEGORY_UNSUPPORTED"
    }
    assert all(
        any(capability in explanation for explanation in unsupported)
        for capability in (
            "ignored paths",
            "internal dependency direction",
            "shared-library relationships",
            "CLI boundaries",
            "worker boundaries",
            "library boundaries",
            "infrastructure-area boundaries",
            "module boundaries",
            "bounded-context boundaries",
            "storage models",
            "deployment-evidence mechanisms",
            "release workflows",
            "preview environments",
            "container definitions",
            "infrastructure-as-code",
            "deployment definitions",
            "environment configuration shapes",
            "rollback mechanisms",
            "dependency audits",
            "static application security testing",
            "secret scanning",
            "permissions",
            "credential boundaries",
            "data retention and privacy controls",
            "security configuration",
            "logs",
            "metrics",
            "traces",
            "alerting",
            "service-level objectives",
            "health checks",
            "incident and rollback evidence",
            "telemetry schemas",
            "production feedback paths",
        )
    )
    assert snapshot.disposition == "BLOCKED"


def test_security_privacy_observability_and_delivery_facets_are_never_silent(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    for path in (".semgrep.yml", "gitleaks.toml", ".snyk", "sentry.yml"):
        _write(repo, path, "enabled: true\n")
    _commit(repo, "required audit facet signals")
    snapshot = _scan(repo)
    for category in (
        "security_privacy",
        "observability_operations",
        "delivery_environments",
    ):
        assert snapshot.inventory[category].status == "BLOCKED"
        assert any(
            item.code == "AUDIT.REQUIRED_SUBCATEGORY_UNSUPPORTED"
            and item.category == category
            and item.blocking
            for item in snapshot.findings
        )


def test_worker_library_and_infrastructure_boundaries_are_typed(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, "workers/queue/worker.py", "def run() -> None:\n    pass\n")
    _write(repo, "libraries/shared/lib.py", "VALUE = 1\n")
    _write(repo, "infra/runtime/main.tf", "terraform {}\n")
    _commit(repo, "typed boundary areas")
    snapshot = _scan(repo)
    boundaries = {(item.kind, item.name) for item in snapshot.boundary_candidates}
    assert {
        ("WORKER", "workers/queue"),
        ("LIBRARY", "libraries/shared"),
        ("INFRASTRUCTURE_AREA", "infra/runtime"),
    } <= boundaries
    unsupported = {
        item.explanation
        for item in snapshot.findings
        if item.code == "AUDIT.REQUIRED_SUBCATEGORY_UNSUPPORTED"
    }
    assert not any("worker boundaries" in explanation for explanation in unsupported)
    assert not any("library boundaries" in explanation for explanation in unsupported)
    assert not any("infrastructure-area boundaries" in explanation for explanation in unsupported)


def test_migration_path_signal_cannot_prove_storage_model_coverage(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, "migrations/README.md", "Migration process documentation only.\n")
    _commit(repo, "migration documentation")
    snapshot = _scan(repo)
    assert any(
        item.code == "AUDIT.REQUIRED_SUBCATEGORY_UNSUPPORTED"
        and "storage models" in item.explanation
        and item.blocking
        for item in snapshot.findings
    )


def test_blocked_subcategory_status_survives_a_concurrent_partial_scan(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, "data-model.yaml", "entities: []\n")
    _write(repo, "extra.txt", "bounded\n")
    _commit(repo, "blocked and partial evidence")
    snapshot = _scan(repo, max_files=2)
    assert snapshot.disposition == "BLOCKED"
    assert snapshot.inventory["apis_data"].status == "BLOCKED"
    assert "apis_data" in snapshot.unsupported_categories
    assert any(item.code == "BUDGET.FILE_COUNT" for item in snapshot.findings)


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


def test_non_github_ci_is_visible_but_remains_structurally_unproven(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, ".gitlab-ci.yml", "test:\n  script: pytest\n")
    _commit(repo, "gitlab ci")
    snapshot = _scan(repo)
    delivery = snapshot.inventory["delivery_environments"].items
    assert any(item.kind == "CI_CONFIGURATION_SIGNAL" for item in delivery)
    assert not any(item.kind == "CI_WORKFLOW" for item in delivery)
    assert any(item.code == "WORKFLOW.STRUCTURE_UNPROVEN" for item in snapshot.findings)
    assert any(item.code == "DELIVERY.CI_ABSENT" for item in snapshot.findings)


@pytest.mark.parametrize(
    ("path", "content"),
    [
        (".gitlab-ci.yml", "variables:\n  FOO: bar\n"),
        (".gitlab-ci.yml", "empty:\n  script: []\n"),
        (".gitlab-ci.yml", "empty:\n  trigger: {}\n"),
        (".gitlab-ci.yml", "empty:\n  trigger:\n    strategy: depend\n"),
        ("azure-pipelines.yml", "steps: []\n"),
        ("azure-pipelines.yml", "jobs:\n  - job: empty\n"),
        ("azure-pipelines.yml", "steps:\n  - checkout: none\n"),
        (
            ".github/workflows/ci.yml",
            "name: empty\non: [push]\njobs:\n  empty: {}\n",
        ),
        (
            ".github/workflows/ci.yml",
            "name: empty trigger\non: []\njobs:\n  test:\n"
            "    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n",
        ),
        (
            ".github/workflows/ci.yml",
            "name: empty trigger\non: {}\njobs:\n  test:\n"
            "    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n",
        ),
        (
            ".github/workflows/ci.yml",
            "name: missing runner\non: [push]\njobs:\n  test:\n"
            "    runs-on:\n    steps:\n      - run: pytest\n",
        ),
        (
            ".github/workflows/ci.yml",
            "name: empty runner\non: [push]\njobs:\n  test:\n"
            "    runs-on: '  '\n    steps:\n      - run: pytest\n",
        ),
        (
            ".github/workflows/ci.yml",
            "name: empty runner labels\non: [push]\njobs:\n  test:\n"
            "    runs-on: []\n    steps:\n      - run: pytest\n",
        ),
        (
            ".github/workflows/ci.yml",
            "name: unknown event\non: imaginary_event\njobs:\n  test:\n"
            "    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n",
        ),
        (
            ".github/workflows/ci.yml",
            "name: mixed event list\non: [push, imaginary_event]\njobs:\n  test:\n"
            "    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n",
        ),
        (
            ".github/workflows/ci.yml",
            "name: invalid event filter\non:\n  push:\n    branches: main\njobs:\n  test:\n"
            "    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n",
        ),
        (
            ".github/workflows/ci.yml",
            "name: invalid activity type\non:\n  pull_request:\n"
            "    types: [invented]\njobs:\n  test:\n"
            "    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n",
        ),
        (
            ".github/workflows/ci.yml",
            "name: invalid runner mapping\non: [push]\njobs:\n  test:\n"
            "    runs-on: {pool: production}\n    steps:\n      - run: pytest\n",
        ),
        (
            ".github/workflows/ci.yml",
            "name: invalid reusable workflow\non: [push]\njobs:\n  test:\n"
            "    uses: arbitrary-string\n",
        ),
        (
            ".github/workflows/ci.yml",
            "name: escaping reusable workflow\non: [push]\njobs:\n  test:\n"
            "    uses: ./.github/workflows/../secret.yml\n",
        ),
        (
            ".github/workflows/ci.yml",
            "name: conflicting reusable job\non: [push]\njobs:\n  test:\n"
            "    uses: ./.github/workflows/build.yml\n    runs-on: ubuntu-latest\n",
        ),
        (
            ".github/workflows/ci.yml",
            "name: mixed valid invalid jobs\non: [push]\njobs:\n  valid:\n"
            "    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n"
            "  invalid:\n    runs-on:\n    steps:\n      - run: pytest\n",
        ),
        (
            ".github/workflows/ci.yml",
            "name: invalid action reference\non: [push]\njobs:\n  test:\n"
            "    runs-on: ubuntu-latest\n    steps:\n      - uses: arbitrary-string\n",
        ),
        (
            ".github/workflows/ci.yml",
            "name: invalid job id\non: [push]\njobs:\n  'bad id':\n"
            "    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n",
        ),
        (
            ".github/workflows/ci.yml",
            "name: unsupported top key\non: [push]\nunsupported: true\njobs:\n  test:\n"
            "    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n",
        ),
        (
            ".github/workflows/ci.yml",
            "name: unsupported job key\non: [push]\njobs:\n  test:\n"
            "    runs-on: ubuntu-latest\n    unsupported: true\n"
            "    steps:\n      - run: pytest\n",
        ),
        (
            ".github/workflows/ci.yml",
            "name: unsupported step key\non: [push]\njobs:\n  test:\n"
            "    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n"
            "        unsupported: true\n",
        ),
        (
            ".github/workflows/ci.yml",
            "name: invalid schedule\non:\n  schedule:\n    - cron: '99 99 * * *'\n"
            "jobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n",
        ),
        (
            ".github/workflows/ci.yml",
            "name: conflicting filters\non:\n  push:\n    branches: [main]\n"
            "    branches-ignore: [legacy]\njobs:\n  test:\n"
            "    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n",
        ),
        (".circleci/config.yml", "version: 2.1\njobs: []\n"),
        (
            ".circleci/config.yml",
            "version: 2.1\njobs:\n  empty:\n    steps:\n      - '  '\n",
        ),
        (
            ".circleci/config.yml",
            "version: 2.1\njobs:\n  empty:\n    steps:\n      - run:\n          name: empty\n",
        ),
        ("bitbucket-pipelines.yml", "pipelines:\n  default:\n"),
        (
            "bitbucket-pipelines.yml",
            "pipelines:\n  default:\n    - step:\n        script:\n          - '  '\n",
        ),
        (
            "bitbucket-pipelines.yml",
            "pipelines:\n  default:\n    - step:\n        script:\n          - pipe: '  '\n",
        ),
    ],
)
def test_non_runnable_ci_scaffolds_do_not_suppress_missing_ci(
    tmp_path: Path,
    path: str,
    content: str,
) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, path, content)
    _commit(repo, "non-runnable CI scaffold")
    snapshot = _scan(repo)
    assert not any(
        item.kind == "CI_WORKFLOW" for item in snapshot.inventory["delivery_environments"].items
    )
    assert any(item.code == "DELIVERY.CI_ABSENT" for item in snapshot.findings)


@pytest.mark.parametrize(
    "content",
    [
        "on:\n  push:\n    branches: [main]\n  schedule:\n    - cron: '23 3 * * *'\n"
        "jobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n",
        "on:\n  pull_request:\n    types: [opened, synchronize, ready_for_review]\n"
        "jobs:\n  test:\n    runs-on: {group: trusted, labels: [linux, x64]}\n"
        "    steps:\n      - run: pytest\n",
        "on: workflow_dispatch\njobs:\n  remote:\n"
        "    uses: example/automation/.github/workflows/build.yml@v1\n",
    ],
)
def test_supported_github_ci_forms_are_reported(tmp_path: Path, content: str) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, ".github/workflows/ci.yml", content)
    _commit(repo, "supported github workflow")
    snapshot = _scan(repo)
    assert any(
        item.kind == "CI_WORKFLOW" for item in snapshot.inventory["delivery_environments"].items
    )
    assert not any(item.code == "DELIVERY.CI_ABSENT" for item in snapshot.findings)


@pytest.mark.parametrize(
    "content",
    [
        "on: [push]\npermissions:\n  arbitrary-scope: read\njobs:\n  test:\n"
        "    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n",
        "on: [push]\njobs:\n  test:\n    needs: missing\n"
        "    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n",
        "on: [push]\njobs:\n  first:\n    needs: second\n"
        "    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n"
        "  second:\n    needs: first\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: pytest\n",
        "on: [push]\njobs:\n  test:\n    strategy:\n      matrix:\n"
        "        include: [ubuntu-latest]\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: pytest\n",
    ],
)
def test_unproven_github_relationships_and_scopes_are_not_verified(
    tmp_path: Path,
    content: str,
) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, ".github/workflows/ci.yml", content)
    _commit(repo, "unproven github workflow")
    snapshot = _scan(repo)
    assert not any(
        item.kind == "CI_WORKFLOW" for item in snapshot.inventory["delivery_environments"].items
    )
    assert any(item.code == "WORKFLOW.STRUCTURE_UNPROVEN" for item in snapshot.findings)


@pytest.mark.parametrize(
    "content",
    [
        "yes: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n",
        "on: [push]\njobs:\n  ignored: {}\njobs:\n  test:\n"
        "    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n",
    ],
)
def test_ambiguous_or_duplicate_github_workflow_keys_are_not_verified(
    tmp_path: Path,
    content: str,
) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, ".github/workflows/ci.yml", content)
    _commit(repo, "ambiguous github workflow")
    snapshot = _scan(repo)
    assert not any(
        item.kind == "CI_WORKFLOW" for item in snapshot.inventory["delivery_environments"].items
    )
    assert any(
        item.code in {"WORKFLOW.MALFORMED", "WORKFLOW.STRUCTURE_UNPROVEN"}
        for item in snapshot.findings
    )


@pytest.mark.parametrize(
    ("path", "content"),
    [
        (
            ".github/workflows/nested/ci.yml",
            "on: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - run: pytest\n",
        ),
        (
            ".github/workflows/ci.yml",
            "on: [push]\njobs:\n  missing:\n    uses: ./.github/workflows/missing.yml\n",
        ),
        (
            ".github/workflows/ci.yml",
            "on: [push]\njobs:\n  local:\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - uses: ./missing-action\n",
        ),
        (
            ".github/workflows/ci.yml",
            "true: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - run: pytest\n",
        ),
    ],
)
def test_undiscoverable_or_unproven_local_github_targets_are_not_verified(
    tmp_path: Path,
    path: str,
    content: str,
) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, path, content)
    _commit(repo, "undiscoverable github workflow")
    snapshot = _scan(repo)
    assert not any(
        item.kind == "CI_WORKFLOW" for item in snapshot.inventory["delivery_environments"].items
    )
    assert any(item.code == "WORKFLOW.STRUCTURE_UNPROVEN" for item in snapshot.findings)


@pytest.mark.parametrize(
    "uses",
    [
        "../..@v1",
        "../../.github/workflows/x.yml@v1",
        "owner/repository/.github/workflows/nested/x.yml@v1",
        "owner/repository/action@../v1",
        "owner/repository/action@refs/heads/.hidden",
        "owner/repository/action@refs/heads/foo./bar",
        "owner/repository/action@refs/heads/topic.lock/child",
        "bad_owner/repository/action@v1",
        "bad.owner/repository/action@v1",
        "bad--owner/repository/action@v1",
        f"{'a' * 40}/repository/action@v1",
    ],
)
def test_malformed_remote_github_references_are_not_verified(
    tmp_path: Path,
    uses: str,
) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    is_workflow = ".github/workflows" in uses
    job = (
        f"  invalid:\n    uses: {uses}\n"
        if is_workflow
        else f"  invalid:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: {uses}\n"
    )
    _write(repo, ".github/workflows/ci.yml", f"on: [push]\njobs:\n{job}")
    _commit(repo, "invalid remote github reference")
    snapshot = _scan(repo)
    assert not any(
        item.kind == "CI_WORKFLOW" for item in snapshot.inventory["delivery_environments"].items
    )
    assert any(item.code == "WORKFLOW.STRUCTURE_UNPROVEN" for item in snapshot.findings)


def test_late_governance_cancellation_changes_the_input_binding() -> None:
    governance = importlib.import_module("pmpe.repository.governance")
    inputs = {
        "evaluation_disposition": "COMPLETE",
        "evaluation_unknowns": [],
        "safe": True,
    }
    initial = importlib.import_module("pmpe.contracts.canonical").canonical_digest(inputs)
    rebound = governance._late_cancellation_input_digest(inputs)
    assert rebound != initial
    assert rebound == governance._late_cancellation_input_digest(inputs)


def test_supported_github_needs_graph_and_matrix_objects_are_verified(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(
        repo,
        ".github/workflows/ci.yml",
        "on: [push]\npermissions:\n  contents: read\njobs:\n  build:\n"
        "    strategy:\n      matrix:\n        python: ['3.12']\n"
        "        include:\n          - python: '3.13'\n            experimental: true\n"
        "    runs-on: ubuntu-latest\n    steps:\n      - run: pytest\n"
        "  report:\n    needs: build\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - run: echo done\n",
    )
    _commit(repo, "supported github dependency graph")
    snapshot = _scan(repo)
    assert any(
        item.kind == "CI_WORKFLOW" for item in snapshot.inventory["delivery_environments"].items
    )


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


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "openapi-v1.json",
            '{"openapi":"3.1.0","info":{"title":"x","version":"1"},"paths":{}}',
        ),
        (
            "openapi_3_1.yaml",
            'openapi: 3.1.0\ninfo: {title: x, version: "1"}\npaths: {}\n',
        ),
        (
            "swagger.json",
            '{"swagger":"2.0","info":{"title":"x","version":"1"},"paths":{}}',
        ),
    ],
)
def test_common_api_declaration_names_are_validated_and_inventoried(
    tmp_path: Path,
    path: str,
    payload: str,
) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, path, payload)
    _commit(repo, "common API declaration")
    snapshot = _scan(repo)
    assert any(
        item.kind == "OPENAPI" and item.path == path
        for item in snapshot.inventory["apis_data"].items
    )
    assert not any(
        item.code == "INTERFACE.DECLARATION_INVALID" and path in item.evidence_refs
        for item in snapshot.findings
    )


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


def test_python_manifests_and_lockfiles_are_explicit_inventory(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, "services/api/requirements.txt", "rfc8785==0.1.4\n")
    _write(repo, "services/api/requirements.lock", "rfc8785==0.1.4\n")
    _write(repo, "services/worker/Pipfile", "[packages]\nrfc8785='==0.1.4'\n")
    _write(repo, "services/worker/Pipfile.lock", "{}\n")
    _write(repo, "services/worker/poetry.lock", "# generated lock\n")
    _write(repo, "services/worker/uv.lock", "version = 1\n")
    _write(repo, "services/legacy/setup.cfg", "[metadata]\nname = legacy\n")
    _commit(repo, "python dependency inputs")
    snapshot = _scan(repo)
    items = snapshot.inventory["languages_build_ecosystems"].items
    manifest_paths = {item.path for item in items if item.kind == "PYTHON_MANIFEST"}
    lock_paths = {item.path for item in items if item.kind == "PYTHON_LOCKFILE"}
    assert {
        "services/api/requirements.txt",
        "services/worker/Pipfile",
        "services/legacy/setup.cfg",
    } <= manifest_paths
    assert {
        "services/api/requirements.lock",
        "services/worker/Pipfile.lock",
        "services/worker/poetry.lock",
        "services/worker/uv.lock",
    } <= lock_paths
    assert not any(
        item.code == "STACK.UNSUPPORTED_ECOSYSTEM"
        and any("Pipfile" in ref for ref in item.evidence_refs)
        for item in snapshot.findings
    )


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


def test_adapter_classified_file_types_are_not_also_reported_unsupported(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, "contracts/events.proto", 'syntax = "proto3";\n')
    _write(repo, "contracts/query.graphql", "type Query { ready: Boolean! }\n")
    _write(repo, "containers/Dockerfile.dev", "FROM scratch\n")
    _write(repo, "config/.env.production", "DEPLOYMENT=production\n")
    _commit(repo, "supported domain-specific files")
    snapshot = _scan(repo)
    unsupported_refs = {
        ref
        for finding in snapshot.findings
        if finding.code == "STACK.UNSUPPORTED_FILE_TYPE"
        for ref in finding.evidence_refs
    }
    assert unsupported_refs.isdisjoint(
        {
            "contracts/events.proto",
            "contracts/query.graphql",
            "containers/Dockerfile.dev",
            "config/.env.production",
        }
    )


def test_every_recognized_python_and_node_source_emits_language_evidence(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, "stubs/widget.pyi", "def ready() -> bool: ...\n")
    _write(repo, "scripts/start.mjs", "export const ready = true;\n")
    _write(repo, "scripts/config.cjs", "module.exports = { ready: true };\n")
    _write(repo, "tests/unit/test_only.py", "def test_ready():\n    assert True\n")
    _write(repo, "tests/web/widget.test.ts", "export const ready = true;\n")
    _commit(repo, "recognized source variants")
    snapshot = _scan(repo)
    observed = {
        (item.path, item.kind) for item in snapshot.inventory["languages_build_ecosystems"].items
    }
    assert {
        ("stubs/widget.pyi", "PYTHON_SOURCE"),
        ("scripts/start.mjs", "NODE_SOURCE"),
        ("scripts/config.cjs", "NODE_SOURCE"),
        ("tests/unit/test_only.py", "PYTHON_SOURCE"),
        ("tests/web/widget.test.ts", "NODE_SOURCE"),
    } <= observed
    assert snapshot.inventory["languages_build_ecosystems"].status == "OBSERVED"


@pytest.mark.parametrize(
    "manifest",
    ["Makefile", "WORKSPACE", "BUILD.bazel", "Jenkinsfile", "Rakefile", "Procfile"],
)
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


def test_extensionless_executable_is_blocked_without_being_run(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    marker = tmp_path / "must-not-run"
    script = repo / "bin" / "deploy"
    _write(repo, "bin/deploy", f"#!/bin/sh\ntouch {marker}\n")
    script.chmod(0o755)
    _commit(repo, "extensionless executable")
    snapshot = _scan(repo)
    assert snapshot.disposition == "BLOCKED"
    assert any(
        item.code == "STACK.UNSUPPORTED_EXTENSIONLESS_PROGRAM"
        and "bin/deploy" in item.evidence_refs
        for item in snapshot.findings
    )
    assert not marker.exists()


def test_adapter_cannot_fabricate_untracked_high_confidence_evidence() -> None:
    api = _api()
    adapters = importlib.import_module("pmpe.repository.adapters")
    models = importlib.import_module("pmpe.repository.models")
    scanner = importlib.import_module("pmpe.repository.scanner")
    adapter = next(
        item for item in api.default_adapters() if item.adapter_id == "core.repository-topology"
    )
    fabricated = adapters.AdapterResult(
        items=(
            (
                "repository_topology",
                models.EvidenceItem(
                    kind="FABRICATED",
                    path="does-not-exist.txt",
                    file_digest="sha256:" + "0" * 64,
                    detector_id=adapter.adapter_id,
                    detector_version=adapter.detector_version,
                    confidence="HIGH",
                ),
            ),
        )
    )
    assert not scanner.RepositoryScanner._adapter_result_is_valid(
        adapter,
        adapters.AdapterContext(files=()),
        fabricated,
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


def test_adapter_failure_is_visible_and_cannot_remove_categories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    scanner = importlib.import_module("pmpe.repository.scanner")
    repo = _init_repo(tmp_path)

    def failing_worker(
        connection: Any,
        _adapter: Any,
        _context: Any,
        _expected_state_digest: str,
        _expected_adapter_identity: int,
        _expected_evaluator_identity: int,
        _expected_module_state_digest: str,
        _expected_import_state_digest: str,
        _expected_import_identities: tuple[tuple[str, int], ...],
    ) -> None:
        os.setsid()
        connection.send_bytes(b'{"error_type":"RuntimeError","status":"ERROR"}')
        connection.close()
        while True:
            signal.pause()

    monkeypatch.setattr(scanner, "_adapter_worker", failing_worker)
    snapshot = api.RepositoryScanner(config=_config()).scan(repo, commit="HEAD")
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


def test_path_and_directory_budgets_filter_before_adapter_evaluation(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, "a/allowed/pyproject.toml", "[project]\nname = 'allowed'\nversion = '1'\n")
    _write(repo, "b/deep/excluded/package.json", '{"name":"excluded"}')
    _commit(repo, "budgeted paths")
    snapshot = _scan(repo, max_directories=2, max_path_depth=32)
    assert any(item.code == "BUDGET.DIRECTORY_COUNT" for item in snapshot.findings)
    emitted_paths = {
        item.path for category in snapshot.inventory.values() for item in category.items
    } | {path for item in snapshot.boundary_candidates for path in item.evidence_paths}
    assert "a/allowed/pyproject.toml" in emitted_paths
    assert "b/deep/excluded/package.json" not in emitted_paths

    depth_limited = _scan(repo, max_path_depth=2)
    assert any(
        item.code == "BUDGET.PATH_DEPTH" and "b/deep/excluded/package.json" in item.evidence_refs
        for item in depth_limited.findings
    )
    depth_paths = {
        item.path for category in depth_limited.inventory.values() for item in category.items
    } | {path for item in depth_limited.boundary_candidates for path in item.evidence_paths}
    assert "b/deep/excluded/package.json" not in depth_paths


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_files", 100_001),
        ("max_directories", 50_001),
        ("max_total_bytes", 2_000_000_001),
        ("max_file_bytes", 50_000_001),
        ("max_tree_output_bytes", 128_000_001),
        ("max_commands", 250_001),
        ("command_timeout_seconds", 121),
        ("max_path_depth", 257),
    ],
)
def test_scan_budget_hard_ceilings_cannot_be_disabled(
    tmp_path: Path,
    field: str,
    value: int,
) -> None:
    with pytest.raises(_api().RepositoryIntelligenceError, match="hard safety ceiling"):
        _scan(_init_repo(tmp_path), **{field: value})


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
    assert snapshot.disposition == "BLOCKED"
    assert any(item.code == "REPOSITORY.SUBMODULE_SCOPE_UNSCANNED" for item in snapshot.findings)


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


def test_environment_files_are_inventory_evidence_without_secret_values(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path, mixed=False)
    secret = "ghp_0123456789abcdefghijklmnop"
    _write(repo, ".env", f"TOKEN={secret}\n")
    _write(repo, "config/.env.production", "DEPLOYMENT=production\n")
    _commit(repo, "environment configuration shapes")
    snapshot = _scan(repo)
    delivery = snapshot.inventory["delivery_environments"].items
    security = snapshot.inventory["security_privacy"].items
    assert any(
        item.path == ".env" and item.kind == "ENVIRONMENT_CONFIGURATION_SHAPE" for item in delivery
    )
    assert any(
        item.path == "config/.env.production" and item.kind == "SECRET_CONFIGURATION_BOUNDARY"
        for item in security
    )
    assert secret not in snapshot.canonical_bytes().decode()


def test_redaction_failure_blocks_artifact_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    redaction = importlib.import_module("pmpe.repository.redaction")
    repo = _init_repo(tmp_path)

    def unavailable(_self: Any, _value: Any) -> Any:
        raise RuntimeError("redaction unavailable")

    monkeypatch.setattr(redaction.EvidenceRedactor, "sanitize", unavailable)
    with pytest.raises(api.RepositorySecurityError, match="redaction"):
        api.RepositoryScanner(config=_config()).scan(repo, commit="HEAD")


@pytest.mark.parametrize("field", ["token", "signature", "sig"])
def test_sensitive_mapping_fields_are_redacted_before_persistence(field: str) -> None:
    redaction = importlib.import_module("pmpe.repository.redaction")
    secret = "TOPSECRET123"
    sanitized = redaction.EvidenceRedactor().sanitize({field: secret})
    assert sanitized[field] == "[REDACTED]"
    assert secret not in json.dumps(sanitized)


@pytest.mark.parametrize(
    "secret",
    [
        "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789",
        "sk-svcacct-abcdefghijklmnopqrstuvwxyz0123456789",
        "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789",
        "sk-abcdefghijklmnopqrstuvwxyz0123456789",
        "sk-or-v1-abcdefghijklmnopqrstuvwxyz0123456789",
        "hf_abcdefghijklmnopqrstuvwxyz0123456789",
    ],
)
def test_modern_service_tokens_are_redacted_without_field_labels(secret: str) -> None:
    redaction = importlib.import_module("pmpe.repository.redaction")
    sanitized = redaction.EvidenceRedactor(environment={}).sanitize(f"provider returned {secret}")
    assert secret not in sanitized
    assert sanitized == "provider returned [REDACTED]"


@pytest.mark.parametrize(
    ("evidence", "secret"),
    [
        ("collector exposed api_key opaque-key-material", "opaque-key-material"),
        ("password hunter2", "hunter2"),
        ('credential "opaque credential material"', "opaque credential material"),
        ("note: access_token opaque-token-material", "opaque-token-material"),
        ("provider returned token opaqueCredentialMaterial123", "opaqueCredentialMaterial123"),
        ("provider returned secret opaqueSecretMaterial123", "opaqueSecretMaterial123"),
        (
            "provider returned cookie session=opaque-cookie-material",
            "session=opaque-cookie-material",
        ),
    ],
)
def test_whitespace_delimited_sensitive_assignments_are_redacted(
    evidence: str,
    secret: str,
) -> None:
    redaction = importlib.import_module("pmpe.repository.redaction")
    sanitized = redaction.EvidenceRedactor(environment={}).sanitize(evidence)
    assert secret not in sanitized
    assert "[REDACTED]" in sanitized


def test_whitespace_redaction_preserves_noncredential_audit_phrases() -> None:
    redaction = importlib.import_module("pmpe.repository.redaction")
    evidence = (
        "credential boundaries and password policy and api_key ownership and "
        "secret scanning and token policy and cookie controls"
    )
    assert redaction.EvidenceRedactor(environment={}).sanitize(evidence) == evidence


@pytest.mark.parametrize(
    ("header", "secrets"),
    [
        ("Authorization: Token opaque-secret", ("Token", "opaque-secret")),
        (
            'Authorization: Digest username="user", nonce="nonce-secret", '
            'response="response-secret"',
            ("username", "user", "nonce-secret", "response-secret"),
        ),
        (
            'Authorization: Digest username="user",\r\n nonce="folded-nonce",\r\n'
            ' response="folded-response"',
            ("username", "user", "folded-nonce", "folded-response"),
        ),
        ("Proxy-Authorization: Custom proxy-secret", ("Custom", "proxy-secret")),
    ],
)
def test_complete_authorization_header_is_redacted_for_every_scheme(
    header: str,
    secrets: tuple[str, ...],
) -> None:
    redaction = importlib.import_module("pmpe.repository.redaction")
    sanitized = redaction.EvidenceRedactor(environment={}).sanitize(f"provider returned {header}")
    assert sanitized == "provider returned Authorization: [REDACTED]"
    assert all(secret not in sanitized for secret in secrets)


@pytest.mark.parametrize(
    "header",
    [
        "Cookie: session=primary-secret; csrf=secondary-secret",
        "Set-Cookie: session=primary-secret; HttpOnly; csrf=secondary-secret",
        "Cookie: session=primary-secret;\r\n csrf=folded-secondary-secret",
    ],
)
def test_complete_cookie_header_is_redacted(header: str) -> None:
    redaction = importlib.import_module("pmpe.repository.redaction")
    sanitized = redaction.EvidenceRedactor(environment={}).sanitize(f"provider returned {header}")
    assert sanitized == "provider returned Cookie: [REDACTED]"
    assert "primary-secret" not in sanitized
    assert "secondary-secret" not in sanitized


def test_non_secret_boolean_control_with_sensitive_word_remains_typed() -> None:
    redaction = importlib.import_module("pmpe.repository.redaction")
    sanitized = redaction.EvidenceRedactor(environment={}).sanitize(
        {"required_signed_commits": True, "signature": "secret-value"}
    )
    assert sanitized == {"required_signed_commits": True, "signature": "[REDACTED]"}


@pytest.mark.parametrize(
    "url",
    [
        "https://hooks.slack.com/services/T000/B000/slack-webhook-secret",
        "https://hooks.slack.com./services/T000/B000/slack-webhook-secret",
        "https://discord.com/api/webhooks/123/discord-webhook-secret",
        "https://canary.discord.com/api/webhooks/123/discord-webhook-secret",
        "https://ptb.discord.com./api/webhooks/123/discord-webhook-secret",
        "https://api.telegram.org/bottelegram-secret/sendMessage",
    ],
)
def test_credential_bearing_url_paths_are_redacted(url: str) -> None:
    redaction = importlib.import_module("pmpe.repository.redaction")
    sanitized = redaction.EvidenceRedactor(environment={}).sanitize(url)
    assert sanitized.endswith("/[REDACTED_PATH]")
    assert "secret" not in sanitized


def test_sensitive_environment_value_is_redacted_under_benign_field() -> None:
    redaction = importlib.import_module("pmpe.repository.redaction")
    secret = "opaque-credential-value-not-matching-a-token-shape"
    sanitized = redaction.EvidenceRedactor(environment={"CLAUDESECRET": secret}).sanitize(
        {"message": f"provider returned {secret}"}
    )
    assert secret not in json.dumps(sanitized)
    assert sanitized["message"] == "provider returned [REDACTED_ENV]"


def test_home_path_minimization_is_host_state_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redaction = importlib.import_module("pmpe.repository.redaction")
    monkeypatch.setenv("HOME", "/Users/first-host")
    first = redaction.EvidenceRedactor(environment={}).sanitize(
        "/Users/repository-owner/work/repository"
    )
    monkeypatch.setenv("HOME", "/home/second-host")
    second = redaction.EvidenceRedactor(environment={}).sanitize(
        "/Users/repository-owner/work/repository"
    )
    assert first == second == "$HOME/work/repository"
    embedded = redaction.EvidenceRedactor(environment={}).sanitize(
        "command failed under /home/repository-owner/work/repository: permission denied"
    )
    assert embedded == "command failed under $HOME/work/repository: permission denied"
    for posix_home in (
        "/root/work/repository",
        "/var/root/work/repository",
        "/usr/home/repository-owner/work/repository",
    ):
        assert (
            redaction.EvidenceRedactor(environment={}).sanitize(posix_home)
            == "$HOME/work/repository"
        )


def _fixed_clock() -> Any:
    return _api().RecordedUtcClock("2026-08-01T00:00:00Z")


def _fixed_ids() -> Any:
    return _api().RecordedObservationIds("OBS-000001")


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
            "default_branch": "main",
            "observed_at": "2026-08-01T00:00:00Z",
            "coverage": ["remote_branches", "pull_requests", "issues", "governance"],
            "remote_branches": [
                {
                    "name": "origin/feature",
                    "sha": "a" * 40,
                    "comparison_ref": ref,
                    "ahead": 1,
                    "behind": 0,
                    "status": "OBSERVED",
                }
            ],
            "pull_requests": [
                {
                    "number": 7,
                    "draft": True,
                    "head": "a" * 40,
                    "updated_at": "2026-07-31T12:00:00Z",
                    "mergeability": "MERGEABLE",
                }
            ],
            "issues": [{"number": 8, "state": "OPEN"}],
            "governance": {
                "schema_version": "pmpe.repository-governance/v2",
                "branch_protection": {
                    "observed": True,
                    "protected": True,
                    "required_checks": ["ci"],
                    "required_signed_commits": True,
                    "required_linear_history": True,
                    "push_restrictions": True,
                    "allow_force_pushes": False,
                    "allow_deletions": False,
                },
                "review_policy": {
                    "required_approvals": 1,
                    "dismiss_stale_reviews": True,
                    "require_code_owner_reviews": True,
                    "require_last_push_approval": True,
                },
                "security_settings": {
                    "observed": True,
                    "leak_detection": "ENABLED",
                    "dependency_alerts": "ENABLED",
                },
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
        }


class _SecretBearingRemote(_FakeRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        payload = super().collect(repository, ref, **bounds)
        payload["governance"].update(
            {
                "database_note": (
                    "DATABASE_URL=postgres://database-user:database-password@db.invalid/app"
                    "?sslmode=require&token=query-secret"
                ),
                "azure_note": "AccountName=demo;AccountKey=azure-secret-value==;Endpoint=x",
                "odbc_note": "Driver=x;UID=demo;PWD={odbc secret value};Server=db",
                "cookie_note": "Cookie: session=cookie-secret; theme=dark",
                "folded_cookie_note": (
                    "Set-Cookie: session=cookie-secret;\r\n csrf=secondary-cookie-secret"
                ),
                "aws_note": "aws_secret_access_key=aws-secret-value",
                "safe_url": "https://user:password@example.invalid/repo?token=secret-value",
                "signed_url": "https://storage.example.invalid/blob?sv=1&sig=signed-secret",
                "authorization": "Basic dXNlcjpwYXNzd29yZA==",
                "x-api-key": "unstructured-bare-secret",
                "note": "Authorization: Basic dXNlcjpwYXNzd29yZA==",
                "custom_auth_note": "Authorization: Token opaque-authorization-secret",
                "digest_auth_note": (
                    'Authorization: Digest username="user", nonce="nonce-secret", '
                    'response="response-secret"'
                ),
                "comment": "glpat-0123456789abcdefghijkl",
                "modern_key_note": (
                    "collector exposed api_key sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"
                ),
                "generic_token_note": ("provider returned token opaqueCredentialMaterial123"),
                "hugging_face_note": "provider returned hf_abcdefghijklmnopqrstuvwxyz0123456789",
            }
        )
        payload["unknowns"].append(
            {
                "fact": "credential_diagnostic",
                "status": "BLOCKED",
                "reason": "provider returned password hunter2",
            }
        )
        return payload


class _InvalidIssueStateRemote(_FakeRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        payload = super().collect(repository, ref, **bounds)
        payload["issues"][0]["state"] = "BANANA"
        return payload


class _ExtraCoverageRemote(_FakeRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        payload = super().collect(repository, ref, **bounds)
        payload["coverage"].append("deployments")
        return payload


class _MissingSecuritySettingsRemote(_FakeRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        payload = super().collect(repository, ref, **bounds)
        del payload["governance"]["security_settings"]
        return payload


class _UnobservedBranchProtectionRemote(_FakeRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        payload = super().collect(repository, ref, **bounds)
        payload["governance"]["branch_protection"] = {
            "observed": False,
            "protected": False,
            "required_checks": [],
            "required_signed_commits": False,
            "required_linear_history": False,
            "push_restrictions": False,
            "allow_force_pushes": False,
            "allow_deletions": False,
        }
        payload["unknowns"] = []
        return payload


class _MaterialGovernanceVariantRemote(_FakeRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        payload = super().collect(repository, ref, **bounds)
        payload["governance"]["branch_protection"]["required_signed_commits"] = False
        payload["governance"]["branch_protection"]["allow_force_pushes"] = True
        payload["governance"]["review_policy"]["dismiss_stale_reviews"] = False
        return payload


class _DeniedRemote:
    tool_identity = "fake-github-readonly/1.0"
    api_version = "github-rest/2026-03-10"

    def collect(self, _repository: str, _ref: str, **_bounds: Any) -> dict[str, Any]:
        raise PermissionError("token ghp_0123456789abcdefghijklmnop denied")


class _PartialRemote(_FakeRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        payload = super().collect(repository, ref, **bounds)
        payload["query_provenance"][0]["has_next_page"] = True
        return payload


class _StaleRemote(_FakeRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        payload = super().collect(repository, ref, **bounds)
        payload["observed_at"] = "2026-07-31T00:00:00Z"
        payload["pull_requests"][0]["updated_at"] = "2026-07-30T12:00:00Z"
        return payload


class _CompleteRemote(_FakeRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        payload = super().collect(repository, ref, **bounds)
        payload["unknowns"] = []
        return payload


class _StaleConflictingPullRequestRemote(_CompleteRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        payload = super().collect(repository, ref, **bounds)
        payload["pull_requests"][0]["updated_at"] = "2026-06-01T00:00:00Z"
        payload["pull_requests"][0]["mergeability"] = "CONFLICTING"
        return payload


class _UnknownMergeabilityRemote(_CompleteRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        payload = super().collect(repository, ref, **bounds)
        payload["pull_requests"][0]["mergeability"] = "UNKNOWN"
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
            "schema_version": "pmpe.repository-governance/v1",
            "branch_protection": "UNKNOWN",
            "review_policy": {"required_approvals": 1},
        }
        payload["unknowns"] = []
        return payload


class _ScalarGovernanceRemote(_FakeRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        payload = super().collect(repository, ref, **bounds)
        payload["governance"] = {
            "schema_version": "pmpe.repository-governance/v1",
            "branch_protection": True,
            "review_policy": 1,
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


class _CollidingCursorRemote(_FakeRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        payload = super().collect(repository, ref, **bounds)
        payload["query_provenance"][0]["cursor"] = "token=firstsecretvalue123"
        payload["query_provenance"][1]["cursor"] = "token=secondsecretvalue456"
        return payload


class _CoerciblePrimitiveRemote(_FakeRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        payload = super().collect(repository, ref, **bounds)
        payload["pull_requests"][0]["draft"] = "false"
        payload["issues"][0]["number"] = True
        payload["query_provenance"][0]["has_next_page"] = "false"
        return payload


class _AgeSensitiveRemote(_FakeRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        payload = super().collect(repository, ref, **bounds)
        payload["observed_at"] = "2026-07-31T23:58:00Z"
        payload["unknowns"] = []
        return payload


class _HugeNumericRemote(_FakeRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        del repository, ref, bounds
        return {"numeric_payload": 10**3000}


class _ExtraFieldRemote(_FakeRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        payload = super().collect(repository, ref, **bounds)
        payload["unexpected"] = "unreviewed provider surface"
        return payload


class _ExtraNestedFieldRemote(_FakeRemote):
    def collect(self, repository: str, ref: str, **bounds: Any) -> dict[str, Any]:
        payload = super().collect(repository, ref, **bounds)
        payload["query_provenance"][0]["truncated"] = True
        return payload


def _sealed_remote(remote: Any) -> Any:
    api = _api()
    bounds = {
        "timeout_seconds": 30,
        "max_output_bytes": 8_000_000,
        "max_items": 20_000,
        "cancellation": None,
    }
    delay_seconds = 30.0 if isinstance(remote, _HangingRemote) else 0.0
    permission_denied = isinstance(remote, _DeniedRemote)
    payload = (
        _FakeRemote().collect("example/fixture", "main", **bounds)
        if delay_seconds or permission_denied
        else remote.collect("example/fixture", "main", **bounds)
    )
    return api.RecordedRemoteProvider(
        payload,
        api_version=remote.api_version,
        delay_seconds=delay_seconds,
        permission_denied=permission_denied,
    )


def _observe(repo: Path, remote: Any = None) -> Any:
    api = _api()
    return api.GovernanceCollector(
        repository="example/fixture",
        clock=_fixed_clock(),
        id_provider=_fixed_ids(),
        remote_provider=_sealed_remote(remote) if remote is not None else None,
    ).observe(repo, ref="main")


def test_dormant_cancellation_signal_does_not_change_governance_observation(
    tmp_path: Path,
) -> None:
    api = _api()
    repo = _init_repo(tmp_path)
    baseline = api.GovernanceCollector(
        repository="example/fixture",
        clock=_fixed_clock(),
        id_provider=_fixed_ids(),
    ).observe(repo, ref="main")
    cancellable = api.GovernanceCollector(
        repository="example/fixture",
        clock=_fixed_clock(),
        id_provider=_fixed_ids(),
        cancellation=api.CancellationSignal(),
    ).observe(repo, ref="main")
    assert cancellable.canonical_bytes() == baseline.canonical_bytes()
    assert cancellable.collector_implementation_digest == baseline.collector_implementation_digest


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
    assert observation.disposition == "BLOCKED"
    assert {item.fact for item in observation.unknowns} >= {
        "dirty_index",
        "dirty_worktree",
        "untracked_files",
    }
    assert any(item.fact == "remote_governance" for item in observation.unknowns)


def test_concurrent_local_mutation_blocks_mixed_time_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _api()
    governance = importlib.import_module("pmpe.repository.governance")
    repo = _init_repo(tmp_path)
    original = governance.GovernanceCommandRunner.run
    status_calls = 0

    def changing_status(
        self: Any,
        args: tuple[str, ...],
        cwd: Path,
        timeout: int,
        *,
        cancellation: Any = None,
    ) -> Any:
        nonlocal status_calls
        if args[1] == "status":
            status_calls += 1
            if status_calls == 2:
                return api.CommandResult(
                    args=args,
                    returncode=0,
                    stdout=b"?? concurrently-created.txt\0",
                    stderr=b"",
                )
        return original(self, args, cwd, timeout, cancellation=cancellation)

    monkeypatch.setattr(governance.GovernanceCommandRunner, "run", changing_status)
    observation = _observe(repo)
    assert observation.disposition == "BLOCKED"
    assert any(item.fact == "concurrent_local_mutation" for item in observation.unknowns)
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == ""


@pytest.mark.parametrize(
    "status_output",
    [
        "XX malformed\0",
        "??\0",
        "?? \0",
        "M malformed\0",
        "?? untracked-without-terminator",
    ],
)
def test_malformed_porcelain_status_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status_output: str,
) -> None:
    api = _api()
    governance = importlib.import_module("pmpe.repository.governance")
    repo = _init_repo(tmp_path)
    original = governance.GovernanceCommandRunner.run

    def malformed_status(
        self: Any,
        args: tuple[str, ...],
        cwd: Path,
        timeout: int,
        *,
        cancellation: Any = None,
    ) -> Any:
        if args[1] == "status":
            return api.CommandResult(
                args=args,
                returncode=0,
                stdout=status_output,
                stderr="",
            )
        return original(self, args, cwd, timeout, cancellation=cancellation)

    monkeypatch.setattr(governance.GovernanceCommandRunner, "run", malformed_status)
    with pytest.raises(api.RepositoryIntelligenceError, match="status output is malformed"):
        _observe(repo)


def test_nul_porcelain_status_preserves_rename_and_untracked_state() -> None:
    governance = importlib.import_module("pmpe.repository.governance")
    assert governance._parse_porcelain_status("R  new-name\0old-name\0?? untracked\0") == (
        True,
        False,
        True,
    )


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
    assert observation.current_branch == "main"
    assert observation.configured_remotes == ()
    assert observation.worktrees
    assert "local_branches" not in _scan(repo).as_dict()


def test_malformed_worktree_record_is_blocked_without_placeholder_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    governance = importlib.import_module("pmpe.repository.governance")
    repo = _init_repo(tmp_path)
    original = governance.GovernanceCommandRunner.run

    def malformed_worktree(
        self: Any,
        args: tuple[str, ...],
        cwd: Path,
        timeout: int,
        *,
        cancellation: Any = None,
    ) -> Any:
        if args[1:3] == ("worktree", "list"):
            return api.CommandResult(
                args=args,
                returncode=0,
                stdout=(
                    f"worktree {repo}\0mystery value\0HEAD {'a' * 40}\0branch refs/heads/main\0\0"
                ),
                stderr="",
            )
        return original(self, args, cwd, timeout, cancellation=cancellation)

    monkeypatch.setattr(governance.GovernanceCommandRunner, "run", malformed_worktree)
    observation = _observe(repo)
    assert observation.disposition == "BLOCKED"
    assert observation.worktrees == ()
    assert any(item.fact == "worktree_record:1" for item in observation.unknowns)
    assert "UNKNOWN" not in observation.canonical_bytes().decode()


def test_worktree_lifecycle_flags_are_preserved_and_prunable_state_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    governance = importlib.import_module("pmpe.repository.governance")
    repo = _init_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    original = governance.GovernanceCommandRunner.run

    def lifecycle_worktree(
        self: Any,
        args: tuple[str, ...],
        cwd: Path,
        timeout: int,
        *,
        cancellation: Any = None,
    ) -> Any:
        if args[1:3] == ("worktree", "list"):
            return api.CommandResult(
                args=args,
                returncode=0,
                stdout=(
                    f"worktree {repo}\0HEAD {head}\0detached\0locked maintenance\0"
                    "prunable gitdir-missing\0\0"
                    f"worktree {repo.parent / 'bare.git'}\0bare\0\0"
                ),
                stderr="",
            )
        return original(self, args, cwd, timeout, cancellation=cancellation)

    monkeypatch.setattr(governance.GovernanceCommandRunner, "run", lifecycle_worktree)
    observation = _observe(repo)
    worktree = next(item for item in observation.worktrees if item.path == str(repo))
    assert worktree.detached is True
    assert worktree.bare is False
    assert worktree.locked is True
    assert worktree.locked_reason == "maintenance"
    assert worktree.prunable is True
    assert worktree.prunable_reason == "gitdir-missing"
    bare = next(item for item in observation.worktrees if item.path.endswith("bare.git"))
    assert bare.bare is True
    assert bare.detached is False
    assert bare.branch == "BARE"
    assert bare.head_sha == ""
    assert observation.disposition == "BLOCKED"
    assert any(item.fact == "worktree_prunable:1" for item in observation.unknowns)


def test_bare_worktree_with_fabricated_head_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    governance = importlib.import_module("pmpe.repository.governance")
    repo = _init_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    original = governance.GovernanceCommandRunner.run

    def invalid_bare_worktree(
        self: Any,
        args: tuple[str, ...],
        cwd: Path,
        timeout: int,
        *,
        cancellation: Any = None,
    ) -> Any:
        if args[1:3] == ("worktree", "list"):
            return api.CommandResult(
                args=args,
                returncode=0,
                stdout=f"worktree {repo.parent / 'bare.git'}\0HEAD {head}\0bare\0\0",
                stderr="",
            )
        return original(self, args, cwd, timeout, cancellation=cancellation)

    monkeypatch.setattr(governance.GovernanceCommandRunner, "run", invalid_bare_worktree)
    observation = _observe(repo)
    assert observation.disposition == "BLOCKED"
    assert observation.worktrees == ()
    assert any(item.fact == "worktree_record:1" for item in observation.unknowns)


@pytest.mark.parametrize(
    "lifecycle_fields",
    [
        "detached unexpected",
        "branch refs/heads/main\0detached",
        "branch refs/heads/main\0bare",
    ],
)
def test_malformed_or_contradictory_worktree_lifecycle_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lifecycle_fields: str,
) -> None:
    api = _api()
    governance = importlib.import_module("pmpe.repository.governance")
    repo = _init_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    original = governance.GovernanceCommandRunner.run

    def malformed_lifecycle(
        self: Any,
        args: tuple[str, ...],
        cwd: Path,
        timeout: int,
        *,
        cancellation: Any = None,
    ) -> Any:
        if args[1:3] == ("worktree", "list"):
            return api.CommandResult(
                args=args,
                returncode=0,
                stdout=f"worktree {repo}\0HEAD {head}\0{lifecycle_fields}\0\0",
                stderr="",
            )
        return original(self, args, cwd, timeout, cancellation=cancellation)

    monkeypatch.setattr(governance.GovernanceCommandRunner, "run", malformed_lifecycle)
    observation = _observe(repo)
    assert observation.disposition == "BLOCKED"
    assert observation.worktrees == ()
    assert any(item.fact == "worktree_record:1" for item in observation.unknowns)


@pytest.mark.parametrize(
    ("path_kind", "branch_ref"),
    [
        ("relative", "refs/heads/main"),
        ("absolute", "refs/tags/v1"),
        ("absolute", "main"),
        ("absolute", "refs/heads/.hidden"),
        ("absolute", "refs/heads/topic.lock/child"),
    ],
)
def test_malformed_worktree_path_or_branch_ref_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path_kind: str,
    branch_ref: str,
) -> None:
    api = _api()
    governance = importlib.import_module("pmpe.repository.governance")
    repo = _init_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    worktree_path = "relative/worktree" if path_kind == "relative" else str(repo)
    original = governance.GovernanceCommandRunner.run

    def malformed_worktree_identity(
        self: Any,
        args: tuple[str, ...],
        cwd: Path,
        timeout: int,
        *,
        cancellation: Any = None,
    ) -> Any:
        if args[1:3] == ("worktree", "list"):
            return api.CommandResult(
                args=args,
                returncode=0,
                stdout=(f"worktree {worktree_path}\0HEAD {head}\0branch {branch_ref}\0\0"),
                stderr="",
            )
        return original(self, args, cwd, timeout, cancellation=cancellation)

    monkeypatch.setattr(
        governance.GovernanceCommandRunner,
        "run",
        malformed_worktree_identity,
    )
    observation = _observe(repo)
    assert observation.disposition == "BLOCKED"
    assert observation.worktrees == ()
    assert any(item.fact == "worktree_record:1" for item in observation.unknowns)


def test_remote_metadata_records_tool_query_cursor_and_redacts_secrets(tmp_path: Path) -> None:
    observation = _observe(_init_repo(tmp_path), _SecretBearingRemote())
    payload = observation.canonical_bytes().decode()
    assert observation.disposition == "BLOCKED"
    assert any(item.fact == "remote_governance_completeness" for item in observation.unknowns)
    assert observation.tool_identity == "recorded-remote-payload/2.0.0"
    assert observation.api_query_version == "github-rest/2026-03-10"
    assert observation.query_provenance[0].surface == "remote_branches"
    assert observation.query_provenance[0].cursor == "branches-page-1"
    assert observation.observation_input_digest.startswith("sha256:")
    assert observation.observation_output_digest.startswith("sha256:")
    assert observation.remote_default_branch == "main"
    assert observation.remote_branches[0].comparison_ref == "main"
    assert observation.remote_branches[0].ahead == 1
    assert observation.remote_branches[0].status == "OBSERVED"
    assert observation.remote_collection_provenance["source_kind"] == "RECORDED_UNATTESTED"
    assert observation.remote_collection_provenance["attestation"] == "ABSENT"
    assert any(item.fact == "remote_collection_attestation" for item in observation.unknowns)
    assert "ghp_0123456789abcdefghijklmnop" not in payload
    assert "dXNlcjpwYXNzd29yZA==" not in payload
    assert "opaque-authorization-secret" not in payload
    assert "nonce-secret" not in payload
    assert "response-secret" not in payload
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
    assert "secondary-cookie-secret" not in payload
    assert "aws-secret-value" not in payload
    assert "query-json-secret" not in payload
    assert "pass-json-secret" not in payload
    assert "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789" not in payload
    assert "opaqueCredentialMaterial123" not in payload
    assert "hf_abcdefghijklmnopqrstuvwxyz0123456789" not in payload
    assert "hunter2" not in payload
    assert "[REDACTED_URL]" in payload
    assert "[REDACTED]" in payload


def test_material_governance_controls_are_typed_and_digest_bound(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    protected = _observe(repo, _CompleteRemote())
    variant = _observe(repo, _MaterialGovernanceVariantRemote())
    assert protected.governance["branch_protection"]["required_signed_commits"] is True
    assert protected.governance["review_policy"]["dismiss_stale_reviews"] is True
    assert variant.governance["branch_protection"]["allow_force_pushes"] is True
    assert protected.observation_output_digest != variant.observation_output_digest


@pytest.mark.parametrize(
    "remote",
    [
        _InvalidIssueStateRemote(),
        _ExtraCoverageRemote(),
        _MissingSecuritySettingsRemote(),
        _UnobservedBranchProtectionRemote(),
    ],
)
def test_untyped_or_overbroad_remote_metadata_cannot_be_complete(
    tmp_path: Path,
    remote: Any,
) -> None:
    observation = _observe(_init_repo(tmp_path), remote)
    assert observation.disposition == "BLOCKED"
    assert any(
        item.fact
        in {
            "remote_governance_completeness",
            "remote_metadata_shape",
            "remote_metadata_completeness",
        }
        for item in observation.unknowns
    )


def test_arbitrary_remote_provider_is_rejected_before_it_can_mutate_repository(
    tmp_path: Path,
) -> None:
    api = _api()
    repo = _init_repo(tmp_path)
    marker = repo / "remote-provider-mutation.txt"

    class MutatingRemote:
        tool_identity = "untrusted"
        api_version = "untrusted"

        def collect(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            marker.write_text("mutated")
            return {}

    with pytest.raises(api.RepositorySecurityError, match="sealed data-only provider"):
        api.GovernanceCollector(
            repository="example/fixture",
            clock=_fixed_clock(),
            id_provider=_fixed_ids(),
            remote_provider=MutatingRemote(),
        )
    assert not marker.exists()


def test_exact_collectors_reject_stateful_redactor_injection(tmp_path: Path) -> None:
    api = _api()
    redaction = importlib.import_module("pmpe.repository.redaction")
    redactor = redaction.EvidenceRedactor(environment={"PRIVATE_VALUE": "host-secret"})
    with pytest.raises(api.RepositorySecurityError, match="state-free"):
        api.RepositoryScanner(config=_config(), redactor=redactor)
    with pytest.raises(api.RepositorySecurityError, match="state-free"):
        api.GovernanceCollector(
            repository="example/fixture",
            clock=_fixed_clock(),
            id_provider=_fixed_ids(),
            redactor=redactor,
        )


def test_recorded_remote_provider_cannot_be_replaced_with_instance_code() -> None:
    provider = _sealed_remote(_FakeRemote())
    with pytest.raises(AttributeError):
        provider.collect = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]


@pytest.mark.parametrize(
    ("max_output_bytes", "max_items", "message"),
    [(8, 1_000, "byte budget"), (8_000_000, 3, "item budget")],
)
def test_recorded_remote_provider_enforces_bounds_before_deserialization(
    monkeypatch: pytest.MonkeyPatch,
    max_output_bytes: int,
    max_items: int,
    message: str,
) -> None:
    api = _api()
    governance = importlib.import_module("pmpe.repository.governance")
    provider = api.RecordedRemoteProvider(
        {"collection": [1, 2, 3]},
        api_version="fixture/1",
    )
    deserialized = False

    def forbidden_loads(_payload: Any) -> Any:
        nonlocal deserialized
        deserialized = True
        raise AssertionError("deserialization must not occur before preflight bounds")

    monkeypatch.setattr(governance.json, "loads", forbidden_loads)
    with pytest.raises(api.RepositoryIntelligenceError, match=message):
        provider.collect(
            "example/fixture",
            "main",
            timeout_seconds=1,
            max_output_bytes=max_output_bytes,
            max_items=max_items,
            cancellation=None,
        )
    assert deserialized is False


def test_recorded_remote_provider_checks_cancellation_before_deserialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _api()
    governance = importlib.import_module("pmpe.repository.governance")
    provider = api.RecordedRemoteProvider({"safe": True}, api_version="fixture/1")
    cancellation = api.CancellationSignal()
    cancellation.cancel()

    def forbidden_loads(_payload: Any) -> Any:
        raise AssertionError("cancelled replay must not deserialize")

    monkeypatch.setattr(governance.json, "loads", forbidden_loads)
    with pytest.raises(api.RepositoryIntelligenceError, match="cancelled"):
        provider.collect(
            "example/fixture",
            "main",
            timeout_seconds=1,
            max_output_bytes=1_000,
            max_items=100,
            cancellation=cancellation,
        )


def test_recorded_remote_provider_is_immutable_and_self_verifying() -> None:
    api = _api()
    provider = api.RecordedRemoteProvider({"safe": True}, api_version="fixture/1")
    original_provenance = provider.collection_provenance

    for attribute, value in (
        ("_payload", b'{"changed":true}'),
        ("_collection_provenance", {}),
        ("api_version", "fixture/2"),
    ):
        with pytest.raises(AttributeError, match="immutable"):
            setattr(provider, attribute, value)

    assert provider.collection_provenance == original_provenance

    object.__setattr__(provider, "_payload", b'{"changed":true}')
    with pytest.raises(api.RepositorySecurityError, match="provenance integrity"):
        _ = provider.collection_provenance


def test_unsealed_parent_collaborators_are_rejected_before_execution(tmp_path: Path) -> None:
    api = _api()
    repo = _init_repo(tmp_path)
    marker = repo / "collaborator-mutation.txt"

    class MutatingCollaborator:
        identity = "untrusted"
        version = "untrusted"

        def _mutate(self) -> None:
            marker.write_text("mutated")

        def run(self, *_args: Any, **_kwargs: Any) -> Any:
            self._mutate()
            return None

        def sanitize(self, value: Any) -> Any:
            self._mutate()
            return value

        def cancelled(self) -> bool:
            self._mutate()
            return False

        def now(self) -> str:
            self._mutate()
            return "2026-08-01T00:00:00Z"

        def new_id(self) -> str:
            self._mutate()
            return "OBS-UNTRUSTED"

    untrusted = MutatingCollaborator()
    for argument in (
        {"command_runner": untrusted},
        {"redactor": untrusted},
        {"cancellation": untrusted},
    ):
        with pytest.raises(api.RepositorySecurityError, match="sealed"):
            api.RepositoryScanner(config=_config(), **argument)
    governance_arguments = (
        {"clock": untrusted, "id_provider": _fixed_ids()},
        {"clock": _fixed_clock(), "id_provider": untrusted},
        {
            "clock": _fixed_clock(),
            "id_provider": _fixed_ids(),
            "command_runner": untrusted,
        },
        {"clock": _fixed_clock(), "id_provider": _fixed_ids(), "redactor": untrusted},
        {
            "clock": _fixed_clock(),
            "id_provider": _fixed_ids(),
            "cancellation": untrusted,
        },
    )
    for arguments in governance_arguments:
        with pytest.raises(api.RepositorySecurityError, match="sealed"):
            api.GovernanceCollector(repository="example/fixture", **arguments)
    assert not marker.exists()


def test_scanner_rejects_post_construction_adapter_substitution_before_mutation(
    tmp_path: Path,
) -> None:
    api = _api()
    adapters = importlib.import_module("pmpe.repository.adapters")
    repo = _init_repo(tmp_path)
    marker = repo / "adapter-substitution.txt"
    before_head = _git(repo, "rev-parse", "HEAD")
    before_status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    candidate = api.RepositoryScanner(config=_config())

    def mutating_evaluator(_context: Any) -> Any:
        marker.write_text("mutated")
        return adapters.AdapterResult()

    replacement = replace(candidate.adapters[0], evaluator=mutating_evaluator)
    substituted = (replacement, *candidate.adapters[1:])
    with pytest.raises(AttributeError):
        candidate.adapters = substituted
    object.__setattr__(candidate, "_adapters", substituted)

    with pytest.raises(api.RepositorySecurityError, match="provenance binding"):
        candidate.scan(repo, commit="HEAD")
    assert not marker.exists()
    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == before_status


def test_scanner_rejects_in_place_adapter_mutation_before_evaluator_runs(
    tmp_path: Path,
) -> None:
    api = _api()
    adapters = importlib.import_module("pmpe.repository.adapters")
    repo = _init_repo(tmp_path)
    marker = repo / "adapter-in-place-mutation.txt"
    candidate = api.RepositoryScanner(config=_config())
    adapter = candidate.adapters[0]
    original_evaluator = adapter.evaluator

    def mutating_evaluator(_context: Any) -> Any:
        marker.write_text("mutated")
        return adapters.AdapterResult()

    try:
        object.__setattr__(adapter, "evaluator", mutating_evaluator)
        with pytest.raises(api.RepositorySecurityError, match="sealed|provenance"):
            candidate.scan(repo, commit="HEAD")
    finally:
        object.__setattr__(adapter, "evaluator", original_evaluator)
    assert not marker.exists()


def test_scanner_rejects_adapter_import_proxy_before_callback_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    adapters = importlib.import_module("pmpe.repository.adapters")
    repo = _init_repo(tmp_path)
    marker = repo / "adapter-import-proxy-ran.txt"
    candidate = api.RepositoryScanner(config=_config())

    class YamlProxy:
        def safe_load(self, _value: Any) -> Any:
            marker.write_text("mutated")
            return {}

    monkeypatch.setattr(adapters, "yaml", YamlProxy())
    with pytest.raises(api.RepositorySecurityError, match="adapter|registry"):
        candidate.scan(repo, commit="HEAD")
    assert not marker.exists()


def test_scanner_rejects_mutated_cancellation_state_before_callback_use(
    tmp_path: Path,
) -> None:
    api = _api()
    repo = _init_repo(tmp_path)
    marker = repo / "cancellation-callback-ran.txt"
    cancellation = api.CancellationSignal()

    class MutatingState:
        def __bool__(self) -> bool:
            marker.write_text("mutated")
            return False

    with pytest.raises(AttributeError):
        object.__setattr__(cancellation, "_event", MutatingState())
    object.__setattr__(cancellation, "_state", MutatingState())
    with pytest.raises(api.RepositorySecurityError, match="sealed"):
        api.RepositoryScanner(config=_config(), cancellation=cancellation).scan(repo, commit="HEAD")

    class MutatingLock:
        def __enter__(self) -> Any:
            marker.write_text("mutated")
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

    cancellation = api.CancellationSignal()
    object.__setattr__(cancellation, "_lock", MutatingLock())
    with pytest.raises(api.RepositorySecurityError, match="sealed"):
        api.RepositoryScanner(config=_config(), cancellation=cancellation).scan(repo, commit="HEAD")
    assert not marker.exists()


def test_redaction_collision_between_tracked_paths_blocks_snapshot(
    tmp_path: Path,
) -> None:
    api = _api()
    repo = _init_repo(tmp_path, mixed=False)
    _write(repo, "docs/token=firstsecretvalue/report.md", "first\n")
    _write(repo, "docs/token=secondsecretvalue/report.md", "second\n")
    _commit(repo, "credential-shaped path identities")
    before_head = _git(repo, "rev-parse", "HEAD")
    before_status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")

    with pytest.raises(api.RepositorySecurityError, match="redaction"):
        _scan(repo)
    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == before_status


def test_redaction_collision_between_evidence_locations_fails_closed() -> None:
    scanner = importlib.import_module("pmpe.repository.scanner")
    original = {
        "included_paths": [],
        "inventory": {
            "dependencies_integrations": {
                "items": [
                    {
                        "path": "a/package.json",
                        "location": "package.json#scripts.token=firstsecretvalue123",
                    },
                    {
                        "path": "b/package.json",
                        "location": "package.json#scripts.token=secondsecretvalue456",
                    },
                ]
            }
        },
        "findings": [],
        "boundary_candidates": [],
    }
    sanitized = json.loads(json.dumps(original))
    for item in sanitized["inventory"]["dependencies_integrations"]["items"]:
        item["location"] = "package.json#scripts.[REDACTED]"

    groups = scanner._snapshot_identity_groups(original, sanitized)
    with pytest.raises(scanner.RedactionError, match="distinct"):
        for namespace, identities in groups.items():
            scanner.assert_distinct_identities_preserved(namespace, identities)


def test_redaction_collision_between_branch_names_blocks_observation(
    tmp_path: Path,
) -> None:
    api = _api()
    repo = _init_repo(tmp_path)
    _git(repo, "branch", "token=firstsecretvalue")
    _git(repo, "branch", "token=secondsecretvalue")
    before_head = _git(repo, "rev-parse", "HEAD")
    before_status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")

    with pytest.raises(api.RepositorySecurityError, match="redaction"):
        _observe(repo)
    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == before_status


def test_remote_cursor_redaction_collision_blocks_before_provenance_construction(
    tmp_path: Path,
) -> None:
    api = _api()
    repo = _init_repo(tmp_path)
    before_head = _git(repo, "rev-parse", "HEAD")
    before_status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")

    with pytest.raises(api.RepositorySecurityError, match="remote evidence redaction"):
        _observe(repo, _CollidingCursorRemote())
    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == before_status


def test_scanner_rejects_every_replaced_execution_collaborator(tmp_path: Path) -> None:
    api = _api()
    scanner_module = importlib.import_module("pmpe.repository.scanner")
    redaction = importlib.import_module("pmpe.repository.redaction")
    repo = _init_repo(tmp_path)
    replacements = {
        "config": replace(_config()),
        "_runner": scanner_module.SubprocessCommandRunner(),
        "_redactor": redaction.EvidenceRedactor(environment={}),
        "_cancellation": api.CancellationSignal(),
        "_extension_implementation_evidence": (),
    }
    for attribute, replacement in replacements.items():
        candidate = api.RepositoryScanner(config=_config())
        object.__setattr__(candidate, attribute, replacement)
        with pytest.raises(api.RepositorySecurityError, match="sealed|provenance binding"):
            candidate.scan(repo, commit="HEAD")

    candidate = api.RepositoryScanner(config=_config())
    candidate._extension_implementation_evidence[0]["source_digest"] = "sha256:tampered"
    with pytest.raises(api.RepositorySecurityError, match="sealed"):
        candidate.scan(repo, commit="HEAD")

    candidate = api.RepositoryScanner(config=_config())
    object.__setattr__(candidate.redactor, "_environment_secrets", ("tampered",))
    with pytest.raises(api.RepositorySecurityError, match="sealed"):
        candidate.scan(repo, commit="HEAD")


def test_governance_rejects_every_replaced_execution_collaborator(tmp_path: Path) -> None:
    api = _api()
    governance = importlib.import_module("pmpe.repository.governance")
    redaction = importlib.import_module("pmpe.repository.redaction")
    repo = _init_repo(tmp_path)
    snapshot = _scan(repo)
    remote = _sealed_remote(_FakeRemote())
    replacements = {
        "_snapshot": replace(snapshot),
        "_clock": _fixed_clock(),
        "_id_provider": _fixed_ids(),
        "_remote_provider": remote,
        "_runner": governance.GovernanceCommandRunner(),
        "_redactor": redaction.EvidenceRedactor(environment={}),
        "_cancellation": api.CancellationSignal(),
        "_extension_implementation_evidence": (),
        "max_commands": 1,
    }
    for attribute, replacement in replacements.items():
        candidate = api.GovernanceCollector(
            repository="example/fixture",
            snapshot=snapshot,
            clock=_fixed_clock(),
            id_provider=_fixed_ids(),
        )
        object.__setattr__(candidate, attribute, replacement)
        with pytest.raises(api.RepositorySecurityError, match="sealed|provenance binding"):
            candidate.observe(repo, ref="main")

    candidate = api.GovernanceCollector(
        repository="example/fixture",
        snapshot=snapshot,
        clock=_fixed_clock(),
        id_provider=_fixed_ids(),
    )
    candidate._extension_implementation_evidence[0]["source_digest"] = "sha256:tampered"
    with pytest.raises(api.RepositorySecurityError, match="sealed"):
        candidate.observe(repo, ref="main")


def test_unproven_remote_pagination_is_blocked_not_complete(tmp_path: Path) -> None:
    observation = _observe(_init_repo(tmp_path), _PartialRemote())
    assert observation.disposition == "BLOCKED"
    assert any(item.fact == "remote_metadata_completeness" for item in observation.unknowns)


def test_stale_remote_metadata_is_blocked_not_complete(tmp_path: Path) -> None:
    observation = _observe(_init_repo(tmp_path), _StaleRemote())
    assert observation.disposition == "BLOCKED"
    assert any(item.fact == "remote_metadata_completeness" for item in observation.unknowns)


def test_pull_request_staleness_and_conflict_evidence_are_explicit(tmp_path: Path) -> None:
    observation = _observe(_init_repo(tmp_path), _StaleConflictingPullRequestRemote())
    pull_request = observation.pull_requests[0]
    assert pull_request.updated_at == "2026-06-01T00:00:00Z"
    assert pull_request.stale is True
    assert pull_request.mergeability == "CONFLICTING"
    assert observation.disposition == "BLOCKED"
    assert any(item.fact == "remote_collection_attestation" for item in observation.unknowns)


def test_unknown_pull_request_mergeability_blocks_complete_observation(tmp_path: Path) -> None:
    observation = _observe(_init_repo(tmp_path), _UnknownMergeabilityRemote())
    assert observation.disposition == "BLOCKED"
    assert any(item.fact == "pull_request_mergeability:7" for item in observation.unknowns)


@pytest.mark.parametrize("remote", [_SingleSurfaceRemote(), _CountMismatchRemote()])
def test_remote_completeness_requires_per_surface_count_bound_pagination(
    tmp_path: Path,
    remote: Any,
) -> None:
    observation = _observe(_init_repo(tmp_path), remote)
    assert observation.disposition == "BLOCKED"
    assert any(item.fact == "remote_metadata_completeness" for item in observation.unknowns)


@pytest.mark.parametrize(
    "remote",
    [_EmptyGovernanceRemote(), _UnknownGovernanceRemote(), _ScalarGovernanceRemote()],
)
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
        clock=_fixed_clock(),
        id_provider=_fixed_ids(),
        remote_provider=_sealed_remote(_HangingRemote()),
        command_timeout_seconds=1,
    ).observe(repo, ref="main")
    assert time.monotonic() - started < 4
    assert observation.disposition == "BLOCKED"
    assert any(item.fact == "remote_governance" for item in observation.unknowns)


def test_remote_numeric_payload_cannot_bypass_parent_byte_bound(tmp_path: Path) -> None:
    api = _api()
    observation = api.GovernanceCollector(
        repository="example/fixture",
        clock=_fixed_clock(),
        id_provider=_fixed_ids(),
        remote_provider=_sealed_remote(_HugeNumericRemote()),
        max_output_bytes=2_048,
    ).observe(_init_repo(tmp_path), ref="main")
    assert observation.disposition == "BLOCKED"
    assert observation.remote_branches == ()
    assert any(item.fact == "remote_governance" for item in observation.unknowns)


@pytest.mark.parametrize(
    "remote",
    [
        _MismatchedRemote(),
        _DuplicateRemote(),
        _CoerciblePrimitiveRemote(),
        _ExtraFieldRemote(),
        _ExtraNestedFieldRemote(),
    ],
)
def test_remote_identity_mismatch_or_duplicate_inventory_fails_closed(
    tmp_path: Path, remote: Any
) -> None:
    observation = _observe(_init_repo(tmp_path), remote)
    assert observation.disposition == "BLOCKED"
    assert any(item.fact == "remote_metadata_shape" for item in observation.unknowns)


def test_remote_provider_cancellation_terminates_the_isolated_process() -> None:
    api = _api()
    cancellation = api.CancellationSignal()
    timer = threading.Timer(0.2, cancellation.cancel)
    timer.start()

    collector = api.GovernanceCollector(
        repository="example/fixture",
        clock=_fixed_clock(),
        id_provider=_fixed_ids(),
        remote_provider=_sealed_remote(_HangingRemote()),
        command_timeout_seconds=10,
        cancellation=cancellation,
    )
    started = time.monotonic()
    with pytest.raises(api.RepositoryIntelligenceError, match="cancelled"):
        collector._collect_remote_bounded("main")
    timer.join(timeout=1)
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


def test_observation_input_digest_binds_staged_object_identity(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _write(repo, "README.md", "first staged value\n")
    _git(repo, "add", "README.md")
    first = _observe(repo, _FakeRemote())

    _write(repo, "README.md", "second staged value\n")
    _git(repo, "add", "README.md")
    second = _observe(repo, _FakeRemote())

    assert first.local_state == second.local_state
    assert first.observation_input_digest != second.observation_input_digest
    assert first.observation_output_digest != second.observation_output_digest


def test_observation_input_digest_binds_freshness_and_collector_budgets(tmp_path: Path) -> None:
    api = _api()
    repo = _init_repo(tmp_path)

    def observe(max_age: int) -> Any:
        return api.GovernanceCollector(
            repository="example/fixture",
            clock=_fixed_clock(),
            id_provider=_fixed_ids(),
            remote_provider=_sealed_remote(_AgeSensitiveRemote()),
            max_remote_age_seconds=max_age,
        ).observe(repo, ref="main")

    fresh = observe(300)
    blocked = observe(60)
    assert fresh.disposition == "BLOCKED"
    assert any(item.fact == "remote_collection_attestation" for item in fresh.unknowns)
    assert blocked.disposition == "BLOCKED"
    assert fresh.observation_input_digest != blocked.observation_input_digest

    alternate_stale_policy = api.GovernanceCollector(
        repository="example/fixture",
        clock=_fixed_clock(),
        id_provider=_fixed_ids(),
        remote_provider=_sealed_remote(_AgeSensitiveRemote()),
        max_remote_age_seconds=300,
        stale_pull_request_after_seconds=60,
    ).observe(repo, ref="main")
    assert fresh.observation_input_digest != alternate_stale_policy.observation_input_digest


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("command_timeout_seconds", 121),
        ("max_commands", 20_001),
        ("max_branches", 10_001),
        ("max_output_bytes", 64_000_001),
        ("max_remote_items", 100_001),
        ("max_remote_age_seconds", 86_401),
        ("stale_pull_request_after_seconds", 31_536_001),
    ],
)
def test_governance_budget_hard_ceilings_cannot_be_disabled(
    tmp_path: Path,
    field: str,
    value: int,
) -> None:
    api = _api()
    kwargs = {
        "repository": "example/fixture",
        "clock": _fixed_clock(),
        "id_provider": _fixed_ids(),
        field: value,
    }
    if field == "max_output_bytes":
        with pytest.raises(api.RepositoryIntelligenceError, match="hard ceiling"):
            api.GovernanceCollector(**kwargs)
        return
    collector = api.GovernanceCollector(**kwargs)
    with pytest.raises(api.RepositoryIntelligenceError, match="hard safety ceiling"):
        collector.observe(_init_repo(tmp_path), ref="main")


def test_governance_runner_budget_must_match_recorded_collector_budget() -> None:
    api = _api()
    governance = importlib.import_module("pmpe.repository.governance")
    with pytest.raises(api.RepositorySecurityError, match="must match"):
        api.GovernanceCollector(
            repository="example/fixture",
            clock=_fixed_clock(),
            id_provider=_fixed_ids(),
            command_runner=governance.GovernanceCommandRunner(max_output_bytes=4_096),
            max_output_bytes=2_048,
        )

    runner = governance.GovernanceCommandRunner(max_output_bytes=2_048)
    collector = api.GovernanceCollector(
        repository="example/fixture",
        clock=_fixed_clock(),
        id_provider=_fixed_ids(),
        command_runner=runner,
        max_output_bytes=2_048,
    )
    with pytest.raises(AttributeError):
        runner.max_output_bytes = 4_096  # type: ignore[misc]
    object.__setattr__(runner, "_max_output_bytes", 4_096)
    with pytest.raises(api.RepositorySecurityError, match="changed after"):
        collector.observe(Path.cwd(), ref="HEAD")


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
            clock=_fixed_clock(),
            id_provider=_fixed_ids(),
        ).observe(repo, ref="--output=outside")


def test_scanner_does_not_execute_tracked_project_code(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    marker = tmp_path / "must-not-exist"
    _write(repo, "setup.py", f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n")
    _commit(repo, "hostile project code")
    _scan(repo)
    assert not marker.exists()


def test_missing_git_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = _api()
    scanner = importlib.import_module("pmpe.repository.scanner")
    repo = _init_repo(tmp_path)
    monkeypatch.setattr(
        scanner,
        "_TRUSTED_GIT_CANDIDATES",
        (tmp_path / "missing-system-git",),
    )
    with pytest.raises(api.RepositoryIntelligenceError):
        api.RepositoryScanner(config=_config()).scan(repo, commit="HEAD")


def test_git_timeout_is_bounded_and_visible(tmp_path: Path) -> None:
    scanner = importlib.import_module("pmpe.repository.scanner")
    result = scanner.SubprocessCommandRunner().run(("git", "version"), tmp_path, 0)
    assert result.timed_out
    assert result.returncode == 124


def test_caller_path_cannot_select_the_git_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_repo(tmp_path)
    expected_head = _git(repo, "rev-parse", "HEAD")
    fake_bin = tmp_path / "attacker-bin"
    fake_bin.mkdir()
    marker = tmp_path / "caller-path-git-ran"
    fake_git = fake_bin / "git"
    fake_git.write_text(f"#!/bin/sh\ntouch {marker}\nexit 9\n")
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    snapshot = _scan(repo)
    observation = _observe(repo)
    assert snapshot.commit_sha == expected_head
    assert observation.local_state.head_sha == expected_head
    assert not marker.exists()


def test_malformed_git_output_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = _api()
    scanner = importlib.import_module("pmpe.repository.scanner")
    repo = _init_repo(tmp_path)
    original = scanner.SubprocessCommandRunner.run

    def malformed(
        self: Any,
        args: tuple[str, ...],
        cwd: Path,
        timeout: int,
        *,
        cancellation: Any = None,
    ) -> Any:
        if args[1] == "rev-parse" and "--show-object-format" in args:
            return api.CommandResult(
                args=args,
                returncode=0,
                stdout="not-a-sha\n",
                stderr="",
            )
        return original(self, args, cwd, timeout, cancellation=cancellation)

    monkeypatch.setattr(scanner.SubprocessCommandRunner, "run", malformed)
    with pytest.raises(api.RepositoryIntelligenceError):
        api.RepositoryScanner(config=_config()).scan(repo, commit="HEAD")


def test_invalid_repository_fails_closed(tmp_path: Path) -> None:
    api = _api()
    with pytest.raises(api.RepositoryIntelligenceError, match="Git repository"):
        api.RepositoryScanner(config=_config()).scan(tmp_path, commit="HEAD")


def test_cancellation_is_visible_and_never_silently_partial(tmp_path: Path) -> None:
    api = _api()
    repo = _init_repo(tmp_path)
    before_head = _git(repo, "rev-parse", "HEAD")
    before_index = (repo / ".git" / "index").read_bytes()
    before_status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    cancellation = api.CancellationSignal()
    cancellation.cancel()
    with pytest.raises(api.RepositoryScanCancelledError) as cancelled:
        api.RepositoryScanner(config=_config(), cancellation=cancellation).scan(repo, commit="HEAD")
    assert cancelled.value.finding.code == "SCAN.CANCELLED"
    assert cancelled.value.finding.blocking
    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert (repo / ".git" / "index").read_bytes() == before_index
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == before_status


def test_cancellation_terminates_bounded_enumeration_and_preserves_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    scanner = importlib.import_module("pmpe.repository.scanner")
    repo = _init_repo(tmp_path)
    before_head = _git(repo, "rev-parse", "HEAD")
    before_index = (repo / ".git" / "index").read_bytes()
    before_status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")

    cancellation = api.CancellationSignal()
    original = scanner.SubprocessCommandRunner.list_tree

    def cancel_then_list(
        self: Any,
        args: tuple[str, ...],
        cwd: Path,
        timeout: int,
        *,
        max_records: int,
        max_output_bytes: int,
        cancellation: Any = None,
    ) -> Any:
        assert cancellation is not None
        cancellation.cancel()
        return original(
            self,
            args,
            cwd,
            timeout,
            max_records=max_records,
            max_output_bytes=max_output_bytes,
            cancellation=cancellation,
        )

    monkeypatch.setattr(scanner.SubprocessCommandRunner, "list_tree", cancel_then_list)
    snapshot = api.RepositoryScanner(config=_config(), cancellation=cancellation).scan(
        repo, commit="HEAD"
    )
    assert snapshot.disposition == "BLOCKED"
    assert any(item.code == "SCAN.CANCELLED" and item.blocking for item in snapshot.findings)
    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert (repo / ".git" / "index").read_bytes() == before_index
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == before_status


def test_cancellation_terminates_an_initial_bounded_git_command(tmp_path: Path) -> None:
    scanner = importlib.import_module("pmpe.repository.scanner")
    cancellation = _api().CancellationSignal(cancel_after_checks=1)
    started = time.monotonic()
    result = scanner.SubprocessCommandRunner().run(
        ("git", "version"), tmp_path, 10, cancellation=cancellation
    )
    assert time.monotonic() - started < 4
    assert result.returncode == 126
    assert result.timed_out is False


def test_cancellation_during_adapter_blocks_snapshot_finalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    scanner = importlib.import_module("pmpe.repository.scanner")
    repo = _init_repo(tmp_path)
    before_head = _git(repo, "rev-parse", "HEAD")
    before_status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")

    cancellation = api.CancellationSignal()
    timer: threading.Timer | None = None

    def hanging_worker(
        _connection: Any,
        _adapter: Any,
        _context: Any,
        _expected_state_digest: str,
        _expected_adapter_identity: int,
        _expected_evaluator_identity: int,
        _expected_module_state_digest: str,
        _expected_import_state_digest: str,
        _expected_import_identities: tuple[tuple[str, int], ...],
    ) -> None:
        os.setsid()
        time.sleep(30)

    original_bounded = scanner.RepositoryScanner._run_adapter_bounded

    def cancel_during_bounded_adapter(self: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal timer
        timer = threading.Timer(0.2, cancellation.cancel)
        timer.start()
        return original_bounded(self, *args, **kwargs)

    monkeypatch.setattr(scanner, "_adapter_worker", hanging_worker)
    monkeypatch.setattr(
        scanner.RepositoryScanner, "_run_adapter_bounded", cancel_during_bounded_adapter
    )
    snapshot = api.RepositoryScanner(
        config=_config(),
        cancellation=cancellation,
    ).scan(repo, commit="HEAD")
    assert timer is not None
    timer.join(timeout=1)
    assert snapshot.disposition == "BLOCKED"
    assert any(item.code == "SCAN.CANCELLED" and item.blocking for item in snapshot.findings)
    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == before_status


def test_cancellation_during_snapshot_digest_loses_atomic_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    scanner = importlib.import_module("pmpe.repository.scanner")
    repo = _init_repo(tmp_path)
    before_head = _git(repo, "rev-parse", "HEAD")
    before_index = (repo / ".git" / "index").read_bytes()
    before_status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    cancellation = api.CancellationSignal()
    original_claim = scanner.CancellationSignal.claim_completion
    cancelled_at_admission = False

    def cancel_before_claim(self: Any) -> bool:
        nonlocal cancelled_at_admission
        if not cancelled_at_admission:
            cancelled_at_admission = True
            self.cancel()
        return original_claim(self)

    monkeypatch.setattr(scanner.CancellationSignal, "claim_completion", cancel_before_claim)
    snapshot = api.RepositoryScanner(config=_config(), cancellation=cancellation).scan(
        repo, commit="HEAD"
    )

    assert cancelled_at_admission
    assert snapshot.disposition == "BLOCKED"
    assert any(item.code == "SCAN.CANCELLED" and item.blocking for item in snapshot.findings)
    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert (repo / ".git" / "index").read_bytes() == before_index
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == before_status


def test_cancellation_after_atomic_completion_cannot_invalidate_artifact() -> None:
    signal = _api().CancellationSignal()
    assert signal.claim_completion() is True
    signal.cancel()
    assert signal.cancelled() is False


def test_governance_cancellation_terminates_bounded_command_and_preserves_repository(
    tmp_path: Path,
) -> None:
    api = _api()
    repo = _init_repo(tmp_path)
    before_head = _git(repo, "rev-parse", "HEAD")
    before_index = (repo / ".git" / "index").read_bytes()

    collector = api.GovernanceCollector(
        repository="example/fixture",
        clock=_fixed_clock(),
        id_provider=_fixed_ids(),
        cancellation=api.CancellationSignal(cancel_after_checks=2),
    )
    with pytest.raises(api.RepositoryIntelligenceError, match="cancelled"):
        collector.observe(repo, ref="main")
    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert (repo / ".git" / "index").read_bytes() == before_index


def test_cancellation_during_observation_digest_loses_atomic_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    governance = importlib.import_module("pmpe.repository.governance")
    repo = _init_repo(tmp_path)
    before_head = _git(repo, "rev-parse", "HEAD")
    before_index = (repo / ".git" / "index").read_bytes()
    before_status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    cancellation = api.CancellationSignal()
    original_claim = governance.CancellationSignal.claim_completion
    cancelled_at_admission = False

    def cancel_before_claim(self: Any) -> bool:
        nonlocal cancelled_at_admission
        if not cancelled_at_admission:
            cancelled_at_admission = True
            self.cancel()
        return original_claim(self)

    monkeypatch.setattr(governance.CancellationSignal, "claim_completion", cancel_before_claim)
    observation = api.GovernanceCollector(
        repository="example/fixture",
        clock=_fixed_clock(),
        id_provider=_fixed_ids(),
        cancellation=cancellation,
    ).observe(repo, ref="main")

    assert cancelled_at_admission
    assert observation.disposition == "BLOCKED"
    assert any(
        item.fact == "observation_cancellation" and item.status == "BLOCKED"
        for item in observation.unknowns
    )
    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert (repo / ".git" / "index").read_bytes() == before_index
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == before_status


def test_git_readers_disable_lazy_fetch_and_repository_defined_accelerators() -> None:
    scanner = importlib.import_module("pmpe.repository.scanner")
    governance = importlib.import_module("pmpe.repository.governance")
    scanner_environment = scanner.SubprocessCommandRunner._environment()
    assert scanner_environment["GIT_NO_LAZY_FETCH"] == "1"
    assert scanner_environment["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert scanner_environment["GIT_CONFIG_VALUE_0"] == "false"
    governance_runner = governance.GovernanceCommandRunner()
    assert scanner_environment["GIT_CONFIG_VALUE_5"] == "false"
    assert governance_runner.identity.endswith("1.10.0")


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


def test_digest_bearing_artifacts_are_self_verified_before_reuse(tmp_path: Path) -> None:
    api = _api()
    repo = _init_repo(tmp_path)
    snapshot = _scan(repo)
    tampered_snapshot = replace(snapshot, scanner_version="tampered")
    assert tampered_snapshot.digest_is_valid() is False
    with pytest.raises(api.RepositorySecurityError, match="snapshot digest"):
        api.GovernanceCollector(
            repository="example/fixture",
            snapshot=tampered_snapshot,
            clock=_fixed_clock(),
            id_provider=_fixed_ids(),
        )

    observation = api.GovernanceCollector(
        repository="example/fixture",
        snapshot=snapshot,
        clock=_fixed_clock(),
        id_provider=_fixed_ids(),
    ).observe(repo, ref="main")
    tampered_observation = replace(observation, disposition="COMPLETE")
    assert tampered_observation.digest_is_valid() is False
    with pytest.raises(ValueError, match="observation digest"):
        snapshot.assessment_reference(tampered_observation)


def test_noncomplete_snapshot_and_observation_cannot_form_a_lifecycle_reference(
    tmp_path: Path,
) -> None:
    api = _api()
    repo = _init_repo(tmp_path)
    snapshot = _scan(repo)
    observation = api.GovernanceCollector(
        repository="example/fixture",
        snapshot=snapshot,
        clock=_fixed_clock(),
        id_provider=_fixed_ids(),
    ).observe(repo, ref="main")
    with pytest.raises(ValueError, match="snapshot is not complete"):
        snapshot.assessment_reference(observation)


def test_complete_snapshot_can_delegate_only_mutable_work_to_governance(
    tmp_path: Path,
) -> None:
    canonical = importlib.import_module("pmpe.contracts.canonical")
    repo = _init_repo(tmp_path)
    snapshot = _scan(repo)
    complete_snapshot = replace(
        snapshot,
        disposition="COMPLETE",
        findings=(),
        unsupported_categories=("active_divergent_work",),
        snapshot_digest="",
    )
    snapshot_payload = complete_snapshot.as_dict()
    snapshot_payload.pop("snapshot_digest")
    complete_snapshot = replace(
        complete_snapshot,
        snapshot_digest=canonical.canonical_digest(snapshot_payload),
    )
    observation = (
        _api()
        .GovernanceCollector(
            repository="example/fixture",
            snapshot=complete_snapshot,
            clock=_fixed_clock(),
            id_provider=_fixed_ids(),
        )
        .observe(repo, ref="main")
    )
    complete_observation = replace(
        observation,
        disposition="COMPLETE",
        unknowns=(),
        observation_output_digest="",
    )
    observation_payload = complete_observation.as_dict()
    observation_payload.pop("observation_output_digest")
    complete_observation = replace(
        complete_observation,
        observation_output_digest=canonical.canonical_digest(observation_payload),
    )
    reference = complete_snapshot.assessment_reference(complete_observation)
    assert reference["repository_snapshot_disposition"] == "COMPLETE"
    assert reference["governance_observation_disposition"] == "COMPLETE"


def test_snapshot_rejects_governance_observation_from_another_repository(
    tmp_path: Path,
) -> None:
    api = _api()
    snapshot = _scan(_init_repo(tmp_path))
    observation = api.GovernanceCollector(
        repository="different/repository",
        clock=_fixed_clock(),
        id_provider=_fixed_ids(),
    ).observe(tmp_path / "fixture-repo", ref="main")
    with pytest.raises(ValueError, match="repositories do not match"):
        snapshot.assessment_reference(observation)
