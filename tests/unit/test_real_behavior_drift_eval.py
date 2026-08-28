from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pmpe.evals import real_behavior_drift_eval as drift_eval


def test_real_matrix_has_repeats_prompt_change_and_distinct_contract() -> None:
    assert len(drift_eval.RUNS) == 7
    assert {item.contract for item in drift_eval.RUNS} == {
        "examples/barebones/e1-contract.json",
        "examples/barebones/readiness-contract.json",
    }
    assert [item.prompt_profile for item in drift_eval.RUNS].count("drift-eval-v2") == 1
    assert ("e1-v1-01", "readiness-v1-01", 3) in drift_eval.COMPARISONS


def test_preflight_children_receive_only_the_sanitized_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "paid-openai-key")
    monkeypatch.setenv("CODEX_API_KEY", "paid-codex-key")
    monkeypatch.setenv("PMPE_CODEX_PROMPT_PROFILE", "unreviewed")
    environment = drift_eval._sanitized_environment()
    observed: list[dict[str, str]] = []

    class MountedProc:
        @staticmethod
        def is_file() -> bool:
            return True

    def checked_output(argv: list[str], *, environment: dict[str, str], timeout: int = 30) -> str:
        del timeout
        observed.append(environment)
        return "Logged in using ChatGPT" if argv[1:] == ["login", "status"] else ""

    def resolve_command(command: str, path: str | None = None) -> str:
        assert path == environment.get("PATH")
        return f"/usr/bin/{command}"

    monkeypatch.setattr(drift_eval, "Path", lambda _value: MountedProc())
    monkeypatch.setattr(drift_eval.shutil, "which", resolve_command)
    monkeypatch.setattr(drift_eval, "_checked_output", checked_output)

    drift_eval._preflight(environment)

    assert observed
    assert all(
        all(
            name not in child
            for name in (*drift_eval.PAID_API_ENVIRONMENT, "PMPE_CODEX_PROMPT_PROFILE")
        )
        for child in observed
    )


def test_pmpe_command_binds_the_active_interpreter_to_this_checkout() -> None:
    command = drift_eval._pmpe_command()

    assert command[:3] == [drift_eval.sys.executable, "-I", "-c"]
    assert str(drift_eval.ROOT / "src") in command[3]
    output = drift_eval._checked_output(
        [*command, "--help"],
        environment=drift_eval._sanitized_environment(),
    )
    assert "usage: pmpe" in output


def test_pmpe_command_can_bind_an_immutable_source_snapshot(tmp_path: Path) -> None:
    command = drift_eval._pmpe_command(tmp_path / "source-snapshot")

    assert str(tmp_path / "source-snapshot" / "src") in command[3]


def test_source_snapshot_is_the_captured_git_tree_and_read_only(tmp_path: Path) -> None:
    environment = drift_eval._sanitized_environment()
    git_executable = shutil.which("git", path=environment.get("PATH"))
    assert git_executable is not None
    git_head = drift_eval._checked_output(
        [git_executable, "rev-parse", "HEAD"],
        environment=environment,
    )
    destination = tmp_path / "source-snapshot"

    try:
        identity = drift_eval._materialize_source_snapshot(
            destination,
            git_executable=git_executable,
            git_head=git_head,
            environment=environment,
        )

        provider = destination / "examples/barebones/codex-cli-provider.py"
        assert identity == {
            "archive_digest": identity["archive_digest"],
            "git_head": git_head,
            "provider_digest": "sha256:" + drift_eval._sha256(provider),
            "tree_digest": drift_eval._snapshot_tree_digest(destination),
        }
        assert identity["archive_digest"].startswith("sha256:")
        assert len(identity["archive_digest"]) == len("sha256:") + 64
        assert not (destination / ".git").exists()
        assert provider.stat().st_mode & 0o222 == 0
        assert destination.stat().st_mode & 0o222 == 0
    finally:
        if destination.exists():
            for path in sorted(destination.rglob("*"), key=lambda item: len(item.parts)):
                if not path.is_symlink():
                    path.chmod(0o755 if path.is_dir() else 0o644)
            destination.chmod(0o755)


