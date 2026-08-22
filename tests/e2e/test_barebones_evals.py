from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from pmpe import barebones as barebones_module
from pmpe.barebones import (
    ContractInvalidError,
    RunState,
    Template,
    TemplateTest,
    run_to_release_ready,
)
from pmpe.contracts.acceptance import AcceptanceCompileError


def _contract() -> dict[str, Any]:
    return {
        "contract_id": "PMOS-EVAL",
        "functional_requirements": {"FR-001": {"statement": "health reports ok"}},
        "acceptance_criteria": {
            "AC-001": {
                "requirement_refs": ["FR-001"],
                "given": [{"path": "service.running", "operator": "eq", "value": True}],
                "when": {"action": "health", "arguments": {}},
                "then": [{"path": "result.status", "operator": "eq", "value": "ok"}],
            }
        },
    }


class PassingProvider:
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if purpose == "code":
            return {
                "request_digest": request["request_digest"],
                "files": {
                    "product.py": ('def health() -> dict[str, str]:\n    return {"status": "ok"}\n')
                },
            }
        return {"request_digest": request["request_digest"], "summary": "advisory only"}


class UnsuccessfulProvider:
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        assert purpose == "code"
        return {
            "request_digest": request["request_digest"],
            "files": {
                "product.py": (
                    'def health() -> dict[str, str]:\n    return {"status": "not_implemented"}\n'
                )
            },
        }


class StaleResponseProvider:
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"request_digest": "sha256:" + "0" * 64, "files": {}}


class SyntaxRepairProvider:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if purpose == "advisory_review":
            return {"request_digest": request["request_digest"], "summary": "advisory"}
        self.calls += 1
        content = (
            "def health(:\n"
            if self.calls == 1
            else "def health() -> dict[str, str]:\n    return {'status': 'ok'}\n"
        )
        return {
            "request_digest": request["request_digest"],
            "files": {"product.py": content},
        }


class RepeatAfterChangedFindingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        assert purpose == "code"
        self.calls += 1
        files = {"product.py": "def health(:\n"} if self.calls == 1 else {"notes.txt": "no fix\n"}
        return {"request_digest": request["request_digest"], "files": files}


class MeasureProvider:
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if purpose == "code":
            return {
                "request_digest": request["request_digest"],
                "files": {
                    "product.py": "def latency():\n    return {'value': 100, 'sample_size': 20}\n"
                },
            }
        return {"request_digest": request["request_digest"], "summary": "advisory"}


class ManifestProvider(PassingProvider):
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        response = dict(super().invoke(purpose=purpose, request=request))
        if purpose == "code":
            response["files"] = {**response["files"], "fixtures/data.csv": "id,value\n1,ok\n"}
        return response


class MutatingActionProvider:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if purpose == "advisory_review":
            return {"request_digest": request["request_digest"], "summary": "advisory"}
        self.calls += 1
        content = (
            "from pathlib import Path\n\n"
            "def health():\n"
            "    Path(__file__).write_text(\n"
            "        \"def health():\\n    return {'status': 'broken'}\\n\"\n"
            "    )\n"
            "    return {'status': 'ok'}\n"
            if self.calls == 1
            else "def health():\n    return {'status': 'ok'}\n"
        )
        return {"request_digest": request["request_digest"], "files": {"product.py": content}}


class BooleanProvider:
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        assert purpose == "code"
        return {
            "request_digest": request["request_digest"],
            "files": {"product.py": "def health():\n    return {'status': True}\n"},
        }


class MissingPathProvider:
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        assert purpose == "code"
        return {
            "request_digest": request["request_digest"],
            "files": {"product.py": "def health():\n    return {}\n"},
        }


class TransientCrossCriterionMutationProvider:
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        assert purpose == "code"
        second_original = "def second():\n    return {'status': 'broken'}\n"
        restoring_second = (
            "from pathlib import Path\n\n"
            "def second():\n"
            f"    Path(__file__).write_text({second_original!r})\n"
            "    return {'status': 'ok'}\n"
        )
        first = (
            "from pathlib import Path\n\n"
            "def first():\n"
            f"    Path(__file__).with_name('second.py').write_text({restoring_second!r})\n"
            "    return {'status': 'ok'}\n"
        )
        return {
            "request_digest": request["request_digest"],
            "files": {"first.py": first, "second.py": second_original},
        }


