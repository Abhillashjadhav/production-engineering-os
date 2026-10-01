"""Offline provider launcher logic; real namespace proof is selected in CI."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from pmpe.barebones import BubblewrapCandidateSandbox, ContractInvalidError
from pmpe.provider_isolation import OfflineConfinedProvider


@pytest.fixture(autouse=True)
def logic_only_system_python(monkeypatch: pytest.MonkeyPatch) -> None:
    # This unit file observes constructed arguments; the dedicated real-host
    # CI test uses the actual protected-system-Python admission check.
    monkeypatch.setattr(
        "pmpe.provider_isolation._protected_system_python", lambda: "/usr/bin/python3"
    )


class FakeSandbox:
    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.calls: list[dict[str, Any]] = []

    def run_with_input(
        self,
        workspace: Path,
        argv: Sequence[str],
        *,
        timeout_seconds: float,
        environment: Mapping[str, str],
        input_data: bytes,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(
            {
                "workspace": workspace,
                "argv": argv,
                "timeout": timeout_seconds,
                "environment": dict(environment),
                "input_data": input_data,
            }
        )
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, "")


def _bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "provider"
    bundle.mkdir()
    (bundle / "adapter.py").write_text("print('fixture')\n")
    return bundle


def test_offline_provider_passes_only_bounded_json_and_sanitized_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLANTED_SECRET", "must-not-cross")
    sandbox = FakeSandbox('{"request_digest":"sha256:fixture","files":{}}')
    bundle = _bundle(tmp_path)
    provider = OfflineConfinedProvider(
        bundle=bundle,
        entry="adapter.py",
        protected_roots=(tmp_path / "trusted",),
        timeout_seconds=5,
        sandbox=sandbox,  # type: ignore[arg-type] - test-only boundary observer
    )
    response = provider.invoke(purpose="code", request={"request_digest": "sha256:fixture"})
    assert response["request_digest"] == "sha256:fixture"
    assert len(sandbox.calls) == 1
    call = sandbox.calls[0]
    assert call["workspace"] == bundle.resolve()
    assert call["argv"] == ("/usr/bin/python3", "-I", "-B", "/workspace/adapter.py")
    assert call["timeout"] == 5
    assert json.loads(call["input_data"]) == {
        "purpose": "code",
        "request": {"request_digest": "sha256:fixture"},
    }
    assert "PLANTED_SECRET" not in call["environment"]
    assert "PYTHONPATH" not in call["environment"]


@pytest.mark.parametrize(
    "entry", ["../adapter.py", "/adapter.py", "a/../../adapter.py", "adapter.txt"]
)
def test_offline_provider_rejects_unsafe_entry(tmp_path: Path, entry: str) -> None:
    with pytest.raises(ContractInvalidError):
        OfflineConfinedProvider(
            bundle=_bundle(tmp_path), entry=entry, protected_roots=(), timeout_seconds=5
        )


def test_offline_provider_rejects_protected_overlap_and_symlink(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    with pytest.raises(ContractInvalidError, match="overlaps protected"):
        OfflineConfinedProvider(
            bundle=bundle, entry="adapter.py", protected_roots=(tmp_path,), timeout_seconds=5
        )
    (bundle / "escape.py").symlink_to(tmp_path / "outside.py")
    with pytest.raises(ContractInvalidError, match="unsafe entry"):
        OfflineConfinedProvider(
            bundle=bundle, entry="adapter.py", protected_roots=(), timeout_seconds=5
        )


@pytest.mark.parametrize("protected", [Path("/usr/local/verifier"), Path("/etc/passwd")])
def test_offline_provider_refuses_protected_input_inside_runtime_mount(
    tmp_path: Path, protected: Path
) -> None:
    with pytest.raises(ContractInvalidError, match="overlaps offline provider runtime mount"):
        OfflineConfinedProvider(
            bundle=_bundle(tmp_path),
            entry="adapter.py",
            protected_roots=(protected,),
            timeout_seconds=5,
        )


@pytest.mark.parametrize("stdout,returncode", [("not json", 0), ('{"x":1,"x":2}', 0), ("{}", 1)])
def test_offline_provider_rejects_malformed_or_failed_output(
    tmp_path: Path, stdout: str, returncode: int
) -> None:
    provider = OfflineConfinedProvider(
        bundle=_bundle(tmp_path),
        entry="adapter.py",
        protected_roots=(),
        timeout_seconds=5,
        sandbox=FakeSandbox(stdout, returncode),  # type: ignore[arg-type] - test-only response
    )
    with pytest.raises(RuntimeError):
        provider.invoke(purpose="code", request={"request_digest": "sha256:fixture"})


def test_provider_stdin_is_inside_bubblewrap_not_ambient_host_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _bundle(tmp_path)
    observed: dict[str, Any] = {}
    sandbox = BubblewrapCandidateSandbox()
    monkeypatch.setattr("pmpe.barebones.shutil.which", lambda name, path=None: f"/usr/bin/{name}")

    def capture(argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        observed["argv"] = list(argv)
        observed["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, 0, b"{}", b"")

    monkeypatch.setattr("pmpe.barebones.subprocess.run", capture)
    result = sandbox.run_with_input(
        bundle,
        ("/usr/bin/python3", "-I", "-B", "/workspace/adapter.py"),
        timeout_seconds=5,
        environment={"HOME": "/tmp/home"},
        input_data=b'{"purpose":"code"}',
    )
    assert result.returncode == 0
    argv = observed["argv"]
    assert "--unshare-all" in argv
    assert "--clearenv" in argv
    assert ["--ro-bind", str(bundle.resolve()), "/workspace"] == argv[
        argv.index(str(bundle.resolve())) - 1 : argv.index(str(bundle.resolve())) + 2
    ]
    assert observed["kwargs"]["input"] == b'{"purpose":"code"}'
    assert observed["kwargs"]["env"] == {"LC_ALL": "C", "PATH": "/usr/local/bin:/usr/bin:/bin"}
