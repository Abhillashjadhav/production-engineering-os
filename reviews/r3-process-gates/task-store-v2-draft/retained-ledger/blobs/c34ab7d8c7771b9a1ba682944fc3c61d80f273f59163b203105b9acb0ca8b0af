"""The V3 full-stack adapter: web product contracts, stack declarations, and
(in later PRs) UX journey validation, web evidence, and preview verification."""

from pmpe.fullstack.api_contract import (
    canonical_openapi_text,
    verify_committed_schema,
    verify_openapi_covers_contract,
)
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
from pmpe.fullstack.preview import (
    ALLOWED_PREVIEW_KINDS,
    PreviewEvidence,
    PreviewViolation,
    record_preview,
    verify_preview,
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
    "canonical_openapi_text",
    "ALLOWED_PREVIEW_KINDS",
    "PreviewEvidence",
    "PreviewViolation",
    "record_preview",
    "verify_preview",
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
    "verify_committed_schema",
    "verify_openapi_covers_contract",
]