class NonFiniteProvider:
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        assert purpose == "code"
        return {
            "request_digest": request["request_digest"],
            "files": {"product.py": "def health():\n    return {'status': float('nan')}\n"},
        }


class MeasureSyntaxRepairProvider:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if purpose == "advisory_review":
            return {"request_digest": request["request_digest"], "summary": "advisory"}
        self.calls += 1
        content = (
            "def latency(:\n"
            if self.calls == 1
            else "def latency():\n    return {'value': 100, 'sample_size': 20}\n"
        )
        return {"request_digest": request["request_digest"], "files": {"product.py": content}}


class TimeoutRepairProvider:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if purpose == "advisory_review":
            return {"request_digest": request["request_digest"], "summary": "advisory"}
        self.calls += 1
        content = (
            "import time\n\ndef health():\n    time.sleep(1)\n    return {'status': 'ok'}\n"
            if self.calls == 1
            else "def health():\n    return {'status': 'ok'}\n"
        )
        return {"request_digest": request["request_digest"], "files": {"product.py": content}}


def test_e2_unsatisfiable_run_halts_with_exact_requirement(tmp_path: Path) -> None:
    result = run_to_release_ready(
        contract=_contract(),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="e2-unsatisfiable",
        provider=UnsuccessfulProvider(),
    )

    assert result.state is RunState.HALTED
    assert result.cause == "REPEAT_FINDING_WITHOUT_RELEVANT_CHANGE:AC-001"


def test_e3_stale_model_response_is_detected_as_drift(tmp_path: Path) -> None:
    result = run_to_release_ready(
        contract=_contract(),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="e3-prompt-drift",
        provider=StaleResponseProvider(),
    )

    assert result.state is RunState.HALTED
    assert result.cause == "MODEL_RESPONSE_UNBOUND"


def test_coder_can_repair_a_candidate_syntax_failure(tmp_path: Path) -> None:
    result = run_to_release_ready(
        contract=_contract(),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="syntax-repair",
        provider=SyntaxRepairProvider(),
    )

    assert result.state is RunState.RELEASE_READY
    assert result.attempts == 2


def test_candidate_action_timeout_becomes_a_repairable_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(barebones_module, "_ACTION_TIMEOUT_SECONDS", 0.2)
    result = run_to_release_ready(
        contract=_contract(),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="timeout-repair",
        provider=TimeoutRepairProvider(),
    )

    assert result.state is RunState.RELEASE_READY
    assert result.attempts == 2


def test_repeat_guard_uses_the_latest_verification_finding(tmp_path: Path) -> None:
    result = run_to_release_ready(
        contract=_contract(),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="repeat-after-finding-change",
        provider=RepeatAfterChangedFindingProvider(),
    )

    assert result.state is RunState.HALTED
    assert result.cause == "REPEAT_FINDING_WITHOUT_RELEVANT_CHANGE:candidate"
    assert result.attempts == 2


def test_e4_contradiction_stops_before_build(tmp_path: Path) -> None:
    contract = _contract()
    criterion = contract["acceptance_criteria"]["AC-001"]
    criterion["given"].append({"path": "service.running", "operator": "eq", "value": False})
    workspace = tmp_path / "candidate"

    with pytest.raises(AcceptanceCompileError):
        run_to_release_ready(
            contract=contract,
            repository_root=tmp_path,
            workspace=workspace,
            run_id="e4-contradiction",
            provider=PassingProvider(),
        )

    assert not workspace.exists()


def test_e5_repeated_runs_produce_identical_evidence(tmp_path: Path) -> None:
    roots = (tmp_path / "first", tmp_path / "second")
    event_logs: list[bytes] = []
    for root in roots:
        result = run_to_release_ready(
            contract=_contract(),
            repository_root=root,
            workspace=root / "candidate",
            run_id="e5-repeat",
            provider=PassingProvider(),
        )
        assert result.state is RunState.RELEASE_READY
        event_logs.append(result.evidence_path.read_bytes())

    assert event_logs[0] == event_logs[1]


