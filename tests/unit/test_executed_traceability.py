"""Executed traceability: coverage is proven by executed test results, never by
markers. Anti-gaming battery required by the V2 spec."""

from __future__ import annotations

import pytest

from pmpe.audit.executed import (
    build_executed_traceability,
    normalize_node_id,
    red_summary,
)
from pmpe.quality.test_evidence import TestEvidence, TestExecution


def _evidence(*executions: TestExecution) -> TestEvidence:
    return TestEvidence(executions=list(executions))


def _execution(node: str, outcome: str, failure_kind: str = "") -> TestExecution:
    return TestExecution(node_id=node, outcome=outcome, failure_kind=failure_kind, detail="")


PASSING = _execution("tests.unit.test_app.AppTests.test_ok", "passed")
ASSERT_FAIL = _execution(
    "tests.unit.test_app.AppTests.test_broken", "failed", failure_kind="assertion"
)
SKIPPED = _execution("tests.unit.test_app.AppTests.test_skipped", "skipped", "skip")
IMPORT_FAIL = _execution(
    "unittest.loader._FailedTest.tests.integration.test_api", "failed", "import"
)


def _build(
    requirements: list[str],
    mapping: dict[str, list[str]],
    evidence: TestEvidence,
    blocked: set[str] | None = None,
):  # noqa: ANN202
    return build_executed_traceability(
        requirement_ids=requirements,
        tests_by_requirement=mapping,
        evidence=evidence,
        blocked_requirements=blocked or set(),
    )


def test_passing_execution_verifies_and_references_the_exact_node() -> None:
    report = _build(
        ["FR-001"],
        {"FR-001": ["tests/unit/test_app.py::AppTests::test_ok"]},
        _evidence(PASSING),
    )
    entry = report.entries[0]
    assert entry.classification == "VERIFIED"
    assert entry.evidence_nodes == ["tests.unit.test_app.AppTests.test_ok"]


def test_fake_covers_marker_does_not_create_coverage() -> None:
    """A marker naming a test that never executed proves nothing."""
    report = _build(
        ["FR-001"],
        {"FR-001": ["tests/unit/test_app.py::AppTests::test_i_do_not_exist"]},
        _evidence(PASSING),
    )
    entry = report.entries[0]
    assert entry.classification == "NOT_PROVEN"
    assert any("not executed" in r for r in entry.reasons)


def test_requirement_with_no_mapping_is_not_proven() -> None:
    report = _build(["FR-009"], {}, _evidence(PASSING))
    assert report.entries[0].classification == "NOT_PROVEN"


def test_skipped_test_does_not_create_coverage() -> None:
    report = _build(
        ["FR-001"],
        {"FR-001": ["tests/unit/test_app.py::AppTests::test_skipped"]},
        _evidence(SKIPPED),
    )
    entry = report.entries[0]
    assert entry.classification == "NOT_PROVEN"
    assert any("skipped" in r for r in entry.reasons)


def test_assertion_failure_classifies_failed() -> None:
    report = _build(
        ["FR-001"],
        {"FR-001": ["tests/unit/test_app.py::AppTests::test_broken"]},
        _evidence(ASSERT_FAIL),
    )
    assert report.entries[0].classification == "FAILED"


def test_import_error_is_not_meaningful_evidence_either_way() -> None:
    report = _build(
        ["FR-001"],
        {"FR-001": ["tests/integration/test_api.py::ApiTests::test_anything"]},
        _evidence(IMPORT_FAIL),
    )
    entry = report.entries[0]
    assert entry.classification == "NOT_PROVEN"
    assert any("import" in r for r in entry.reasons)


def test_import_failure_inside_an_executed_test_is_not_evidence() -> None:
    """A mapped test whose own body died on an import EXECUTED under its own node
    id — but an import death is never meaningful evidence: NOT_PROVEN, never
    VERIFIED (distinct from the loader collection-death path above)."""
    executed_import_fail = _execution(
        "tests.unit.test_app.AppTests.test_uses_missing_dep", "failed", "import"
    )
    report = _build(
        ["FR-001"],
        {"FR-001": ["tests/unit/test_app.py::AppTests::test_uses_missing_dep"]},
        _evidence(executed_import_fail),
    )
    entry = report.entries[0]
    assert entry.classification == "NOT_PROVEN"
    assert any("import" in r for r in entry.reasons)


def test_open_product_decision_blocks_the_requirement() -> None:
    report = _build(
        ["FR-001"],
        {"FR-001": ["tests/unit/test_app.py::AppTests::test_ok"]},
        _evidence(PASSING),
        blocked={"FR-001"},
    )
    assert report.entries[0].classification == "BLOCKED_PRODUCT_DECISION"


def test_mixed_pass_and_assertion_failure_is_failed() -> None:
    report = _build(
        ["FR-001"],
        {
            "FR-001": [
                "tests/unit/test_app.py::AppTests::test_ok",
                "tests/unit/test_app.py::AppTests::test_broken",
            ]
        },
        _evidence(PASSING, ASSERT_FAIL),
    )
    assert report.entries[0].classification == "FAILED"


def test_report_is_complete_only_when_all_requirements_verified() -> None:
    report = _build(
        ["FR-001", "FR-002"],
        {"FR-001": ["tests/unit/test_app.py::AppTests::test_ok"]},
        _evidence(PASSING),
    )
    assert not report.all_verified
    assert report.counts["VERIFIED"] == 1
    assert report.counts["NOT_PROVEN"] == 1


# --- red meaningfulness -----------------------------------------------------------------


def test_red_summary_distinguishes_assertion_from_import_failures() -> None:
    summary = red_summary(_evidence(ASSERT_FAIL, IMPORT_FAIL, SKIPPED))
    assert summary["assertion"] == 1
    assert summary["import"] == 1
    assert summary["meaningful_red"] is True

    import_only = red_summary(_evidence(IMPORT_FAIL))
    assert import_only["meaningful_red"] is False


# --- node id normalization ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "tests/unit/test_app.py::AppTests::test_ok",
            "tests.unit.test_app.AppTests.test_ok",
        ),
        ("tests.unit.test_app.AppTests.test_ok", "tests.unit.test_app.AppTests.test_ok"),
    ],
)
def test_normalize_node_id(raw: str, expected: str) -> None:
    assert normalize_node_id(raw) == expected
