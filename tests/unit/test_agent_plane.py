"""PD-05/PD-06: agent definitions, read-only proof by tool config, minimum routing,
and worktree isolation for write-capable agents."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pmpe.agents.permissions import (
    READ_ONLY_TOOLS,
    ReadOnlyViolation,
    assert_reviewers_read_only,
    is_read_only,
)
from pmpe.agents.registry import AgentRegistry
from pmpe.agents.router import RoutingError, validate_routing
from pmpe.assurance.readonly_guard import readonly_snapshot, tree_digest, verify_unmodified


def _git_repo(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "t@t.t"], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "t"], check=True, capture_output=True
    )
    for rel, body in files.items():
        (root / rel).write_text(body)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-qm", "base"], check=True, capture_output=True
    )
    return root

REPO_ROOT = Path(__file__).resolve().parents[2]

REVIEWERS = (
    "v2-code-reviewer",
    "v2-product-conformance-reviewer",
    "v2-architecture-simplicity-reviewer",
    "v2-eval-integrity-auditor",
)
READ_ONLY_AGENTS = REVIEWERS + (
    "v2-system-architect",
    "v2-implementation-planner",
    "v2-engineer-router",
)
WRITE_CAPABLE = (
    "v2-backend-engineer",
    "v2-test-engineer",
    "v2-integration-engineer",
    "v2-approved-findings-fixer",
)


@pytest.fixture(scope="module")
def registry() -> AgentRegistry:
    return AgentRegistry(REPO_ROOT / ".claude" / "agents")


# --- definitions and permissions -------------------------------------------------------


def test_all_v2_agents_are_defined(registry: AgentRegistry) -> None:
    names = {a.name for a in registry.v2_agents()}
    assert set(READ_ONLY_AGENTS) | set(WRITE_CAPABLE) <= names


def test_all_lists_every_parsed_definition(registry: AgentRegistry) -> None:
    """all() is the registry's full inventory: consistent with has()/get() and a
    superset of the v2 agents."""
    inventory = registry.all()
    names = [d.name for d in inventory]
    assert len(names) == len(set(names)), "duplicate agent names in inventory"
    assert {d.name for d in registry.v2_agents()} <= set(names)
    for definition in inventory:
        assert registry.has(definition.name)
        assert registry.get(definition.name) == definition


def test_reviewers_are_read_only_by_tool_configuration(registry: AgentRegistry) -> None:
    """PD-06: reviewers cannot write files — provable from their tool list alone."""
    for name in REVIEWERS:
        agent = registry.get(name)
        assert agent.tools, f"{name} must declare an explicit tool list"
        assert set(agent.tools) <= READ_ONLY_TOOLS, f"{name} has write-capable tools"
        assert is_read_only(agent)


def test_architect_planner_router_are_read_only(registry: AgentRegistry) -> None:
    """Their artifacts enter the run only through `pmpe eng submit` — the agents
    themselves need no write access."""
    for name in ("v2-system-architect", "v2-implementation-planner", "v2-engineer-router"):
        assert is_read_only(registry.get(name)), name


def test_write_capable_agents_declare_worktree_isolation(registry: AgentRegistry) -> None:
    for name in ("v2-backend-engineer", "v2-test-engineer"):
        agent = registry.get(name)
        assert not is_read_only(agent)
        assert agent.isolation == "worktree", f"{name} must run in an isolated worktree"


def test_assert_reviewers_read_only_catches_a_write_tool(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "v2-code-reviewer.md").write_text(
        "---\nname: v2-code-reviewer\ndescription: x\ntools: Read, Grep, Glob, Write\n---\nbody\n"
    )
    bad_registry = AgentRegistry(agents_dir)
    with pytest.raises(ReadOnlyViolation, match="v2-code-reviewer"):
        assert_reviewers_read_only(bad_registry)


def test_inherit_all_tool_list_is_not_read_only(tmp_path: Path) -> None:
    """A definition whose frontmatter omits `tools:` inherits ALL tools in Claude
    Code — the permission model must fail closed on it, not certify it read-only."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "v2-code-reviewer.md").write_text(
        "---\nname: v2-code-reviewer\ndescription: x\n---\nbody\n"
    )
    bad_registry = AgentRegistry(agents_dir)
    assert not is_read_only(bad_registry.get("v2-code-reviewer"))
    with pytest.raises(ReadOnlyViolation, match="inherit-all"):
        assert_reviewers_read_only(bad_registry)


