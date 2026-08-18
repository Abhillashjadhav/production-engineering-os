"""Issue #105 red-first contract for exact-commit isolated execution."""

from __future__ import annotations

import hashlib
import hmac
import shutil
import subprocess
import sys
import time
import zlib
from dataclasses import replace
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from pmpe.admission import FileArtifactAdmissionAuthority, FileArtifactAdmissionVerifier
from pmpe.contracts.intake import KeyedFingerprint


class _FingerprintProvider:
    key_version = "test-v1"

    def fingerprint(self, domain: str, payload: bytes) -> str:
        return hmac.new(
            b"issue-105-test-key", domain.encode() + b"\0" + payload, hashlib.sha256
        ).hexdigest()

    def candidate_fingerprints(self, domain: str, payload: bytes) -> tuple[KeyedFingerprint, ...]:
        return (KeyedFingerprint(self.key_version, self.fingerprint(domain, payload)),)


def _api():  # type: ignore[no-untyped-def]
    try:
        from pmpe import execution
    except (ImportError, ModuleNotFoundError):
        pytest.fail("issue #105 isolated execution is not implemented", pytrace=False)
    return execution


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-q")
    (repository / "tracked.txt").write_text("committed\n")
    _git(repository, "add", "tracked.txt")
    _git(repository, "commit", "-qm", "fixture")
    return repository, _git(repository, "rev-parse", "HEAD")


class _MutatingSandbox:
    identity = "test-copy-sandbox/1"

    def __init__(self) -> None:
        self.observed_source = ""

    def run(self, workspace: Path, command: object, policy: object) -> object:
        api = _api()
        self.observed_source = (workspace / "tracked.txt").read_text()
        (workspace / "tracked.txt").write_text("mutated by red test\n")
        return api.CommandOutcome(
            return_code=1,
            stdout=b"meaningful red\n",
            stderr=b"",
            resolved_executable="/usr/bin/python3",
        )


def _kernel(tmp_path: Path, sandbox: object) -> object:
    api = _api()
    return api.IsolatedExecutionKernel(
        authority=FileArtifactAdmissionAuthority(tmp_path / "receipts", _FingerprintProvider()),
        sandbox=sandbox,
        policy=api.ExecutionPolicy(timeout_seconds=5.0, max_output_bytes=4096),
    )


def test_dirty_caller_and_mutating_command_cannot_change_evaluated_subject(
    tmp_path: Path,
) -> None:
    api = _api()
    repository, commit = _repository(tmp_path)
    (repository / "tracked.txt").write_text("dirty caller\n")
    sandbox = _MutatingSandbox()

    result = _kernel(tmp_path, sandbox).execute(
        repository=repository,
        commit_sha=commit,
        plan_digest="sha256:" + "a" * 64,
        command=api.ExecutionCommand(argv=(sys.executable, "-c", "raise SystemExit(1)")),
    )

    assert sandbox.observed_source == "committed\n"
    assert result.subject_digest_before == result.subject_digest_after
    assert (repository / "tracked.txt").read_text() == "dirty caller\n"
    assert result.return_code == 1


@pytest.mark.parametrize("commit", ("0" * 40, "not-a-commit", ""))
def test_commit_mismatch_blocks_execution(tmp_path: Path, commit: str) -> None:
    api = _api()
    repository, _ = _repository(tmp_path)

    with pytest.raises(api.ExecutionError, match="commit"):
        _kernel(tmp_path, _MutatingSandbox()).execute(
            repository=repository,
            commit_sha=commit,
            plan_digest="sha256:" + "b" * 64,
            command=api.ExecutionCommand(argv=("python", "-V")),
        )


def test_execution_receipt_is_durable_idempotent_and_not_caller_forgeable(
    tmp_path: Path,
) -> None:
    api = _api()
    repository, commit = _repository(tmp_path)
    sandbox = _MutatingSandbox()
    kernel = _kernel(tmp_path, sandbox)
    arguments = {
        "repository": repository,
        "commit_sha": commit,
        "plan_digest": "sha256:" + "c" * 64,
        "command": api.ExecutionCommand(argv=(sys.executable, "-c", "raise SystemExit(1)")),
    }

    first = kernel.execute(**arguments)
    second = kernel.execute(**arguments)

    assert first.receipt == second.receipt
    assert first.stdout_digest == "sha256:" + hashlib.sha256(b"meaningful red\n").hexdigest()
    verifier = FileArtifactAdmissionVerifier(tmp_path / "receipts", _FingerprintProvider())
    assert verifier.verify(
        first.receipt,
        artifact_kind="RED_TEST_EXECUTION",
        artifact_digest=first.execution_digest,
        subject_bindings=first.receipt_bindings,
    )
    assert not verifier.verify(
        replace(first.receipt, fingerprint="0" * 64),
        artifact_kind="RED_TEST_EXECUTION",
        artifact_digest=first.execution_digest,
        subject_bindings=first.receipt_bindings,
    )


