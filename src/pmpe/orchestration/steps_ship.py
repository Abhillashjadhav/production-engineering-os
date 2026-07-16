"""Workflow ship steps. At this stage: the quality-gate step; review/merge/deploy
steps land with their own PRs."""

from __future__ import annotations

from pmpe.config import PipelineConfig
from pmpe.orchestration.context import RunContext
from pmpe.policies.engine import PolicyEngine


class ShipSteps:
    def __init__(self, config: PipelineConfig, policy: PolicyEngine) -> None:
        self.config = config
        self.policy = policy

    def _run_gates(self, ctx: RunContext, artifact: str, stage: str) -> None:
        results = ctx.gate_runner.run()
        ctx.store.write_json(artifact, results)
        for result in results:
            ctx.events.emit(
                "gate_result",
                stage=stage,
                gate=result.gate,
                passed=result.passed,
                required=result.required,
                skipped=result.skipped,
            )

    def _step_quality_gates(self, ctx: RunContext) -> None:
        self._run_gates(ctx, "gate_results.json", "quality_gates")