def test_human_authored_escape_hatch_is_executable_and_protected(tmp_path: Path) -> None:
    test_file = tmp_path / "tests/acceptance/test_health.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "from product import health\n\ndef test_health():\n    assert health()['status'] == 'ok'\n"
    )
    contract = _contract()
    contract["acceptance_criteria"]["AC-001"] = {
        "requirement_refs": ["FR-001"],
        "human_test": {
            "path": "tests/acceptance/test_health.py",
            "node_id": "test_health",
            "command": [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/acceptance/test_health.py::test_health",
            ],
        },
    }

    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="human-test",
        provider=PassingProvider(),
    )

    assert result.state is RunState.RELEASE_READY


@pytest.mark.parametrize(
    "source",
    [
        "import pytest\n@pytest.mark.skip\ndef test_health():\n    assert False\n",
        "def test_health(:\n    assert False\n",
    ],
)
def test_human_test_must_execute_once_and_report_a_structured_assertion(
    tmp_path: Path, source: str
) -> None:
    test_file = tmp_path / "tests/acceptance/test_health.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(source)
    contract = _contract()
    contract["acceptance_criteria"]["AC-001"] = {
        "requirement_refs": ["FR-001"],
        "human_test": {
            "path": "tests/acceptance/test_health.py",
            "node_id": "test_health",
            "command": [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/acceptance/test_health.py::test_health",
            ],
        },
    }

    with pytest.raises(ContractInvalidError):
        run_to_release_ready(
            contract=contract,
            repository_root=tmp_path,
            workspace=tmp_path / "candidate",
            run_id="human-test-structured",
            provider=PassingProvider(),
        )


class TamperingProvider:
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "request_digest": request["request_digest"],
            "files": {"tests/acceptance/test_health.py": "def test_health(): assert True\n"},
        }


def test_coder_cannot_rewrite_human_authored_evidence(tmp_path: Path) -> None:
    test_file = tmp_path / "tests/acceptance/test_health.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_health():\n    assert False\n")
    contract = _contract()
    contract["acceptance_criteria"]["AC-001"] = {
        "requirement_refs": ["FR-001"],
        "human_test": {
            "path": "tests/acceptance/test_health.py",
            "node_id": "test_health",
            "command": [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/acceptance/test_health.py::test_health",
            ],
        },
    }

    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="human-test-tamper",
        provider=TamperingProvider(),
    )

    assert result.state is RunState.HALTED
    assert result.cause == "CODER_MODIFIED_EVIDENCE"


class DotSegmentTamperingProvider:
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "request_digest": request["request_digest"],
            "files": {"tests/acceptance/./test_health.py": "def test_health(): assert True\n"},
        }


def test_coder_cannot_bypass_test_protection_with_dot_segments(tmp_path: Path) -> None:
    test_file = tmp_path / "tests/acceptance/test_health.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_health():\n    assert False\n")
    contract = _contract()
    contract["acceptance_criteria"]["AC-001"] = {
        "requirement_refs": ["FR-001"],
        "human_test": {
            "path": "tests/acceptance/test_health.py",
            "node_id": "test_health",
            "command": [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/acceptance/test_health.py::test_health",
            ],
        },
    }

    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="human-test-dot-tamper",
        provider=DotSegmentTamperingProvider(),
    )

    assert result.state is RunState.HALTED
    assert result.cause == "CODER_RESPONSE_INVALID"


class ConftestCheatProvider:
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        assert purpose == "code"
        return {
            "request_digest": request["request_digest"],
            "files": {
                "conftest.py": (
                    "def pytest_runtest_setup(item):\n"
                    "    item.module.health = lambda: {'status': 'ok'}\n"
                )
            },
        }


