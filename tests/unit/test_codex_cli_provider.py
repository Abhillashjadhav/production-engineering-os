from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import time
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

    @staticmethod
    def _completed(
        argv: tuple[str, ...], returncode: int, stdout: bytes, stderr: bytes
    ) -> subprocess.CompletedProcess[bytes]:
        completed = subprocess.CompletedProcess(argv, returncode, stdout, stderr)
        completed.stdout_truncated = False  # type: ignore[attr-defined]
        completed.stderr_truncated = False  # type: ignore[attr-defined]
        return completed

    def __call__(
        self,
        argv: tuple[str, ...],
        *,
        input_bytes: bytes,
        cwd: Path,
        environment: dict[str, str],
        timeout_seconds: float | None = None,
        output_limit_bytes: int | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        self.calls.append(
            {
                "argv": argv,
                "input": input_bytes,
                "cwd": cwd,
                "environment": environment,
                "timeout_seconds": timeout_seconds,
                "output_limit_bytes": output_limit_bytes,
            }
        )
        if argv[1:] == ("login", "status"):
            return self._completed(argv, 0, self.auth, b"")
        if argv[1:] == ("--version",):
            return self._completed(argv, self.version_returncode, b"codex-cli 9.8.7\n", b"")
        assert argv[1] == "exec"
        schema_path = Path(argv[argv.index("--output-schema") + 1])
        self.calls[-1]["schema"] = json.loads(schema_path.read_text())
        if self.write_result:
            output_path = Path(argv[argv.index("--output-last-message") + 1])
            output_path.write_text(json.dumps(self.generated))
        return self._completed(argv, self.exec_returncode, self.jsonl, b"private")


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
        "prompt_version": "pmpe-barebones-codex-cli-v1;effort=xhigh",
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
    assert exec_call["timeout_seconds"] == 900.0
    assert "OPENAI_API_KEY" not in exec_call["environment"]
    assert "CODEX_API_KEY" not in exec_call["environment"]
    assert exec_call["environment"]["CODEX_HOME"] == "/host/codex-home"


def test_codex_child_environment_is_an_explicit_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider_module()
    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin:/bin")
    monkeypatch.setenv("HOME", "/home/operator")
    monkeypatch.setenv("CODEX_HOME", "/home/operator/.codex")
    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-cross")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-cross")
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-cross")
    monkeypatch.setenv("PMPE_PLANTED_HOST_SECRET", "must-not-cross")

    environment = provider._child_environment()

    assert environment["CODEX_HOME"] == "/home/operator/.codex"
    assert environment["HOME"] == "/home/operator"
    assert environment["LANG"] == "C.UTF-8"
    assert environment["PATH"] == "/usr/local/bin:/usr/bin:/bin"
    assert set(environment).issubset(provider._CHILD_ENV_ALLOWLIST)
    for secret in (
        "OPENAI_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "GITHUB_TOKEN",
        "PMPE_PLANTED_HOST_SECRET",
    ):
        assert secret not in environment


def test_codex_timeout_override_is_clamped_below_the_outer_provider_budget() -> None:
    provider = _provider_module()

    assert (
        provider._effective_exec_timeout(
            {
                "PMPE_CODEX_TIMEOUT_SECONDS": "1200",
                "PMPE_PROVIDER_TIMEOUT_SECONDS": "960",
            }
        )
        == 959.0
    )
    assert provider._effective_exec_timeout({"PMPE_PROVIDER_TIMEOUT_SECONDS": "960"}) == 900.0


def test_invoke_deducts_elapsed_preflight_time_from_the_outer_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider_module()
    fake = _FakeCodex()
    _install_fake(provider, monkeypatch, fake)
    monkeypatch.setenv("PMPE_CODEX_TIMEOUT_SECONDS", "1200")
    monkeypatch.setenv("PMPE_PROVIDER_TIMEOUT_SECONDS", "960")
    moments = iter((100.0, 160.0))
    monkeypatch.setattr(provider.time, "monotonic", lambda: next(moments))

    provider._invoke(_message(), "/usr/bin/codex")

    assert fake.calls[2]["timeout_seconds"] == 899.0


@pytest.mark.parametrize(
    "environment",
    [
        {"PMPE_CODEX_TIMEOUT_SECONDS": "not-a-number"},
        {"PMPE_CODEX_TIMEOUT_SECONDS": "0"},
        {"PMPE_PROVIDER_TIMEOUT_SECONDS": "1"},
    ],
)
def test_invalid_codex_timeout_configuration_fails_closed(
    environment: dict[str, str],
) -> None:
    provider = _provider_module()

    with pytest.raises(provider.ProviderError, match="CODEX_TIMEOUT_INVALID"):
        provider._effective_exec_timeout(environment)


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


@pytest.mark.parametrize(
    ("oversized_stream", "expected_input_tokens"),
    [("stdout", 0), ("stderr", 100)],
)
def test_oversized_exec_telemetry_does_not_discard_a_valid_result(
    tmp_path: Path,
    oversized_stream: str,
    expected_input_tokens: int,
) -> None:
    provider = _provider_module()
    executable = tmp_path / "codex"
    executable.write_text(
        f"""#!{sys.executable}
import json
import sys
from pathlib import Path

arguments = sys.argv[1:]
if arguments == ["login", "status"]:
    print("Logged in using ChatGPT")
elif arguments == ["--version"]:
    print("codex-cli 9.8.7")
else:
    output = Path(arguments[arguments.index("--output-last-message") + 1])
    output.write_text(json.dumps({{"files": []}}))
    usage = (
        b'{{"type":"turn.completed","usage":{{"input_tokens":100,'
        b'"output_tokens":20}}}}\\n'
    )
    if {oversized_stream!r} == "stdout":
        sys.stdout.buffer.write(b"x" * ({provider._OUTPUT_LIMIT_BYTES} + 1))
    else:
        sys.stdout.buffer.write(usage)
        sys.stderr.buffer.write(b"x" * ({provider._OUTPUT_LIMIT_BYTES} + 1))
"""
    )
    executable.chmod(0o755)

    response = provider._invoke(_message(), str(executable))

    assert response["files"] == {}
    assert response["usage"]["telemetry_status"] == "truncated"
    assert response["usage"]["input_tokens"] == expected_input_tokens


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
    assert (
        response["provider_metadata"]["prompt_version"]
        == "pmpe-barebones-codex-cli-v1;effort=xhigh"
    )