class _FailingSandbox:
    identity = "test-failing-sandbox/1"

    def __init__(self, error_name: str) -> None:
        self.error_name = error_name

    def run(self, workspace: Path, command: object, policy: object) -> object:
        api = _api()
        raise getattr(api, self.error_name)(self.error_name)


@pytest.mark.parametrize(
    "error_name",
    ("ExecutableUnavailable", "ExecutionTimedOut", "OutputLimitExceeded"),
)
def test_execution_boundary_failures_block_receipt(tmp_path: Path, error_name: str) -> None:
    api = _api()
    repository, commit = _repository(tmp_path)

    with pytest.raises(getattr(api, error_name)):
        _kernel(tmp_path, _FailingSandbox(error_name)).execute(
            repository=repository,
            commit_sha=commit,
            plan_digest="sha256:" + "d" * 64,
            command=api.ExecutionCommand(argv=("missing-tool",)),
        )

    assert not (tmp_path / "receipts" / "RED_TEST_EXECUTION").exists()


def test_cleanup_failure_blocks_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    repository, commit = _repository(tmp_path)
    original_rmtree = shutil.rmtree

    def failed_cleanup(path: object, *args: object, **kwargs: object) -> None:
        if Path(path).name.startswith("pmpe-red-execution-"):
            raise OSError("simulated cleanup failure")
        original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", failed_cleanup)

    with pytest.raises(api.ExecutionCleanupError):
        _kernel(tmp_path, _MutatingSandbox()).execute(
            repository=repository,
            commit_sha=commit,
            plan_digest="sha256:" + "e" * 64,
            command=api.ExecutionCommand(argv=(sys.executable, "-c", "raise SystemExit(1)")),
        )


def test_command_validation_rejects_shell_strings_and_unbounded_arguments() -> None:
    api = _api()

    with pytest.raises(api.ExecutionError):
        api.ExecutionCommand(argv="pytest; rm -rf /")
    with pytest.raises(api.ExecutionError):
        api.ExecutionCommand(argv=())
    with pytest.raises(api.ExecutionError):
        api.ExecutionCommand(argv=("python", "x" * 9000))


def test_bubblewrap_runner_blocks_missing_executable_and_bounds_output(tmp_path: Path) -> None:
    api = _api()
    runner = api.BubblewrapSandbox()
    policy = api.ExecutionPolicy(timeout_seconds=2.0, max_output_bytes=64)

    with pytest.raises(api.ExecutableUnavailable):
        runner.run(tmp_path, api.ExecutionCommand(argv=("definitely-not-a-tool",)), policy)
    if not runner.is_available():
        with pytest.raises(api.ExecutionIsolationUnavailable):
            runner.run(tmp_path, api.ExecutionCommand(argv=("python3", "-V")), policy)
        return
    with pytest.raises(api.OutputLimitExceeded):
        runner.run(
            tmp_path,
            api.ExecutionCommand(argv=("python3", "-c", "print('x' * 4096)")),
            policy,
        )


def test_git_replacement_refs_cannot_substitute_the_admitted_commit(tmp_path: Path) -> None:
    api = _api()
    repository, admitted_commit = _repository(tmp_path)
    (repository / "tracked.txt").write_text("replacement tree\n")
    _git(repository, "add", "tracked.txt")
    _git(repository, "commit", "-qm", "replacement")
    replacement_commit = _git(repository, "rev-parse", "HEAD")
    _git(repository, "replace", admitted_commit, replacement_commit)
    sandbox = _MutatingSandbox()

    _kernel(tmp_path, sandbox).execute(
        repository=repository,
        commit_sha=admitted_commit,
        plan_digest="sha256:" + "f" * 64,
        command=api.ExecutionCommand(argv=(sys.executable, "-c", "raise SystemExit(1)")),
    )

    assert sandbox.observed_source == "committed\n"


