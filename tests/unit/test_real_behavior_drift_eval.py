from __future__ import annotations

from pmpe.evals import real_behavior_drift_eval as drift_eval


def test_real_matrix_has_repeats_prompt_change_and_distinct_contract() -> None:
    assert len(drift_eval.RUNS) == 7
    assert {item.contract for item in drift_eval.RUNS} == {
        "examples/barebones/e1-contract.json",
        "examples/barebones/readiness-contract.json",
    }
    assert [item.prompt_profile for item in drift_eval.RUNS].count("drift-eval-v2") == 1
    assert ("e1-v1-01", "readiness-v1-01", 3) in drift_eval.COMPARISONS


def _passing_results() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    runs: list[dict[str, object]] = [
        {"exit_code": 0, "result": {"state": "RELEASE_READY", "cause": "PASS"}}
        for _ in drift_eval.RUNS
    ]
    comparisons: list[dict[str, object]] = [
        {
            "name": f"{baseline}--{current}",
            "exit_code": expected,
            "expected_exit_code": expected,
            "result": (
                {
                    "status": "COMPARABLE",
                    "plan_repeatable": True,
                    "behavior_drift": {
                        "detected": True,
                        "attribution": ["prompt_version"],
                    },
                }
                if expected == 0
                else {"status": "NOT_COMPARABLE", "cause": "CONTRACT_CHANGED"}
            ),
        }
        for baseline, current, expected in drift_eval.COMPARISONS
    ]
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


def test_gate_rejects_success_exit_without_complete_release_evidence() -> None:
    runs, comparisons = _passing_results()

    runs[0]["result"] = {"state": "VALIDATED", "cause": "IN_PROGRESS"}
    assert drift_eval._gate_passes(runs, comparisons) is False
    runs[0]["result"] = {"state": "RELEASE_READY", "cause": "PASS"}
    first_comparison = comparisons[0]["result"]
    assert isinstance(first_comparison, dict)
    first_comparison["plan_repeatable"] = False
    assert drift_eval._gate_passes(runs, comparisons) is False
