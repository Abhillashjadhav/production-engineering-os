"""The build graph is a bound execution context, not completion evidence."""

from __future__ import annotations

from dataclasses import replace

import pytest

from pmpe.contracts.acceptance import AcceptanceBuildPlan, BuildTask, CompiledCriterion
from pmpe.contracts.task_graph import TaskGraphError, compile_task_graph


def _plan() -> AcceptanceBuildPlan:
    return AcceptanceBuildPlan(
        contract_digest="contract-digest",
        requirements=("REQ-A", "REQ-B"),
        tasks=(BuildTask("TASK-001", "REQ-A"), BuildTask("TASK-002", "REQ-B")),
        criteria=(
            CompiledCriterion("AC-A", ("REQ-A",), "given_when_then"),
            CompiledCriterion("AC-B", ("REQ-B",), "given_when_then"),
        ),
        trusted_test_digests=(("tests/test_protected.py", "sha256"),),
        plan_digest="plan-digest",
    )


def _mapping() -> dict[str, object]:
    return {
        "plan_digest": "plan-digest",
        "architecture_digest": "a" * 64,
        "tasks": [
            {
                "task_id": "API",
                "requirement_refs": ["REQ-A"],
                "acceptance_ids": ["AC-A"],
                "prerequisites": [],
                "data_owners": ["records"],
                "interface_owners": ["records-api"],
                "allowed_files": ["src/api.py"],
                "outputs": ["records endpoint"],
                "affected_checks": ["AC-A"],
            },
            {
                "task_id": "UI",
                "requirement_refs": ["REQ-B"],
                "acceptance_ids": ["AC-B"],
                "prerequisites": ["API"],
                "data_owners": [],
                "interface_owners": ["browser-ui"],
                "allowed_files": ["src/ui.py"],
                "outputs": ["records page"],
                "affected_checks": ["AC-A", "AC-B"],
            },
        ],
    }


def test_default_is_a_single_whole_candidate_task_without_invented_edges() -> None:
    graph = compile_task_graph(_plan())
    assert graph.execution_mode == "whole_candidate_with_dependency_context"
    assert [task.task_id for task in graph.ready(())] == ["WHOLE-CANDIDATE"]
    assert graph.tasks[0].acceptance_ids == ("AC-A", "AC-B")
    assert graph.tasks[0].prerequisites == ()
    assert graph.as_dict()["plan_digest"] == "plan-digest"


def test_explicit_graph_has_deterministic_identity_and_dependency_slices() -> None:
    mapping = _mapping()
    graph = compile_task_graph(_plan(), mapping)
    assert [task.task_id for task in graph.ready(())] == ["API"]
    assert [task.task_id for task in graph.ready(("API",))] == ["UI"]
    assert [task.task_id for task in graph.completed_slice(("API",))] == ["API"]
    assert compile_task_graph(_plan(), mapping).graph_digest == graph.graph_digest
    assert graph.as_dict()["execution_mode"] == "whole_candidate_with_dependency_context"
    with pytest.raises(TaskGraphError, match="UNKNOWN_COMPLETED_TASK"):
        graph.ready(("not-a-task",))
    with pytest.raises(TaskGraphError, match="PREREQUISITE_INCOMPLETE"):
        graph.completed_slice(("UI",))


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda m: m.update(plan_digest="stale"), "PLAN_DIGEST_MISMATCH"),
        (lambda m: m["tasks"][0].update(task_id="UI"), "DUPLICATE_TASK_ID"),
        (lambda m: m["tasks"][1].update(prerequisites=["missing"]), "UNKNOWN_PREREQUISITE"),
        (lambda m: m["tasks"][0].update(prerequisites=["UI"]), "DEPENDENCY_CYCLE"),
        (lambda m: m["tasks"][1].update(acceptance_ids=[]), "ACCEPTANCE_IDS_MISSING"),
        (lambda m: m["tasks"][1].update(requirement_refs=[]), "REQUIREMENT_REFS_MISSING"),
        (lambda m: m["tasks"][1].update(acceptance_ids=["AC-A"]), "ACCEPTANCE_MISMATCH"),
        (lambda m: m["tasks"][1].update(allowed_files=["src/api.py"]), "FILE_OWNER_CONFLICT"),
        (lambda m: m["tasks"][1].update(data_owners=["records"]), "DATA_OWNER_CONFLICT"),
        (
            lambda m: m["tasks"][1].update(interface_owners=["records-api"]),
            "INTERFACE_OWNER_CONFLICT",
        ),
        (lambda m: m["tasks"][1].update(allowed_files=["../escape.py"]), "UNSAFE_ALLOWED_FILE"),
        (
            lambda m: m["tasks"][1].update(allowed_files=["tests/test_protected.py"]),
            "PROTECTED_FILE",
        ),
        (lambda m: m["tasks"][1].update(affected_checks=[]), "AFFECTED_CHECKS_MISSING"),
        (lambda m: m["tasks"][1].update(affected_checks=["unknown"]), "UNKNOWN_ACCEPTANCE_ID"),
        (
            lambda m: m["tasks"][0].update(
                requirement_refs=["REQ-A", "REQ-B"], acceptance_ids=["AC-A", "AC-B"]
            ),
            "AFFECTED_CHECKS_UNCOVERED",
        ),
        (lambda m: m.update(required_runtime_check="IMPORTANT"), "UNKNOWN_GRAPH_FIELD"),
        (lambda m: m["tasks"][0].update(required_runtime_check="IMPORTANT"), "UNKNOWN_TASK_FIELD"),
        (
            lambda m: m.update(architecture_digest="architecture-digest"),
            "ARCHITECTURE_DIGEST_INVALID",
        ),
        (lambda m: m["tasks"][0].update(task_id="X" * 129), "TASK_ID_INVALID"),
        (lambda m: m["tasks"][0].update(outputs=["X" * 1025]), "OUTPUTS_LIMIT_EXCEEDED"),
        (lambda m: m["tasks"][0].update(outputs=["X"] * 65), "OUTPUTS_LIMIT_EXCEEDED"),
    ],
)
def test_rejects_invalid_graph(change: object, code: str) -> None:
    mapping = _mapping()
    change(mapping)  # type: ignore[operator]
    with pytest.raises(TaskGraphError, match=code):
        compile_task_graph(_plan(), mapping)


def test_external_protected_path_and_plan_change_invalidate_graph() -> None:
    mapping = _mapping()
    mapping["tasks"][0]["allowed_files"] = ["src/api.py"]
    with pytest.raises(TaskGraphError, match="PROTECTED_FILE"):
        compile_task_graph(_plan(), mapping, protected_paths=("src/api.py",))
    with pytest.raises(TaskGraphError, match="PLAN_DIGEST_MISMATCH"):
        compile_task_graph(replace(_plan(), plan_digest="new-plan"), mapping)


def test_coverage_cannot_omit_a_requirement_or_criterion() -> None:
    mapping = _mapping()
    mapping["tasks"].pop()  # type: ignore[union-attr]
    with pytest.raises(TaskGraphError, match="REQUIREMENT_UNCOVERED"):
        compile_task_graph(_plan(), mapping)

    mapping = _mapping()
    extra = CompiledCriterion("AC-EXTRA", ("REQ-A",), "given_when_then")
    with pytest.raises(TaskGraphError, match="ACCEPTANCE_UNCOVERED"):
        compile_task_graph(replace(_plan(), criteria=(*_plan().criteria, extra)), mapping)
