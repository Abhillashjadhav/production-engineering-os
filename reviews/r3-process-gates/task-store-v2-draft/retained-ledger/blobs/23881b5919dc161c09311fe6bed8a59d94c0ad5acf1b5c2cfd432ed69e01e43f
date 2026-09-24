"""The Claude Code agent plane: definitions, permissions, and routing validation.

Agents are AI execution roles, not software components (PD-05). Python never
invokes a model — it parses the definitions, proves permission properties, and
validates routing decisions the Engineer Router agent proposes.
"""

from pmpe.agents.permissions import (
    FULLSTACK_REVIEW_LENSES,
    READ_ONLY_TOOLS,
    ReadOnlyViolation,
    assert_fullstack_reviewers_read_only,
    assert_reviewers_read_only,
    is_read_only,
)
from pmpe.agents.registry import AgentDefinition, AgentRegistry
from pmpe.agents.router import SPECIALIST_PROFILES, RoutingError, validate_routing

__all__ = [
    "READ_ONLY_TOOLS",
    "SPECIALIST_PROFILES",
    "AgentDefinition",
    "AgentRegistry",
    "ReadOnlyViolation",
    "RoutingError",
    "FULLSTACK_REVIEW_LENSES",
    "assert_fullstack_reviewers_read_only",
    "assert_reviewers_read_only",
    "is_read_only",
    "validate_routing",
]
