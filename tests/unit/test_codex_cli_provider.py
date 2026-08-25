from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _provider_module() -> ModuleType:
    path = Path(__file__).parents[2] / "examples" / "barebones" / "codex-cli-provider.py"
    spec = importlib.util.spec_from_file_location("pmpe_codex_cli_provider", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _message(purpose: str = "code") -> dict[str, Any]:
    return {
        "purpose": purpose,
        "request": {
            "request_digest": "sha256:" + "1" * 64,
            "contract": {"contract_id": "PMOS-E1"},
            "plan": {"plan_digest": "sha256:" + "2" * 64},
            "files": {"product.py": "def health(): return {}\n"},
            "findings": [{"code": "ASSERTION_FAILED", "subject_id": "AC-001"}],
        },
    }


class _FakeCodex:
    def __init__(
        self,
        generated: dict[str, Any] | None = None,
        *,
        auth: bytes = b"Logged in using ChatGPT\n",
        version_returncode: int = 0,
        exec_returncode: int = 0,
        jsonl: bytes | None = None,
        write_result: bool = True,
    ) -> None:
        self.generated = generated or {"files": []}
        self.auth = auth
        self.version_returncode = version_returncode
        self.exec_returncode = exec_returncode
        self.jsonl = (
            b'{"type":"turn.completed","usage":{"input_tokens":100,'
            b'"cached_input_tokens":40,"output_tokens":20,'
            b'"reasoning_output_tokens":7}}\n'
            if jsonl is None
            else jsonl
        )
        self.write_result = write_result
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        argv: tuple[str, ...],
        *,
        input_bytes: bytes,
        cwd: Path,
        environment: dict[str, str],
    ) -> subprocess.CompletedProcess[bytes]:
        self.calls.append(
            {
                "argv": argv,
                "input": input_bytes,
                "cwd": cwd,
                "environment": environment,
            }
        )
        if argv[1:] == ("login", "status"):
            return subprocess.CompletedProcess(argv, 0, self.auth, b"")
        if argv[1:] == ("--version",):
            return subprocess.CompletedProcess(
                argv, self.version_returncode, b"codex-cli 9.8.7\n", b""
            )
        assert argv[1] == "exec"
        schema_path = Path(argv[argv.index("--output-schema") + 1])
        self.calls[-1]["schema"] = json.loads(schema_path.read_text())
        if self.write_result:
            output_path = Path(argv[argv.index("--output-last-message") + 1])
            output_path.write_text(json.dumps(self.generated))
        return subprocess.CompletedProcess(argv, self.exec_returncode, self.jsonl, b"private")


def _install_fake(
    provider: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    fake: _FakeCodex,
) -> None:
    monkeypatch.setattr(provider, "_run_command", fake)
    monkeypatch.setattr(provider.shutil, "which", lambda name: f"/usr/bin/{name}")


def _run_main(
    provider: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    message: dict[str, Any],
) -> int:
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(message)))
    return provider.main()


