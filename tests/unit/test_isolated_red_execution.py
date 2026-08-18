"""Issue #105 red-first contract for exact-commit isolated execution."""

from __future__ import annotations

import hashlib
import hmac
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
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
        return api.CommandOutcome(return_code=1, stdout=b"meaningful red\n", stderr=b"")


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
def test_execution_boundary_failures_block_receipt(
    tmp_path: Path, error_name: str
) -> None:
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
            runner.run(tmp_path, api.ExecutionCommand(argv=(sys.executable, "-V")), policy)
        return
    with pytest.raises(api.OutputLimitExceeded):
        runner.run(
            tmp_path,
            api.ExecutionCommand(argv=(sys.executable, "-c", "print('x' * 4096)")),
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
        assert runner.run(
            tmp_path,
            api.ExecutionCommand(argv=("./run-tests",)),
            api.ExecutionPolicy(),
        ).return_code == 1


def test_bubblewrap_binds_workspace_before_hiding_host_tmp(tmp_path: Path) -> None:
    api = _api()
    runner = api.BubblewrapSandbox()
    argv = runner._argv(  # noqa: SLF001 - exact sandbox policy is the contract under test
        tmp_path,
        api.ExecutionCommand(argv=(sys.executable, "-V")),
        api.ExecutionPolicy(),
    )

    bind_index = argv.index("--bind")
    tmpfs_index = argv.index("--tmpfs")
    chdir_index = argv.index("--chdir")
    assert bind_index < tmpfs_index
    assert argv[bind_index + 2] == "/workspace"
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
    monkeypatch.setattr(kernel_module, "_run_bounded_process", lambda *args, **kwargs: outcome)

    observed = runner.run(
        tmp_path,
        api.ExecutionCommand(argv=(sys.executable, "-V")),
        api.ExecutionPolicy(),
    )

    assert observed.stderr == b"bwrap: child assertion failed"
