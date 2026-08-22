from __future__ import annotations

from pathlib import Path

import pytest

from pmpe.contracts.acceptance import AcceptanceCompileError, compile_acceptance_plan


def _contract(criterion: dict[str, object]) -> dict[str, object]:
    return {
        "functional_requirements": {"FR-001": {"statement": "health reports ok"}},
        "acceptance_criteria": {"AC-001": criterion},
    }


def test_compiles_structured_given_when_then_without_model_interpretation(
    tmp_path: Path,
) -> None:
    contract = _contract(
        {
            "requirement_refs": ["FR-001"],
            "given": [{"path": "service.running", "operator": "eq", "value": True}],
            "when": {"action": "health", "arguments": {}},
            "then": [{"path": "result.status", "operator": "eq", "value": "ok"}],
        }
    )

    plan = compile_acceptance_plan(
        contract,
        repository_root=tmp_path,
        registered_actions=frozenset({"health"}),
        template_version="barebones-1",
        template_test_digests={},
    )

    assert plan.requirements == ("FR-001",)
    assert plan.tasks[0].requirement_id == "FR-001"
    assert plan.criteria[0].when is not None
    assert plan.criteria[0].when.action == "health"
    assert plan.plan_digest.startswith("sha256:")


def test_free_text_criterion_fails_before_build(tmp_path: Path) -> None:
    contract = _contract(
        {
            "requirement_refs": ["FR-001"],
            "criterion": "Given a service, when health runs, then status is ok.",
        }
    )

    with pytest.raises(AcceptanceCompileError) as failure:
        compile_acceptance_plan(
            contract,
            repository_root=tmp_path,
            registered_actions=frozenset({"health"}),
            template_version="barebones-1",
            template_test_digests={},
        )

    assert failure.value.diagnostics[0].code == "CRITERION_FORM_INVALID"


def test_human_test_is_path_and_digest_bound(tmp_path: Path) -> None:
    test_path = tmp_path / "tests" / "acceptance" / "test_security.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("def test_safe():\n    assert True\n")
    contract = _contract(
        {
            "requirement_refs": ["FR-001"],
            "human_test": {
                "path": "tests/acceptance/test_security.py",
                "node_id": "test_safe",
                "command": [
                    "pytest",
                    "-q",
                    "tests/acceptance/test_security.py::test_safe",
                ],
            },
        }
    )

    plan = compile_acceptance_plan(
        contract,
        repository_root=tmp_path,
        registered_actions=frozenset(),
        template_version="barebones-1",
        template_test_digests={},
    )

    assert plan.criteria[0].human_test is not None
    assert plan.criteria[0].human_test.file_digest.startswith("sha256:")


def test_human_test_missing_fails_before_build(tmp_path: Path) -> None:
    contract = _contract(
        {
            "requirement_refs": ["FR-001"],
            "human_test": {
                "path": "tests/acceptance/test_missing.py",
                "node_id": "test_missing",
                "command": [
                    "pytest",
                    "-q",
                    "tests/acceptance/test_missing.py::test_missing",
                ],
            },
        }
    )

    with pytest.raises(AcceptanceCompileError) as failure:
        compile_acceptance_plan(
            contract,
            repository_root=tmp_path,
            registered_actions=frozenset(),
            template_version="barebones-1",
            template_test_digests={},
        )

    assert failure.value.diagnostics[0].code == "HUMAN_TEST_MISSING"


def test_human_test_rejects_dot_segments_and_requires_exact_node(tmp_path: Path) -> None:
    test_path = tmp_path / "tests/acceptance/test_security.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("def test_safe():\n    assert True\n")
    for human_test in (
        {
            "path": "tests/acceptance/./test_security.py",
            "node_id": "test_safe",
            "command": ["pytest", "tests/acceptance/./test_security.py::test_safe"],
        },
        {
            "path": "tests/acceptance/test_security.py",
            "node_id": "test_safe",
            "command": ["pytest", "tests/acceptance/test_security.py"],
        },
    ):
        with pytest.raises(AcceptanceCompileError) as failure:
            compile_acceptance_plan(
                _contract({"requirement_refs": ["FR-001"], "human_test": human_test}),
                repository_root=tmp_path,
                registered_actions=frozenset(),
                template_version="barebones-1",
                template_test_digests={},
            )
        assert failure.value.diagnostics[0].code in {
            "INVALID_HUMAN_TEST_REFERENCE",
            "HUMAN_TEST_COMMAND_MISMATCH",
        }


