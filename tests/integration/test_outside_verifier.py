"""PE8: assertions and verdicts belong to the supervisor, not candidate Python."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from pmpe import barebones
from pmpe.barebones import RunState, Template, TemplateTest, run_to_release_ready
from pmpe.cli import main
from pmpe.cli.barebones_cmd import _verification_assurance
from pmpe.contracts.acceptance import Operator, PropertyAssertion
from pmpe.contracts.canonical import CanonicalInputError, strict_json_value_loads
from pmpe.evidence.ledger import EvidenceLedger
from tests.conftest import _LocalCandidateTestSandbox

ROOT = Path(__file__).parents[2]


def _contract() -> dict[str, Any]:
    return cast(
        dict[str, Any], json.loads((ROOT / "examples/barebones/e1-contract.json").read_text())
    )


class NeverProvider:
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        raise AssertionError("provider must not run")


class NeverSandbox:
    def run(
        self,
        workspace: Path,
        argv: Sequence[str],
        *,
        timeout_seconds: float,
        environment: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]:
        raise AssertionError("candidate must not run")


class E1Provider:
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if purpose == "code":
            return {
                "request_digest": request["request_digest"],
                "files": {"product.py": "def health():\n    return {'status': 'ok'}\n"},
            }
        return {"request_digest": request["request_digest"], "summary": "advisory"}


class OutputSandbox:
    """Logic-only test double. Real Bubblewrap is exercised in selected CI."""

    def __init__(self, replies: list[tuple[int, bytes | str]]) -> None:
        self.replies = replies
        self.calls = 0
        self.commands: list[Sequence[str]] = []
        self.timeouts: list[float] = []

    def run(
        self,
        workspace: Path,
        argv: Sequence[str],
        *,
        timeout_seconds: float,
        environment: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]:
        code, output = self.replies[self.calls]
        self.calls += 1
        self.commands.append(argv)
        self.timeouts.append(timeout_seconds)
        return subprocess.CompletedProcess(argv, code, cast(str, output), "")


def test_e1_supervisor_observes_red_then_healthy_response(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sandbox = OutputSandbox([(0, '{"status":"not_implemented"}'), (0, '{"status":"ok"}')])
    contract = _contract()
    receipt_path = ROOT / "examples/barebones/e1-approval-receipt.json"
    receipt = json.loads(receipt_path.read_text())
    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="outside-e1",
        provider=E1Provider(),
        candidate_sandbox=sandbox,
        approval_receipt=receipt,
        approval_authority="fixture-human",
        approval_receipt_bytes=receipt_path.read_bytes(),
    )
    assert result.state is RunState.HALTED
    assert result.cause == "PROVIDER_WRITE_ISOLATION_UNVERIFIED"
    assert result.annotation["candidate_response_verified"] is True
    assert sandbox.calls == 2
    events = tuple(EvidenceLedger.open_existing(tmp_path, result.run_id).verify())
    observations = [item for item in events if item["event_type"] == "supervisor_observations"]
    assert len(observations) == 2
    assert [item["payload"]["observations"][0]["assertions_passed"] for item in observations] == [
        False,
        True,
    ]
    candidate = next(item for item in events if item["event_type"] == "candidate_response_verified")
    assert events[-1]["state"] == "HALTED"
    assert not any(item["event_type"] == "release_ready" for item in events)
    assert candidate["payload"]["verification_protocol"] == "external-json-response-v1"
    assert candidate["payload"]["provider_write_isolation"] == "UNVERIFIED_GENERIC_COMMAND"
    assert candidate["payload"]["verification_observations_digest"] in candidate["blob_digests"]
    assert main(["barebones", "inspect", result.run_id, "--repository-root", str(tmp_path)]) == 3
    inspection = json.loads(capsys.readouterr().out)
    assert inspection["verification_assurance"] == "CANDIDATE_RESPONSE_VERIFIED"
    assert inspection["candidate_response_verified"] is True
    assert inspection["assurance_scope"] == "CANDIDATE_RESPONSE_ONLY"
    assert inspection["release_eligible"] is False
    assert inspection["release_blocker"] == "PROVIDER_WRITE_ISOLATION_UNVERIFIED"


@pytest.mark.parametrize("mode", ["human_test", "satisfied_by_template", "measure", "mixed"])
def test_unsupported_modes_refuse_before_candidate_or_provider(
    tmp_path: Path, mode: str, capsys: pytest.CaptureFixture[str]
) -> None:
    contract = _contract()
    template = barebones.default_template()
    extra: dict[str, Any] = {}
    if mode in {"human_test", "mixed"}:
        path = tmp_path / "tests" / "test_honest.py"
        path.parent.mkdir()
        path.write_text("def test_health():\n    assert False\n")
        extra = {
            "human_test": {
                "path": "tests/test_honest.py",
                "node_id": "test_health",
                "command": [sys.executable, "-m", "pytest", "tests/test_honest.py::test_health"],
            }
        }
    elif mode == "satisfied_by_template":
        template = Template(
            version="barebones-1",
            files={**template.files, "tests/test_shape.py": "def test_shape():\n    assert True\n"},
            actions=template.actions,
            context=template.context,
            proofs={
                "shape": TemplateTest(
                    "tests/test_shape.py",
                    "test_shape",
                    (sys.executable, "-m", "pytest", "tests/test_shape.py::test_shape"),
                )
            },
        )
        extra = {"satisfied_by_template": {"template_version": "barebones-1", "test_id": "shape"}}
    else:
        template = Template(
            version="barebones-1",
            files=template.files,
            actions=template.actions,
            context=template.context,
            measures={"latency": "product:health"},
        )
        extra = {"measure": "latency", "operator": "lte", "value": 100, "sample": {"minimum": 2}}
    if mode == "mixed":
        contract["functional_requirements"]["FR-002"] = {"statement": "human proof"}
        contract["acceptance_criteria"]["AC-002"] = {"requirement_refs": ["FR-002"], **extra}
    else:
        contract["acceptance_criteria"]["AC-001"] = {"requirement_refs": ["FR-001"], **extra}
    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id=f"unsupported-{mode}",
        provider=NeverProvider(),
        template=template,
        candidate_sandbox=NeverSandbox(),
    )
    assert (result.state, result.cause, result.model_calls) == (
        RunState.HALTED,
        "UNSUPPORTED_VERIFICATION_MODE",
        0,
    )
    assert result.annotation["diagnostics"][0]["criterion_id"] == (
        "AC-002" if mode == "mixed" else "AC-001"
    )
    events = tuple(EvidenceLedger.open_existing(tmp_path, result.run_id).verify())
    assert [event["event_type"] for event in events] == ["contract_validated", "halted"]
    assert events[-1]["payload"]["diagnostics"][0]["criterion_id"] == (
        "AC-002" if mode == "mixed" else "AC-001"
    )
    assert main(["barebones", "status", result.run_id, "--repository-root", str(tmp_path)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["cause"] == "UNSUPPORTED_VERIFICATION_MODE"
    assert status["diagnostics"][0]["form"] == ("human_test" if mode == "mixed" else mode)


@pytest.mark.parametrize(
    "output",
    [
        b'{"status":"ok","status":"broken"}',
        b'{"status":NaN}',
        b'{"status":9007199254740992}',
        b'{"status":"ok"} {"status":"broken"}',
        b'__PMPE_PYTEST_RESULT__:{"outcome":"passed"}',
        b"\xff",
        b"[" * 130 + b"0" + b"]" * 130,
        b" " * 1_000_001,
        b"9" * 5_000,
    ],
)
def test_untrusted_action_response_is_strictly_rejected(tmp_path: Path, output: bytes) -> None:
    (tmp_path / "product.py").write_text("def health():\n    return {'status': 'broken'}\n")
    sandbox = OutputSandbox([(0, output)])
    with pytest.raises(barebones.ContractInvalidError):
        barebones._run_action(tmp_path, "product:health", {}, sandbox)
    assert sandbox.calls == 1


def test_nonzero_exit_and_missing_response_are_not_assertion_red(tmp_path: Path) -> None:
    (tmp_path / "product.py").write_text("def health():\n    return {'status': 'broken'}\n")
    for reply in [(1, '{"status":"ok"}'), (0, "")]:
        with pytest.raises(barebones.ContractInvalidError):
            barebones._run_action(tmp_path, "product:health", {}, OutputSandbox([reply]))


def test_supervisor_preserves_literal_registered_action_arguments(tmp_path: Path) -> None:
    (tmp_path / "product.py").write_text("def health(name):\n    return {'name': name}\n")
    sandbox = OutputSandbox([(0, '{"name":"literal"}')])
    assert barebones._run_action(tmp_path, "product:health", {"name": "literal"}, sandbox) == {
        "name": "literal"
    }
    assert json.loads(sandbox.commands[0][-1]) == {"name": "literal"}


def test_candidate_verdict_fields_cannot_override_supervisor_assertion(tmp_path: Path) -> None:
    (tmp_path / "product.py").write_text("def health():\n    return {'status': 'broken'}\n")
    plan = barebones.compile_barebones_plan(contract=_contract(), repository_root=tmp_path)
    findings = barebones._criterion_findings(
        plan.criteria[0],
        workspace=tmp_path,
        template=barebones.default_template(),
        sandbox=OutputSandbox([(0, '{"status":"broken","verdict":"PASS","tests":999}')]),
    )
    assert len(findings) == 1
    assert findings[0].code == "ASSERTION_FAILED"


def test_legacy_release_record_is_not_labeled_outside_verified() -> None:
    assert (
        _verification_assurance(
            (), {"event_type": "release_ready", "payload": {}, "blob_digests": []}
        )
        == "LEGACY_UNVERIFIED"
    )


def test_changed_plan_body_with_old_digest_refuses_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = barebones.compile_barebones_plan

    def changed_plan(**kwargs: Any) -> Any:
        plan = original(**kwargs)
        criterion = replace(plan.criteria[0], then=())
        return replace(plan, criteria=(criterion,))

    monkeypatch.setattr(barebones, "compile_barebones_plan", changed_plan)
    with pytest.raises(barebones.ContractInvalidError, match="approved verifier inputs changed"):
        run_to_release_ready(
            contract=_contract(),
            repository_root=tmp_path,
            workspace=tmp_path / "candidate",
            run_id="changed-body",
            provider=NeverProvider(),
            candidate_sandbox=NeverSandbox(),
        )
    assert not (tmp_path / "candidate").exists()


def test_changed_action_registry_after_compile_refuses_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = barebones.compile_barebones_plan

    def changed_registry(**kwargs: Any) -> Any:
        plan = original(**kwargs)
        kwargs["template"].actions["health"] = "product:forged"
        return plan

    monkeypatch.setattr(barebones, "compile_barebones_plan", changed_registry)
    with pytest.raises(barebones.ContractInvalidError, match="approved verifier inputs changed"):
        run_to_release_ready(
            contract=_contract(),
            repository_root=tmp_path,
            workspace=tmp_path / "candidate",
            run_id="changed-registry",
            provider=NeverProvider(),
            candidate_sandbox=NeverSandbox(),
        )
    assert not (tmp_path / "candidate").exists()


def test_strict_value_parser_accepts_scalar_and_rejects_duplicate() -> None:
    assert strict_json_value_loads(b"true") is True
    with pytest.raises(CanonicalInputError, match="duplicate"):
        strict_json_value_loads(b'{"x":1,"x":2}')
    with pytest.raises(CanonicalInputError) as error:
        strict_json_value_loads(b"9" * 5_000)
    assert error.value.code == "NON_JSON_NUMBER"


def test_trusted_matches_preserves_predicate_and_bounds_catastrophic_regex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matching = PropertyAssertion("result.status", Operator.MATCHES, "^ok$")
    assert barebones._assertion_passes(matching, {"result": {"status": "ok"}}) is True
    assert barebones._assertion_passes(matching, {"result": {"status": "broken"}}) is False
    adversarial = PropertyAssertion("result.status", Operator.MATCHES, "(a+)+$")
    monkeypatch.setattr(barebones, "_TRUSTED_REGEX_TIMEOUT_SECONDS", 0.2)
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="TRUSTED_PREDICATE_TIMEOUT"):
        barebones._assertion_passes(adversarial, {"result": {"status": "a" * 32 + "!"}})
    assert time.monotonic() - started < 2


def test_remaining_verification_budget_caps_actions_and_each_predicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "product.py").write_text("def health():\n    return {'status': 'ok'}\n")
    sandbox = OutputSandbox([(0, '{"status":"ok"}')])
    deadline = time.monotonic() + 0.2
    barebones._run_action(tmp_path, "product:health", {}, sandbox, deadline=deadline)
    assert 0 < sandbox.timeouts[0] <= 0.2

    original = barebones._bounded_regex_search
    calls = []

    def slow_match(pattern: str, value: str, *, deadline: float | None = None) -> bool:
        calls.append((pattern, deadline))
        time.sleep(0.15)
        return True

    monkeypatch.setattr(barebones, "_bounded_regex_search", slow_match)
    assertion = PropertyAssertion("result.status", Operator.MATCHES, "^ok$")
    predicate_deadline = time.monotonic() + 0.1
    with pytest.raises(RuntimeError, match="TRUSTED_VERIFICATION_TIME_LIMIT"):
        barebones._assertion_passes(
            assertion, {"result": {"status": "ok"}}, deadline=predicate_deadline
        )
    assert calls == [("^ok$", predicate_deadline)]
    monkeypatch.setattr(barebones, "_bounded_regex_search", original)


def test_historical_recorder_system_exit_forgery_is_not_an_admitted_mode(tmp_path: Path) -> None:
    """Record the exact old exploit; the current run path refuses this form."""
    honest = "import product\ndef test_health():\n    assert product.health() == {'status': 'ok'}\n"
    malicious = (
        "import sys,builtins\n"
        "runner=sys.modules['__main__']\n"
        "class ForgedReports(dict):\n"
        " def __setitem__(self,key,value):\n"
        "  super().__setitem__(key,{'outcome':'passed','when':'call'})\n"
        "runner.recorder.reports=ForgedReports()\n"
        "runner.SystemExit=lambda code: builtins.SystemExit(0)\n"
        "def health():return {'status':'broken'}\n"
    )
    (tmp_path / "test_honest.py").write_text(honest)
    (tmp_path / "product.py").write_text(malicious)
    node = TemplateTest(
        "test_honest.py",
        "test_health",
        (sys.executable, "-m", "pytest", "test_honest.py::test_health", "-q"),
    )
    assert (
        barebones._run_pytest_node(
            tmp_path, node, frozenset({"test_honest.py"}), _LocalCandidateTestSandbox()
        )
        is True
    )
    assert (tmp_path / "test_honest.py").read_text() == honest
