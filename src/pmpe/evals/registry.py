"""Agent-level eval registry (provider-neutral, fixture-driven).

Each agent's cases live in evals/agents/<agent>.yaml. Cases are validated by the
same deterministic submission validators the engine uses at admission time — so
a planted failure the eval accepts would also slip into a live run, and vice
versa. Permission and stage-fire cases are auto-generated from the agent
definitions and the stage map (both are enforced surfaces, not documentation).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from pmpe.agents.permissions import REVIEWER_NAMES, is_read_only
from pmpe.agents.registry import AgentRegistry
from pmpe.engineering.submissions import VALIDATORS, validate_routing_submission

# Which stage each agent is allowed to act in — used by the engine for admission
# and by the fire/no-fire eval cases.
STAGE_AGENTS: dict[str, tuple[str, ...]] = {
    "architecture": ("v2-system-architect",),
    "plan": ("v2-implementation-planner",),
    "route": ("v2-engineer-router",),
    "implement": ("v2-backend-engineer", "v2-test-engineer"),
    "integrate": ("v2-integration-engineer",),
    "review": REVIEWER_NAMES,
    "fix": ("v2-approved-findings-fixer",),
}

_READ_ONLY_EXPECTED = frozenset(
    {
        "v2-system-architect",
        "v2-implementation-planner",
        "v2-engineer-router",
        *REVIEWER_NAMES,
    }
)
_WORKTREE_EXPECTED = frozenset({"v2-backend-engineer", "v2-test-engineer"})


def should_fire(agent: str, stage: str) -> bool:
    return agent in STAGE_AGENTS.get(stage, ())


def stage_of(agent: str) -> str:
    for stage, agents in STAGE_AGENTS.items():
        if agent in agents:
            return stage
    return ""


@dataclass(frozen=True)
class EvalCase:
    id: str
    kind: str  # valid_output | planted_failure | product_boundary | escalation
    expect: str  # valid | invalid
    output: dict[str, Any]
    context: dict[str, Any]
    hard_gate: bool = False


@dataclass(frozen=True)
class AgentEvalSpec:
    agent: str
    stage: str
    cases: list[EvalCase]


@dataclass(frozen=True)
class CaseResult:
    agent: str
    case_id: str
    kind: str
    passed: bool
    hard_gate: bool
    detail: str


@dataclass
class EvalResults:
    results: list[CaseResult] = field(default_factory=list)

    @property
    def pass_rate_by_agent(self) -> dict[str, float]:
        totals: dict[str, list[int]] = {}
        for result in self.results:
            bucket = totals.setdefault(result.agent, [0, 0])
            bucket[1] += 1
            bucket[0] += int(result.passed)
        return {agent: round(p / t, 4) for agent, (p, t) in sorted(totals.items())}

    @property
    def hard_gate_failures(self) -> list[str]:
        return [f"{r.agent}:{r.case_id}" for r in self.results if r.hard_gate and not r.passed]

    def to_dict(self) -> dict[str, Any]:
        return {
            "results": [
                {
                    "agent": r.agent,
                    "case_id": r.case_id,
                    "kind": r.kind,
                    "passed": r.passed,
                    "hard_gate": r.hard_gate,
                    "detail": r.detail,
                }
                for r in self.results
            ],
            "pass_rate_by_agent": self.pass_rate_by_agent,
            "hard_gate_failures": self.hard_gate_failures,
        }


def load_eval_suite(evals_dir: Path) -> list[AgentEvalSpec]:
    suite: list[AgentEvalSpec] = []
    for path in sorted(Path(evals_dir).glob("*.yaml")):
        raw: dict[str, Any] = yaml.safe_load(path.read_text())
        cases = [
            EvalCase(
                id=str(c["id"]),
                kind=str(c["kind"]),
                expect=str(c["expect"]),
                output=dict(c.get("output", {})),
                context=dict(c.get("context", {})),
                hard_gate=bool(c.get("hard_gate", False)),
            )
            for c in raw.get("cases", [])
        ]
        suite.append(
            AgentEvalSpec(agent=str(raw["agent"]), stage=str(raw.get("stage", "")), cases=cases)
        )
    return suite


def run_agent_evals(suite: list[AgentEvalSpec], registry: AgentRegistry) -> EvalResults:
    results = EvalResults()
    for spec in suite:
        results.results.extend(_permission_cases(spec.agent, registry))
        results.results.extend(_fire_cases(spec.agent, spec.stage))
        for case in spec.cases:
            errors = _validate(spec.agent, case, registry)
            is_valid = not errors
            passed = is_valid == (case.expect == "valid")
            results.results.append(
                CaseResult(
                    agent=spec.agent,
                    case_id=case.id,
                    kind=case.kind,
                    passed=passed,
                    hard_gate=case.hard_gate or case.kind == "planted_failure",
                    detail="; ".join(errors)[:300],
                )
            )
    return results


def _validate(agent: str, case: EvalCase, registry: AgentRegistry) -> list[str]:
    if agent == "v2-engineer-router":
        return validate_routing_submission(case.output, case.context, registry)
    validator = VALIDATORS.get(agent)
    if validator is None:
        return [f"no validator for agent '{agent}'"]
    return validator(case.output, case.context)


def _permission_cases(agent: str, registry: AgentRegistry) -> list[CaseResult]:
    if not registry.has(agent):
        return [
            CaseResult(
                agent, "permission-defined", "permission", False, True, "no agent definition"
            )
        ]
    definition = registry.get(agent)
    cases: list[CaseResult] = []
    if agent in _READ_ONLY_EXPECTED:
        ok = is_read_only(definition)
        cases.append(
            CaseResult(
                agent,
                "permission-read-only",
                "permission",
                ok,
                True,
                "" if ok else f"tools: {', '.join(definition.tools) or '<inherit-all>'}",
            )
        )
    if agent in _WORKTREE_EXPECTED:
        ok = definition.isolation == "worktree"
        cases.append(
            CaseResult(
                agent,
                "permission-worktree",
                "permission",
                ok,
                True,
                "" if ok else f"isolation: {definition.isolation!r}",
            )
        )
    return cases


def _fire_cases(agent: str, declared_stage: str) -> list[CaseResult]:
    actual_stage = stage_of(agent)
    fire_ok = should_fire(agent, actual_stage) and actual_stage == declared_stage
    wrong_stage = "review" if actual_stage != "review" else "implement"
    no_fire_ok = not should_fire(agent, wrong_stage)
    return [
        CaseResult(
            agent,
            "fires-at-own-stage",
            "routing",
            fire_ok,
            False,
            f"declared={declared_stage} actual={actual_stage}",
        ),
        CaseResult(agent, f"does-not-fire-at-{wrong_stage}", "routing", no_fire_ok, False, ""),
    ]