def test_missing_tool_is_reported_before_missing_sandbox(tmp_path: Path) -> None:
    api = _api()
    runner = api.BubblewrapSandbox(executable="definitely-not-bubblewrap")

    with pytest.raises(api.ExecutableUnavailable):
        runner.run(
            tmp_path,
            api.ExecutionCommand(argv=("definitely-not-a-tool",)),
            api.ExecutionPolicy(),
        )


def test_repository_relative_executable_is_resolved_from_snapshot_workspace(
    tmp_path: Path,
) -> None:
    api = _api()
    executable = tmp_path / "run-tests"
    executable.write_text("#!/bin/sh\nexit 1\n")
    executable.chmod(0o700)
    runner = api.BubblewrapSandbox()

    if not runner.is_available():
        with pytest.raises(api.ExecutionIsolationUnavailable):
            runner.run(
                tmp_path,
                api.ExecutionCommand(argv=("./run-tests",)),
                api.ExecutionPolicy(),
            )
    else:
        assert (
            runner.run(
                tmp_path,
                api.ExecutionCommand(argv=("./run-tests",)),
                api.ExecutionPolicy(),
            ).return_code
            == 1
        )


def test_bubblewrap_mounts_workspace_before_hiding_host_tmp(tmp_path: Path) -> None:
    api = _api()
    runner = api.BubblewrapSandbox()
    argv = runner._argv(  # noqa: SLF001 - exact sandbox policy is the contract under test
        tmp_path,
        api.ExecutionCommand(argv=("python3", "-V")),
        api.ExecutionPolicy(),
    )

    workspace_index = argv.index(str(tmp_path))
    tmp_index = argv.index("/tmp")
    chdir_index = argv.index("--chdir")
    assert argv[workspace_index - 1] == "--ro-bind"
    assert workspace_index < tmp_index
    assert argv[workspace_index + 1] == "/workspace"
    assert argv[chdir_index + 1] == "/workspace"


def test_export_attributes_cannot_change_the_admitted_tree(tmp_path: Path) -> None:
    api = _api()
    repository, _ = _repository(tmp_path)
    (repository / ".gitattributes").write_text("tracked.txt export-ignore\n")
    _git(repository, "add", ".gitattributes")
    _git(repository, "commit", "-qm", "archive attributes")
    admitted_commit = _git(repository, "rev-parse", "HEAD")
    sandbox = _MutatingSandbox()

    _kernel(tmp_path, sandbox).execute(
        repository=repository,
        commit_sha=admitted_commit,
        plan_digest="sha256:" + "0" * 64,
        command=api.ExecutionCommand(argv=(sys.executable, "-c", "raise SystemExit(1)")),
    )

    assert sandbox.observed_source == "committed\n"


def test_child_stderr_prefixed_with_bwrap_is_not_a_setup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    from pmpe.execution import kernel as kernel_module

    runner = api.BubblewrapSandbox()
    runner._available = True  # noqa: SLF001 - skip the host-specific probe in this unit test
    outcome = SimpleNamespace(
        return_code=1,
        stdout=b"",
        stderr=b"bwrap: child assertion failed",
        isolation_status=b'{"child-pid": 123}',
    )
    original_which = shutil.which
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name, path=None: (
            "/usr/bin/bwrap" if name == "bwrap" else original_which(name, path=path)
        ),
    )
    monkeypatch.setattr(kernel_module, "_run_bounded_process", lambda *args, **kwargs: outcome)

    observed = runner.run(
        tmp_path,
        api.ExecutionCommand(argv=("python3", "-V")),
        api.ExecutionPolicy(),
    )

    assert observed.stderr == b"bwrap: child assertion failed"


def test_execution_policy_rejects_relative_or_empty_path_entries() -> None:
    api = _api()

    with pytest.raises(api.ExecutionError):
        api.ExecutionPolicy(executable_path="/usr/bin:.")
    with pytest.raises(api.ExecutionError):
        api.ExecutionPolicy(executable_path=":/usr/bin")