def test_every_requirement_must_have_a_criterion(tmp_path: Path) -> None:
    contract = {
        "functional_requirements": {
            "FR-001": {"statement": "health reports ok"},
            "FR-002": {"statement": "config is safe"},
        },
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

    with pytest.raises(AcceptanceCompileError) as failure:
        compile_acceptance_plan(
            contract,
            repository_root=tmp_path,
            registered_actions=frozenset(),
            template_version="barebones-1",
            template_test_digests={"template::health": "sha256:" + "0" * 64},
        )

    assert any(
        item.code == "REQUIREMENT_UNCOVERED" and item.subject_id == "FR-002"
        for item in failure.value.diagnostics
    )


def test_template_pass_requires_exact_pinned_proof(tmp_path: Path) -> None:
    contract = _contract(
        {
            "requirement_refs": ["FR-001"],
            "satisfied_by_template": {
                "template_version": "old-template",
                "test_id": "template::health",
            },
        }
    )

    with pytest.raises(AcceptanceCompileError) as failure:
        compile_acceptance_plan(
            contract,
            repository_root=tmp_path,
            registered_actions=frozenset(),
            template_version="barebones-1",
            template_test_digests={"template::health": "sha256:" + "0" * 64},
        )

    assert failure.value.diagnostics[0].code == "TEMPLATE_PROOF_INVALID"


def test_contradictory_assertions_fail_at_compile_time(tmp_path: Path) -> None:
    contract = _contract(
        {
            "requirement_refs": ["FR-001"],
            "given": [
                {"path": "service.running", "operator": "eq", "value": True},
                {"path": "service.running", "operator": "eq", "value": False},
            ],
            "when": {"action": "health", "arguments": {}},
            "then": [{"path": "result.status", "operator": "eq", "value": "ok"}],
        }
    )

    with pytest.raises(AcceptanceCompileError) as failure:
        compile_acceptance_plan(
            contract,
            repository_root=tmp_path,
            registered_actions=frozenset({"health"}),
            template_version="barebones-1",
            template_test_digests={},
        )

    assert any(item.code == "CONTRADICTORY_ASSERTIONS" for item in failure.value.diagnostics)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (("gt", 5), ("lte", 5)),
        (("gte", 6), ("lt", 6)),
        (("eq", 5), ("gt", 5)),
    ],
)
def test_ordered_contradictions_fail_at_compile_time(
    tmp_path: Path,
    left: tuple[str, int],
    right: tuple[str, int],
) -> None:
    contract = _contract(
        {
            "requirement_refs": ["FR-001"],
            "given": [
                {"path": "service.count", "operator": left[0], "value": left[1]},
                {"path": "service.count", "operator": right[0], "value": right[1]},
            ],
            "when": {"action": "health", "arguments": {}},
            "then": [{"path": "result.status", "operator": "eq", "value": "ok"}],
        }
    )

    with pytest.raises(AcceptanceCompileError) as failure:
        compile_acceptance_plan(
            contract,
            repository_root=tmp_path,
            registered_actions=frozenset({"health"}),
            template_version="barebones-1",
            template_test_digests={},
        )

    assert any(item.code == "CONTRADICTORY_ASSERTIONS" for item in failure.value.diagnostics)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (("eq", True), ("is_false", None)),
        (("eq", None), ("not_null", None)),
        (("ne", True), ("is_true", None)),
        (("is_null", None), ("ne", None)),
    ],
)
def test_equality_and_unary_contradictions_fail_at_compile_time(
    tmp_path: Path,
    left: tuple[str, object],
    right: tuple[str, object],
) -> None:
    contract = _contract(
        {
            "requirement_refs": ["FR-001"],
            "given": [
                {"path": "service.value", "operator": left[0], "value": left[1]},
                {"path": "service.value", "operator": right[0], "value": right[1]},
            ],
            "when": {"action": "health", "arguments": {}},
            "then": [{"path": "result.status", "operator": "eq", "value": "ok"}],
        }
    )

    with pytest.raises(AcceptanceCompileError) as failure:
        compile_acceptance_plan(
            contract,
            repository_root=tmp_path,
            registered_actions=frozenset({"health"}),
            template_version="barebones-1",
            template_test_digests={},
        )

    assert any(item.code == "CONTRADICTORY_ASSERTIONS" for item in failure.value.diagnostics)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (("eq", "x"), ("gt", 1)),
        (("eq", True), ("gt", 0)),
        (("gt", "x"), ("lt", 1)),
    ],
)
def test_incompatible_equality_and_ordered_bounds_fail_at_compile_time(
    tmp_path: Path,
    left: tuple[str, object],
    right: tuple[str, object],
) -> None:
    contract = _contract(
        {
            "requirement_refs": ["FR-001"],
            "given": [
                {"path": "service.value", "operator": left[0], "value": left[1]},
                {"path": "service.value", "operator": right[0], "value": right[1]},
            ],
            "when": {"action": "health", "arguments": {}},
            "then": [{"path": "result.status", "operator": "eq", "value": "ok"}],
        }
    )

    with pytest.raises(AcceptanceCompileError) as failure:
        compile_acceptance_plan(
            contract,
            repository_root=tmp_path,
            registered_actions=frozenset({"health"}),
            template_version="barebones-1",
            template_test_digests={},
        )

    assert any(item.code == "CONTRADICTORY_ASSERTIONS" for item in failure.value.diagnostics)


