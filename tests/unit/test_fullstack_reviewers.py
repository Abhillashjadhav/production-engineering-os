"""PD-V3-15: six independent full-stack assurance lenses, each a fresh-context
read-only reviewer — read-only proven from the tool configuration the runtime
actually grants, and the roster enforced so no lens can silently disappear."""

from __future__ import annotations

from pathlib import Path

import pytest

from pmpe.agents.permissions import (
    FULLSTACK_REVIEW_LENSES,
    ReadOnlyViolation,
    assert_fullstack_reviewers_read_only,
    is_read_only,
)
from pmpe.agents.registry import AgentRegistry

AGENTS_DIR = Path(__file__).resolve().parents[2] / ".claude" / "agents"


@pytest.fixture()
def registry() -> AgentRegistry:
    return AgentRegistry(AGENTS_DIR)


def test_the_roster_covers_exactly_the_six_pd_v3_15_lenses() -> None:
    assert set(FULLSTACK_REVIEW_LENSES) == {
        "ux-journey",
        "frontend-accessibility",
        "backend-api-security",
        "architecture-simplicity",
        "product-conformance",
        "evidence-integrity",
    }


def test_every_lens_maps_to_a_v3_agent_definition(registry: AgentRegistry) -> None:
    for lens, name in FULLSTACK_REVIEW_LENSES.items():
        assert name.startswith("v3-"), (lens, name)
        assert registry.has(name), f"lens '{lens}' has no agent definition '{name}'"


def test_every_fullstack_reviewer_is_read_only_by_tool_configuration(
    registry: AgentRegistry,
) -> None:
    for name in FULLSTACK_REVIEW_LENSES.values():
        agent = registry.get(name)
        assert is_read_only(agent), f"{name} tools: {agent.tools}"


def test_assert_passes_on_the_real_registry(registry: AgentRegistry) -> None:
    assert_fullstack_reviewers_read_only(registry)


def test_a_write_capable_tool_is_a_violation(tmp_path: Path) -> None:
    for name in FULLSTACK_REVIEW_LENSES.values():
        (tmp_path / f"{name}.md").write_text(
            f"---\nname: {name}\ndescription: x\ntools: Read, Grep, Glob\n---\nbody\n"
        )
    target = next(iter(FULLSTACK_REVIEW_LENSES.values()))
    (tmp_path / f"{target}.md").write_text(
        f"---\nname: {target}\ndescription: x\ntools: Read, Grep, Glob, Bash\n---\nbody\n"
    )
    with pytest.raises(ReadOnlyViolation, match="Bash"):
        assert_fullstack_reviewers_read_only(AgentRegistry(tmp_path))


def test_a_missing_lens_definition_is_a_violation(tmp_path: Path) -> None:
    names = list(FULLSTACK_REVIEW_LENSES.values())
    for name in names[:-1]:  # one lens has no definition at all
        (tmp_path / f"{name}.md").write_text(
            f"---\nname: {name}\ndescription: x\ntools: Read, Grep, Glob\n---\nbody\n"
        )
    with pytest.raises(ReadOnlyViolation, match="no agent definition"):
        assert_fullstack_reviewers_read_only(AgentRegistry(tmp_path))


def test_an_inherit_all_tool_list_is_a_violation(tmp_path: Path) -> None:
    for name in FULLSTACK_REVIEW_LENSES.values():
        (tmp_path / f"{name}.md").write_text(
            f"---\nname: {name}\ndescription: x\ntools: Read, Grep, Glob\n---\nbody\n"
        )
    target = next(iter(FULLSTACK_REVIEW_LENSES.values()))
    (tmp_path / f"{target}.md").write_text(
        f"---\nname: {target}\ndescription: x\n---\nbody\n"  # no tool list = inherit all
    )
    with pytest.raises(ReadOnlyViolation, match="inherit"):
        assert_fullstack_reviewers_read_only(AgentRegistry(tmp_path))


def test_definitions_declare_their_charter_honestly(registry: AgentRegistry) -> None:
    """Each lens definition must say it is read-only and never fixes — the
    description is what routes the agent, so dishonest routing text is a
    real defect, not cosmetics."""
    for name in FULLSTACK_REVIEW_LENSES.values():
        description = registry.get(name).description.lower()
        assert "read-only" in description, name
        assert "never" in description, name