def test_success_is_one_digest_bound_object_and_codex_jsonl_is_not_forwarded(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    provider = _provider_module()
    generated = {
        "files": [
            {
                "path": "product.py",
                "content": "def health():\n    return {'status': 'ok'}\n",
            }
        ]
    }
    fake = _FakeCodex(generated)
    _install_fake(provider, monkeypatch, fake)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-child")
    monkeypatch.setenv("CODEX_API_KEY", "must-not-reach-child")
    monkeypatch.setenv("CODEX_HOME", "/host/codex-home")

    assert _run_main(provider, monkeypatch, _message()) == 0

    captured = capsys.readouterr()
    response = json.loads(captured.out)
    assert captured.err == ""
    assert captured.out.count("request_digest") == 1
    assert '"type":"turn.completed"' not in captured.out
    assert response["request_digest"] == _message()["request"]["request_digest"]
    assert isinstance(response["files"], dict)
    assert response["files"]["product.py"].endswith("{'status': 'ok'}\n")
    assert response["provider_metadata"] == {
        "auth_mode": "chatgpt",
        "cli_version": "codex-cli_9.8.7",
        "model": "gpt-5.6-sol",
        "prompt_version": "pmpe-barebones-codex-cli-v1;effort=xhigh;cli=codex-cli_9.8.7",
        "provider": "codex-cli-chatgpt",
        "reasoning_effort": "xhigh",
    }

    assert [call["argv"][1:] for call in fake.calls[:2]] == [
        ("login", "status"),
        ("--version",),
    ]
    exec_call = fake.calls[2]
    argv = exec_call["argv"]
    assert argv[1] == "exec"
    assert "--ephemeral" in argv
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in argv
    assert "--ignore-rules" in argv
    assert "--skip-git-repo-check" in argv
    assert argv[argv.index("--model") + 1] == "gpt-5.6-sol"
    assert 'model_reasoning_effort="xhigh"' in argv
    assert 'forced_login_method="chatgpt"' in argv
    assert 'web_search="disabled"' in argv
    assert argv[-1] == "-"
    assert "PMOS-E1" not in " ".join(argv)
    assert b"PMOS-E1" in exec_call["input"]
    assert exec_call["schema"]["properties"]["files"]["type"] == "array"
    assert exec_call["schema"]["additionalProperties"] is False
    assert exec_call["cwd"].name.startswith("pmpe-codex-provider-")
    assert "OPENAI_API_KEY" not in exec_call["environment"]
    assert "CODEX_API_KEY" not in exec_call["environment"]
    assert exec_call["environment"]["CODEX_HOME"] == "/host/codex-home"


def test_usage_keeps_output_only_and_preserves_cached_and_reasoning_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider_module()
    fake = _FakeCodex()
    _install_fake(provider, monkeypatch, fake)

    response = provider._invoke(_message(), "/usr/bin/codex")

    assert response["usage"] == {
        "input_tokens": 100,
        "cached_input_tokens": 40,
        "output_tokens": 20,
        "reasoning_output_tokens": 7,
        "telemetry_status": "reported",
        "pricing": {
            "source": "chatgpt_subscription",
            "per_run_cost_applicable": False,
        },
    }


@pytest.mark.parametrize("jsonl", [b"", b'{"type":"turn.completed","usage":'])
def test_missing_or_truncated_telemetry_does_not_fail_a_valid_result(
    monkeypatch: pytest.MonkeyPatch, jsonl: bytes
) -> None:
    provider = _provider_module()
    fake = _FakeCodex(jsonl=jsonl)
    _install_fake(provider, monkeypatch, fake)

    response = provider._invoke(_message(), "/usr/bin/codex")

    assert response["files"] == {}
    assert response["usage"] == {
        "input_tokens": 0,
        "output_tokens": 0,
        "telemetry_status": "unavailable",
        "pricing": {
            "source": "chatgpt_subscription",
            "per_run_cost_applicable": False,
        },
    }


def test_advisory_uses_its_own_schema_and_remains_digest_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider_module()
    fake = _FakeCodex({"summary": "Checks passed; a human may inspect the candidate."})
    _install_fake(provider, monkeypatch, fake)

    response = provider._invoke(_message("advisory_review"), "/usr/bin/codex")

    assert response["summary"].startswith("Checks passed")
    exec_argv = fake.calls[2]["argv"]
    schema_path = Path(exec_argv[exec_argv.index("--output-schema") + 1])
    assert schema_path.name == "output-schema.json"
    assert fake.calls[2]["schema"]["required"] == ["summary"]
    assert b"non-blocking human advisory summary" in fake.calls[2]["input"]


def test_cli_version_is_recorded_but_not_a_run_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider_module()
    fake = _FakeCodex(version_returncode=1)
    _install_fake(provider, monkeypatch, fake)

    response = provider._invoke(_message(), "/usr/bin/codex")

    assert response["provider_metadata"]["cli_version"] == "unknown"
    assert response["provider_metadata"]["prompt_version"].endswith("cli=unknown")


@pytest.mark.parametrize(
    "auth",
    [b"Logged in using API key\n", b"Not logged in\n", b""],
)
def test_non_chatgpt_auth_fails_before_version_or_exec(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    auth: bytes,
) -> None:
    provider = _provider_module()
    fake = _FakeCodex(auth=auth)
    _install_fake(provider, monkeypatch, fake)

    with pytest.raises(SystemExit, match="2"):
        _run_main(provider, monkeypatch, _message())

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "CODEX_CHATGPT_AUTH_REQUIRED\n"
    assert len(fake.calls) == 1
    assert fake.calls[0]["argv"][1:] == ("login", "status")


def test_missing_cli_fails_with_empty_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    provider = _provider_module()
    monkeypatch.setattr(provider.shutil, "which", lambda _name: None)

    with pytest.raises(SystemExit, match="2"):
        _run_main(provider, monkeypatch, _message())

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "CODEX_CLI_NOT_FOUND\n"


def test_nonzero_exec_does_not_echo_private_codex_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    provider = _provider_module()
    fake = _FakeCodex(exec_returncode=1, jsonl=b"private progress and content")
    _install_fake(provider, monkeypatch, fake)

    with pytest.raises(SystemExit, match="2"):
        _run_main(provider, monkeypatch, _message())

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "CODEX_EXEC_FAILED\n"
    assert "private" not in captured.err


@pytest.mark.parametrize(
    ("generated", "purpose"),
    [({"files": "not-a-list"}, "code"), ({"summary": 42}, "advisory_review")],
)
def test_malformed_structured_result_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    generated: dict[str, Any],
    purpose: str,
) -> None:
    provider = _provider_module()
    fake = _FakeCodex(generated)
    _install_fake(provider, monkeypatch, fake)

    with pytest.raises(SystemExit, match="2"):
        _run_main(provider, monkeypatch, _message(purpose))

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "CODEX_RESULT_MALFORMED\n"