def test_optional_cli_version_probe_does_not_change_prompt_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider_module()
    known = _FakeCodex()
    _install_fake(provider, monkeypatch, known)
    known_response = provider._invoke(_message(), "/usr/bin/codex")

    unknown = _FakeCodex(version_returncode=1)
    _install_fake(provider, monkeypatch, unknown)
    unknown_response = provider._invoke(_message(), "/usr/bin/codex")

    assert known_response["provider_metadata"]["cli_version"] == "codex-cli_9.8.7"
    assert unknown_response["provider_metadata"]["cli_version"] == "unknown"
    assert (
        known_response["provider_metadata"]["prompt_version"]
        == unknown_response["provider_metadata"]["prompt_version"]
    )


def test_planted_drift_profile_changes_prompt_and_records_exact_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider_module()
    fake = _FakeCodex()
    _install_fake(provider, monkeypatch, fake)
    monkeypatch.setenv("PMPE_CODEX_PROMPT_PROFILE", "drift-eval-v2")

    response = provider._invoke(_message(), "/usr/bin/codex")

    assert (
        response["provider_metadata"]["prompt_version"]
        == "pmpe-barebones-codex-cli-v1;profile=drift-eval-v2;effort=xhigh"
    )
    assert b"PMPE_PROMPT_PROFILE" in fake.calls[2]["input"]
    assert b"drift-eval-v2" in fake.calls[2]["input"]
    assert "PMPE_CODEX_PROMPT_PROFILE" not in fake.calls[2]["environment"]


def test_unknown_prompt_profile_fails_before_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider_module()
    fake = _FakeCodex()
    _install_fake(provider, monkeypatch, fake)
    monkeypatch.setenv("PMPE_CODEX_PROMPT_PROFILE", "unreviewed")

    with pytest.raises(provider.ProviderError, match="CODEX_PROMPT_PROFILE_INVALID"):
        provider._invoke(_message(), "/usr/bin/codex")

    assert fake.calls == []


def test_truncated_auth_preflight_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _provider_module()
    result = provider._CommandResult(
        ("/usr/bin/codex", "login", "status"),
        0,
        b"Logged in using ChatGPT\n",
        b"",
        True,
        False,
    )
    monkeypatch.setattr(provider, "_run_command", lambda *args, **kwargs: result)

    with pytest.raises(provider.ProviderError, match="CODEX_CHATGPT_AUTH_REQUIRED"):
        provider._auth_preflight("/usr/bin/codex", cwd=tmp_path, environment={})


def test_truncated_optional_version_probe_returns_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _provider_module()
    result = provider._CommandResult(
        ("/usr/bin/codex", "--version"),
        0,
        b"codex-cli 9.8.7\n",
        b"",
        True,
        False,
    )
    monkeypatch.setattr(provider, "_run_command", lambda *args, **kwargs: result)

    assert provider._cli_version("/usr/bin/codex", cwd=tmp_path, environment={}) == "unknown"


@pytest.mark.parametrize(
    "auth",
    [
        b"Logged in using API key\n",
        b"Not logged in to ChatGPT\n",
        b"Not logged in\n",
        b"",
    ],
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


def test_duplicate_generated_paths_fail_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    provider = _provider_module()
    fake = _FakeCodex(
        {
            "files": [
                {"path": "product.py", "content": "first\n"},
                {"path": "product.py", "content": "second\n"},
            ]
        }
    )
    _install_fake(provider, monkeypatch, fake)

    with pytest.raises(SystemExit, match="2"):
        _run_main(provider, monkeypatch, _message())

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

    with pytest.raises(provider.ProviderError, match="CODEX_RESULT_OUTPUT_LIMIT"):
        provider._load_result(result)


def test_command_timeout_kills_codex_without_creating_a_new_process_group(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _provider_module()
    real_popen = provider.subprocess.Popen
    observed: list[bool | None] = []

    def recording_popen(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        observed.append(kwargs.get("start_new_session"))
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(provider.subprocess, "Popen", recording_popen)
    started = time.monotonic()

    with pytest.raises(provider.ProviderError, match="CODEX_EXEC_TIMEOUT"):
        provider._run_command(
            (sys.executable, "-c", "import time; time.sleep(5)"),
            input_bytes=b"prompt",
            cwd=tmp_path,
            environment={},
            timeout_seconds=0.1,
        )

    assert time.monotonic() - started < 2
    assert observed == [False]


def test_command_output_is_bounded_while_codex_is_running(tmp_path: Path) -> None:
    provider = _provider_module()
    started = time.monotonic()

    completed = provider._run_command(
        (sys.executable, "-c", "import os; os.write(1, b'x' * 1024)"),
        input_bytes=b"prompt",
        cwd=tmp_path,
        environment={},
        timeout_seconds=2,
        output_limit_bytes=32,
    )

    assert time.monotonic() - started < 2
    assert completed.returncode == 0
    assert completed.stdout == b"x" * 32
    assert completed.stderr == b""
    assert completed.stdout_truncated is True
    assert completed.stderr_truncated is False