def test_snapshot_materialization_uses_one_aggregate_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    from pmpe.execution import kernel as kernel_module

    commit = "a" * 40
    object_id = hashlib.sha1(  # noqa: S324 - Git SHA-1 object identity
        b"blob 1\0x", usedforsecurity=False
    ).hexdigest()
    object_ids = (object_id, object_id, object_id)
    listing = b"".join(
        f"100644 blob {object_id}\tfile-{index}.txt\0".encode()
        for index, object_id in enumerate(object_ids)
    )

    def delayed_git(argv: object, **kwargs: object) -> object:
        arguments = list(argv)  # type: ignore[arg-type]
        if "rev-parse" in arguments:
            return api.CommandOutcome(0, (commit + "\n").encode(), b"")
        if "fsck" in arguments:
            return api.CommandOutcome(0, b"", b"")
        if "ls-tree" in arguments:
            return api.CommandOutcome(0, listing, b"")
        if "cat-file" in arguments:
            time.sleep(0.03)
            return api.CommandOutcome(0, b"x", b"")
        raise AssertionError(arguments)

    monkeypatch.setattr(kernel_module, "_run_bounded_process", delayed_git)

    with pytest.raises(api.ExecutionTimedOut):
        kernel_module._exact_commit_archive(  # noqa: SLF001 - aggregate deadline contract
            tmp_path,
            commit,
            api.ExecutionPolicy(timeout_seconds=0.05),
        )


def test_bare_workspace_tool_is_resolved_against_the_sandbox_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    from pmpe.execution import kernel as kernel_module

    executable = tmp_path / "run-tests"
    executable.write_text("#!/bin/sh\nexit 1\n")
    executable.chmod(0o700)
    runner = api.BubblewrapSandbox()
    runner._available = True  # noqa: SLF001 - skip the host-specific probe in this unit test
    original_which = shutil.which

    def sandbox_which(name: str, path: str | None = None) -> str | None:
        if name == "bwrap":
            return "/usr/bin/bwrap"
        if name == "prlimit":
            return "/usr/bin/prlimit"
        return original_which(name, path=path)

    monkeypatch.setattr(shutil, "which", sandbox_which)
    monkeypatch.setattr(
        kernel_module,
        "_run_bounded_process",
        lambda *args, **kwargs: api.CommandOutcome(1, b"", b"", b'{"child-pid": 123}'),
    )

    observed = runner.run(
        tmp_path,
        api.ExecutionCommand(argv=("run-tests",)),
        api.ExecutionPolicy(executable_path="/workspace"),
    )

    assert observed.return_code == 1
    assert observed.resolved_executable == "/workspace/run-tests"


def test_bubblewrap_process_is_launched_with_resource_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    from pmpe.execution import kernel as kernel_module

    runner = api.BubblewrapSandbox()
    runner._available = True  # noqa: SLF001 - skip the host-specific probe in this unit test
    observed_argv: list[str] = []
    original_which = shutil.which

    def trusted_which(name: str, path: str | None = None) -> str | None:
        if name in {"bwrap", "prlimit"}:
            return f"/usr/bin/{name}"
        return original_which(name, path=path)

    def capture(argv: object, **kwargs: object) -> object:
        observed_argv.extend(argv)  # type: ignore[arg-type]
        return api.CommandOutcome(1, b"", b"", b'{"child-pid": 123}')

    monkeypatch.setattr(shutil, "which", trusted_which)
    monkeypatch.setattr(kernel_module, "_run_bounded_process", capture)
    policy = api.ExecutionPolicy(
        timeout_seconds=2,
        max_memory_bytes=512 * 1024 * 1024,
        max_processes=32,
        max_file_bytes=8 * 1024 * 1024,
        max_open_files=128,
    )

    runner.run(
        tmp_path,
        api.ExecutionCommand(argv=("python3", "-V")),
        policy,
    )

    assert observed_argv[0] == "/usr/bin/prlimit"
    assert "--as=536870912" in observed_argv
    assert "--nproc=32" in observed_argv
    assert "--fsize=8388608" in observed_argv
    assert "--nofile=128" in observed_argv
    assert "--cpu=3" in observed_argv
    assert "/usr/bin/bwrap" in observed_argv


def test_execution_policy_rejects_noncanonical_absolute_path_entries() -> None:
    api = _api()

    with pytest.raises(api.ExecutionError):
        api.ExecutionPolicy(executable_path="/workspace/../usr/bin")


def test_execution_receipt_signs_the_resolved_sandbox_executable(tmp_path: Path) -> None:
    api = _api()
    repository, commit = _repository(tmp_path)

    class ResolvedSandbox:
        identity = "resolved-sandbox/1"

        def run(self, workspace: Path, command: object, policy: object) -> object:
            return api.CommandOutcome(
                1,
                b"meaningful red\n",
                b"",
                resolved_executable="/usr/bin/pytest",
            )

    result = _kernel(tmp_path, ResolvedSandbox()).execute(
        repository=repository,
        commit_sha=commit,
        plan_digest="sha256:" + "9" * 64,
        command=api.ExecutionCommand(argv=("pytest", "--json-report")),
    )

    assert result.resolved_executable == "/usr/bin/pytest"
    assert result.receipt_bindings["resolved_executable"] == "/usr/bin/pytest"


