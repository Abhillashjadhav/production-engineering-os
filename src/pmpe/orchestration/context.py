"""Run context: lazy access to run state, artifacts, and escalation machinery.

Deterministic products (plan, architecture, generated files) are recomputed on
demand (ADR-002); everything else round-trips through artifacts so resumes are
exact.
"""

from __future__ import annotations

from pmpe.architecture.agent import ArchitectureAgent
from pmpe.artifacts.store import ArtifactStore
from pmpe.config import PipelineConfig
from pmpe.domain.models import (
    Approval,
    ArchitectureOutput,
    EngineeringPlan,
    Escalation,
    GeneratedTests,
    Implementation,
    MvpSpec,
    RiskLevel,
)
from pmpe.domain.serialize import atomic_write_json
from pmpe.gitops.local import LocalGitAdapter
from pmpe.implementation.agent import StdlibCrudGenerator
from pmpe.ingestion import ingest
from pmpe.orchestration import decoders
from pmpe.orchestration.state import RunState
from pmpe.planning.planner import EngineeringPlanner
from pmpe.policies.engine import PolicyEngine
from pmpe.quality.gates import (
    QualityGateRunner,
)
from pmpe.telemetry.events import EventLog, utc_now
from pmpe.testing.architect import TestArchitect


class _Blocked(Exception):  # noqa: N818 — control-flow signal, not an error
    pass


class _Rejected(Exception):  # noqa: N818 — control-flow signal, not an error
    pass


class RunContext:
    """Lazy access to everything a step needs; deterministic products are recomputed."""

    def __init__(self, config: PipelineConfig, state: RunState) -> None:
        self.config = config
        self.state = state
        self.store = ArtifactStore(state.run_dir)
        self.events = EventLog(state.run_dir)
        self.workspace = state.run_dir / "workspace"
        self.branch = f"build/{state.run_id}"
        self._spec: MvpSpec | None = None
        self._plan: EngineeringPlan | None = None
        self._arch: ArchitectureOutput | None = None
        self._tests: GeneratedTests | None = None
        self._impl: Implementation | None = None

    @property
    def spec(self) -> MvpSpec:
        if self._spec is None:
            spec_path = self.state.run_dir / self.state.spec_file
            self._spec = ingest(spec_path, self.config.schema_path)
        return self._spec

    @property
    def plan(self) -> EngineeringPlan:
        if self._plan is None:
            self._plan = EngineeringPlanner().plan(self.spec)
        return self._plan

    @property
    def architecture(self) -> ArchitectureOutput:
        if self._arch is None:
            self._arch = ArchitectureAgent(PolicyEngine()).design(self.spec, self.plan)
        return self._arch

    @property
    def generated_tests(self) -> GeneratedTests:
        if self._tests is None:
            self._tests = TestArchitect().design(self.spec, self.plan)
        return self._tests

    @property
    def implementation(self) -> Implementation:
        if self._impl is None:
            self._impl = StdlibCrudGenerator().implement(self.spec, self.plan)
        return self._impl

    @property
    def git(self) -> LocalGitAdapter:
        return LocalGitAdapter(self.workspace)

    @property
    def gate_runner(self) -> QualityGateRunner:
        return QualityGateRunner(self.workspace, tuple(self.config.required_gates))

    def load_escalations(self) -> list[Escalation]:
        return decoders.load_escalations(self.state.run_dir)

    def load_approvals(self) -> dict[str, Approval]:
        return decoders.load_approvals(self.state.run_dir)

    def ensure_escalation(
        self, *, key: str, step: str, risk: RiskLevel, reason: str, rule: str
    ) -> tuple[Escalation, bool]:
        """Create-or-return the escalation identified by ``key``.

        Single owner of id allocation (max existing suffix + 1, collision-proof
        across gaps) and of the dedup convention that makes resume idempotent.
        """
        existing = self.load_escalations()
        for esc in existing:
            if esc.context.get("key") == key:
                return esc, False
        highest = 0
        for esc in existing:
            _, _, suffix = esc.id.partition("-")
            if suffix.isdigit():
                highest = max(highest, int(suffix))
        new = Escalation(
            id=f"ESC-{highest + 1:03d}",
            risk=risk,
            reason=reason,
            step=step,
            context={"key": key, "rule": rule},
            created_at=utc_now(),
        )
        self._write_escalation(new)
        return new, True

    def _write_escalation(self, esc: Escalation) -> None:
        atomic_write_json(self.state.run_dir / "escalations" / f"{esc.id}.json", esc)
        self.events.emit(
            "escalation_created",
            escalation_id=esc.id,
            step=esc.step,
            reason=esc.reason,
        )