def test_missing_reviewer_fails_closed(tmp_path: Path) -> None:
    """Every assurance reviewer must exist — an empty registry is a violation,
    not a vacuous pass."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    with pytest.raises(ReadOnlyViolation, match="no agent definition"):
        assert_reviewers_read_only(AgentRegistry(agents_dir))


def test_assert_reviewers_read_only_passes_on_real_definitions(
    registry: AgentRegistry,
) -> None:
    assert_reviewers_read_only(registry)


# --- minimum routing --------------------------------------------------------------------


def _tasks() -> list[dict[str, object]]:
    return [
        {"id": "T-001", "required_capability": "backend"},
        {"id": "T-002", "required_capability": "backend"},
        {"id": "T-003", "required_capability": "test"},
    ]


def _routing(selected: list[dict[str, object]], not_selected: list[dict[str, object]]):  # noqa: ANN202
    return {"selected": selected, "not_selected": not_selected}


def _good_routing() -> dict[str, object]:
    return _routing(
        selected=[
            {
                "agent": "v2-backend-engineer",
                "tasks": ["T-001", "T-002"],
                "reason": "two backend tasks",
            },
            {"agent": "v2-test-engineer", "tasks": ["T-003"], "reason": "test harness task"},
        ],
        not_selected=[
            {"agent": "frontend-engineer", "reason": "no UI in contract scope"},
            {"agent": "data-migration-engineer", "reason": "no schema migration"},
            {"agent": "security-engineer", "reason": "no auth surface beyond templates"},
            {"agent": "eval-engineer", "reason": "no model-backed behaviour to eval"},
            {"agent": "platform-reliability-engineer", "reason": "single-process local deploy"},
        ],
    )


def test_valid_minimum_routing_passes(registry: AgentRegistry) -> None:
    validate_routing(_tasks(), _good_routing(), registry)


def test_unassigned_task_is_rejected(registry: AgentRegistry) -> None:
    routing = _good_routing()
    routing["selected"][1]["tasks"] = []  # type: ignore[index]
    with pytest.raises(RoutingError, match="T-003"):
        validate_routing(_tasks(), routing, registry)


def test_selected_agent_with_no_tasks_is_not_minimal(registry: AgentRegistry) -> None:
    routing = _good_routing()
    routing["selected"].append(  # type: ignore[union-attr]
        {"agent": "v2-integration-engineer", "tasks": [], "reason": "just in case"}
    )
    with pytest.raises(RoutingError, match="minimum|no assigned"):
        validate_routing(_tasks(), routing, registry)


def test_capability_mismatch_is_rejected(registry: AgentRegistry) -> None:
    routing = _good_routing()
    routing["selected"][0]["tasks"] = ["T-001", "T-002", "T-003"]  # type: ignore[index]
    routing["selected"] = [routing["selected"][0]]  # type: ignore[index]
    with pytest.raises(RoutingError, match="capability"):
        validate_routing(_tasks(), routing, registry)


def test_unexplained_non_selection_is_rejected(registry: AgentRegistry) -> None:
    routing = _good_routing()
    routing["not_selected"] = []  # type: ignore[assignment]
    with pytest.raises(RoutingError, match="not_selected"):
        validate_routing(_tasks(), routing, registry)


def test_selected_agent_without_definition_is_rejected(registry: AgentRegistry) -> None:
    routing = _good_routing()
    routing["selected"][0]["agent"] = "v2-quantum-engineer"  # type: ignore[index]
    with pytest.raises(RoutingError, match="definition"):
        validate_routing(_tasks(), routing, registry)


# --- runtime read-only guard -------------------------------------------------------------


def test_tree_digest_detects_any_modification(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("y = 2\n")
    before = tree_digest(tmp_path)
    assert tree_digest(tmp_path) == before  # stable

    (tmp_path / "sub" / "b.py").write_text("y = 3\n")
    assert tree_digest(tmp_path) != before


def test_verify_unmodified_reports_changed_and_removed(tmp_path: Path) -> None:
    # the read-only proof is drawn at the git-tracked boundary (readonly_snapshot)
    repo = _git_repo(tmp_path / "repo", {"keep.py": "k = 1\n", "gone.py": "g = 1\n"})
    before = readonly_snapshot(repo)

    (repo / "keep.py").write_text("k = 2\n")
    (repo / "gone.py").unlink()
    (repo / "new.py").write_text("n = 1\n")  # untracked: outside the boundary by design
    violations = verify_unmodified(repo, before)
    blob = " ".join(violations)
    assert "changed: keep.py" in blob
    assert "removed: gone.py" in blob
    assert "new.py" not in blob  # an untracked addition is not a reviewer write


def test_verify_unmodified_clean_tree_passes(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo", {"a.py": "x = 1\n"})
    before = readonly_snapshot(repo)
    assert verify_unmodified(repo, before) == []
