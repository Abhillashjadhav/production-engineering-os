from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pmpe import barebones
from pmpe.barebones import BubblewrapCandidateSandbox, ContractInvalidError


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
    assert "--unshare-all" in argv
    assert "--clearenv" in argv
    assert ["--ro-bind", str(workspace), "/workspace"] == argv[
        argv.index(str(workspace)) - 1 : argv.index(str(workspace)) + 2
    ]
    assert not {"/root", "/home"}.intersection(argv)
    assert observed["environment"] == {"LC_ALL": "C", "PATH": "/usr/local/bin:/usr/bin:/bin"}


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
