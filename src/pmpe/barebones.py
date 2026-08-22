"""Minimal contract-to-RELEASE_READY runtime with no deployment dependency."""

from __future__ import annotations

import json
import operator as comparison
import re
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from pmpe.contracts.acceptance import (
    AcceptanceBuildPlan,
    CompiledCriterion,
    Operator,
    PropertyAssertion,
    compile_acceptance_plan,
)
from pmpe.contracts.canonical import canonical_digest
from pmpe.evidence.ledger import EvidenceLedger
from pmpe.model_provider import ModelProvider


class RunState(StrEnum):
    VALIDATED = "VALIDATED"
    BUILDING = "BUILDING"
    VERIFYING = "VERIFYING"
    RELEASE_READY = "RELEASE_READY"
    HALTED = "HALTED"
    STOPPED = "STOPPED"


@dataclass(frozen=True)
class Template:
    version: str
    files: Mapping[str, str]
    actions: Mapping[str, str]
    context: Mapping[str, Any]
    test_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class BudgetCaps:
    max_attempts: int = 3
    max_model_calls: int = 8
    max_model_output_bytes: int = 1_000_000


@dataclass(frozen=True)
class Finding:
    code: str
    subject_id: str
    message: str
    files: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunResult:
    run_id: str
    state: RunState
    cause: str
    attempts: int
    model_calls: int
    elapsed_ms: int
    evidence_path: Path
    annotation: Mapping[str, Any] = field(default_factory=dict)


class ContractInvalidError(ValueError):
    """The baseline proves that an admitted contract or template is not runnable."""


_SAFE_RELATIVE = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\Z")
_MODULE_TARGET = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*):([A-Za-z_][A-Za-z0-9_]*)\Z")
_CREDENTIAL = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|AKIA[0-9A-Z]{16}")
_HIGH_RISK_CODE = re.compile(r"\b(?:eval|exec)\s*\(")


def default_template() -> Template:
    """The one v1 template; products compose behavior inside this single skeleton."""

    return Template(
        version="barebones-1",
        files={
            "product.py": (
                '"""Product behavior generated from a PMOS contract."""\n\n'
                "def health() -> dict[str, str]:\n"
                '    return {"status": "not_implemented"}\n'
            )
        },
        actions={"health": "product:health"},
        context={"service": {"running": True}},
    )


def _safe_path(root: Path, relative: str) -> Path:
    if not _SAFE_RELATIVE.fullmatch(relative) or ".." in Path(relative).parts:
        raise ValueError(f"unsafe candidate path: {relative}")
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError(f"candidate path escapes workspace: {relative}")
    return target


def _write_files(root: Path, files: Mapping[str, str]) -> tuple[str, ...]:
    changed: list[str] = []
    for relative, content in sorted(files.items()):
        if not isinstance(relative, str) or not isinstance(content, str):
            raise ValueError("candidate files must map safe paths to UTF-8 text")
        target = _safe_path(root, relative)
        before = target.read_text() if target.is_file() else None
        if before == content:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        changed.append(relative)
    return tuple(changed)


def _path(value: Any, dotted_path: str) -> Any:
    current = value
    for part in dotted_path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise KeyError(dotted_path)
        current = current[part]
    return current


def _assertion_passes(assertion: PropertyAssertion, value: Any) -> bool:
    try:
        actual = _path(value, assertion.path)
    except KeyError:
        actual = None
    binary: dict[Operator, Callable[[Any, Any], bool]] = {
        Operator.EQ: comparison.eq,
        Operator.NE: comparison.ne,
        Operator.LT: comparison.lt,
        Operator.LTE: comparison.le,
        Operator.GT: comparison.gt,
        Operator.GTE: comparison.ge,
        Operator.CONTAINS: lambda left, right: right in left,
        Operator.NOT_CONTAINS: lambda left, right: right not in left,
        Operator.MATCHES: lambda left, right: bool(re.search(str(right), str(left))),
    }
    if assertion.operator in binary:
        try:
            return binary[assertion.operator](actual, assertion.value)
        except (TypeError, re.error):
            return False
    unary = {
        Operator.IS_TRUE: actual is True,
        Operator.IS_FALSE: actual is False,
        Operator.IS_NULL: actual is None,
        Operator.NOT_NULL: actual is not None,
    }
    return unary[assertion.operator]


