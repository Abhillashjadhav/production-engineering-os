"""Eval-run file format (v1) — typed, bounded, deterministic to parse.

One documented JSON format (PD-V3-12 excludes arbitrary spreadsheets): a run
carries identity (`run_id`, `suite`), optional metadata, `criteria` (with
`hard_gate` flags and optional `min_pass_rate` guardrails), and `traces` with
per-criterion pass/fail results. Parsing is strict and size-bounded; every
problem is reported as a named issue, never a stack trace.
"""

from __future__ import annotations

import json
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

FORMAT_VERSION = 1
MAX_CRITERIA = 200
MAX_TRACES = 5000


class Criterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    description: str = ""
    hard_gate: bool = False
    min_pass_rate: float | None = Field(default=None, ge=0.0, le=1.0)


class Trace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(min_length=1)
    label: str = ""
    results: dict[str, Literal["pass", "fail"]]
    notes: str = ""


class EvalRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_version: int
    run_id: str = Field(min_length=1)
    suite: str = Field(min_length=1)
    model: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    criteria: list[Criterion] = Field(min_length=1, max_length=MAX_CRITERIA)
    traces: list[Trace] = Field(min_length=1, max_length=MAX_TRACES)

    def criterion_ids(self) -> list[str]:
        return [c.id for c in self.criteria]

    def hard_gate_ids(self) -> list[str]:
        return [c.id for c in self.criteria if c.hard_gate]

    def trace_by_id(self) -> dict[str, Trace]:
        return {t.trace_id: t for t in self.traces}


class ParseIssue(BaseModel):
    """One named problem with an uploaded run file."""

    location: str
    message: str


class ParseResult(BaseModel):
    run: EvalRun | None = None
    issues: list[ParseIssue] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.run is not None and not self.issues


class _StrictJSONError(ValueError):
    """A structurally ambiguous or non-standard JSON construct that ``json.loads``
    accepts by default but this parser refuses: a duplicate object key (silent
    last-value-wins, which could hide an evidence flip) or a non-finite number
    (NaN/Infinity — non-standard and not deterministically re-serializable)."""


_MAX_JSON_NESTING = 512


def _exceeds_json_nesting_limit(raw: str | bytes) -> bool:
    """Detect pathological container nesting before runtime-specific JSON parsing.

    CPython's JSON decoder reaches its recursion guard at different depths across
    supported runtimes.  Scan only structural tokens outside strings so the same
    payload receives the same named malformed-input result everywhere.
    """
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return False
    else:
        text = raw

    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > _MAX_JSON_NESTING:
                return True
        elif character in "]}":
            depth = max(0, depth - 1)
    return False


def _clip(text: str, limit: int = 64) -> str:
    # Uploaded keys and numeric literals can be megabytes long (bounded only by
    # the upload cap); never echo an unbounded slice of the payload back in an
    # error message.
    return text if len(text) <= limit else text[:limit] + "…"


def _reject_non_finite(token: str) -> Any:
    # parse_constant is called only for the bare tokens NaN / Infinity / -Infinity.
    raise _StrictJSONError(f"non-finite number {token} is not allowed")


def _finite_float(token: str) -> float:
    # parse_float handles ordinary numeric literals — including ones like 1e400
    # that overflow to inf without ever reaching parse_constant. Reject any that
    # is not finite so the non-finite guarantee covers the overflow path too.
    value = float(token)
    if not math.isfinite(value):
        raise _StrictJSONError(f"non-finite number {_clip(token)} is not allowed")
    return value


def _forbid_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    # object_pairs_hook fires for every object at every depth, before the
    # last-value-wins collapse, so a repeated key is caught wherever it appears.
    seen: set[str] = set()
    for key, _ in pairs:
        if key in seen:
            raise _StrictJSONError(f"duplicate key {_clip(repr(key))} in a JSON object")
        seen.add(key)
    return dict(pairs)


def parse_run(raw: str | bytes, *, source_name: str = "upload") -> ParseResult:
    """Parse one run file. Never raises on bad input — returns named issues."""
    if _exceeds_json_nesting_limit(raw):
        return ParseResult(
            issues=[
                ParseIssue(
                    location=source_name,
                    message=f"not valid JSON: nesting exceeds {_MAX_JSON_NESTING} levels",
                )
            ]
        )
    try:
        data = json.loads(
            raw,
            parse_constant=_reject_non_finite,
            parse_float=_finite_float,
            object_pairs_hook=_forbid_duplicate_keys,
        )
    except _StrictJSONError as exc:
        return ParseResult(issues=[ParseIssue(location=source_name, message=str(exc))])
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
        return ParseResult(
            issues=[ParseIssue(location=source_name, message=f"not valid JSON: {exc}")]
        )
    if not isinstance(data, dict):
        return ParseResult(
            issues=[ParseIssue(location=source_name, message="the file must be a JSON object")]
        )
    if data.get("format_version") != FORMAT_VERSION:
        return ParseResult(
            issues=[
                ParseIssue(
                    location=f"{source_name}.format_version",
                    message=f"unsupported format_version {data.get('format_version')!r} "
                    f"(supported: {FORMAT_VERSION})",
                )
            ]
        )
    try:
        run = EvalRun.model_validate(data)
    except ValidationError as exc:
        issues = [
            ParseIssue(
                location=source_name + "." + ".".join(str(p) for p in err["loc"]),
                message=err["msg"],
            )
            for err in exc.errors()
        ]
        return ParseResult(issues=issues)

    issues = []
    known = set(run.criterion_ids())
    seen_criteria: set[str] = set()
    for criterion in run.criteria:
        if criterion.id in seen_criteria:
            issues.append(
                ParseIssue(
                    location=f"{source_name}.criteria",
                    message=f"duplicate criterion id '{criterion.id}'",
                )
            )
        seen_criteria.add(criterion.id)
    seen_traces: set[str] = set()
    for trace in run.traces:
        if trace.trace_id in seen_traces:
            issues.append(
                ParseIssue(
                    location=f"{source_name}.traces",
                    message=f"duplicate trace_id '{trace.trace_id}'",
                )
            )
        seen_traces.add(trace.trace_id)
        unknown = sorted(set(trace.results) - known)
        if unknown:
            issues.append(
                ParseIssue(
                    location=f"{source_name}.traces.{trace.trace_id}",
                    message="results reference undeclared criteria: " + ", ".join(unknown),
                )
            )
    if issues:
        return ParseResult(issues=issues)
    return ParseResult(run=run)