def test_corrupted_reachable_git_object_blocks_exact_commit_execution(tmp_path: Path) -> None:
    api = _api()
    repository, commit = _repository(tmp_path)
    blob_id = _git(repository, "rev-parse", f"{commit}:tracked.txt")
    loose_object = repository / ".git" / "objects" / blob_id[:2] / blob_id[2:]
    replacement = b"tampered!\n"
    loose_object.write_bytes(
        zlib.compress(b"blob " + str(len(replacement)).encode() + b"\0" + replacement)
    )

    with pytest.raises(api.ExecutionError, match="object"):
        _kernel(tmp_path, _MutatingSandbox()).execute(
            repository=repository,
            commit_sha=commit,
            plan_digest="sha256:" + "8" * 64,
            command=api.ExecutionCommand(argv=("python3", "-V")),
        )


def test_private_tmp_path_does_not_search_the_service_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    service_cwd = tmp_path / "service"
    workspace = tmp_path / "workspace"
    service_cwd.mkdir()
    workspace.mkdir()
    executable = service_cwd / "tool"
    executable.write_text("#!/bin/sh\nexit 1\n")
    executable.chmod(0o700)
    monkeypatch.chdir(service_cwd)

    with pytest.raises(api.ExecutableUnavailable):
        api.BubblewrapSandbox().run(
            workspace,
            api.ExecutionCommand(argv=("tool",)),
            api.ExecutionPolicy(executable_path="/tmp"),
        )


def test_proc_cwd_alias_is_signed_as_the_workspace_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    from pmpe.execution import kernel as kernel_module

    service_cwd = tmp_path / "service"
    workspace = tmp_path / "workspace"
    service_cwd.mkdir()
    workspace.mkdir()
    for directory in (service_cwd, workspace):
        executable = directory / "tool"
        executable.write_text("#!/bin/sh\nexit 1\n")
        executable.chmod(0o700)
    monkeypatch.chdir(service_cwd)
    runner = api.BubblewrapSandbox()
    runner._available = True  # noqa: SLF001 - skip host-specific probe in this unit test
    original_which = shutil.which

    def trusted_which(name: str, path: str | None = None) -> str | None:
        if name in {"bwrap", "prlimit"}:
            return f"/usr/bin/{name}"
        return original_which(name, path=path)

    monkeypatch.setattr(shutil, "which", trusted_which)
    monkeypatch.setattr(
        kernel_module,
        "_run_bounded_process",
        lambda *args, **kwargs: api.CommandOutcome(1, b"", b"", b'{"child-pid": 123}'),
    )

    outcome = runner.run(
        workspace,
        api.ExecutionCommand(argv=("/proc/self/cwd/tool",)),
        api.ExecutionPolicy(),
    )

    assert outcome.resolved_executable == "/workspace/tool"


def test_bubblewrap_excludes_host_credential_directories(tmp_path: Path) -> None:
    api = _api()
    argv = api.BubblewrapSandbox()._argv(  # noqa: SLF001 - isolation argv contract
        tmp_path,
        api.ExecutionCommand(argv=("/usr/bin/python3", "-V")),
        api.ExecutionPolicy(),
    )

    assert not {
        "/root",
        "/home",
        "/var",
        "/run",
        "/etc/ssh",
        "/etc/ssl/private",
    }.intersection(argv)


def test_materialized_blob_bytes_must_match_the_listed_object_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    from pmpe.execution import kernel as kernel_module

    commit = "a" * 40
    expected = b"expected bytes\n"
    blob_id = hashlib.sha1(  # noqa: S324 - Git SHA-1 object identity
        b"blob " + str(len(expected)).encode() + b"\0" + expected
    ).hexdigest()
    listing = f"100644 blob {blob_id}\ttracked.txt\0".encode()

    def replaced_object(argv: object, **kwargs: object) -> object:
        arguments = list(argv)  # type: ignore[arg-type]
        if "rev-parse" in arguments:
            return api.CommandOutcome(0, (commit + "\n").encode(), b"")
        if "fsck" in arguments:
            return api.CommandOutcome(0, b"", b"")
        if "ls-tree" in arguments:
            return api.CommandOutcome(0, listing, b"")
        if "cat-file" in arguments:
            return api.CommandOutcome(0, b"replaced after fsck\n", b"")
        raise AssertionError(arguments)

    monkeypatch.setattr(kernel_module, "_run_bounded_process", replaced_object)

    with pytest.raises(api.ExecutionError, match="object"):
        kernel_module._exact_commit_archive(  # noqa: SLF001 - materialization contract
            tmp_path,
            commit,
            api.ExecutionPolicy(),
        )


