"""Minimal contract-to-RELEASE_READY runtime with no deployment dependency."""

from __future__ import annotations

import hashlib
import json
import operator as comparison
import os
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
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
class TemplateTest:
    path: str
    node_id: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class Template:
    version: str
    files: Mapping[str, str]
    actions: Mapping[str, str]
    context: Mapping[str, Any]
    proofs: Mapping[str, TemplateTest] = field(default_factory=dict)
    measures: Mapping[str, str] = field(default_factory=dict)


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
    if not _SAFE_RELATIVE.fullmatch(relative) or any(
        part in {".", ".."} for part in relative.split("/")
    ):
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
        [sys.executable, "-I", "-B", "-c", runner, str(module_path), json.dumps(arguments)],
        cwd=workspace,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if completed.returncode != 0:
        raise ContractInvalidError("action failed before an assertion: " + completed.stderr.strip())
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ContractInvalidError("action did not return one JSON value") from exc


def _run_pytest_node(workspace: Path, test: TemplateTest) -> bool:
    descriptor, report_name = tempfile.mkstemp(suffix=".xml")
    os.close(descriptor)
    report = Path(report_name)
    try:
        completed = subprocess.run(
            [
                *test.command,
                f"--junitxml={report}",
                "-o",
                "junit_family=xunit2",
                "-p",
                "no:cacheprovider",
            ],
            cwd=workspace,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        try:
            root = ET.parse(report).getroot()
        except (ET.ParseError, OSError) as exc:
            raise ContractInvalidError("human test produced no structured pytest result") from exc
        cases = [item for item in root.iter("testcase") if item.get("name") == test.node_id]
        if len(cases) != 1:
            raise ContractInvalidError("bound human test node did not execute exactly once")
        case = cases[0]
        if case.find("skipped") is not None or case.find("error") is not None:
            raise ContractInvalidError("bound human test was skipped or errored")
        failure = case.find("failure")
        if failure is not None and completed.returncode == 1:
            return False
        if failure is None and completed.returncode == 0:
            return True
        raise ContractInvalidError("human test failed outside its bound assertion")
    finally:
        report.unlink(missing_ok=True)


def _criterion_findings(
    criterion: CompiledCriterion,
    *,
    workspace: Path,
    template: Template,
) -> tuple[Finding, ...]:
    if criterion.form == "satisfied_by_template":
        assert criterion.template_proof is not None
        proof = template.proofs[criterion.template_proof.test_id]
        proof_path = _safe_path(workspace, proof.path)
        digest = "sha256:" + hashlib.sha256(proof_path.read_bytes()).hexdigest()
        if digest != criterion.template_proof.file_digest:
            raise ContractInvalidError("template proof file does not match its compiled digest")
        if not _run_pytest_node(workspace, proof):
            return (
                Finding(
                    "ASSERTION_FAILED",
                    criterion.criterion_id,
                    "template acceptance proof failed",
                    (proof.path,),
                ),
            )
        return ()
    if criterion.form == "human_test":
        assert criterion.human_test is not None
        human_test = TemplateTest(
            criterion.human_test.path,
            criterion.human_test.node_id,
            criterion.human_test.command,
        )
        if _run_pytest_node(workspace, human_test):
            return ()
        return (
            Finding(
                "ASSERTION_FAILED",
                criterion.criterion_id,
                "human-authored acceptance assertion failed",
                (criterion.human_test.path,),
            ),
        )
    if criterion.form == "measure":
        assert criterion.operator is not None
        assert criterion.minimum_sample is not None
        target = template.measures[criterion.measure]
        observation = _run_action(workspace, target, {})
        if not isinstance(observation, Mapping):
            raise ContractInvalidError("measure did not return a JSON object")
        sample_size = observation.get("sample_size")
        if isinstance(sample_size, bool) or not isinstance(sample_size, int):
            raise ContractInvalidError("measure did not return an integer sample_size")
        assertion = PropertyAssertion("value", criterion.operator, criterion.value)
        if sample_size >= criterion.minimum_sample and _assertion_passes(assertion, observation):
            return ()
        module = target.split(":", maxsplit=1)[0].replace(".", "/") + ".py"
        return (
            Finding(
                "ASSERTION_FAILED",
                criterion.criterion_id,
                "compiled measure assertion failed",
                (module,),
            ),
        )
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


def _candidate_manifest(workspace: Path, ledger: EvidenceLedger) -> tuple[str, tuple[str, ...]]:
    manifest: dict[str, str] = {}
    blobs: list[str] = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file():
            continue
        digest = ledger.put_blob(path.read_bytes())
        manifest[str(path.relative_to(workspace))] = digest
        blobs.append(digest)
    manifest_blob = ledger.put_blob(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    )
    return manifest_blob, tuple(sorted(set(blobs)))


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

    template_test_digests: dict[str, str] = {}
    for test_id, proof in active_template.proofs.items():
        _safe_path(workspace, proof.path)
        target = f"{proof.path}::{proof.node_id}"
        if proof.path not in active_template.files or target not in proof.command:
            raise ContractInvalidError(f"invalid template proof binding: {test_id}")
        template_test_digests[test_id] = (
            "sha256:" + hashlib.sha256(active_template.files[proof.path].encode()).hexdigest()
        )

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
        template_test_digests=template_test_digests,
        registered_measures=frozenset(active_template.measures),
    )
    plan_blob = ledger.put_blob(
        json.dumps(plan.as_dict(), sort_keys=True, separators=(",", ":")).encode()
    )
    contract_blob = ledger.put_blob(
        json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    )
    ledger.append(
        event_type="contract_validated",
        state=RunState.VALIDATED,
        subject_digest=subject_digest,
        blob_digests=(contract_blob, plan_blob),
        payload={"contract_digest": contract_blob, "plan_digest": plan.plan_digest},
    )
    if stop_requested():
        ledger.append(event_type="stopped", state=RunState.STOPPED, subject_digest=subject_digest)
        return finish(RunState.STOPPED, "STOP_REQUESTED", 0)

    workspace.mkdir(parents=True, exist_ok=True)
    if any(workspace.iterdir()):
        raise ValueError("candidate workspace must be empty")
    _write_files(workspace, active_template.files)
    protected_tests = {
        _safe_path(workspace, proof.path) for proof in active_template.proofs.values()
    }
    for criterion in plan.criteria:
        if criterion.human_test is None:
            continue
        relative = criterion.human_test.path
        source = repository_root / relative
        digest = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != criterion.human_test.file_digest:
            raise ContractInvalidError("human test changed after compilation")
        _write_files(workspace, {relative: source.read_text()})
        protected_tests.add(_safe_path(workspace, relative))
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
        try:
            response_paths = {
                _safe_path(workspace, relative) for relative in files if isinstance(relative, str)
            }
            if len(response_paths) != len(files):
                raise ValueError("candidate paths must be strings")
        except ValueError:
            ledger.append(
                event_type="halted",
                state=RunState.HALTED,
                subject_digest=subject_digest,
                payload={"cause": "CODER_RESPONSE_INVALID"},
            )
            return finish(RunState.HALTED, "CODER_RESPONSE_INVALID", attempt)
        if protected_tests.intersection(response_paths):
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
            try:
                findings = _verify(plan, workspace, active_template)
            except ContractInvalidError as exc:
                implicated_files = tuple(
                    sorted(
                        {
                            target.split(":", maxsplit=1)[0].replace(".", "/") + ".py"
                            for target in active_template.actions.values()
                        }
                    )
                )
                findings = (
                    Finding(
                        "CANDIDATE_EXECUTION_FAILED",
                        "candidate",
                        str(exc),
                        implicated_files,
                    ),
                )
            if not findings:
                evidence = {
                    "assertions": "passed",
                    "coverage": "complete",
                    "security": [asdict(item) for item in security],
                    "attempt": attempt,
                }
                blob = ledger.put_blob(json.dumps(evidence, sort_keys=True).encode())
                candidate_blob, candidate_file_blobs = _candidate_manifest(workspace, ledger)
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
                    blob_digests=(blob, candidate_blob, *candidate_file_blobs),
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
        previous_finding_digest = canonical_digest([asdict(item) for item in findings])

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