class PytestShadowProvider:
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        assert purpose == "code"
        fake_pytest = (
            "import pathlib, sys\n"
            "report = next(item.split('=', 1)[1] for item in sys.argv if "
            "item.startswith('--junitxml='))\n"
            "pathlib.Path(report).write_text(\n"
            "    '<testsuite><testcase name=\"test_health\" /></testsuite>'\n"
            ")\n"
        )
        return {
            "request_digest": request["request_digest"],
            "files": {"pytest.py": fake_pytest},
        }


class TestPackageInitializerProvider:
    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        assert purpose == "code"
        initializer = (
            "import sys, types\n"
            "fake = types.ModuleType('product')\n"
            "fake.health = lambda: {'status': 'ok'}\n"
            "sys.modules['product'] = fake\n"
        )
        return {
            "request_digest": request["request_digest"],
            "files": {"tests/__init__.py": initializer},
        }


def test_coder_controlled_conftest_cannot_change_bound_test_outcome(tmp_path: Path) -> None:
    test_file = tmp_path / "tests/acceptance/test_health.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "from product import health\n\ndef test_health():\n    assert health()['status'] == 'ok'\n"
    )
    contract = _contract()
    contract["acceptance_criteria"]["AC-001"] = {
        "requirement_refs": ["FR-001"],
        "human_test": {
            "path": "tests/acceptance/test_health.py",
            "node_id": "test_health",
            "command": [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/acceptance/test_health.py::test_health",
            ],
        },
    }

    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="conftest-isolation",
        provider=ConftestCheatProvider(),
    )

    assert result.state is RunState.HALTED
    assert result.cause == "REPEAT_FINDING_WITHOUT_RELEVANT_CHANGE:AC-001"


def test_coder_cannot_shadow_the_bound_pytest_runner(tmp_path: Path) -> None:
    test_file = tmp_path / "tests/acceptance/test_health.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "from product import health\n\ndef test_health():\n    assert health()['status'] == 'ok'\n"
    )
    contract = _contract()
    contract["acceptance_criteria"]["AC-001"] = {
        "requirement_refs": ["FR-001"],
        "human_test": {
            "path": "tests/acceptance/test_health.py",
            "node_id": "test_health",
            "command": [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/acceptance/test_health.py::test_health",
            ],
        },
    }

    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="pytest-shadow-isolation",
        provider=PytestShadowProvider(),
    )

    assert result.state is RunState.HALTED
    assert result.cause == "REPEAT_FINDING_WITHOUT_RELEVANT_CHANGE:AC-001"


def test_coder_cannot_add_initializers_above_a_protected_test(tmp_path: Path) -> None:
    test_file = tmp_path / "tests/acceptance/test_health.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "from product import health\n\ndef test_health():\n    assert health()['status'] == 'ok'\n"
    )
    contract = _contract()
    contract["acceptance_criteria"]["AC-001"] = {
        "requirement_refs": ["FR-001"],
        "human_test": {
            "path": "tests/acceptance/test_health.py",
            "node_id": "test_health",
            "command": [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/acceptance/test_health.py::test_health",
            ],
        },
    }

    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="test-package-initializer",
        provider=TestPackageInitializerProvider(),
    )

    assert result.state is RunState.HALTED
    assert result.cause == "CODER_MODIFIED_EVIDENCE"


def test_template_proof_is_digest_bound_and_executed(tmp_path: Path) -> None:
    template = Template(
        version="barebones-1",
        files={
            "product.py": "def health():\n    return {'status': 'not_implemented'}\n",
            "tests/template/test_shape.py": (
                "from product import health\n\n"
                "def test_health_shape():\n"
                "    assert callable(health)\n"
            ),
        },
        actions={"health": "product:health"},
        context={"service": {"running": True}},
        proofs={
            "template::health-shape": TemplateTest(
                "tests/template/test_shape.py",
                "test_health_shape",
                (
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "tests/template/test_shape.py::test_health_shape",
                ),
            )
        },
    )
    contract = _contract()
    contract["functional_requirements"]["FR-002"] = {"statement": "template exposes health"}
    contract["acceptance_criteria"]["AC-002"] = {
        "requirement_refs": ["FR-002"],
        "satisfied_by_template": {
            "template_version": "barebones-1",
            "test_id": "template::health-shape",
        },
    }

    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="template-proof",
        provider=PassingProvider(),
        template=template,
    )

    assert result.state is RunState.RELEASE_READY


