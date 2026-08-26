from __future__ import annotations

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


def test_run_wrapper_timeout_covers_the_complete_model_call_budget() -> None:
    provider_timeout = 960

    wrapper_timeout = drift_eval._run_wrapper_timeout(provider_timeout)

    assert wrapper_timeout > provider_timeout * drift_eval.BudgetCaps().max_model_calls


def test_output_directory_must_be_outside_the_source_checkout(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outside the source checkout"):
        drift_eval._validate_output_path(drift_eval.ROOT / "generated-evidence")

    drift_eval._validate_output_path(tmp_path / "generated-evidence")


def _passing_results() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    runs: list[dict[str, object]] = [
        {"exit_code": 0, "result": {"state": "RELEASE_READY", "cause": "PASS"}}
        for _ in drift_eval.RUNS
    ]
    comparisons: list[dict[str, object]] = []
    for baseline, current, expected in drift_eval.COMPARISONS:
        name = f"{baseline}--{current}"
        result = (
            {
                "status": "COMPARABLE",
                "plan_repeatable": True,
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
    return runs, comparisons


def test_gate_requires_real_prompt_version_drift_attribution() -> None:
    runs, comparisons = _passing_results()

    assert drift_eval._gate_passes(runs, comparisons) is True
    version_change = comparisons[2]["result"]
    assert isinstance(version_change, dict)
    behavior_drift = version_change["behavior_drift"]
    assert isinstance(behavior_drift, dict)
    behavior_drift["attribution"] = []
    assert drift_eval._gate_passes(runs, comparisons) is False


def test_gate_rejects_prompt_drift_confounded_by_cli_change() -> None:
    runs, comparisons = _passing_results()
    version_change = comparisons[2]["result"]
    assert isinstance(version_change, dict)
    behavior_drift = version_change["behavior_drift"]
    assert isinstance(behavior_drift, dict)
    behavior_drift["attribution"] = ["prompt_version", "cli_version"]

    assert drift_eval._gate_passes(runs, comparisons) is False


def test_gate_rejects_configuration_drift_in_control_repeats() -> None:
    runs, comparisons = _passing_results()
    control = comparisons[0]["result"]
    assert isinstance(control, dict)
    behavior_drift = control["behavior_drift"]
    assert isinstance(behavior_drift, dict)
    behavior_drift["attribution"] = ["cli_version"]

    assert drift_eval._gate_passes(runs, comparisons) is False
    behavior_drift["attribution"] = []
    assert drift_eval._gate_passes(runs, comparisons) is True


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
    runs, comparisons = _passing_results()

    runs[0]["result"] = {"state": "VALIDATED", "cause": "IN_PROGRESS"}
    assert drift_eval._gate_passes(runs, comparisons) is False
    runs[0]["result"] = {"state": "RELEASE_READY", "cause": "PASS"}
    first_comparison = comparisons[0]["result"]
    assert isinstance(first_comparison, dict)
    first_comparison["plan_repeatable"] = False
    assert drift_eval._gate_passes(runs, comparisons) is False
