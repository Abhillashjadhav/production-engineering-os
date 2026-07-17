"""Permission model: read-only is a provable property of the tool list (PD-06)."""

from __future__ import annotations

from pmpe.agents.registry import AgentDefinition, AgentRegistry
from pmpe.domain.errors import PmpeError

READ_ONLY_TOOLS = frozenset({"Read", "Grep", "Glob"})

REVIEWER_NAMES = (
    "v2-code-reviewer",
    "v2-product-conformance-reviewer",
    "v2-architecture-simplicity-reviewer",
    "v2-eval-integrity-auditor",
)


class ReadOnlyViolation(PmpeError):  # noqa: N818 — it is a violation, not an incidental error
    """An agent that must be read-only has write-capable tools configured."""


def is_read_only(agent: AgentDefinition) -> bool:
    """True only when the agent declares an explicit tool list that cannot write.

    An empty tool list means 'inherit all tools' in Claude Code — that is NOT
    read-only, so it fails this check by design.
    """
    return bool(agent.tools) and set(agent.tools) <= READ_ONLY_TOOLS


def _assert_named_read_only(registry: AgentRegistry, names: tuple[str, ...]) -> None:
    for name in names:
        if not registry.has(name):
            raise ReadOnlyViolation(f"reviewer '{name}' has no agent definition")
        agent = registry.get(name)
        if not is_read_only(agent):
            offending = sorted(set(agent.tools) - READ_ONLY_TOOLS) or ["<inherit-all>"]
            raise ReadOnlyViolation(
                f"reviewer '{name}' is not read-only: tool(s) {', '.join(offending)}"
            )


def assert_reviewers_read_only(registry: AgentRegistry) -> None:
    """Fail closed if any assurance reviewer could write a file (PD-06)."""
    _assert_named_read_only(registry, REVIEWER_NAMES)


# PD-V3-15: the six full-stack assurance lenses. The mapping is the enforced
# roster — dropping a lens (or pointing one at a write-capable agent) fails
# the permission proof, so no lens can silently disappear from a run.
FULLSTACK_REVIEW_LENSES: dict[str, str] = {
    "ux-journey": "v3-ux-journey-reviewer",
    "frontend-accessibility": "v3-frontend-accessibility-reviewer",
    "backend-api-security": "v3-backend-api-security-reviewer",
    "architecture-simplicity": "v3-architecture-simplicity-reviewer",
    "product-conformance": "v3-product-conformance-reviewer",
    "evidence-integrity": "v3-evidence-integrity-reviewer",
}


def assert_fullstack_reviewers_read_only(registry: AgentRegistry) -> None:
    """Fail closed if any PD-V3-15 lens is missing or could write a file."""
    _assert_named_read_only(registry, tuple(FULLSTACK_REVIEW_LENSES.values()))