def test_missing_result_file_fails_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    provider = _provider_module()
    fake = _FakeCodex(write_result=False)
    _install_fake(provider, monkeypatch, fake)

    with pytest.raises(SystemExit, match="2"):
        _run_main(provider, monkeypatch, _message())

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "CODEX_RESULT_MISSING\n"


def test_missing_request_digest_fails_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    provider = _provider_module()
    fake = _FakeCodex()
    _install_fake(provider, monkeypatch, fake)
    message = _message()
    del message["request"]["request_digest"]

    with pytest.raises(SystemExit, match="2"):
        _run_main(provider, monkeypatch, message)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "CODEX_REQUEST_DIGEST_MISSING\n"


def test_unsupported_purpose_fails_before_auth(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    provider = _provider_module()
    fake = _FakeCodex()
    _install_fake(provider, monkeypatch, fake)

    with pytest.raises(SystemExit, match="2"):
        _run_main(provider, monkeypatch, _message("deployment"))

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "CODEX_UNSUPPORTED_PURPOSE\n"
    assert fake.calls == []


def test_result_output_limit_is_enforced(tmp_path: Path) -> None:
    provider = _provider_module()
    result = tmp_path / "result.json"
    result.write_bytes(b"x" * (provider._OUTPUT_LIMIT_BYTES + 1))

    with pytest.raises(provider.ProviderFailure, match="CODEX_RESULT_OUTPUT_LIMIT"):
        provider._load_result(result)


def test_command_timeout_kills_the_process_group(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _provider_module()

    class _TimedOutProcess:
        pid = 1234
        returncode = -9

        def __init__(self) -> None:
            self.calls = 0

        def communicate(
            self, *, input: bytes | None = None, timeout: float | None = None
        ) -> None:
            del input, timeout
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired(("codex", "exec"), 1)

    process = _TimedOutProcess()
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(provider.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(provider.os, "killpg", lambda pid, sig: killed.append((pid, sig)))

    with pytest.raises(provider.ProviderFailure, match="CODEX_EXEC_TIMEOUT"):
        provider._run_command(
            ("codex", "exec"),
            input_bytes=b"prompt",
            cwd=tmp_path,
            environment={},
        )

    assert killed == [(1234, provider.signal.SIGKILL)]


def test_command_output_limit_is_enforced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _provider_module()

    class _LargeOutputProcess:
        pid = 1234
        returncode = 0

        def communicate(
            self, *, input: bytes | None = None, timeout: float | None = None
        ) -> None:
            del input, timeout

    def fake_popen(*_args: Any, **kwargs: Any) -> _LargeOutputProcess:
        kwargs["stdout"].write(b"x" * (provider._OUTPUT_LIMIT_BYTES + 1))
        return _LargeOutputProcess()

    monkeypatch.setattr(provider.subprocess, "Popen", fake_popen)

    with pytest.raises(provider.ProviderFailure, match="CODEX_EXEC_OUTPUT_LIMIT"):
        provider._run_command(
            ("codex", "exec"),
            input_bytes=b"prompt",
            cwd=tmp_path,
            environment={},
        )
