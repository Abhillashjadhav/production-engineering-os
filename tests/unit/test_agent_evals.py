"""Agent-level evals: every agent's cases run deterministically against its
validators, tool permissions, and stage-fire rules."""

from __future__ import annotations

from pathlib import Path

from pmpe.agents.registry import AgentRegistry
from pmpe.evals.registry import load_eval_suite, run_agent_evals

REPO_ROOT = Path(__file__).resolve().parents[2]
EVALS_DIR = REPO_ROOT / "evals" / "agents"

MINIMUM_AGENTS = {
    "v2-system-architect",
    "v2-implementation-planner",
    "v2-engineer-router",
    "v2-backend-engineer",
    "frontend-engineer",
    "data-migration-engineer",
    "eval-engineer",
    "security-engineer",
    "platform-reliability-engineer",
    "v2-integration-engineer",
    "v2-code-reviewer",
    "v2-product-conformance-reviewer",
    "v2-architecture-simplicity-reviewer",
    "v2-eval-integrity-auditor",
    "v2-approved-findings-fixer",
}


def _run():  # noqa: ANN202
    registry = AgentRegistry(REPO_ROOT / ".claude" / "agents")
    suite = load_eval_suite(EVALS_DIR)
    return run_agent_evals(suite, registry)


def test_every_required_agent_has_eval_cases() -> None:
    suite = load_eval_suite(EVALS_DIR)
    assert {s.agent for s in suite} >= MINIMUM_AGENTS


def test_case_kinds_cover_the_required_dimensions() -> None:
    suite = load_eval_suite(EVALS_DIR)
    for spec in suite:
        if spec.agent not in MINIMUM_AGENTS:
            continue
        kinds = {c.kind for c in spec.cases}
        assert "valid_output" in kinds, spec.agent
        assert "planted_failure" in kinds, spec.agent
        # permission + fire/no-fire cases are auto-generated per agent by the runner


def test_full_suite_passes_on_current_definitions() -> None:
    results = _run()
    failures = [r for r in results.results if not r.passed]
    assert failures == [], [f"{r.agent}:{r.case_id}" for r in failures]


def test_planted_failures_are_actually_exercised() -> None:
    """Every planted-failure case must expect INVALID — a planted failure the
    validator accepts would mean the gate is decorative."""
    suite = load_eval_suite(EVALS_DIR)
    planted = [c for s in suite for c in s.cases if c.kind == "planted_failure"]
    assert planted
    assert all(c.expect == "invalid" for c in planted)


def test_results_report_pass_rates_and_hard_gates() -> None:
    results = _run()
    assert results.pass_rate_by_agent
    assert all(0.0 <= rate <= 1.0 for rate in results.pass_rate_by_agent.values())
    hard_gate_cases = [r for r in results.results if r.hard_gate]
    assert hard_gate_cases, "permission and planted-failure cases are hard gates"


def test_permission_case_fails_if_reviewer_gains_write_tool(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    source = (REPO_ROOT / ".claude" / "agents" / "v2-code-reviewer.md").read_text()
    (agents_dir / "v2-code-reviewer.md").write_text(
        source.replace("tools: Read, Grep, Glob", "tools: Read, Grep, Glob, Write")
    )
    registry = AgentRegistry(agents_dir)
    suite = [s for s in load_eval_suite(EVALS_DIR) if s.agent == "v2-code-reviewer"]
    results = run_agent_evals(suite, registry)
    permission_results = [r for r in results.results if r.kind == "permission"]
    assert any(not r.passed for r in permission_results)
