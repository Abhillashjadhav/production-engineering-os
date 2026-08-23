from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from pmpe import barebones
from pmpe.barebones import (
    BubblewrapCandidateSandbox,
    ContractInvalidError,
    run_to_release_ready,
)


def test_default_candidate_sandbox_removes_host_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        barebones.shutil,
        "which",
        lambda name, path=None: f"/usr/bin/{name}",
    )

    def completed(argv: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["argv"] = argv
        observed["environment"] = kwargs["env"]  # type: ignore[index]
        return subprocess.CompletedProcess(argv, 0, "{}", "")  # type: ignore[arg-type]

    monkeypatch.setattr(barebones.subprocess, "run", completed)
    sandbox = BubblewrapCandidateSandbox()
    sandbox.run(
        workspace,
        ("/usr/bin/python3", "-V"),
        timeout_seconds=2,
        environment={"PATH": "/usr/bin:/bin", "HOME": "/tmp/home"},
    )

    argv = observed["argv"]
    assert isinstance(argv, list)
    assert "--die-with-parent" in argv
    assert "--new-session" in argv
    assert "--unshare-all" in argv
    assert "--clearenv" in argv
    assert f"--fsize={64 * 1024 * 1024}" in argv
    assert ["--ro-bind", str(workspace), "/workspace"] == argv[
        argv.index(str(workspace)) - 1 : argv.index(str(workspace)) + 2
    ]
    assert not {"/root", "/home"}.intersection(argv)
    assert observed["environment"] == {"LC_ALL": "C", "PATH": "/usr/local/bin:/usr/bin:/bin"}


def test_model_file_path_cannot_escape_candidate_root(tmp_path: Path) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    escaped = tmp_path / "escaped.py"

    with pytest.raises(ValueError, match="unsafe candidate path"):
        barebones._write_files(workspace, {"../escaped.py": "HOST_WRITE = True\n"})

    assert not escaped.exists()


def test_model_file_path_cannot_escape_through_symlink(tmp_path: Path) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="escapes workspace"):
        barebones._write_files(workspace, {"linked/escaped.py": "HOST_WRITE = True\n"})

    assert not (outside / "escaped.py").exists()


def test_candidate_execution_fails_closed_without_os_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(barebones.shutil, "which", lambda *args, **kwargs: None)

    with pytest.raises(ContractInvalidError, match="sandbox is unavailable"):
        BubblewrapCandidateSandbox().run(
            tmp_path,
            ("/usr/bin/python3", "-V"),
            timeout_seconds=2,
            environment={},
        )


def test_engine_fails_closed_when_candidate_sandbox_is_unavailable(tmp_path: Path) -> None:
    class ProviderMustNotRun:
        def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
            raise AssertionError("provider must not run before sandbox verification")

    contract = {
        "contract_id": "PMOS-FAIL-CLOSED",
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

    with pytest.raises(ContractInvalidError, match="sandbox is unavailable"):
        run_to_release_ready(
            contract=contract,
            repository_root=tmp_path,
            workspace=tmp_path / "candidate",
            run_id="sandbox-unavailable",
            provider=ProviderMustNotRun(),
            candidate_sandbox=BubblewrapCandidateSandbox(executable="pmpe-missing-bwrap"),
        )


def test_candidate_output_is_bounded_outside_the_parent_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        barebones.shutil,
        "which",
        lambda name, path=None: f"/usr/bin/{name}",
    )

    def oversized(argv: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        kwargs["stdout"].write(b"x" * (barebones._CANDIDATE_OUTPUT_LIMIT_BYTES + 1))  # type: ignore[union-attr]
        return subprocess.CompletedProcess(argv, 0, b"", b"")  # type: ignore[arg-type]

    monkeypatch.setattr(barebones.subprocess, "run", oversized)

    with pytest.raises(ContractInvalidError, match="output exceeded limit"):
        BubblewrapCandidateSandbox().run(
            tmp_path,
            ("/usr/bin/python3", "-V"),
            timeout_seconds=2,
            environment={},
        )


@pytest.mark.skipif(
    os.environ.get("PMPE_TEST_REAL_SANDBOX") != "true",
    reason="requires the dedicated CI namespace runtime",
)
def test_real_candidate_sandbox_has_no_host_credentials_network_or_write_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    (workspace / "product.py").write_text("VALUE = 1\n")
    monkeypatch.setenv("PMPE_PLANTED_HOST_SECRET", "must-not-cross")
    program = (
        "import json, os, pathlib, socket\n"
        "result = {'secret': os.environ.get('PMPE_PLANTED_HOST_SECRET')}\n"
        "try:\n"
        " pathlib.Path('/workspace/product.py').write_text('changed')\n"
        " result['write'] = True\n"
        "except OSError:\n"
        " result['write'] = False\n"
        "try:\n"
        " socket.create_connection(('1.1.1.1', 53), timeout=0.1)\n"
        " result['network'] = True\n"
        "except OSError:\n"
        " result['network'] = False\n"
        "print(json.dumps(result, sort_keys=True))\n"
    )

    completed = BubblewrapCandidateSandbox().run(
        workspace,
        (sys.executable, "-I", "-B", "-c", program),
        timeout_seconds=5,
        environment={"HOME": "/tmp/home", "PATH": "/usr/local/bin:/usr/bin:/bin"},
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {"network": False, "secret": None, "write": False}
    assert (workspace / "product.py").read_text() == "VALUE = 1\n"


@pytest.mark.skipif(
    os.environ.get("PMPE_TEST_REAL_SANDBOX") != "true",
    reason="requires the dedicated CI namespace runtime",
)
def test_real_candidate_sandbox_applies_resource_limits(tmp_path: Path) -> None:
    workspace = tmp_path / "candidate"
    workspace.mkdir()
    program = (
        "import json, resource\n"
        "limits = {\n"
        " 'address_space': resource.RLIMIT_AS,\n"
        " 'cpu': resource.RLIMIT_CPU,\n"
        " 'file_size': resource.RLIMIT_FSIZE,\n"
        " 'open_files': resource.RLIMIT_NOFILE,\n"
        " 'processes': resource.RLIMIT_NPROC,\n"
        "}\n"
        "print(json.dumps({name: list(resource.getrlimit(kind)) "
        "for name, kind in limits.items()}, sort_keys=True))\n"
    )

    completed = BubblewrapCandidateSandbox().run(
        workspace,
        (sys.executable, "-I", "-B", "-c", program),
        timeout_seconds=5,
        environment={"HOME": "/tmp/home", "PATH": "/usr/local/bin:/usr/bin:/bin"},
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {
        "address_space": [1024 * 1024 * 1024, 1024 * 1024 * 1024],
        "cpu": [6, 6],
        "file_size": [64 * 1024 * 1024, 64 * 1024 * 1024],
        "open_files": [256, 256],
        "processes": [128, 128],
    }
