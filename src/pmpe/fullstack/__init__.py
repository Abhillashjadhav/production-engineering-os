"""The V3 full-stack adapter: web product contracts, stack declarations, and
(in later PRs) UX journey validation, web evidence, and preview verification."""

from pmpe.fullstack.contract import (
    FullStackProductContract,
    fullstack_schema_path,
    load_fullstack_contract,
)
from pmpe.fullstack.stack import (
    CAPABILITY_SURFACES,
    REFERENCE_STACK,
    FullStackAdapter,
    StackCapability,
    get_stack,
)

__all__ = [
    "CAPABILITY_SURFACES",
    "REFERENCE_STACK",
    "FullStackAdapter",
    "FullStackProductContract",
    "StackCapability",
    "fullstack_schema_path",
    "get_stack",
    "load_fullstack_contract",
]