def test_contract_fully_satisfied_by_template_proofs_is_valid(tmp_path: Path) -> None:
    template = Template(
        version="barebones-1",
        files={
            "product.py": "def health():\n    return {'status': 'ok'}\n",
            "tests/template/test_health.py": (
                "from product import health\n\n"
                "def test_health():\n"
                "    assert health()['status'] == 'ok'\n"
            ),
        },
        actions={},
        context={},
        proofs={
            "template::health": TemplateTest(
                "tests/template/test_health.py",
                "test_health",
                (
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "tests/template/test_health.py::test_health",
                ),
            )
        },
    )
    contract = {
        "functional_requirements": {"FR-001": {"statement": "health is ready"}},
        "acceptance_criteria": {
            "AC-001": {
                "requirement_refs": ["FR-001"],
                "satisfied_by_template": {
                    "template_version": "barebones-1",
                    "test_id": "template::health",
                },
            }
        },
    }

    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="template-only-contract",
        provider=PassingProvider(),
        template=template,
    )

    assert result.state is RunState.RELEASE_READY


def test_registered_measure_runs_deterministically(tmp_path: Path) -> None:
    template = Template(
        version="barebones-1",
        files={"product.py": "def latency():\n    return {'value': 500, 'sample_size': 20}\n"},
        actions={},
        context={},
        measures={"latency.p95_ms": "product:latency"},
    )
    contract = {
        "functional_requirements": {"FR-001": {"statement": "latency is bounded"}},
        "acceptance_criteria": {
            "AC-001": {
                "requirement_refs": ["FR-001"],
                "measure": "latency.p95_ms",
                "operator": "lte",
                "value": 200,
                "sample": {"minimum": 20},
            }
        },
    }

    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="measure",
        provider=MeasureProvider(),
        template=template,
    )

    assert result.state is RunState.RELEASE_READY


def test_measure_execution_failure_can_be_repaired(tmp_path: Path) -> None:
    template = Template(
        version="barebones-1",
        files={"product.py": "def latency():\n    return {'value': 500, 'sample_size': 20}\n"},
        actions={},
        context={},
        measures={"latency.p95_ms": "product:latency"},
    )
    contract = {
        "functional_requirements": {"FR-001": {"statement": "latency is bounded"}},
        "acceptance_criteria": {
            "AC-001": {
                "requirement_refs": ["FR-001"],
                "measure": "latency.p95_ms",
                "operator": "lte",
                "value": 200,
                "sample": {"minimum": 20},
            }
        },
    }

    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="measure-repair",
        provider=MeasureSyntaxRepairProvider(),
        template=template,
    )

    assert result.state is RunState.RELEASE_READY
    assert result.attempts == 2


def test_json_equality_does_not_treat_boolean_as_number(tmp_path: Path) -> None:
    contract = _contract()
    contract["acceptance_criteria"]["AC-001"]["then"][0]["value"] = 1
    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="json-type-equality",
        provider=BooleanProvider(),
    )

    assert result.state is RunState.HALTED
    assert result.cause == "REPEAT_FINDING_WITHOUT_RELEVANT_CHANGE:AC-001"


def test_missing_path_never_satisfies_a_null_assertion(tmp_path: Path) -> None:
    contract = _contract()
    contract["acceptance_criteria"]["AC-001"]["then"][0] = {
        "path": "result.status",
        "operator": "is_null",
    }
    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="missing-path",
        provider=MissingPathProvider(),
    )

    assert result.state is RunState.HALTED
    assert result.cause == "REPEAT_FINDING_WITHOUT_RELEVANT_CHANGE:AC-001"