def _run_action(workspace: Path, target: str, arguments: Mapping[str, Any]) -> Any:
    match = _MODULE_TARGET.fullmatch(target)
    if match is None:
        raise ContractInvalidError(f"invalid template action target: {target}")
    module, function = match.groups()
    module_path = workspace / (module.replace(".", "/") + ".py")
    runner = (
        "import importlib.util,json,sys;"
        "s=importlib.util.spec_from_file_location('candidate',sys.argv[1]);"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        f"v=getattr(m,{function!r})(**json.loads(sys.argv[2]));"
        "print(json.dumps(v,sort_keys=True,separators=(',',':')))"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", runner, str(module_path), json.dumps(arguments)],
        cwd=workspace,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
        env={"PYTHONPATH": str(workspace)},
    )
    if completed.returncode != 0:
        raise ContractInvalidError("action failed before an assertion: " + completed.stderr.strip())
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ContractInvalidError("action did not return one JSON value") from exc


def _criterion_findings(
    criterion: CompiledCriterion,
    *,
    workspace: Path,
    template: Template,
) -> tuple[Finding, ...]:
    if criterion.form == "satisfied_by_template":
        return ()
    if criterion.form == "human_test":
        assert criterion.human_test is not None
        completed = subprocess.run(
            criterion.human_test.command,
            cwd=workspace,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        if completed.returncode == 0:
            return ()
        output = completed.stdout + completed.stderr
        if "AssertionError" not in output and "assert " not in output:
            raise ContractInvalidError("human test failed before an assertion")
        return (
            Finding(
                "ASSERTION_FAILED",
                criterion.criterion_id,
                "human-authored acceptance assertion failed",
                (criterion.human_test.path,),
            ),
        )
    if criterion.form == "measure":
        raise ContractInvalidError("measure has no registered deterministic observation source")
    assert criterion.when is not None
    if any(not _assertion_passes(item, template.context) for item in criterion.given):
        raise ContractInvalidError(f"{criterion.criterion_id}: Given precondition is false")
    target = template.actions[criterion.when.action]
    result = _run_action(workspace, target, criterion.when.arguments)
    wrapped = {"result": result}
    if all(_assertion_passes(item, wrapped) for item in criterion.then):
        return ()
    module = target.split(":", maxsplit=1)[0].replace(".", "/") + ".py"
    return (
        Finding(
            "ASSERTION_FAILED",
            criterion.criterion_id,
            "compiled acceptance assertion failed",
            (module,),
        ),
    )


def _verify(plan: AcceptanceBuildPlan, workspace: Path, template: Template) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    for criterion in plan.criteria:
        findings.extend(_criterion_findings(criterion, workspace=workspace, template=template))
    return tuple(findings)


def _security_findings(workspace: Path) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    for path in sorted(workspace.rglob("*.py")):
        content = path.read_text()
        relative = str(path.relative_to(workspace))
        if _CREDENTIAL.search(content):
            findings.append(
                Finding("CRITICAL_CREDENTIAL", relative, "credential material", (relative,))
            )
        if _HIGH_RISK_CODE.search(content):
            findings.append(
                Finding("HIGH_DYNAMIC_EXECUTION", relative, "dynamic execution", (relative,))
            )
        if "TODO" in content:
            findings.append(Finding("LOW_TODO", relative, "TODO remains", (relative,)))
    return tuple(findings)


def _model_request(
    *,
    contract: Mapping[str, Any],
    plan: AcceptanceBuildPlan,
    workspace: Path,
    findings: Sequence[Finding],
) -> dict[str, Any]:
    body = {
        "contract": contract,
        "plan": plan.as_dict(),
        "files": {
            str(path.relative_to(workspace)): path.read_text()
            for path in sorted(workspace.rglob("*"))
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix in {".json", ".md", ".py", ".toml", ".txt", ".yaml", ".yml"}
        },
        "findings": [asdict(item) for item in findings],
    }
    return {**body, "request_digest": canonical_digest(body)}


def _invoke_bound(
    provider: ModelProvider,
    *,
    purpose: str,
    request: Mapping[str, Any],
    budget: BudgetCaps,
    counters: dict[str, int],
) -> Mapping[str, Any]:
    if counters["calls"] >= budget.max_model_calls:
        raise RuntimeError("MODEL_CALL_BUDGET_EXHAUSTED")
    response = provider.invoke(purpose=purpose, request=request)
    counters["calls"] += 1
    size = len(json.dumps(response, sort_keys=True, separators=(",", ":")).encode())
    counters["bytes"] += size
    if counters["bytes"] > budget.max_model_output_bytes:
        raise RuntimeError("MODEL_OUTPUT_BUDGET_EXHAUSTED")
    if response.get("request_digest") != request.get("request_digest"):
        raise RuntimeError("MODEL_RESPONSE_UNBOUND")
    return response


def run_to_release_ready(
    *,
    contract: Mapping[str, Any],
    repository_root: Path,
    workspace: Path,
    run_id: str,
    provider: ModelProvider,
    template: Template | None = None,
    budget: BudgetCaps | None = None,
    stop_requested: Callable[[], bool] = lambda: False,
) -> RunResult:
    """Run the frozen core. It never deploys and stops at RELEASE_READY."""

    started = time.monotonic()
    active_template = template or default_template()
    active_budget = budget or BudgetCaps()
    ledger = EvidenceLedger(repository_root, run_id)
    counters = {"calls": 0, "bytes": 0}
    subject_digest = canonical_digest(contract)

    def finish(
        state: RunState, cause: str, attempts: int, annotation: Mapping[str, Any] | None = None
    ) -> RunResult:
        return RunResult(
            run_id,
            state,
            cause,
            attempts,
            counters["calls"],
            int((time.monotonic() - started) * 1000),
            ledger.events_path,
            dict(annotation or {}),
        )

    plan = compile_acceptance_plan(
        contract,
        repository_root=repository_root,
        registered_actions=frozenset(active_template.actions),
        template_version=active_template.version,
        template_test_ids=active_template.test_ids,
    )
    plan_blob = ledger.put_blob(
        json.dumps(plan.as_dict(), sort_keys=True, separators=(",", ":")).encode()
    )
    ledger.append(
        event_type="contract_validated",
        state=RunState.VALIDATED,
        subject_digest=subject_digest,
        blob_digests=(plan_blob,),
        payload={"plan_digest": plan.plan_digest},
    )
    if stop_requested():
        ledger.append(event_type="stopped", state=RunState.STOPPED, subject_digest=subject_digest)
        return finish(RunState.STOPPED, "STOP_REQUESTED", 0)

    workspace.mkdir(parents=True, exist_ok=True)
    if any(workspace.iterdir()):
        raise ValueError("candidate workspace must be empty")
    _write_files(workspace, active_template.files)
    protected_tests: set[str] = set()
    for criterion in plan.criteria:
        if criterion.human_test is None:
            continue
        relative = criterion.human_test.path
        source = repository_root / relative
        _write_files(workspace, {relative: source.read_text()})
        protected_tests.add(relative)
    baseline = _verify(plan, workspace, active_template)
    non_template = tuple(item for item in plan.criteria if item.form != "satisfied_by_template")
    failed_ids = {item.subject_id for item in baseline}
    if not non_template or failed_ids != {item.criterion_id for item in non_template}:
        raise ContractInvalidError("baseline must fail every non-template criterion by assertion")
    baseline_blob = ledger.put_blob(
        json.dumps(
            [asdict(item) for item in baseline], sort_keys=True, separators=(",", ":")
        ).encode()
    )
    ledger.append(
        event_type="meaningful_red_confirmed",
        state=RunState.BUILDING,
        subject_digest=subject_digest,
        blob_digests=(baseline_blob,),
        payload={"findings": [asdict(item) for item in baseline]},
    )

    findings: tuple[Finding, ...] = baseline
    previous_finding_digest = ""
    for attempt in range(1, active_budget.max_attempts + 1):
        if stop_requested():
            ledger.append(
                event_type="stopped", state=RunState.STOPPED, subject_digest=subject_digest
            )
            return finish(RunState.STOPPED, "STOP_REQUESTED", attempt - 1)
        request = _model_request(
            contract=contract,
            plan=plan,
            workspace=workspace,
            findings=findings,
        )
        try:
            response = _invoke_bound(
                provider,
                purpose="code",
                request=request,
                budget=active_budget,
                counters=counters,
            )
        except RuntimeError as exc:
            ledger.append(
                event_type="halted",
                state=RunState.HALTED,
                subject_digest=subject_digest,
                payload={"cause": str(exc)},
            )
            return finish(RunState.HALTED, str(exc), attempt - 1)
        files = response.get("files")
        if not isinstance(files, Mapping):
            ledger.append(
                event_type="halted",
                state=RunState.HALTED,
                subject_digest=subject_digest,
                payload={"cause": "CODER_RESPONSE_INVALID"},
            )
            return finish(RunState.HALTED, "CODER_RESPONSE_INVALID", attempt)
        if protected_tests.intersection(files):
            ledger.append(
                event_type="halted",
                state=RunState.HALTED,
                subject_digest=subject_digest,
                payload={"cause": "CODER_MODIFIED_EVIDENCE"},
            )
            return finish(RunState.HALTED, "CODER_MODIFIED_EVIDENCE", attempt)
        try:
            changed = _write_files(workspace, files)
        except ValueError:
            ledger.append(
                event_type="halted",
                state=RunState.HALTED,
                subject_digest=subject_digest,
                payload={"cause": "CODER_RESPONSE_INVALID"},
            )
            return finish(RunState.HALTED, "CODER_RESPONSE_INVALID", attempt)
        coder_blob = ledger.put_blob(
            json.dumps(response, sort_keys=True, separators=(",", ":")).encode()
        )
        ledger.append(
            event_type="coder_completed",
            state=RunState.BUILDING,
            subject_digest=subject_digest,
            blob_digests=(coder_blob,),
            payload={"attempt": attempt, "changed": list(changed)},
        )
        finding_digest = canonical_digest([asdict(item) for item in findings])
        implicated = {path for item in findings for path in item.files}
        if previous_finding_digest == finding_digest and not implicated.intersection(changed):
            subjects = ",".join(sorted({item.subject_id for item in findings}))
            cause = f"REPEAT_FINDING_WITHOUT_RELEVANT_CHANGE:{subjects}"
            ledger.append(
                event_type="halted",
                state=RunState.HALTED,
                subject_digest=subject_digest,
                payload={"cause": cause, "findings": [asdict(item) for item in findings]},
            )
            return finish(RunState.HALTED, cause, attempt)

        security = _security_findings(workspace)
        blocking_security = tuple(
            item for item in security if item.code.startswith(("CRITICAL_", "HIGH_"))
        )
        if blocking_security:
            findings = blocking_security
            finding_blob = ledger.put_blob(
                json.dumps(
                    [asdict(item) for item in findings],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            )
            ledger.append(
                event_type="security_failed",
                state=RunState.BUILDING,
                subject_digest=subject_digest,
                blob_digests=(finding_blob,),
                payload={"attempt": attempt, "findings": [asdict(item) for item in findings]},
            )
        else:
            ledger.append(
                event_type="verification_started",
                state=RunState.VERIFYING,
                subject_digest=subject_digest,
                payload={"attempt": attempt, "changed": list(changed)},
            )
            findings = _verify(plan, workspace, active_template)
            if not findings:
                evidence = {
                    "assertions": "passed",
                    "coverage": "complete",
                    "security": [asdict(item) for item in security],
                    "attempt": attempt,
                }
                blob = ledger.put_blob(json.dumps(evidence, sort_keys=True).encode())
                candidate = {
                    str(path.relative_to(workspace)): path.read_text()
                    for path in sorted(workspace.rglob("*"))
                    if path.is_file()
                    and "__pycache__" not in path.parts
                    and path.suffix in {".json", ".md", ".py", ".toml", ".txt", ".yaml", ".yml"}
                }
                candidate_blob = ledger.put_blob(
                    json.dumps(candidate, sort_keys=True, separators=(",", ":")).encode()
                )
                review_body = {
                    "contract_digest": subject_digest,
                    "plan_digest": plan.plan_digest,
                    "evidence_digest": blob,
                    "instruction": "Return one non-blocking advisory annotation.",
                }
                review_request = {
                    **review_body,
                    "request_digest": canonical_digest(review_body),
                }
                try:
                    annotation = _invoke_bound(
                        provider,
                        purpose="advisory_review",
                        request=review_request,
                        budget=active_budget,
                        counters=counters,
                    )
                except RuntimeError as exc:
                    annotation = {"status": "unavailable", "cause": str(exc)}
                ledger.append(
                    event_type="release_ready",
                    state=RunState.RELEASE_READY,
                    subject_digest=subject_digest,
                    blob_digests=(blob, candidate_blob),
                    payload={
                        "annotation": dict(annotation),
                        "candidate_digest": candidate_blob,
                        "telemetry": dict(counters),
                    },
                )
                return finish(RunState.RELEASE_READY, "PASS", attempt, annotation)
            finding_blob = ledger.put_blob(
                json.dumps(
                    [asdict(item) for item in findings],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            )
            ledger.append(
                event_type="verification_failed",
                state=RunState.BUILDING,
                subject_digest=subject_digest,
                blob_digests=(finding_blob,),
                payload={"attempt": attempt, "findings": [asdict(item) for item in findings]},
            )
        previous_finding_digest = finding_digest

    ledger.append(
        event_type="halted",
        state=RunState.HALTED,
        subject_digest=subject_digest,
        payload={
            "cause": "ATTEMPT_BUDGET_EXHAUSTED",
            "findings": [asdict(item) for item in findings],
        },
    )
    return finish(RunState.HALTED, "ATTEMPT_BUDGET_EXHAUSTED", active_budget.max_attempts)