def test_snapshot_command_uses_read_only_mount_and_rechecks_the_tree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_checkout = tmp_path / "source-snapshot"
    source_checkout.mkdir()
    source_directory = source_checkout / "package"
    source_directory.mkdir()
    source_file = source_directory / "source.py"
    source_file.write_text("VALUE = 1\n")
    source_file.chmod(0o440)
    source_directory.chmod(0o550)
    source_checkout.chmod(0o555)
    tree_digest = drift_eval._snapshot_tree_digest(source_checkout)

    def command(
        argv: list[str],
        *,
        environment: dict[str, str],
        pass_fds: tuple[int, ...],
        timeout: int,
        cwd: Path,
    ) -> tuple[int, str]:
        assert len(pass_fds) == 1
        descriptor = pass_fds[0]
        assert os.pread(descriptor, 64, 0) == b"VALUE = 1\n"
        with pytest.raises(OSError):
            os.pwrite(descriptor, b"tampered", 0)
        assert argv == [
            "/usr/bin/bwrap",
            "--die-with-parent",
            "--bind",
            "/",
            "/",
            "--perms",
            "0555",
            "--tmpfs",
            str(source_checkout),
            "--perms",
            "0550",
            "--dir",
            str(source_directory),
            "--perms",
            "0440",
            "--file",
            str(descriptor),
            str(source_file),
            "--remount-ro",
            str(source_checkout),
            "--chdir",
            str(source_checkout),
            "--",
            "/bin/true",
        ]
        assert environment == {"PATH": "/trusted"}
        assert timeout == 60
        assert cwd == source_checkout
        return 0, ""

    monkeypatch.setattr(drift_eval, "_command", command)

    try:
        result = drift_eval._snapshot_command(
            ["/bin/true"],
            bwrap_executable="/usr/bin/bwrap",
            environment={"PATH": "/trusted"},
            expected_tree_digest=tree_digest,
            source_checkout=source_checkout,
            timeout=60,
        )

        assert result == (0, "")
    finally:
        source_checkout.chmod(0o755)
        source_directory.chmod(0o755)
        source_file.chmod(0o644)


