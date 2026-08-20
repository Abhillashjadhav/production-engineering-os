from __future__ import annotations

from pathlib import Path

from pmpe.agents.registry import AgentRegistry
from pmpe.agents.router import SPECIALIST_PROFILES


def test_every_declared_specialist_has_worktree_definition_and_eval_contract() -> None:
    root = Path(__file__).resolve().parents[2]
    registry = AgentRegistry(root / ".claude" / "agents")

    for specialist in sorted(set(SPECIALIST_PROFILES.values())):
        definition = registry.get(specialist)
        assert definition.isolation == "worktree"
        assert definition.tools
        eval_name = specialist if specialist.startswith("v2-") else f"v2-{specialist}"
        assert (root / "evals" / "agents" / f"{eval_name}.yaml").is_file()
