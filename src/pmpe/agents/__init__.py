"""The Claude Code agent plane: definitions and routing validation.

Agents are AI execution roles, not software components (PD-05). Python never
invokes a model — it parses the definitions, proves permission properties, and
validates routing decisions the Engineer Router agent proposes.
"""

from pmpe.agents.registry import AgentDefinition, AgentRegistry
from pmpe.agents.router import SPECIALIST_PROFILES, RoutingError, validate_routing

__all__ = [
    "SPECIALIST_PROFILES",
    "AgentDefinition",
    "AgentRegistry",
    "RoutingError",
    "validate_routing",
]