def test_snapshot_command_detects_owner_mutation_after_the_child(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_checkout = tmp_path / "source-snapshot"
    source_checkout.mkdir()
    source_file = source_checkout / "source.py"
    source_file.write_text("VALUE = 1\n")
    source_file.chmod(0o444)
    source_checkout.chmod(0o555)
    tree_digest = drift_eval._snapshot_tree_digest(source_checkout)

    def command(
        _argv: list[str],
        *,
        environment: dict[str, str],
        pass_fds: tuple[int, ...],
        timeout: int,
        cwd: Path,
    ) -> tuple[int, str]:
        del environment, pass_fds, timeout, cwd
        source_file.chmod(0o644)
        source_file.write_text("VALUE = 2\n")
        return 0, ""

    monkeypatch.setattr(drift_eval, "_command", command)

    try:
        with pytest.raises(RuntimeError, match="source snapshot changed"):
            drift_eval._snapshot_command(
                ["/bin/true"],
                bwrap_executable="/usr/bin/bwrap",
                environment={"PATH": "/trusted"},
                expected_tree_digest=tree_digest,
                source_checkout=source_checkout,
                timeout=60,
            )
    finally:
        source_checkout.chmod(0o755)
        source_file.chmod(0o644)


def test_run_wrapper_timeout_covers_the_complete_model_call_budget() -> None:
    provider_timeout = 960

    wrapper_timeout = drift_eval._run_wrapper_timeout(provider_timeout)

    assert wrapper_timeout > provider_timeout * drift_eval.BudgetCaps().max_model_calls


def test_output_directory_must_be_outside_the_source_checkout(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outside the source checkout"):
        drift_eval._validate_output_path(drift_eval.ROOT / "generated-evidence")

    drift_eval._validate_output_path(tmp_path / "generated-evidence")


def _passing_results() -> tuple[
    list[dict[str, object]], list[dict[str, object]], dict[str, object]
]:
    runs: list[dict[str, object]] = [
        {"exit_code": 0, "result": {"state": "RELEASE_READY", "cause": "PASS"}}
        for _ in drift_eval.RUNS
    ]
    comparisons: list[dict[str, object]] = []
    for baseline, current, expected in drift_eval.COMPARISONS:
        name = f"{baseline}--{current}"
        baseline_behavior = {
            "provider": "codex-cli-chatgpt",
            "model": "gpt-example",
            "prompt_version": "prompt-v1",
            "cli_version": "codex-cli_1.0.0",
        }
        current_behavior = dict(baseline_behavior)
        if name == drift_eval.PLANTED_COMPARISON:
            current_behavior["prompt_version"] = "prompt-v2"
        result = (
            {
                "status": "COMPARABLE",
                "plan_repeatable": True,
                "baseline": {"provider_behavior": baseline_behavior},
                "current": {"provider_behavior": current_behavior},
                "behavior_drift": {
                    "detected": True,
                    "attribution": (
                        ["prompt_version"] if name == drift_eval.PLANTED_COMPARISON else []
                    ),
                },
            }
            if expected == 0
            else {"status": "NOT_COMPARABLE", "cause": "CONTRACT_CHANGED"}
        )
        comparisons.append(
            {
                "name": name,
                "exit_code": expected,
                "expected_exit_code": expected,
                "result": result,
            }
        )
    planted_behavior: dict[str, object] = {
        "baseline_exit_code": 0,
        "baseline_run_id": drift_eval.PLANTED_BASELINE_RUN_ID,
        "baseline_selected_file_digest": "sha256:" + "b" * 64,
        "baseline_observed": False,
        "exit_code": 0,
        "run_id": drift_eval.PLANTED_RUN_ID,
        "file": drift_eval.PLANTED_FILE,
        "selected_file_digest": "sha256:" + "a" * 64,
        "constant": drift_eval.PLANTED_CONSTANT,
        "expected_value": drift_eval.PLANTED_VALUE,
        "observed": True,
    }
    return runs, comparisons, planted_behavior


def test_gate_requires_real_prompt_version_drift_attribution() -> None:
    runs, comparisons, planted_behavior = _passing_results()

    assert drift_eval._gate_passes(runs, comparisons, planted_behavior) is True
    version_change = comparisons[2]["result"]
    assert isinstance(version_change, dict)
    behavior_drift = version_change["behavior_drift"]
    assert isinstance(behavior_drift, dict)
    behavior_drift["attribution"] = []
    assert drift_eval._gate_passes(runs, comparisons, planted_behavior) is False


def test_gate_rejects_prompt_drift_confounded_by_cli_change() -> None:
    runs, comparisons, planted_behavior = _passing_results()
    version_change = comparisons[2]["result"]
    assert isinstance(version_change, dict)
    behavior_drift = version_change["behavior_drift"]
    assert isinstance(behavior_drift, dict)
    behavior_drift["attribution"] = ["prompt_version", "cli_version"]

    assert drift_eval._gate_passes(runs, comparisons, planted_behavior) is False


def test_gate_rejects_configuration_drift_in_control_repeats() -> None:
    runs, comparisons, planted_behavior = _passing_results()
    control = comparisons[0]["result"]
    assert isinstance(control, dict)
    behavior_drift = control["behavior_drift"]
    assert isinstance(behavior_drift, dict)
    behavior_drift["attribution"] = ["cli_version"]

    assert drift_eval._gate_passes(runs, comparisons, planted_behavior) is False
    behavior_drift["attribution"] = []
    assert drift_eval._gate_passes(runs, comparisons, planted_behavior) is True
    behavior_drift["detected"] = False
    current = control["current"]
    assert isinstance(current, dict)
    current_behavior = current["provider_behavior"]
    assert isinstance(current_behavior, dict)
    current_behavior["cli_version"] = "codex-cli_2.0.0"
    assert drift_eval._gate_passes(runs, comparisons, planted_behavior) is False


@pytest.mark.parametrize(
    "content",
    [
        "PMPE_PROMPT_PROFILE = 'wrong'\n",
        "# PMPE_PROMPT_PROFILE = 'drift-eval-v2'\n",
        "OTHER = 'drift-eval-v2'\n",
        ("PMPE_PROMPT_PROFILE = 'drift-eval-v2'\nPMPE_PROMPT_PROFILE = 'replacement'\n"),
        "def broken(:\n",
    ],
)
def test_planted_behavior_requires_one_exact_top_level_constant(content: str) -> None:
    assert drift_eval._has_exact_planted_constant(content) is False


def test_planted_behavior_accepts_the_exact_top_level_constant() -> None:
    content = "PMPE_PROMPT_PROFILE = 'drift-eval-v2'\n"

    assert drift_eval._has_exact_planted_constant(content) is True


def test_planted_behavior_is_read_from_both_sealed_candidates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []

    source_checkout = tmp_path / "source-snapshot"

    def command(
        argv: list[str],
        *,
        bwrap_executable: str,
        environment: dict[str, str],
        expected_tree_digest: str,
        source_checkout: Path,
        timeout: int,
    ) -> tuple[int, str]:
        assert bwrap_executable == "/usr/bin/bwrap"
        assert environment == {"PATH": "/trusted"}
        assert expected_tree_digest == "sha256:trusted"
        assert timeout == 60
        assert source_checkout == expected_source_checkout
        calls.append(argv)
        run_id = argv[argv.index("inspect") + 1]
        content = (
            "PMPE_PROMPT_PROFILE = 'drift-eval-v2'\n"
            if run_id == drift_eval.PLANTED_RUN_ID
            else "STATUS = 'ok'\n"
        )
        return 0, json.dumps(
            {
                "selected_file": {
                    "content": content,
                    "digest": "sha256:"
                    + ("a" if run_id == drift_eval.PLANTED_RUN_ID else "b") * 64,
                }
            }
        )

    expected_source_checkout = source_checkout
    monkeypatch.setattr(drift_eval, "_snapshot_command", command)

    result = drift_eval._inspect_planted_behavior(
        ["python", "-m", "pmpe"],
        tmp_path / "evidence",
        {"PATH": "/trusted"},
        bwrap_executable="/usr/bin/bwrap",
        expected_tree_digest="sha256:trusted",
        source_checkout=source_checkout,
    )

    assert result["baseline_observed"] is False
    assert result["observed"] is True
    assert [call[call.index("inspect") + 1] for call in calls] == [
        drift_eval.PLANTED_BASELINE_RUN_ID,
        drift_eval.PLANTED_RUN_ID,
    ]
    assert all("--workspace" not in call for call in calls)


def test_gate_rejects_unrelated_drift_when_planted_behavior_is_absent() -> None:
    runs, comparisons, planted_behavior = _passing_results()
    planted_behavior["observed"] = False

    assert drift_eval._gate_passes(runs, comparisons, planted_behavior) is False


def test_gate_rejects_a_marker_already_present_in_the_baseline() -> None:
    runs, comparisons, planted_behavior = _passing_results()
    planted_behavior["baseline_observed"] = True

    assert drift_eval._gate_passes(runs, comparisons, planted_behavior) is False


def test_documented_runner_loads_this_checkout_before_a_stale_install(tmp_path: Path) -> None:
    stale = tmp_path / "stale"
    (stale / "pmpe" / "evals").mkdir(parents=True)
    (stale / "pmpe" / "__init__.py").write_text("")
    (stale / "pmpe" / "evals" / "__init__.py").write_text("")
    (stale / "pmpe" / "evals" / "real_behavior_drift_eval.py").write_text(
        "raise RuntimeError('stale package imported')\n"
    )
    runner = drift_eval.ROOT / "examples/barebones/run_real_behavior_drift_eval.py"
    environment = {**os.environ, "PYTHONPATH": str(stale)}

    completed = subprocess.run(
        [sys.executable, str(runner), "--help"],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "real ChatGPT-authenticated #146 evidence matrix" in completed.stdout
    assert "stale package imported" not in completed.stderr


def test_source_reverification_rejects_mid_matrix_source_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = {
        "codex_version": "codex-cli 1.0.0",
        "git_head": "a" * 40,
        "git_status": "",
        "provider_digest": "sha256:" + "b" * 64,
        "python": "3.12.0",
    }
    observed = {**expected, "git_head": "c" * 40, "git_status": " M provider.py"}
    monkeypatch.setattr(drift_eval, "_source_identity", lambda _commands, _environment: observed)

    result = drift_eval._reverify_source_identity(expected, {}, {})

    assert result["status"] == "FAIL"
    assert result["changed_fields"] == ["git_head", "git_status"]


def test_gate_rejects_success_exit_without_complete_release_evidence() -> None:
    runs, comparisons, planted_behavior = _passing_results()

    runs[0]["result"] = {"state": "VALIDATED", "cause": "IN_PROGRESS"}
    assert drift_eval._gate_passes(runs, comparisons, planted_behavior) is False
    runs[0]["result"] = {"state": "RELEASE_READY", "cause": "PASS"}
    first_comparison = comparisons[0]["result"]
    assert isinstance(first_comparison, dict)
    first_comparison["plan_repeatable"] = False
    assert drift_eval._gate_passes(runs, comparisons, planted_behavior) is False
