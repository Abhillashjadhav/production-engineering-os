"""Immutable TestPlan persistence and pre-implementation authorization."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .evidence import MeaningfulRedGate, MeaningfulRedRun
from .models import TestPlan


class TestPlanConflictError(RuntimeError):
    pass


class TestPlanNotAdmittedError(RuntimeError):
    pass


TestPlanConflict = TestPlanConflictError
TestPlanNotAdmitted = TestPlanNotAdmittedError


@dataclass(frozen=True)
class TestPlanReceipt:
    plan_digest: str
    artifact_path: str


@dataclass(frozen=True)
class ImplementationAuthorization:
    plan_digest: str
    red_run_digest: str
    commit_sha: str


class TestPlanStore:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = Path(run_dir)
        self.path = self.run_dir / "test-plan.json"

    def admit(self, plan: TestPlan) -> TestPlanReceipt:
        payload = plan.canonical_bytes()
        if self.path.exists():
            if self.path.read_bytes() != payload:
                raise TestPlanConflict(
                    "an immutable different TestPlan already exists for this run"
                )
            if not plan.digest_is_valid() or plan.disposition != "ADMITTED":
                raise TestPlanNotAdmitted("persisted TestPlan is not digest-valid and ADMITTED")
            return TestPlanReceipt(plan.plan_digest, str(self.path))
        if not plan.digest_is_valid() or plan.disposition != "ADMITTED":
            raise TestPlanNotAdmitted("only a digest-valid ADMITTED TestPlan can be persisted")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.run_dir,
                prefix=".test-plan.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            try:
                os.link(temporary_path, self.path)
            except FileExistsError:
                if self.path.read_bytes() != payload:
                    raise TestPlanConflict(
                        "an immutable different TestPlan already exists for this run"
                    ) from None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        return TestPlanReceipt(plan.plan_digest, str(self.path))

    def authorize_implementation(
        self,
        plan: TestPlan,
        red_run: MeaningfulRedRun,
        *,
        expected_commit_sha: str,
    ) -> ImplementationAuthorization:
        if not self.path.exists():
            raise TestPlanNotAdmitted("implementation refused: TestPlan is not persisted")
        try:
            persisted = json.loads(self.path.read_bytes())
        except (OSError, json.JSONDecodeError) as exc:
            raise TestPlanNotAdmitted("persisted TestPlan is unreadable") from exc
        if persisted != plan.as_dict() or not plan.digest_is_valid():
            raise TestPlanNotAdmitted("implementation refused: persisted TestPlan does not match")
        admission = MeaningfulRedGate().validate(
            plan, red_run, expected_commit_sha=expected_commit_sha
        )
        if not admission.admitted:
            rules = ", ".join(item.rule_id for item in admission.diagnostics)
            raise TestPlanNotAdmitted(f"implementation refused: meaningful-red failed ({rules})")
        return ImplementationAuthorization(
            plan_digest=plan.plan_digest,
            red_run_digest=red_run.run_digest(),
            commit_sha=red_run.commit_sha,
        )
