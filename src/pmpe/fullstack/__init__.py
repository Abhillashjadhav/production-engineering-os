"""The V3 full-stack adapter: web product contracts, stack declarations, and
(in later PRs) UX journey validation, web evidence, and preview verification."""

from pmpe.fullstack.contract import (
    FullStackProductContract,
    fullstack_schema_path,
    load_fullstack_contract,
)
from pmpe.fullstack.journey import (
    JourneyNotValidated,
    record_validated_journey,
    require_validated_journey,
    validate_ux_architecture,
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
    "JourneyNotValidated",
    "StackCapability",
    "fullstack_schema_path",
    "get_stack",
    "load_fullstack_contract",
    "record_validated_journey",
    "require_validated_journey",
    "validate_ux_architecture",
]