def test_nested_proc_alias_is_canonicalized_to_the_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _api()
    from pmpe.execution import kernel as kernel_module

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = workspace / "tool"
    executable.write_text("#!/bin/sh\nexit 1\n")
    executable.chmod(0o700)
    runner = api.BubblewrapSandbox()
    runner._available = True  # noqa: SLF001 - skip host-specific probe in this unit test
    original_which = shutil.which

    def trusted_which(name: str, path: str | None = None) -> str | None:
        if name in {"bwrap", "prlimit"}:
            return f"/usr/bin/{name}"
        return original_which(name, path=path)

    monkeypatch.setattr(shutil, "which", trusted_which)
    monkeypatch.setattr(
        kernel_module,
        "_run_bounded_process",
        lambda *args, **kwargs: api.CommandOutcome(1, b"", b"", b'{"child-pid": 123}'),
    )

    outcome = runner.run(
        workspace,
        api.ExecutionCommand(argv=("/proc/self/root/proc/self/cwd/tool",)),
        api.ExecutionPolicy(),
    )

    assert outcome.resolved_executable == "/workspace/tool"


def test_workspace_is_readonly_and_private_tmp_has_an_aggregate_limit(
    tmp_path: Path,
) -> None:
    api = _api()
    policy = api.ExecutionPolicy(max_writable_bytes=32 * 1024 * 1024)
    argv = api.BubblewrapSandbox()._argv(  # noqa: SLF001 - mount policy contract
        tmp_path,
        api.ExecutionCommand(argv=("/usr/bin/python3", "-V")),
        policy,
    )

    workspace_index = argv.index(str(tmp_path))
    assert argv[workspace_index - 1] == "--ro-bind"
    tmp_index = argv.index("/tmp")
    assert argv[tmp_index - 3 : tmp_index + 1] == [
        "--size",
        str(policy.max_writable_bytes),
        "--tmpfs",
        "/tmp",
    ]


def test_host_masking_preserves_etc_alternatives_for_system_executables(
    tmp_path: Path,
) -> None:
    api = _api()
    argv = api.BubblewrapSandbox()._argv(  # noqa: SLF001 - mount policy contract
        tmp_path,
        api.ExecutionCommand(argv=("/usr/bin/awk", "BEGIN { exit 1 }")),
        api.ExecutionPolicy(),
    )
    tmpfs_targets = {
        argv[index + 1] for index, argument in enumerate(argv[:-1]) if argument == "--tmpfs"
    }

    assert "/etc" not in tmpfs_targets
    assert "/etc/alternatives" not in tmpfs_targets


def test_writable_storage_limit_changes_the_signed_policy_digest() -> None:
    api = _api()

    small = api.ExecutionPolicy(max_writable_bytes=1024 * 1024)
    large = api.ExecutionPolicy(max_writable_bytes=1024 * 1024 * 1024)

    assert small.digest != large.digest


def test_sandbox_uses_a_runtime_allowlist_instead_of_binding_the_host_root(
    tmp_path: Path,
) -> None:
    api = _api()
    argv = api.BubblewrapSandbox()._argv(  # noqa: SLF001 - mount policy contract
        tmp_path,
        api.ExecutionCommand(argv=("/usr/bin/python3", "-V")),
        api.ExecutionPolicy(),
    )
    mounts = list(zip(argv, argv[1:], strict=False))

    assert ("--ro-bind", "/") not in mounts
    assert ("--tmpfs", "/") in mounts
    assert any(
        argv[index : index + 3] == ["--ro-bind-try", "/usr", "/usr"]
        for index in range(len(argv) - 2)
    )
    assert "/etc/machine-id" not in argv
    assert "/opt" not in argv


def test_host_executable_resolution_rejects_paths_outside_runtime_mounts(
    tmp_path: Path,
) -> None:
    api = _api()

    resolved = api.BubblewrapSandbox()._host_path(  # noqa: SLF001 - mount identity contract
        tmp_path,
        PurePosixPath("/opt/unmounted-tool"),
    )

    assert resolved is None
