"""The only external adapter used by the bare-bones Engineering OS core."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from pmpe.privacy_policy import (
    ProviderPrivacyPolicy,
    validate_private_payload,
    validate_provider_request,
)

GENERIC_PROVIDER_ISOLATION = "UNVERIFIED_GENERIC_COMMAND"
OFFLINE_PROVIDER_ISOLATION = "UNVERIFIED_OFFLINE_MODE"


class ModelProvider(Protocol):
    """Return structured output for one digest-bound model request."""

    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]: ...


class PrivacyCheckedProvider:
    """Check the exact request before invoking either provider adapter mode.

    It does not change the underlying provider's isolation or release status.
    Errors from an adapter are replaced with a fixed code so provider stderr or
    an exception containing request content cannot become terminal evidence.
    """

    def __init__(
        self, provider: ModelProvider, *, policy: ProviderPrivacyPolicy | None = None
    ) -> None:
        self.provider = provider
        self.policy = policy or ProviderPrivacyPolicy()

    def invoke(self, *, purpose: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        validate_provider_request(purpose, request, policy=self.policy)
        try:
            response = self.provider.invoke(purpose=purpose, request=request)
        except Exception:
            raise RuntimeError("MODEL_PROVIDER_FAILED") from None
        validate_private_payload(response, policy=self.policy)
        if not isinstance(response, Mapping):
            raise RuntimeError("MODEL_PROVIDER_RESPONSE_INVALID")
        return response
