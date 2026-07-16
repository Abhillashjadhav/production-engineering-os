"""The workflow engine: 18 idempotent steps, persisted state, human gates.

Design rules (see ARCHITECTURE.md):
- steps communicate through artifacts, never in-memory state that a resume would lose;
  deterministic products (plan, architecture, generated files) are recomputed from the
  spec on demand (ADR-002)
- a HIGH-risk decision writes an Escalation and blocks; `approve` + `resume` continue
- gate failures never stop the pipeline silently: the run completes through the merge
  gate, which says NO_MERGE with reasons, and the final report still lands

Step bodies live in steps_build.py / steps_ship.py; run-scoped machinery in
context.py; artifact markdown in render.py.
"""

from __future__ import annotations

import hashlib
import secrets
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pmpe.config import PipelineConfig
from pmpe.domain.errors import SpecError, StepFailure
from pmpe.domain.models import Approval, StepStatus
from pmpe.domain.serialize import atomic_write_json
from pmpe.orchestration.context import RunContext, _Blocked, _Rejected
from pmpe.orchestration.state import RunState
from pmpe.orchestration.steps_build import BuildSteps
from pmpe.orchestration.steps_ship import ShipSteps
from pmpe.policies.engine import PolicyEngine
from pmpe.telemetry.events import EventLog, utc_now


@dataclass
class RunResult:
    run_id: str
    status: str  # success | no_merge | blocked | failed
    run_dir: Path
    state: RunState


class WorkflowEngine:
    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.policy = PolicyEngine()

    # --- public API -----------------------------------------------------------------

    def run(self, spec_path: Path) -> RunResult:
        spec_path = Path(spec_path)
        if not spec_path.exists():
            raise SpecError(f"specification file not found: {spec_path}")
        run_id = "run-{}-{}".format(
            datetime.now(UTC).strftime("%Y%m%d-%H%M%S"), secrets.token_hex(3)
        )
        run_dir = self.config.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        spec_copy = run_dir / ("spec" + spec_path.suffix.lower())
        shutil.copyfile(spec_path, spec_copy)
        digest = hashlib.sha256(spec_copy.read_bytes()).hexdigest()
        state = RunState.new(
            run_id=run_id, run_dir=run_dir, spec_digest=digest, spec_file=spec_copy.name
        )
        state.save()
        return self._execute(state)

    def resume(self, run_id: str) -> RunResult:
        state = RunState.load(self.config.runs_dir / run_id)
        # blocked/failed steps are re-executed; done/skipped steps never are
        return self._execute(state)

    def approve(
        self,
        run_id: str,
        escalation_id: str,
        approver: str,
        reason: str,
        approved: bool = True,
    ) -> Approval:
        run_dir = self.config.runs_dir / run_id
        esc_path = run_dir / "escalations" / f"{escalation_id}.json"
        if not esc_path.exists():
            raise StepFailure("approve", f"unknown escalation '{escalation_id}' in {run_id}")
        approval = Approval(
            escalation_id=escalation_id,
            approver=approver,
            reason=reason,
            approved=approved,
            timestamp=utc_now(),
        )
        atomic_write_json(run_dir / "approvals" / f"{escalation_id}.json", approval)
        EventLog(run_dir).emit(
            "approval_recorded",
            escalation_id=escalation_id,
            approver=approver,
            approved=approved,
        )
        return approval

    # --- engine loop ------------------------------------------------------------------

    def _execute(self, state: RunState) -> RunResult:
        ctx = RunContext(self.config, state)
        build = BuildSteps(self.config, self.policy)
        ship = ShipSteps(self.config, self.policy)
        handlers = {
            "ingest": build._step_ingest,
            "validate": build._step_validate,
            "plan": build._step_plan,
            "architecture": build._step_architecture,
            "acceptance": build._step_acceptance,
            "generate_tests": build._step_generate_tests,
            "confirm_red": build._step_confirm_red,
            "implement": build._step_implement,
            "quality_gates": ship._step_quality_gates,
        }
        while (step := state.next_step()) is not None:
            if self.config.chaos_fail_at_step == step:
                state.mark(step, StepStatus.FAILED, detail="chaos_fail_at_step (test hook)")
                state.outcome = "failed"
                state.save()
                ctx.events.emit("step_failed", step=step, error="chaos hook")
                return RunResult(state.run_id, "failed", state.run_dir, state)
            state.mark(step, StepStatus.RUNNING)
            state.save()
            ctx.events.emit("step_started", step=step)
            try:
                handlers[step](ctx)
            except _Blocked as blocked:
                state.mark(step, StepStatus.BLOCKED, detail=str(blocked))
                state.outcome = "blocked"
                state.save()
                ctx.events.emit("step_blocked", step=step, reason=str(blocked))
                return RunResult(state.run_id, "blocked", state.run_dir, state)
            except _Rejected as rejected:
                state.mark(step, StepStatus.FAILED, detail=str(rejected))
                state.outcome = "failed"
                state.save()
                ctx.events.emit("step_failed", step=step, error=str(rejected))
                return RunResult(state.run_id, "failed", state.run_dir, state)
            except SpecError:
                state.mark(step, StepStatus.FAILED, detail="specification rejected")
                state.outcome = "failed"
                state.save()
                ctx.events.emit("step_failed", step=step, error="specification rejected")
                raise
            except Exception as exc:
                state.mark(step, StepStatus.FAILED, detail=str(exc)[:500])
                state.outcome = "failed"
                state.save()
                ctx.events.emit("step_failed", step=step, error=str(exc)[:500])
                raise
            if state.status_of(step) is StepStatus.RUNNING:
                state.mark(step, StepStatus.DONE)
            state.save()
            ctx.events.emit("step_completed", step=step, status=state.status_of(step).value)

        outcome = "success"
        state.outcome = outcome
        state.save()
        ctx.events.emit("run_finished", outcome=outcome)
        return RunResult(state.run_id, outcome, state.run_dir, state)