def test_equal_contains_and_not_contains_are_contradictory(tmp_path: Path) -> None:
    contract = _contract(
        {
            "requirement_refs": ["FR-001"],
            "given": [
                {"path": "service.values", "operator": "contains", "value": True},
                {"path": "service.values", "operator": "not_contains", "value": True},
            ],
            "when": {"action": "health", "arguments": {}},
            "then": [{"path": "result.status", "operator": "eq", "value": "ok"}],
        }
    )

    with pytest.raises(AcceptanceCompileError) as failure:
        compile_acceptance_plan(
            contract,
            repository_root=tmp_path,
            registered_actions=frozenset({"health"}),
            template_version="barebones-1",
            template_test_digests={},
        )

    assert any(item.code == "CONTRADICTORY_ASSERTIONS" for item in failure.value.diagnostics)


@pytest.mark.parametrize(
    "assertions",
    [
        [
            {"path": "service.value", "operator": "gte", "value": 5},
            {"path": "service.value", "operator": "lte", "value": 5},
            {"path": "service.value", "operator": "ne", "value": 5},
        ],
        [
            {"path": "service.value", "operator": "is_true"},
            {"path": "service.value", "operator": "gt", "value": 0},
        ],
        [
            {"path": "service.value", "operator": "is_null"},
            {"path": "service.value", "operator": "matches", "value": ".*"},
        ],
        [
            {"path": "service.value", "operator": "is_false"},
            {"path": "service.value", "operator": "contains", "value": False},
        ],
        [
            {"path": "service.value", "operator": "gte", "value": 1},
            {"path": "service.value", "operator": "gte", "value": "a"},
        ],
    ],
)
def test_multi_assertion_and_unary_type_contradictions_fail_before_build(
    tmp_path: Path, assertions: list[dict[str, object]]
) -> None:
    contract = _contract(
        {
            "requirement_refs": ["FR-001"],
            "given": assertions,
            "when": {"action": "health", "arguments": {}},
            "then": [{"path": "result.status", "operator": "eq", "value": "ok"}],
        }
    )

    with pytest.raises(AcceptanceCompileError) as failure:
        compile_acceptance_plan(
            contract,
            repository_root=tmp_path,
            registered_actions=frozenset({"health"}),
            template_version="barebones-1",
            template_test_digests={},
        )

    assert any(item.code == "CONTRADICTORY_ASSERTIONS" for item in failure.value.diagnostics)


@pytest.mark.parametrize(
    ("assertion", "code"),
    [
        ({"path": "service.value", "operator": "eq"}, "MISSING_ASSERTION_VALUE"),
        (
            {"path": "service.value", "operator": "matches", "value": "["},
            "INVALID_REGEX_ASSERTION",
        ),
        (
            {"path": "service.value", "operator": "matches", "value": 1},
            "INVALID_REGEX_ASSERTION",
        ),
    ],
)
def test_binary_assertion_operands_are_validated_before_build(
    tmp_path: Path, assertion: dict[str, object], code: str
) -> None:
    contract = _contract(
        {
            "requirement_refs": ["FR-001"],
            "given": [assertion],
            "when": {"action": "health", "arguments": {}},
            "then": [{"path": "result.status", "operator": "eq", "value": "ok"}],
        }
    )

    with pytest.raises(AcceptanceCompileError) as failure:
        compile_acceptance_plan(
            contract,
            repository_root=tmp_path,
            registered_actions=frozenset({"health"}),
            template_version="barebones-1",
            template_test_digests={},
        )

    assert any(item.code == code for item in failure.value.diagnostics)


def test_measure_requires_a_registered_observation_source(tmp_path: Path) -> None:
    contract = _contract(
        {
            "requirement_refs": ["FR-001"],
            "measure": "latency.p95_ms",
            "operator": "lte",
            "value": 200,
            "sample": {"minimum": 20},
        }
    )

    with pytest.raises(AcceptanceCompileError) as failure:
        compile_acceptance_plan(
            contract,
            repository_root=tmp_path,
            registered_actions=frozenset(),
            template_version="barebones-1",
            template_test_digests={},
        )

    assert failure.value.diagnostics[0].code == "MEASURE_INVALID"


@pytest.mark.parametrize(
    ("operator", "value", "code"),
    [
        ("matches", "[", "INVALID_REGEX_ASSERTION"),
        ("matches", 42, "INVALID_REGEX_ASSERTION"),
        ("lte", None, "INVALID_ORDERED_ASSERTION_VALUE"),
        ("gt", True, "INVALID_ORDERED_ASSERTION_VALUE"),
    ],
)
def test_measure_assertion_operands_are_validated_before_build(
    tmp_path: Path, operator: str, value: object, code: str
) -> None:
    contract = _contract(
        {
            "requirement_refs": ["FR-001"],
            "measure": "latency.p95_ms",
            "operator": operator,
            "value": value,
            "sample": {"minimum": 20},
        }
    )

    with pytest.raises(AcceptanceCompileError) as failure:
        compile_acceptance_plan(
            contract,
            repository_root=tmp_path,
            registered_actions=frozenset(),
            template_version="barebones-1",
            template_test_digests={},
            registered_measures=frozenset({"latency.p95_ms"}),
        )

    assert any(item.code == code for item in failure.value.diagnostics)
