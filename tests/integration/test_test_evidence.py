"""The evidence runner captures per-node outcomes and failure kinds from a real
unittest workspace — the executed ground truth traceability binds to."""

from __future__ import annotations

from pathlib import Path

import pytest

from pmpe.quality.test_evidence import run_tests_with_evidence


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "app").mkdir(parents=True)
    (ws / "app" / "__init__.py").write_text("")
    (ws / "app" / "logic.py").write_text("def double(x):\n    return x * 2\n")
    tests = ws / "tests"
    (tests / "unit").mkdir(parents=True)
    (tests / "__init__.py").write_text("")
    (tests / "unit" / "__init__.py").write_text("")
    (tests / "unit" / "test_logic.py").write_text(
        "import unittest\n"
        "from app.logic import double\n\n\n"
        "class LogicTests(unittest.TestCase):\n"
        "    def test_double_works(self):\n"
        "        self.assertEqual(double(2), 4)\n\n"
        "    def test_double_broken_expectation(self):\n"
        "        self.assertEqual(double(2), 5)\n\n"
        "    @unittest.skip('not ready')\n"
        "    def test_skipped_case(self):\n"
        "        self.assertTrue(False)\n\n"
        "    def test_runtime_error(self):\n"
        "        raise RuntimeError('boom')\n"
    )
    (tests / "unit" / "test_missing_import.py").write_text(
        "from app.does_not_exist import nope  # noqa: F401\n"
    )
    return ws


def test_evidence_captures_every_outcome_kind(workspace: Path) -> None:
    evidence = run_tests_with_evidence(workspace)
    by_kind = {(e.outcome, e.failure_kind) for e in evidence.executions}
    assert ("passed", "") in by_kind
    assert ("failed", "assertion") in by_kind
    assert ("skipped", "skip") in by_kind
    assert ("failed", "error") in by_kind
    assert ("failed", "import") in by_kind
    assert not evidence.all_passed


def test_node_ids_are_stable_module_paths(workspace: Path) -> None:
    evidence = run_tests_with_evidence(workspace)
    passing = [e for e in evidence.executions if e.outcome == "passed"]
    assert passing[0].node_id == "tests.unit.test_logic.LogicTests.test_double_works"


def test_green_workspace_reports_all_passed(workspace: Path) -> None:
    test_file = workspace / "tests" / "unit" / "test_logic.py"
    test_file.write_text(
        "import unittest\n"
        "from app.logic import double\n\n\n"
        "class LogicTests(unittest.TestCase):\n"
        "    def test_double_works(self):\n"
        "        self.assertEqual(double(2), 4)\n"
    )
    (workspace / "tests" / "unit" / "test_missing_import.py").unlink()
    evidence = run_tests_with_evidence(workspace)
    assert evidence.all_passed
    assert all(e.outcome == "passed" for e in evidence.executions)
