"""Run-wide resource guardrails for every model invocation.

These rules account for reported provider usage, including replies that fail
the response binding or candidate schema checks. There is no replay/resume
claim: counters live for one admitted run only.
"""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from typing import Any

_MAX_SAFE_JSON_INTEGER = (1 << 53) - 1


class ResourceBudgetError(RuntimeError):
    """A named, operator-configured resource rule halted the current run."""

    def __init__(self, cause: str, rule_id: str) -> None:
        super().__init__(cause)
        self.rule_id = rule_id


def validate_resource_caps(
    *, max_wall_time_seconds: float, max_input_tokens: int | None, max_output_tokens: int | None
) -> None:
    try:
        valid_wall_time = (
            not isinstance(max_wall_time_seconds, bool)
            and isinstance(max_wall_time_seconds, (int, float))
            and math.isfinite(max_wall_time_seconds)
            and max_wall_time_seconds > 0
        )
    except OverflowError:
        valid_wall_time = False
    if not valid_wall_time:
        raise ValueError("resource budget wall time must be finite and positive")
    for name, cap in (("input tokens", max_input_tokens), ("output tokens", max_output_tokens)):
        if cap is not None and (
            not isinstance(cap, int)
            or isinstance(cap, bool)
            or not 0 < cap <= _MAX_SAFE_JSON_INTEGER
        ):
            raise ValueError(f"resource budget {name} must be a positive safe integer")


def check_wall_time(started: float, max_wall_time_seconds: float) -> None:
    # BUD-001: a run cannot begin more work after its monotonic wall clock cap.
    if time.monotonic() - started >= max_wall_time_seconds:
        raise ResourceBudgetError("RUN_WALL_TIME_BUDGET_EXHAUSTED", "BUD-001")


def capture_provider_usage(
    response: Mapping[str, Any],
    counters: dict[str, Any],
    *,
    max_input_tokens: int | None,
    max_output_tokens: int | None,
) -> None:
    """Validate one provider report, then charge actual use before other response checks."""
    usage = response.get("usage")
    if not isinstance(usage, Mapping):
        if max_input_tokens is not None or max_output_tokens is not None:
            # BUD-004: a configured token cap requires provider usage evidence.
            raise ResourceBudgetError("MODEL_PROVIDER_USAGE_MISSING", "BUD-004")
        return
    for key, cap in (("input_tokens", max_input_tokens), ("output_tokens", max_output_tokens)):
        if cap is not None and usage.get(key) is None:
            raise ResourceBudgetError("MODEL_PROVIDER_USAGE_MISSING", "BUD-004")

    updated: dict[str, int] = {}
    for source, target in (("input_tokens", "tokens_in"), ("output_tokens", "tokens_out")):
        value = usage.get(source)
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise RuntimeError("MODEL_PROVIDER_USAGE_INVALID")
        accumulated = counters[target] + value
        if accumulated > _MAX_SAFE_JSON_INTEGER:
            raise RuntimeError("MODEL_PROVIDER_USAGE_INVALID")
        updated[target] = accumulated

    # These reported counts are actual consumption even if ancillary cost
    # telemetry is malformed. Keep them in the terminal record on any error.
    counters.update(updated)
    if max_input_tokens is not None and counters["tokens_in"] > max_input_tokens:
        raise ResourceBudgetError("MODEL_INPUT_TOKEN_BUDGET_EXHAUSTED", "BUD-002")
    if max_output_tokens is not None and counters["tokens_out"] > max_output_tokens:
        raise ResourceBudgetError("MODEL_OUTPUT_TOKEN_BUDGET_EXHAUSTED", "BUD-003")

    estimated = usage.get("estimated_cost_usd")
    updated_cost: float | None = None
    if estimated is not None:
        if not isinstance(estimated, (int, float)) or isinstance(estimated, bool):
            raise RuntimeError("MODEL_PROVIDER_USAGE_INVALID")
        if isinstance(estimated, int) and abs(estimated) > _MAX_SAFE_JSON_INTEGER:
            raise RuntimeError("MODEL_PROVIDER_USAGE_INVALID")
        try:
            estimated_value = float(estimated)
        except (OverflowError, ValueError) as exc:
            raise RuntimeError("MODEL_PROVIDER_USAGE_INVALID") from exc
        if not math.isfinite(estimated_value) or estimated_value < 0:
            raise RuntimeError("MODEL_PROVIDER_USAGE_INVALID")
        updated_cost = counters["estimated_cost_usd"] + estimated_value
        if not math.isfinite(updated_cost):
            raise RuntimeError("MODEL_PROVIDER_USAGE_INVALID")

    if updated_cost is not None:
        counters["estimated_cost_usd"] = updated_cost


def reserve_provider_call(
    counters: Mapping[str, Any], *, max_input_tokens: int | None, max_output_tokens: int | None
) -> None:
    # A next call cannot be made with no reported token allowance left.
    if max_input_tokens is not None and counters["tokens_in"] >= max_input_tokens:
        raise ResourceBudgetError("MODEL_INPUT_TOKEN_BUDGET_EXHAUSTED", "BUD-002")
    if max_output_tokens is not None and counters["tokens_out"] >= max_output_tokens:
        raise ResourceBudgetError("MODEL_OUTPUT_TOKEN_BUDGET_EXHAUSTED", "BUD-003")
