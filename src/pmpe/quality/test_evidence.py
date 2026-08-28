"""Executed test evidence: per-node outcomes with failure kinds.

Runs a workspace's unittest suite under an evidence-collecting result class (in a
subprocess, stdlib only) and returns typed executions. This output — not markers,
not claims — is what executed traceability binds requirements to.

Failure kinds: ``assertion`` (the test's own expectation failed — meaningful),
``import`` (collection/import error — NOT meaningful evidence), ``error`` (other
exception), ``skip``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from pmpe.domain.errors import StepFailure

_HARNESS = r"""
import json
import sys
import traceback
import unittest


class EvidenceResult(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.records = []

    def _record(self, test, outcome, failure_kind="", detail=""):
        self.records.append(
            {
                "node_id": test.id(),
                "outcome": outcome,
                "failure_kind": failure_kind,
                "detail": detail[-500:],
            }
        )

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, "passed")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        detail = "".join(traceback.format_exception_only(err[0], err[1]))
        self._record(test, "failed", "assertion", detail)

    def addError(self, test, err):
        super().addError(test, err)
        detail = "".join(traceback.format_exception_only(err[0], err[1]))
        kind = "error"
        if issubclass(err[0], (ImportError, ModuleNotFoundError, SyntaxError)):
            kind = "import"
        elif "_FailedTest" in type(test).__name__:
            kind = "import"
        self._record(test, "failed", kind, detail)

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, "skipped", "skip", reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._record(test, "passed", "expected_failure")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._record(test, "failed", "unexpected_success")


def main():
    start_dir, out_path = sys.argv[1], sys.argv[2]
    suite = unittest.defaultTestLoader.discover(start_dir, top_level_dir=".")
    result = EvidenceResult()
    suite.run(result)
    with open(out_path, "w") as fh:
        json.dump(result.records, fh)


if __name__ == "__main__":
    main()
"""


@dataclass(frozen=True)
class TestExecution:
    __test__ = False  # not a pytest class despite the name

    node_id: str
    outcome: str  # passed | failed | skipped
    failure_kind: str  # "" | assertion | import | error | skip | ...
    detail: str = ""


@dataclass
class TestEvidence:
    __test__ = False  # not a pytest class despite the name

    executions: list[TestExecution] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return bool(self.executions) and all(e.outcome == "passed" for e in self.executions)

    def by_node(self) -> dict[str, TestExecution]:
        return {e.node_id: e for e in self.executions}


def run_tests_with_evidence(workspace: Path, start_dir: str = "tests") -> TestEvidence:
    workspace = Path(workspace)
    with tempfile.TemporaryDirectory(prefix="pmpe-evidence-") as tmp:
        harness = Path(tmp) / "evidence_harness.py"
        out = Path(tmp) / "evidence.json"
        harness.write_text(_HARNESS)
        proc = subprocess.run(
            [sys.executable, str(harness), start_dir, str(out)],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if not out.exists():
            raise StepFailure(
                "test_evidence",
                f"evidence harness produced no output (rc={proc.returncode}): {proc.stderr[-500:]}",
            )
        records = json.loads(out.read_text())
    return TestEvidence(
        executions=[
            TestExecution(
                node_id=r["node_id"],
                outcome=r["outcome"],
                failure_kind=r.get("failure_kind", ""),
                detail=r.get("detail", ""),
            )
            for r in records
        ]
    )