def test_non_finite_action_output_becomes_a_repair_finding(tmp_path: Path) -> None:
    result = run_to_release_ready(
        contract=_contract(),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="non-finite-action-output",
        provider=NonFiniteProvider(),
    )

    assert result.state is RunState.HALTED
    assert result.cause == "REPEAT_FINDING_WITHOUT_RELEVANT_CHANGE:candidate"


@pytest.mark.parametrize("operator,value", [("lte", 2), ("gt", 0)])
def test_ordered_assertions_reject_boolean_results(
    tmp_path: Path, operator: str, value: int
) -> None:
    contract = _contract()
    contract["acceptance_criteria"]["AC-001"]["then"][0] = {
        "path": "result.status",
        "operator": operator,
        "value": value,
    }
    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id=f"ordered-boolean-{operator}",
        provider=BooleanProvider(),
    )

    assert result.state is RunState.HALTED
    assert result.cause == "REPEAT_FINDING_WITHOUT_RELEVANT_CHANGE:AC-001"


def test_each_criterion_verifies_a_fresh_exact_snapshot(tmp_path: Path) -> None:
    template = Template(
        version="barebones-1",
        files={
            "first.py": "def first():\n    return {'status': 'broken'}\n",
            "second.py": "def second():\n    return {'status': 'broken'}\n",
        },
        actions={"first": "first:first", "second": "second:second"},
        context={"ready": None},
    )
    contract = {
        "functional_requirements": {
            "FR-001": {"statement": "first works"},
            "FR-002": {"statement": "second works"},
        },
        "acceptance_criteria": {
            "AC-001": {
                "requirement_refs": ["FR-001"],
                "given": [{"path": "ready", "operator": "is_null"}],
                "when": {"action": "first", "arguments": {}},
                "then": [{"path": "result.status", "operator": "eq", "value": "ok"}],
            },
            "AC-002": {
                "requirement_refs": ["FR-002"],
                "given": [{"path": "ready", "operator": "is_null"}],
                "when": {"action": "second", "arguments": {}},
                "then": [{"path": "result.status", "operator": "eq", "value": "ok"}],
            },
        },
    }
    result = run_to_release_ready(
        contract=contract,
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="transient-cross-criterion-mutation",
        provider=TransientCrossCriterionMutationProvider(),
        template=template,
    )

    assert result.state is RunState.HALTED
    assert result.cause == "REPEAT_FINDING_WITHOUT_RELEVANT_CHANGE:AC-001,AC-002"


def test_release_manifest_digests_every_candidate_file(tmp_path: Path) -> None:
    result = run_to_release_ready(
        contract=_contract(),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="complete-manifest",
        provider=ManifestProvider(),
    )

    event = json.loads(result.evidence_path.read_text().splitlines()[-1])
    manifest_digest = event["payload"]["candidate_digest"]
    manifest_path = tmp_path / ".pmpe/blobs" / manifest_digest.removeprefix("sha256:")
    manifest = json.loads(manifest_path.read_text())
    assert "fixtures/data.csv" in manifest
    file_blob = tmp_path / ".pmpe/blobs" / manifest["fixtures/data.csv"].removeprefix("sha256:")
    assert file_blob.read_bytes() == b"id,value\n1,ok\n"
    assert set(manifest.values()).issubset(set(event["blob_digests"]))


def test_release_manifest_is_the_exact_snapshot_that_was_verified(tmp_path: Path) -> None:
    result = run_to_release_ready(
        contract=_contract(),
        repository_root=tmp_path,
        workspace=tmp_path / "candidate",
        run_id="mutation-detection",
        provider=MutatingActionProvider(),
    )

    assert result.state is RunState.RELEASE_READY
    assert result.attempts == 2
    event = json.loads(result.evidence_path.read_text().splitlines()[-1])
    manifest_path = (
        tmp_path / ".pmpe/blobs" / event["payload"]["candidate_digest"].removeprefix("sha256:")
    )
    manifest = json.loads(manifest_path.read_text())
    product_blob = tmp_path / ".pmpe/blobs" / manifest["product.py"].removeprefix("sha256:")
    assert product_blob.read_text() == "def health():\n    return {'status': 'ok'}\n"
