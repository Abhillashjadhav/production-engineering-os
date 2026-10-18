from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from pmpe import barebones as barebones_runtime
from pmpe.barebones import (
    BudgetCaps,
    ContractInvalidError,
    RunState,
    _invoke_bound,
    run_to_release_ready,
)

_CONTRACT = Path(__file__).parents[2] / "examples/barebones/e1-contract.json"


def _counters() -> dict[str, Any]:
    return {
        "calls": 0,
        "bytes": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "estimated_cost_usd": 0.0,
        "provider_model_id": "",
    }


class _UsageProvider:
    def __init__(self, usage: Mapping[str, Any] | None, *, bound: bool = True) -> None:
        self.usage = usage
        self.bound = bound
        self.calls = 0

    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls += 1
        response: dict[str, Any] = {
            "request_digest": request["request_digest"] if self.bound else "wrong",
            "files": "malformed coder answer",
        }
        if self.usage is not None:
            response["usage"] = self.usage
        return response


@pytest.mark.parametrize(
    "budget",
    [
        BudgetCaps(max_wall_time_seconds=0),
        BudgetCaps(max_wall_time_seconds=float("nan")),
        BudgetCaps(max_wall_time_seconds=float("inf")),
        BudgetCaps(max_wall_time_seconds=10**400),
        BudgetCaps(max_input_tokens=0),
        BudgetCaps(max_input_tokens=True),
        BudgetCaps(max_output_tokens=-1),
        BudgetCaps(max_output_tokens=(1 << 53)),
    ],
)
def test_invalid_resource_cap_is_rejected_before_provider_and_workspace(
    tmp_path: Path, budget: BudgetCaps
) -> None:
    provider = _UsageProvider({"input_tokens": 1, "output_tokens": 1})
    with pytest.raises(ContractInvalidError, match="resource budget"):
        run_to_release_ready(
            contract=json.loads(_CONTRACT.read_text()),
            repository_root=tmp_path,
            workspace=tmp_path / "candidate",
            run_id="bad-budget",
            provider=provider,
            budget=budget,
        )
    assert provider.calls == 0
    assert not (tmp_path / "candidate").exists()


def test_token_caps_are_cumulative_across_provider_purposes_and_reserve_before_calls() -> None:
    provider = _UsageProvider({"input_tokens": 2, "output_tokens": 3})
    counters = _counters()
    budget = BudgetCaps(max_input_tokens=4, max_output_tokens=6)
    for purpose in ("code", "advisory_review"):
        _invoke_bound(
            provider,
            purpose=purpose,
            request={"request_digest": "bound"},
            budget=budget,
            counters=counters,
        )
    with pytest.raises(RuntimeError, match="MODEL_INPUT_TOKEN_BUDGET_EXHAUSTED"):
        _invoke_bound(
            provider,
            purpose="code",
            request={"request_digest": "bound"},
            budget=budget,
            counters=counters,
        )
    assert provider.calls == counters["calls"] == 2
    assert counters["tokens_in"] == 4
    assert counters["tokens_out"] == 6


@pytest.mark.parametrize(
    ("budget", "usage", "cause", "counter"),
    [
        (
            BudgetCaps(max_input_tokens=2),
            {"input_tokens": 3, "output_tokens": 1},
            "MODEL_INPUT_TOKEN_BUDGET_EXHAUSTED",
            "tokens_in",
        ),
        (
            BudgetCaps(max_output_tokens=2),
            {"input_tokens": 1, "output_tokens": 3},
            "MODEL_OUTPUT_TOKEN_BUDGET_EXHAUSTED",
            "tokens_out",
        ),
    ],
)
def test_overspend_is_charged_even_for_unbound_malformed_answer(
    budget: BudgetCaps, usage: Mapping[str, int], cause: str, counter: str
) -> None:
    provider = _UsageProvider(usage, bound=False)
    counters = _counters()
    with pytest.raises(RuntimeError, match=cause):
        _invoke_bound(
            provider,
            purpose="code",
            request={"request_digest": "bound"},
            budget=budget,
            counters=counters,
        )
    assert counters[counter] == 3
    assert counters["calls"] == 1


@pytest.mark.parametrize("usage", [None, {}, {"input_tokens": None}])
def test_missing_required_usage_fails_closed_even_for_malformed_answer(
    usage: Mapping[str, Any] | None,
) -> None:
    provider = _UsageProvider(usage)
    counters = _counters()
    with pytest.raises(RuntimeError, match="MODEL_PROVIDER_USAGE_MISSING"):
        _invoke_bound(
            provider,
            purpose="advisory_review",
            request={"request_digest": "bound"},
            budget=BudgetCaps(max_input_tokens=10),
            counters=counters,
        )
    assert counters["calls"] == 1
    assert counters["bytes"] > 0


def test_wall_clock_budget_checks_before_and_after_provider_invocation() -> None:
    provider = _UsageProvider({"input_tokens": 1, "output_tokens": 1})
    counters = _counters()
    with pytest.raises(RuntimeError, match="RUN_WALL_TIME_BUDGET_EXHAUSTED"):
        _invoke_bound(
            provider,
            purpose="code",
            request={"request_digest": "bound"},
            budget=BudgetCaps(max_wall_time_seconds=0.1),
            counters=counters,
            started=time.monotonic() - 1,
        )
    assert provider.calls == counters["calls"] == 0

    class SlowProvider(_UsageProvider):
        def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
            time.sleep(0.02)
            return super().invoke(purpose=purpose, request=request)

    slow = SlowProvider({"input_tokens": 1, "output_tokens": 1})
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="RUN_WALL_TIME_BUDGET_EXHAUSTED"):
        _invoke_bound(
            slow,
            purpose="code",
            request={"request_digest": "bound"},
            budget=BudgetCaps(max_wall_time_seconds=0.01),
            counters=counters,
            started=started,
        )
    assert slow.calls == counters["calls"] == 1
    assert counters["tokens_in"] == counters["tokens_out"] == 1


def test_run_persists_actual_overspend_in_terminal_telemetry(tmp_path: Path) -> None:
    class BaselineSandbox:
        def run(self, *_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess([], 0, '{"status":"not-ready"}', "")

    provider = _UsageProvider({"input_tokens": 3, "output_tokens": 1})
    result = run_to_release_ready(
        contract=json.loads(_CONTRACT.read_text()),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="token-exhausted",
        provider=provider,
        budget=BudgetCaps(max_input_tokens=2),
        candidate_sandbox=BaselineSandbox(),
    )
    assert result.state is RunState.HALTED
    assert result.cause == "MODEL_INPUT_TOKEN_BUDGET_EXHAUSTED"
    assert result.model_calls == 1
    assert result.telemetry["tokens_in"] == 3
    final_event = json.loads(result.evidence_path.read_text().splitlines()[-1])
    assert final_event["payload"]["cause"] == result.cause
    assert final_event["payload"]["rule_id"] == "BUD-002"
    assert final_event["payload"]["telemetry"]["tokens_in"] == 3


def test_invalid_ancillary_cost_preserves_known_actual_token_spend() -> None:
    provider = _UsageProvider({"input_tokens": 7, "output_tokens": 3, "estimated_cost_usd": "bad"})
    counters = _counters()
    with pytest.raises(RuntimeError, match="MODEL_PROVIDER_USAGE_INVALID"):
        _invoke_bound(
            provider,
            purpose="code",
            request={"request_digest": "bound"},
            budget=BudgetCaps(max_input_tokens=10, max_output_tokens=10),
            counters=counters,
        )
    assert counters["calls"] == 1
    assert counters["tokens_in"] == 7
    assert counters["tokens_out"] == 3
    assert counters["estimated_cost_usd"] == 0.0


def test_compile_time_exhaustion_halts_before_baseline_files_or_observer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_compile = barebones_runtime.compile_barebones_plan

    def slow_compile(**kwargs: Any) -> Any:
        compiled = original_compile(**kwargs)
        time.sleep(0.02)
        return compiled

    class BaselineMustNotRun:
        def run(self, *_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("baseline must not run after budget expires")

    monkeypatch.setattr(barebones_runtime, "compile_barebones_plan", slow_compile)
    provider = _UsageProvider({"input_tokens": 1, "output_tokens": 1})
    result = run_to_release_ready(
        contract=json.loads(_CONTRACT.read_text()),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="compile-time-exhausted",
        provider=provider,
        budget=BudgetCaps(max_wall_time_seconds=0.005),
        candidate_sandbox=BaselineMustNotRun(),
    )
    assert result.state is RunState.HALTED
    assert result.cause == "RUN_WALL_TIME_BUDGET_EXHAUSTED"
    assert result.annotation["rule_id"] == "BUD-001"
    assert result.model_calls == provider.calls == 0
    assert not (tmp_path / "candidate" / "product.py").exists()
